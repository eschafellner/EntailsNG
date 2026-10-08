"""Clan management with fresh permissions and serialized role/succession changes."""
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.db import transaction

from configuration.translations import get_translation
from .models import Clan, ClanMembership
from .texts import TEXTS


class ClanManagementError(Exception):
    def __init__(self, key):
        self.key = key
        super().__init__(get_translation(key, TEXTS[key]))


def active_memberships(clan):
    return clan.memberships.filter(
        status=ClanMembership.Status.ACCEPTED,
        user__is_active=True,
        user__deleted_at__isnull=True,
    )


@contextmanager
def locked_management(clan_id, actor_id, membership_id=None, *, require_admin=True):
    """Lock User -> Clan -> Membership, compatible with account deletion.

    User locks are acquired in ID order before the clan lock. Recheck both
    target identity and actor rights after waiting; never trust a page snapshot.
    """
    with transaction.atomic():
        target_user_id = None
        if membership_id is not None:
            target_user_id = ClanMembership.objects.get(pk=membership_id, clan_id=clan_id).user_id
        user_ids = {actor_id}
        if target_user_id is not None:
            user_ids.add(target_user_id)
        users = {
            user.pk: user for user in get_user_model().objects.select_for_update(no_key=True)
            .filter(pk__in=user_ids).order_by('pk')
        }
        actor = users.get(actor_id)
        if actor is None or not actor.is_active or actor.deleted_at is not None:
            raise ClanManagementError('msg_clan_no_permission')
        clan = Clan.objects.select_for_update().get(pk=clan_id)
        if require_admin and not clan.is_admin(actor):
            raise ClanManagementError('msg_clan_no_permission')
        membership = None
        if membership_id is not None:
            membership = ClanMembership.objects.select_for_update().get(pk=membership_id, clan=clan)
            if membership.user_id != target_user_id or target_user_id not in users:
                raise ClanManagementError('msg_clan_membership_changed')
            membership.user = users[target_user_id]
        yield clan, membership


def _protect_last_admin(clan, membership):
    # Inactive admin accounts do not substitute for an admin who can log in.
    if (membership.role == ClanMembership.Role.ADMIN
            and membership.user.is_active and membership.user.deleted_at is None
            and not active_memberships(clan).filter(role=ClanMembership.Role.ADMIN)
            .exclude(pk=membership.pk).exists()):
        raise ClanManagementError('msg_clan_last_admin')


def manage_member(clan_id, actor_id, membership_id, action):
    if action not in {'promote', 'demote', 'kick'}:
        raise ClanManagementError('msg_clan_invalid_action')
    with locked_management(clan_id, actor_id, membership_id) as (clan, membership):
        if membership.status != ClanMembership.Status.ACCEPTED:
            raise ClanManagementError('msg_clan_confirmed_member_required')
        if action == 'kick':
            if membership.user_id == actor_id:
                raise ClanManagementError('msg_clan_self_kick')
            _protect_last_admin(clan, membership)
            username = membership.user.username
            membership.delete()
            return username
        role = ClanMembership.Role.ADMIN if action == 'promote' else ClanMembership.Role.MEMBER
        if membership.role == role:
            raise ClanManagementError('msg_clan_role_unchanged')
        if action == 'promote':
            if not membership.user.is_active or membership.user.deleted_at is not None:
                raise ClanManagementError('msg_clan_active_member_required')
        else:
            _protect_last_admin(clan, membership)
        membership.role = role
        membership.save(update_fields=['role'])
        return membership.user.username


def manage_request(clan_id, actor_id, membership_id, action):
    if action not in {'accept', 'reject'}:
        raise ClanManagementError('msg_clan_invalid_action')
    with locked_management(clan_id, actor_id, membership_id) as (clan, membership):
        if membership.status != ClanMembership.Status.PENDING:
            raise ClanManagementError('msg_clan_pending_required')
        username = membership.user.username
        if action == 'reject':
            membership.delete()
            return username, None
        if not membership.user.is_active or membership.user.deleted_at is not None:
            raise ClanManagementError('msg_clan_active_member_required')
        other_active = ClanMembership.get_user_active_membership(membership.user)
        if other_active:
            membership.delete()
            return username, other_active.clan.name
        membership.role = ClanMembership.Role.MEMBER
        membership.status = ClanMembership.Status.ACCEPTED
        membership.save(update_fields=['role', 'status'])
        return username, None


def leave_clan(clan_id, actor_id):
    """Keep existing dissolution and oldest-member succession, under the clan lock."""
    with locked_management(clan_id, actor_id, require_admin=False) as (clan, _):
        membership = clan.memberships.select_for_update().filter(
            user_id=actor_id, status=ClanMembership.Status.ACCEPTED,
        ).first()
        if membership is None:
            raise ClanManagementError('msg_clan_not_member')
        from seating.models import ClanSeatPayment
        if not clan.memberships.filter(status=ClanMembership.Status.ACCEPTED).exclude(pk=membership.pk).exists() and ClanSeatPayment.objects.filter(allocation__clan=clan).exists():
            from configuration.translations import get_translation
            raise ClanManagementError('clan_payment_clan_delete_blocked')
        was_admin = membership.role == ClanMembership.Role.ADMIN
        membership.delete()
        if not clan.memberships.filter(status=ClanMembership.Status.ACCEPTED).exists():
            clan.delete()
            return True, None
        successor = None
        if was_admin and not active_memberships(clan).filter(role=ClanMembership.Role.ADMIN).exists():
            next_member = active_memberships(clan).select_related('user').order_by('created_at', 'pk').first()
            if next_member is None:
                # Roll back the departure rather than leaving an unusable clan.
                raise ClanManagementError('msg_clan_last_admin')
            next_member.role = ClanMembership.Role.ADMIN
            next_member.save(update_fields=['role'])
            successor = next_member.user.username
        return False, successor
