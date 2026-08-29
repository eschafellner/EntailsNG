import logging

from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags

from .models import EmailTemplate

logger = logging.getLogger(__name__)


def safe_format(text, context):
    """Ersetzt Platzhalter wie {username} gefahrlos im Text."""
    if not text:
        return ""
    result = text
    for key, value in context.items():
        placeholder = f"{{{key}}}"
        result = result.replace(placeholder, str(value if value is not None else ""))
    return result


def send_system_email(template_key, recipient_email, context_data):
    """
    Versendet eine System-E-Mail auf Basis eines Templates.

    Transport, Absender, Testmodus und Kill-Switch liegen im konfigurierten
    EMAIL_BACKEND (emails.backends.ConfiguredSMTPBackend). Diese Funktion
    kümmert sich ausschließlich um Inhalt und Platzhalter.
    """
    if not recipient_email:
        logger.warning("Kein Empfänger für Template '%s' angegeben.", template_key)
        return False

    try:
        template = EmailTemplate.objects.get(key=template_key)
    except EmailTemplate.DoesNotExist:
        logger.error(
            "E-Mail-Template '%s' fehlt in der Datenbank. Wurde "
            "'manage.py seed_email_templates' ausgeführt?",
            template_key,
        )
        return False

    if not template.is_active:
        logger.warning(
            "Template '%s' ist deaktiviert. Die Nachricht an %s wurde nicht gesendet.",
            template_key, recipient_email,
        )
        return False

    subject = safe_format(template.subject, context_data)
    html_content = safe_format(template.content, context_data)
    text_content = strip_tags(html_content)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        to=[recipient_email],
        # from_email und reply_to setzt das Backend aus den Einstellungen
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
