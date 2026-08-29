import logging

from django.conf import settings as dj
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.utils import timezone

logger = logging.getLogger(__name__)


class ConfiguredSMTPBackend(BaseEmailBackend):
    """
    E-Mail-Backend, das seine Transportkonfiguration zur Laufzeit aus der
    Datenbank liest (GeneralEmailSettings).

    Damit gelten Kill-Switch, Absender und Sandbox für JEDEN Mailversand der
    Anwendung — auch für Passwort-Reset und mail_admins(), die bisher direkt
    über die .env liefen.
    """

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        from .crypto import SecretUnreadable
        from .models import GeneralEmailSettings

        try:
            cfg = GeneralEmailSettings.load()
        except Exception as exc:
            # z. B. Migration noch nicht gelaufen — Versand darf nicht crashen
            logger.error("E-Mail-Einstellungen nicht ladbar: %s", exc)
            if not self.fail_silently:
                raise
            return 0

        # 1. Kill-Switch
        if not cfg.is_enabled:
            logger.warning(
                "E-Mail-Versand ist in den Einstellungen ausgeschaltet. "
                "%d Nachricht(en) wurden nicht gesendet. Empfänger: %s",
                len(email_messages),
                ', '.join(a for m in email_messages for a in m.to),
            )
            return 0

        if cfg.transport_mode == cfg.TransportMode.UNCONFIGURED:
            logger.error(
                "Der E-Mail-Versandweg ist nicht eingerichtet. "
                "%d Nachricht(en) wurden nicht gesendet.",
                len(email_messages),
            )
            return 0

        # 2. Absender und Reply-To erzwingen
        self._apply_sender(cfg, email_messages)

        # 3. Sandbox
        if cfg.is_sandbox:
            if not cfg.sandbox_redirect_email:
                logger.error(
                    "Testmodus ist aktiv, aber keine Weiterleitungsadresse "
                    "hinterlegt. %d Nachricht(en) verworfen.",
                    len(email_messages),
                )
                return 0
            self._apply_sandbox(cfg, email_messages)

        # 4. Transport aufbauen und senden
        try:
            backend = self._build_backend(cfg)
        except SecretUnreadable as exc:
            logger.error("SMTP-Zugangsdaten nicht lesbar: %s", exc)
            self._record_error(cfg, str(exc))
            if not self.fail_silently:
                raise
            return 0

        try:
            sent = backend.send_messages(email_messages)
        except Exception as exc:
            from .diagnostics import explain_smtp_error
            message = explain_smtp_error(exc, cfg)
            logger.error("Mailversand fehlgeschlagen: %s", message)
            self._record_error(cfg, message)
            if not self.fail_silently:
                raise
            return 0

        if sent and (cfg.last_send_error or cfg.last_send_error_at):
            self._clear_error(cfg)
        return sent or 0

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _build_backend(self, cfg):
        timeout = cfg.smtp_timeout or getattr(dj, 'EMAIL_TIMEOUT', 10)

        if cfg.transport_mode == cfg.TransportMode.CUSTOM_SMTP:
            return SMTPBackend(
                host=cfg.smtp_host,
                port=cfg.smtp_port,
                username=cfg.smtp_username or None,
                password=cfg.get_smtp_password() or None,
                use_tls=cfg.smtp_use_tls,
                use_ssl=cfg.smtp_use_ssl,
                timeout=timeout,
                fail_silently=False,
            )

        return SMTPBackend(
            host=dj.EMAIL_HOST,
            port=dj.EMAIL_PORT,
            username=dj.EMAIL_HOST_USER or None,
            password=dj.EMAIL_HOST_PASSWORD or None,
            use_tls=dj.EMAIL_USE_TLS,
            use_ssl=dj.EMAIL_USE_SSL,
            timeout=timeout,
            fail_silently=False,
        )

    @staticmethod
    def _apply_sender(cfg, email_messages):
        if not cfg.sender_email:
            return
        sender = (
            f"{cfg.sender_name} <{cfg.sender_email}>"
            if cfg.sender_name else cfg.sender_email
        )
        for msg in email_messages:
            msg.from_email = sender
            if cfg.reply_to_email and not msg.reply_to:
                msg.reply_to = [cfg.reply_to_email]

    @staticmethod
    def _apply_sandbox(cfg, email_messages):
        for msg in email_messages:
            original = ', '.join(msg.to) or '(keine)'
            if not msg.subject.startswith('[TESTMODUS]'):
                msg.subject = f"[TESTMODUS] {msg.subject}"
            msg.extra_headers = {
                **(msg.extra_headers or {}),
                'X-EntailsNG-Original-To': original,
            }
            msg.to = [cfg.sandbox_redirect_email]
            msg.cc = []
            msg.bcc = []

    @staticmethod
    def _record_error(cfg, message):
        type(cfg).objects.filter(pk=cfg.pk).update(
            last_send_error=message[:2000],
            last_send_error_at=timezone.now(),
        )

    @staticmethod
    def _clear_error(cfg):
        type(cfg).objects.filter(pk=cfg.pk).update(
            last_send_error='', last_send_error_at=None,
        )
