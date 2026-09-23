import datetime
import logging
import re
import sys
import threading
import uuid

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import connection, models, transaction
from django.utils import timezone
from django.utils.html import escape, strip_tags

from .models import EmailTemplate, OutgoingEmail

logger = logging.getLogger(__name__)


def safe_format(text, context, escape_html=False):
    """
    Ersetzt Platzhalter wie {username} in einem einzigen Durchlauf (Single-Pass),
    um kaskadierende Platzhalter-Injektionen und Abhängigkeiten von der
    Dictionary-Reihenfolge zu verhindern.
    """
    if not text:
        return ""

    def _replacer(match):
        key = match.group(1)
        if key in context:
            val = context[key]
            val_str = str(val if val is not None else "")
            return escape(val_str) if escape_html else val_str
        return match.group(0)

    return re.sub(r'\{([a-zA-Z0-9_]+)\}', _replacer, text)


def render_system_email(template_key, recipient_email, context_data):
    """
    Rendert ein E-Mail-Template mit den übergebenen Kontextdaten.
    Gibt (template, subject, text_content, html_content) zurück, oder (None, None, None, None).
    """
    if not recipient_email:
        logger.warning("Kein Empfänger für Template '%s' angegeben.", template_key)
        return None, None, None, None

    template = EmailTemplate.objects.filter(key=template_key).first()
    if not template and template_key == 'email_change_verification':
        template = EmailTemplate.objects.filter(key='email_verification').first()

    if not template:
        logger.error(
            "E-Mail-Template '%s' fehlt in der Datenbank. Wurde "
            "'manage.py seed_email_templates' ausgeführt?",
            template_key,
        )
        return None, None, None, None

    if not template.is_active:
        logger.warning(
            "Template '%s' ist deaktiviert. Die Nachricht an %s wurde nicht gesendet.",
            template_key, recipient_email,
        )
        return None, None, None, None

    subject = safe_format(template.subject, context_data, escape_html=False)
    html_content = safe_format(template.content, context_data, escape_html=True)
    text_content = strip_tags(html_content)

    return template, subject, text_content, html_content


def queue_system_email(template_key, recipient_email, context_data, trigger_worker=True, expires_at=None):
    """
    Stellt eine System-E-Mail in die persistente Versandwarteschlange (OutgoingEmail / Outbox).
    Wird innerhalb der aktuellen DB-Transaktion gespeichert (Transactional Outbox).
    Triggert nach Commit automatisch die Hintergrundverarbeitung.
    """
    template, subject, text_content, html_content = render_system_email(
        template_key, recipient_email, context_data
    )
    if not template:
        return None

    outgoing = OutgoingEmail.objects.create(
        template_key=template_key,
        recipient_email=recipient_email,
        subject=subject,
        body_text=text_content,
        body_html=html_content,
        status=OutgoingEmail.Status.PENDING,
        scheduled_at=timezone.now(),
        expires_at=expires_at,
    )
    logger.info("E-Mail '%s' an %s in Warteschlange eingereiht (ID %s).", template_key, recipient_email, outgoing.pk)

    if trigger_worker:
        trigger_queue_processing()

    return outgoing


def trigger_queue_processing():
    """Startet die Hintergrundverarbeitung der E-Mail-Queue (nach DB-Commit)."""
    if 'test' in sys.argv or getattr(settings, 'IS_TESTING', False):
        return

    def _run_worker():
        thread = threading.Thread(target=process_email_queue, kwargs={'limit': 25}, daemon=True)
        thread.start()

    try:
        if transaction.get_connection().in_atomic_block:
            transaction.on_commit(_run_worker)
        else:
            _run_worker()
    except Exception as e:
        logger.warning("Trigger für E-Mail-Hintergrundversand fehlgeschlagen: %s", e)


def recover_stale_processing_emails(timeout_seconds=None):
    """
    Findet E-Mails, deren Lease abgelaufen ist oder die länger als timeout_seconds
    im Status PROCESSING feststecken, und setzt diese atomar zurück auf PENDING
    bzw. markiert sie nach max_attempts als FAILED.
    Bereits erfolgreich versendete Nachrichten (sent_at gesetzt) werden niemals überschrieben!
    Gibt die Anzahl wiederhergestellter E-Mails zurück.
    """
    if timeout_seconds is None:
        timeout_seconds = getattr(settings, 'EMAIL_QUEUE_LEASE_TIMEOUT_SECONDS', 300)

    now = timezone.now()
    stale_cutoff = now - datetime.timedelta(seconds=timeout_seconds)

    stale_candidates = list(OutgoingEmail.objects.filter(
        status=OutgoingEmail.Status.PROCESSING,
        sent_at__isnull=True,
    ).filter(
        models.Q(lease_expires_at__isnull=False, lease_expires_at__lte=now) |
        models.Q(lease_expires_at__isnull=True, updated_at__lte=stale_cutoff)
    ))

    recovered = 0
    for candidate in stale_candidates:
        if candidate.mark_stale_recovered(timeout_seconds):
            logger.warning(
                "Stale E-Mail ID %s (Status PROCESSING abgelaufen) atomar zurückgesetzt.",
                candidate.pk
            )
            recovered += 1

    return recovered


