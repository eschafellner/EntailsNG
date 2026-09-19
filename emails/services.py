import logging

from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape, strip_tags

from .models import EmailTemplate

logger = logging.getLogger(__name__)


def safe_format(text, context, escape_html=False):
    """
    Ersetzt Platzhalter wie {username} gefahrlos im Text.
    Wenn escape_html=True, werden die eingefügten Variablenwerte HTML-sicher maskiert.
    """
    if not text:
        return ""
    result = text
    for key, value in context.items():
        placeholder = f"{{{key}}}"
        val_str = str(value if value is not None else "")
        if escape_html:
            val_str = escape(val_str)
        result = result.replace(placeholder, val_str)
    return result


import threading
from django.db import transaction, connection
from django.utils import timezone
from .models import EmailTemplate, OutgoingEmail


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


def queue_system_email(template_key, recipient_email, context_data, trigger_worker=True):
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
    )
    logger.info("E-Mail '%s' an %s in Warteschlange eingereiht (ID %s).", template_key, recipient_email, outgoing.pk)

    if trigger_worker:
        trigger_queue_processing()

    return outgoing


def trigger_queue_processing():
    """Startet die Hintergrundverarbeitung der E-Mail-Queue (nach DB-Commit)."""
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


def process_email_queue(limit=50):
    """
    Verarbeitet fällige E-Mails aus der Warteschlange.
    Nutzt select_for_update(skip_locked=True), sofern von der Datenbank unterstützt.
    Gibt (gesendet_anzahl, fehlgeschlagen_anzahl) zurück.
    """
    now = timezone.now()
    supports_skip_locked = getattr(connection.features, 'has_select_for_update_skip_locked', False)

    with transaction.atomic():
        qs = OutgoingEmail.objects.filter(
            status=OutgoingEmail.Status.PENDING,
            scheduled_at__lte=now,
        ).order_by('scheduled_at')[:limit]

        if supports_skip_locked:
            emails = list(qs.select_for_update(skip_locked=True))
        else:
            emails = list(qs)

        # Vorab auf PROCESSING setzen, um doppelte Abholung durch parallele Worker zu verhindern
        email_ids = [e.id for e in emails]
        if email_ids:
            OutgoingEmail.objects.filter(id__in=email_ids, status=OutgoingEmail.Status.PENDING).update(
                status=OutgoingEmail.Status.PROCESSING
            )

    sent_count = 0
    failed_count = 0

    for outgoing in emails:
        outgoing.refresh_from_db()
        if outgoing.status != OutgoingEmail.Status.PROCESSING:
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
                outgoing.mark_sent()
                logger.info(
                    "E-Mail '%s' an %s (ID %s) erfolgreich gesendet.",
                    outgoing.template_key, outgoing.recipient_email, outgoing.pk
                )
                sent_count += 1
            else:
                reason = "Backend hat den Versand blockiert (Kill-Switch oder unkonfiguriert)."
                logger.warning("E-Mail ID %s blockiert: %s", outgoing.pk, reason)
                outgoing.mark_failed_attempt(reason)
                failed_count += 1
        except Exception as exc:
            logger.error(
                "Versand von OutgoingEmail ID %s an %s fehlgeschlagen: %s",
                outgoing.pk, outgoing.recipient_email, exc
            )
            outgoing.mark_failed_attempt(str(exc))
            failed_count += 1

    return sent_count, failed_count


def send_system_email(template_key, recipient_email, context_data, immediate=True):
    """
    Versendet eine System-E-Mail auf Basis eines Templates.
    Bei immediate=True (Standard für Synchronität / Tests) wird die Mail direkt versendet.
    Bei immediate=False wird die Mail in die persistente Outbox-Queue gestellt.
    """
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

    msg = EmailMultiAlternatives(subject=subject, body=text, to=[target_email])
    msg.attach_alternative(html, "text/html")

    try:
        transport = backend_wrapper._build_backend(cfg)
        backend_wrapper._apply_sender(cfg, [msg])
        if cfg.is_sandbox and cfg.sandbox_redirect_email:
            backend_wrapper._apply_sandbox(cfg, [msg])
        transport.send_messages([msg])
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
