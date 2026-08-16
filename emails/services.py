import logging
from django.conf import settings as django_settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils.html import strip_tags
from .models import EmailTemplate, GeneralEmailSettings

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
    """Haupt-Funktion zum Versenden von System-E-Mails basierend auf Templates,

    Einstellungen und Sandbox-Modus.
    """
    settings = GeneralEmailSettings.load()

    # 1. Prüfen, ob der E-Mail-Versand global aktiviert ist
    if not settings.is_enabled:
        logger.info(f"E-Mail-Versand ist global deaktiviert. Template '{template_key}' wird nicht gesendet.")
        return False

    # 2. Template laden & Prüfen, ob es aktiv ist
    try:
        template = EmailTemplate.objects.get(key=template_key)
    except EmailTemplate.DoesNotExist:
        logger.warning(f"E-Mail-Template '{template_key}' nicht gefunden.")
        return False

    if not template.is_active:
        logger.info(f"E-Mail-Template '{template_key}' ist deaktiviert.")
        return False

    # 3. Empfänger & Sandbox-Modus auswerten
    if settings.is_sandbox:
        if not settings.sandbox_redirect_email:
            logger.warning("Sandbox-Modus ist aktiv, aber keine Weiterleitungsadresse konfiguriert!")
            return False
        target_recipient = settings.sandbox_redirect_email
        subject_prefix = "[SANDBOX HIGHLIGHT] "
    else:
        target_recipient = recipient_email
        subject_prefix = ""

    if not target_recipient:
        logger.warning("Keine Ziel-E-Mail-Adresse angegeben.")
        return False

    # 4. Platzhalter im Betreff & HTML-Inhalt ersetzen
    subject = subject_prefix + safe_format(template.subject, context_data)
    html_content = safe_format(template.content, context_data)
    text_content = strip_tags(html_content)

    sender = f"{settings.sender_name} <{settings.sender_email}>"
    reply_to = [settings.reply_to_email] if settings.reply_to_email else None

    # 5. E-Mail versenden (Eigenes SMTP-Setup oder Django-Standard)
    try:
        timeout = getattr(django_settings, 'EMAIL_TIMEOUT', 10)
        connection = None
        if settings.smtp_host:
            connection = get_connection(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username or None,
                password=settings.smtp_password or None,
                use_tls=settings.smtp_use_tls,
                timeout=timeout,
            )
        else:
            connection = get_connection(timeout=timeout)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=sender,
            to=[target_recipient],
            reply_to=reply_to,
            connection=connection,
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        logger.info(f"E-Mail '{template_key}' erfolgreich an {target_recipient} gesendet.")
        return True

    except Exception as e:
        logger.error(f"Fehler beim Senden der E-Mail '{template_key}' an {target_recipient}: {e}")
        return False


def send_test_email(target_email):
    """Hilfsfunktion zum Senden einer Test-E-Mail über das Admin-Panel."""
    settings = GeneralEmailSettings.load()
    context = {
        'username': 'Test-Admin',
        'sender': settings.sender_email,
        'sandbox_status': 'AKTIV' if settings.is_sandbox else 'INAKTIV',
    }

    test_subject = "[EntailsNG Test] E-Mail Konfiguration erfolgreich verifiziert"
    test_html = f"""
    <h2>EntailsNG E-Mail Test</h2>
    <p>Hallo <strong>{context['username']}</strong>,</p>
    <p>dies ist eine automatische Test-E-Mail aus deinem EntailsNG System.</p>
    <ul>
        <li><strong>Absender:</strong> {context['sender']}</li>
        <li><strong>Sandbox-Modus:</strong> {context['sandbox_status']}</li>
        <li><strong>Ziel-Adresse:</strong> {target_email}</li>
    </ul>
    <p>Die SMTP-Einstellungen funktionieren einwandfrei!</p>
    """
    test_text = strip_tags(test_html)

    sender = f"{settings.sender_name} <{settings.sender_email}>"

    try:
        connection = None
        if settings.smtp_host:
            connection = get_connection(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username or None,
                password=settings.smtp_password or None,
                use_tls=settings.smtp_use_tls,
            )

        msg = EmailMultiAlternatives(
            subject=test_subject,
            body=test_text,
            from_email=sender,
            to=[target_email],
            connection=connection,
        )
        msg.attach_alternative(test_html, "text/html")
        msg.send()
        return True, f"Test-E-Mail erfolgreich an {target_email} gesendet!"
    except Exception as e:
        return False, f"Fehler beim Senden: {str(e)}"