def process_email_queue(limit=50, email_ids=None):
    """
    Verarbeitet fällige E-Mails aus der Warteschlange.
    - Stellt vorab verwaiste PROCESSING-Einträge atomar wieder her (Stale Lease Recovery).
    - Verwendet eindeutige Worker-UUIDs und Leases gegen Race Conditions.
    - Unterstützt den Filter email_ids zur gezielten Abarbeitung (z.B. durch Admin-Aktionen).
    - Prüft Ablaufzeitpunkte (expires_at) und verwirft abgelaufene Codes.
    - Berücksichtigt administrative Pausierung, ohne Retry-Versuche zu verbrauchen.
    Gibt (gesendet_anzahl, fehlgeschlagen_anzahl) zurück.
    """
    recover_stale_processing_emails()

    now = timezone.now()
    supports_skip_locked = getattr(connection.features, 'has_select_for_update_skip_locked', False)
    lease_timeout = getattr(settings, 'EMAIL_QUEUE_LEASE_TIMEOUT_SECONDS', 300)
    worker_uuid = uuid.uuid4().hex

    from .models import GeneralEmailSettings
    cfg = GeneralEmailSettings.load()

    # Wenn der Versand administrativ deaktiviert ist, keine Versuche starten
    if not cfg.is_enabled and email_ids is None:
        logger.info("E-Mail Queue Worker: Versand ist administrativ pausiert (is_enabled=False).")
        return 0, 0

    with transaction.atomic():
        qs = OutgoingEmail.objects.filter(
            status=OutgoingEmail.Status.PENDING,
        )
        if email_ids is not None:
            qs = qs.filter(id__in=email_ids)
        else:
            qs = qs.filter(scheduled_at__lte=now)

        qs = qs.order_by('scheduled_at')[:limit]

        if supports_skip_locked:
            emails = list(qs.select_for_update(skip_locked=True))
        else:
            emails = list(qs)

        selected_ids = [e.id for e in emails]
        if selected_ids:
            lease_until = now + datetime.timedelta(seconds=lease_timeout)
            OutgoingEmail.objects.filter(
                id__in=selected_ids,
                status=OutgoingEmail.Status.PENDING,
            ).update(
                status=OutgoingEmail.Status.PROCESSING,
                worker_id=worker_uuid,
                lease_expires_at=lease_until,
                updated_at=now,
            )

    sent_count = 0
    failed_count = 0

    for outgoing in emails:
        outgoing.refresh_from_db()
        # Nur bearbeiten, wenn der Status noch PROCESSING ist und unser worker_id gesetzt ist
        if outgoing.status != OutgoingEmail.Status.PROCESSING or outgoing.worker_id != worker_uuid:
            continue

        # Ablaufzeitpunkt prüfen (z. B. zeitkritischer Verifizierungscode)
        if outgoing.expires_at and outgoing.expires_at <= timezone.now():
            outgoing.mark_expired("E-Mail ist vor dem Versand abgelaufen (expires_at überschritten).")
            logger.info("E-Mail ID %s ist abgelaufen und wurde verworfen.", outgoing.pk)
            continue

        # Prüfung des Schalters vor jedem Versand
        cfg = GeneralEmailSettings.load()
        if not cfg.is_enabled:
            outgoing.mark_paused("Versand während Queue-Durchlauf administrativ pausiert.")
            continue

        msg = EmailMultiAlternatives(
            subject=outgoing.subject,
            body=outgoing.body_text,
            to=[outgoing.recipient_email],
        )
        msg.attach_alternative(outgoing.body_html, "text/html")

        try:
            sent = msg.send(fail_silently=False)
            if sent:
                outgoing.mark_sent(worker_id=worker_uuid)
                logger.info(
                    "E-Mail '%s' an %s (ID %s) erfolgreich gesendet.",
                    outgoing.template_key, outgoing.recipient_email, outgoing.pk
                )
                sent_count += 1
            else:
                reason = "Backend hat den Versand blockiert (Kill-Switch oder unkonfiguriert)."
                logger.warning("E-Mail ID %s blockiert: %s", outgoing.pk, reason)
                cfg = GeneralEmailSettings.load()
                is_pause = not cfg.is_enabled
                outgoing.mark_failed_attempt(reason, is_pause=is_pause)
                if not is_pause:
                    failed_count += 1
        except Exception as exc:
            logger.error(
                "Versand von OutgoingEmail ID %s an %s fehlgeschlagen: %s",
                outgoing.pk, outgoing.recipient_email, exc
            )
            outgoing.mark_failed_attempt(str(exc))
            failed_count += 1

    return sent_count, failed_count



