"""Organizer bans, persistent email identities and serialized lifecycle actions."""
import hashlib
import hmac
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.validators import validate_email
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from configuration.translations import get_translation as tr
from .exceptions import RegistrationBlockedError, UserBanError
from .models import BannedEmail, UserBan, UserBanLog


def normalize_email(email):
    return (email or '').strip().lower()


def key_material():
    key = settings.USER_BAN_HMAC_KEY
    if len(key) < 32:
        raise UserBanError(tr('ban_key_missing'))
    return key.encode(), hashlib.sha256(key.encode()).hexdigest()


def email_fingerprint(email):
    key, key_id = key_material()
    return hmac.new(key, normalize_email(email).encode(), hashlib.sha256).hexdigest(), key_id


def validate_key():
    _, key_id = key_material()
    if BannedEmail.objects.filter(ban__revoked_at__isnull=True).exclude(key_id=key_id).exists():
        raise UserBanError(tr('ban_key_changed'))


def is_email_banned(email):
    active = BannedEmail.objects.filter(ban__revoked_at__isnull=True)
    if not active.exists():
        return False
    validate_key()
    fingerprint, key_id = email_fingerprint(email)
    return active.filter(fingerprint=fingerprint, key_id=key_id).exists()


def assert_registration_allowed(email):
    try:
        blocked = get_user_model().objects.filter(email__iexact=normalize_email(email), is_banned=True).exists() or is_email_banned(email)
    except UserBanError:
        blocked = True
    if blocked:
        raise RegistrationBlockedError(tr('ban_registration_failed'))


def lock_email(email):
    # Stable, transaction-scoped serialization without retaining raw identities.
    lock_id = int.from_bytes(hashlib.sha256(('entails.email.' + normalize_email(email)).encode()).digest()[:8], 'big', signed=True)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_id])


def can_manage_bans(actor):
    return bool(actor and actor.is_active and actor.is_staff and not actor.is_banned
                and not actor.deleted_at and actor.has_perm('users.manage_user_bans'))


def authorize(actor, target=None):
    if not can_manage_bans(actor):
        raise PermissionDenied(tr('ban_permission'))
    if target:
        if target.pk == actor.pk:
            raise UserBanError(tr('ban_self'))
        if (target.is_staff or target.is_superuser or target.role != target.Roles.USER) and not actor.is_superuser:
            raise UserBanError(tr('ban_privileged'))


def locked_parties(actor, target_id=None):
    ids = {actor.pk}
    if target_id:
        ids.add(target_id)
    parties = {u.pk: u for u in get_user_model().objects.select_for_update(no_key=True).filter(pk__in=ids).order_by('pk')}
    if actor.pk not in parties:
        raise PermissionDenied(tr('ban_permission'))
    actor = parties[actor.pk]
    target = parties.get(target_id)
    if target_id and target is None:
        raise UserBanError(tr('ban_stale'))
    authorize(actor, target)
    return actor, target


def require_reason(reason):
    reason = (reason or '').strip()
    if not reason or len(reason) > 1000:
        raise UserBanError(tr('ban_reason_required'))
    return reason


def ban_state(user):
    return hashlib.sha256(f'{user.email}:{int(user.is_banned)}:{user.session_version}:{int(user.is_active)}:{user.deleted_at}'.encode()).hexdigest()


def _add_email(ban, email):
    fingerprint, key_id = email_fingerprint(email)
    return BannedEmail.objects.get_or_create(ban=ban, fingerprint=fingerprint, defaults={'key_id': key_id})


