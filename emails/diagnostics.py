import re
import smtplib
import socket
import ssl


def explain_smtp_error(exc: Exception, cfg=None) -> str:
    """Übersetzt eine Versand-Exception in eine verständliche Handlungsanweisung."""
    host = getattr(cfg, 'smtp_host', '') or ''
    port = getattr(cfg, 'smtp_port', '') or ''
    sender = getattr(cfg, 'sender_email', '') or ''
    domain = sender.split('@')[-1] if '@' in sender else ''
    raw = str(exc)

    if isinstance(exc, smtplib.SMTPAuthenticationError):
        base = "Der Mailserver hat die Zugangsdaten abgelehnt."
        if 'resend' in host.lower():
            return (
                f"{base} Bei Resend ist der Benutzername wortwörtlich 'resend' "
                "und das Passwort der API-Key, der mit 're_' beginnt."
            )
        return f"{base} Bitte Benutzername und Passwort prüfen. Serverantwort: {raw}"

    if isinstance(exc, smtplib.SMTPSenderRefused) or 'not verified' in raw.lower() or 'sender refused' in raw.lower():
        return (
            f"Der Mailanbieter akzeptiert die Absenderadresse '{sender}' nicht. "
            f"Die Domain '{domain}' ist dort nicht verifiziert. Verwende eine "
            "Adresse deiner verifizierten Domain oder verifiziere die Domain "
            "beim Anbieter."
        )

    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return (
            "Der Mailserver hat die Empfängeradresse abgelehnt. Ohne "
            "verifizierte Domain erlauben viele Anbieter nur den Versand an "
            "die eigene Kontoadresse."
        )

    if isinstance(exc, (socket.timeout, TimeoutError)):
        hint = (
            " Viele Hoster sperren Port 587. Resend bietet ersatzweise Port 2587 an."
            if str(port) in ('587', '25') else ""
        )
        return f"Keine Antwort von {host}:{port} innerhalb des Zeitlimits.{hint}"

    if isinstance(exc, (ConnectionRefusedError, smtplib.SMTPConnectError)):
        return (
            f"Verbindung zu {host}:{port} wurde abgelehnt. Serveradresse und "
            "Port prüfen. Bei gesperrtem Port 587 einen Alternativport nutzen."
        )

    if isinstance(exc, socket.gaierror):
        return f"Die Serveradresse '{host}' ist nicht auflösbar. Auf Tippfehler prüfen."

    if isinstance(exc, ssl.SSLError) or 'wrong version number' in raw.lower():
        return (
            "Verschlüsselungsfehler. Port 587 benötigt TLS (STARTTLS), "
            "Port 465 benötigt SSL. Aktuell ist die Kombination "
            f"Port {port} mit "
            f"{'SSL' if getattr(cfg, 'smtp_use_ssl', False) else 'TLS'} gesetzt."
        )

    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return (
            f"Der Server {host}:{port} unterstützt die gewählte "
            "Verschlüsselung nicht. TLS-/SSL-Einstellung prüfen."
        )

    if isinstance(exc, smtplib.SMTPResponseException):
        code = exc.smtp_code
        if code == 550:
            return f"Der Server hat die Nachricht abgelehnt (550). Antwort: {raw}"
        if code in (421, 450, 451, 452):
            return (
                f"Der Server ist vorübergehend nicht verfügbar ({code}) oder "
                f"drosselt den Versand. Später erneut versuchen. Antwort: {raw}"
            )
        return f"Der Mailserver meldet Fehler {code}. Antwort: {raw}"

    return f"Der Versand ist fehlgeschlagen: {raw}"