def send_system_email(template_key, recipient_email, context_data, immediate=None):
    """
    Versendet eine System-E-Mail auf Basis eines Templates.
    Bei immediate=True wird die Mail direkt synchron versendet.
    Bei immediate=False wird die Mail in die persistente Outbox-Queue gestellt.
    Wenn immediate=None:
        - Im normalen Betrieb (oder wenn FORCE_EMAIL_ASYNC_QUEUE gesetzt ist) wird settings.EMAIL_ASYNC_QUEUE
          beachtet (Standard: True -> E-Mail wird in die Queue gestellt).
        - In Unit-Tests ('test' in sys.argv und nicht FORCE_EMAIL_ASYNC_QUEUE) bleibt immediate=True
          als Standard, damit bestehende synchrone Test-Assertions auf mail.outbox ohne manuelles
          process_email_queue funktionieren.
    """
    if immediate is None:
        is_testing = 'test' in sys.argv
        force_async = getattr(settings, 'FORCE_EMAIL_ASYNC_QUEUE', False)
        async_enabled = getattr(settings, 'EMAIL_ASYNC_QUEUE', True)
        if is_testing and not force_async:
            immediate = True
        else:
            immediate = not async_enabled

    if not immediate:
        outgoing = queue_system_email(template_key, recipient_email, context_data)
        return outgoing is not None

    template, subject, text_content, html_content = render_system_email(
        template_key, recipient_email, context_data
    )
    if not template:
        return False

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        to=[recipient_email],
    )
    msg.attach_alternative(html_content, "text/html")

    try:
        sent = msg.send(fail_silently=False)
    except Exception as exc:
        logger.error(
            "Versand von '%s' an %s fehlgeschlagen: %s",
            template_key, recipient_email, exc,
        )
        return False

    if sent:
        logger.info("E-Mail '%s' an %s gesendet.", template_key, recipient_email)
        return True

    # sent == 0: Backend hat blockiert (Kill-Switch, nicht eingerichtet).
    # Das Backend hat den Grund bereits geloggt.
    return False



def send_test_email(target_email):
    """
    Sendet eine Testnachricht und gibt (erfolg, klartext_meldung) zurück.

    Umgeht den Kill-Switch bewusst: der Betreiber will die Verbindung prüfen,
    bevor er den Versand für Gäste einschaltet.
    """
    from .backends import ConfiguredSMTPBackend
    from .crypto import SecretUnreadable
    from .diagnostics import explain_smtp_error
    from .models import GeneralEmailSettings

    cfg = GeneralEmailSettings.load()

    if not target_email:
        return False, "Bitte eine Zieladresse angeben."
    if cfg.transport_mode == cfg.TransportMode.UNCONFIGURED:
        return False, "Wähle zuerst einen Versandweg und speichere die Einstellungen."
    if not cfg.sender_email:
        return False, "Es ist keine Absenderadresse hinterlegt."

    backend_wrapper = ConfiguredSMTPBackend(fail_silently=False)

    subject = "EntailsNG: Verbindungstest"
    lines = [
        "Diese Nachricht bestätigt, dass EntailsNG E-Mails versenden kann.",
        "",
        f"Versandweg: {cfg.get_transport_mode_display()}",
        f"Absender: {cfg.sender_email}",
        f"Testmodus: {'ein' if cfg.is_sandbox else 'aus'}",
        f"Zieladresse: {target_email}",
    ]
    text = "\n".join(lines)
    html = "<p>" + "</p><p>".join(lines) + "</p>"

    if cfg.is_sandbox:
        if not cfg.sandbox_redirect_email:
            msg = "Testmodus (Sandbox) ist aktiv, aber es ist keine Weiterleitungsadresse hinterlegt."
            _record_test(cfg, False, msg)
            return False, msg

    msg = EmailMultiAlternatives(subject=subject, body=text, to=[target_email])
    msg.attach_alternative(html, "text/html")

    try:
        transport = backend_wrapper._build_backend(cfg)
        backend_wrapper._apply_sender(cfg, [msg])
        if cfg.is_sandbox:
            backend_wrapper._apply_sandbox(cfg, [msg])
        sent_count = transport.send_messages([msg])
        if not sent_count:
            message = "Das Backend hat die Nachricht abgewiesen oder blockiert (0 Nachrichten gesendet)."
            _record_test(cfg, False, message)
            return False, message
    except SecretUnreadable as exc:
        _record_test(cfg, False, str(exc))
        return False, str(exc)
    except Exception as exc:
        message = explain_smtp_error(exc, cfg)
        _record_test(cfg, False, message)
        return False, message

    delivered_to = cfg.sandbox_redirect_email if cfg.is_sandbox else target_email
    message = f"Testnachricht an {delivered_to} gesendet."
    if cfg.is_sandbox and delivered_to != target_email:
        message += " (Testmodus ist aktiv, daher umgeleitet.)"
    _record_test(cfg, True, message)
    return True, message


def _record_test(cfg, ok, message):
    from django.utils import timezone
    type(cfg).objects.filter(pk=cfg.pk).update(
        last_test_at=timezone.now(),
        last_test_ok=ok,
        last_test_message=message[:2000],
    )