def _disable_user(user, actor, reason):
    from events.models import Event, EventRegistration
    from .services import UserService
    if user.deleted_at:
        raise UserBanError(tr('ban_deleted'))
    if user.is_banned:
        raise UserBanError(tr('ban_already_active'))
    ban = UserBan.objects.create(user=user, reason=reason, created_by=actor, was_active=user.is_active)
    # Active accounts include accounts explicitly activated by an administrator.
    if user.email_verified or user.is_active:
        _add_email(ban, user.email)
        get_user_model().objects.filter(pk=user.pk).update(email_verified=True)
    get_user_model().objects.filter(pk=user.pk).update(is_banned=True, is_active=False, session_version=F('session_version') + 1)
    user.verification_codes.update(is_used=True)
    events = {e.pk: e for e in Event.objects.select_for_update().filter(
        pk__in=user.registrations.values('event_id')).order_by('pk')}
    for registration in EventRegistration.objects.select_for_update().filter(user=user).order_by('pk'):
        registration.checkin_token = uuid.uuid4()
        fields = ['checkin_token']
        if events[registration.event_id].effective_status not in (Event.Status.FINISHED, Event.Status.CANCELLED):
            registration.is_checked_in = False
            registration.checked_in_at = None
            fields += ['is_checked_in', 'checked_in_at']
        registration.save(update_fields=fields)
    UserService._erase_account_sessions(user)
    UserBanLog.objects.create(ban=ban, actor=actor, action='BAN', reason=reason)
    return ban


@transaction.atomic
def ban_user(user_id, *, actor, reason, expected_state=None):
    authorize(actor)
    reason = require_reason(reason)
    validate_key()
    User = get_user_model()
    email = User.objects.values_list('email', flat=True).get(pk=user_id)
    lock_email(email)
    actor, user = locked_parties(actor, user_id)
    if user.email != email or (expected_state is not None and expected_state != ban_state(user)):
        raise UserBanError(tr('ban_stale'))
    return _disable_user(user, actor, reason)


@transaction.atomic
def ban_email(email, *, actor, reason):
    """Explicit organizer decision, including identities of deleted accounts."""
    authorize(actor)
    reason = require_reason(reason)
    email = normalize_email(email)
    validate_email(email)
    validate_key()
    lock_email(email)
    if is_email_banned(email):
        raise UserBanError(tr('ban_already_active'))
    user_id = get_user_model().objects.filter(email__iexact=email, deleted_at__isnull=True).values_list('pk', flat=True).first()
    actor, user = locked_parties(actor, user_id)
    if user:
        if user.email != email:
            raise UserBanError(tr('ban_stale'))
        authorize(actor, user)
        if user.is_banned:
            ban = user.orga_bans.get(revoked_at__isnull=True)
            _add_email(ban, email)
            UserBanLog.objects.create(ban=ban, actor=actor, action='ADD_EMAIL', reason=reason)
            return ban
        ban = _disable_user(user, actor, reason)
    else:
        ban = UserBan.objects.create(reason=reason, created_by=actor)
        UserBanLog.objects.create(ban=ban, actor=actor, action='BAN', reason=reason)
    _add_email(ban, email)
    return ban


@transaction.atomic
def revoke_ban(ban_id, *, actor, reason, expected_state=None):
    authorize(actor)
    reason = require_reason(reason)
    user_id = UserBan.objects.values_list('user_id', flat=True).get(pk=ban_id)
    actor, user = locked_parties(actor, user_id)
    if user:
        if expected_state is not None and expected_state != ban_state(user):
            raise UserBanError(tr('ban_stale'))
    ban = UserBan.objects.select_for_update().get(pk=ban_id)
    if not ban.is_active:
        raise UserBanError(tr('ban_stale'))
    ban.revoked_at, ban.revoked_by, ban.revoke_reason = timezone.now(), actor, reason
    ban.save(update_fields=['revoked_at', 'revoked_by', 'revoke_reason'])
    if user and not user.deleted_at:
        get_user_model().objects.filter(pk=user.pk).update(is_banned=False,
            is_active=ban.was_active and user.email_verified, session_version=F('session_version') + 1)
    UserBanLog.objects.create(ban=ban, actor=actor, action='UNBAN', reason=reason)
    return ban
