"""Contact delivery through the transactional outbox, with durable abuse limits."""
import hashlib
from datetime import timedelta
from html import unescape

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connection, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.html import strip_tags

from configuration.models import ContactCategory, GeneralConfiguration
from configuration.translations import get_translation as tr
from configuration.validators import parse_contact_recipients
from emails.models import EmailTemplate, GeneralEmailSettings, OutgoingEmail
from emails.services import queue_system_email, render_system_email, trigger_queue_processing
from users.auth_backends import get_client_ip
from .tokens import read_submission_token

TEMPLATE_KEY = 'contact_request'


def _mail_is_operational():
    cfg = GeneralEmailSettings.load()
    return cfg.is_operational and (not cfg.is_sandbox or bool(cfg.sandbox_redirect_email))


def is_contact_available():
    cfg = GeneralConfiguration.load()
    if not cfg.contact_enabled:
        return False
    try:
        recipients = parse_contact_recipients(cfg.contact_recipient_emails)
    except ValidationError:
        return False
    return bool(
        recipients and _mail_is_operational()
        and ContactCategory.objects.filter(configuration_id=cfg.pk, is_active=True).exists()
        and EmailTemplate.objects.filter(key=TEMPLATE_KEY, is_active=True).exists()
    )


def _lock(key):
    lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big', signed=True)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_id])


def _check_limits(email, ip_hash, now):
    submissions = OutgoingEmail.objects.filter(contact_submission_id__isnull=False)
    sender_submissions = submissions.filter(reply_to_email=email)
    hour_limit = getattr(settings, 'CONTACT_MAX_PER_EMAIL_HOUR', 5)
    cooldown = getattr(settings, 'CONTACT_MIN_INTERVAL_SECONDS', 60)
    if (
        sender_submissions.filter(created_at__gte=now - timedelta(hours=1))
        .values('contact_submission_id').distinct().count() >= hour_limit
        or sender_submissions.filter(created_at__gte=now - timedelta(seconds=cooldown)).exists()
    ):
        raise ValidationError(tr('contact_rate_limit'), code='rate_limit')
    ip_limit = getattr(settings, 'CONTACT_MAX_PER_IP_TEN_MINUTES', 100)
    if (
        submissions.filter(contact_ip_hash=ip_hash, created_at__gte=now - timedelta(minutes=10))
        .values('contact_submission_id').distinct().count() >= ip_limit
    ):
        raise ValidationError(tr('contact_ip_rate_limit'), code='ip_rate_limit')


def submit_contact(request, *, email, category_id, message, submission_token):
    """Queue all recipients atomically; repeated submission tokens reuse the original jobs."""
    submission_id = read_submission_token(request, submission_token)
    email = (email or '').strip().lower()
    try:
        validate_email(email)
    except ValidationError as exc:
        raise ValidationError(tr('contact_invalid_email')) from exc
    if len(email) > 254:
        raise ValidationError(tr('contact_invalid_email'))
    message = (message or '').strip()
    if not message:
        raise ValidationError(tr('contact_required'))
    if len(message) > 10000:
        raise ValidationError(tr('contact_message_too_long'))
    ip_hash = salted_hmac('contact.ip.v1', get_client_ip(request), algorithm='sha256').hexdigest()

    with transaction.atomic():
        actor = None
        if request.user.is_authenticated:
            actor = get_user_model().objects.select_for_update(no_key=True).filter(
                pk=request.user.pk, is_active=True, is_banned=False, deleted_at__isnull=True,
            ).first()
            if actor is None:
                raise ValidationError(tr('contact_invalid_token'))
        # Same ordering on every request; independent of Redis and the number of web workers.
        _lock(f'contact.submission:{submission_id}')
        previous = list(OutgoingEmail.objects.filter(contact_submission_id=submission_id).order_by('pk'))
        if previous:
            return previous
        _lock(f'contact.sender:{email}')
        _lock(f'contact.ip:{ip_hash}')
        now = timezone.now()
        _check_limits(email, ip_hash, now)

        cfg = GeneralConfiguration.objects.select_for_update().filter(pk=1).first()
        if not cfg or not cfg.contact_enabled or not _mail_is_operational():
            raise ValidationError(tr('contact_unavailable'))
        category = ContactCategory.objects.select_for_update().filter(
            pk=category_id, configuration=cfg, is_active=True,
        ).first()
        if category is None:
            raise ValidationError(tr('contact_invalid_category'))
        try:
            recipients = parse_contact_recipients(category.recipient_emails or cfg.contact_recipient_emails)
        except ValidationError as exc:
            raise ValidationError(tr('contact_unavailable')) from exc
        if not recipients:
            raise ValidationError(tr('contact_unavailable'))
        # Prevent changes to the template partway through a multi-recipient submission.
        if not EmailTemplate.objects.select_for_update().filter(key=TEMPLATE_KEY, is_active=True).exists():
            raise ValidationError(tr('contact_unavailable'))
        context = {
            'email': email, 'category': category.name, 'message': message,
            'submitted_at': timezone.localtime(now).strftime('%d.%m.%Y %H:%M %Z'),
        }
        _, subject, _, _ = render_system_email(TEMPLATE_KEY, recipients[0], context)
        if not subject or len(subject) > 255 or '\r' in subject or '\n' in subject:
            raise ValidationError(tr('contact_unavailable'))
        outgoing_emails = []
        for recipient in recipients:
            outgoing = queue_system_email(
                TEMPLATE_KEY, recipient, context, trigger_worker=False,
                reply_to_email=email, submitted_by=actor,
            )
            if outgoing is None:
                raise ValidationError(tr('contact_unavailable'))
            outgoing.contact_submission_id = submission_id
            outgoing.contact_ip_hash = ip_hash
            outgoing.body_text = unescape(strip_tags(outgoing.body_html))
            outgoing.save(update_fields=['contact_submission_id', 'contact_ip_hash', 'body_text'])
            outgoing_emails.append(outgoing)
        trigger_queue_processing()
        return outgoing_emails
