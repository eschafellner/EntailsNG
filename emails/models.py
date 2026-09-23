from datetime import timedelta
import logging
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from tinymce.models import HTMLField


logger = logging.getLogger(__name__)


class GeneralEmailSettings(models.Model):
    """Singleton-Modell für Allgemeine E-Mail Einstellungen."""

    class TransportMode(models.TextChoices):
        UNCONFIGURED = 'unconfigured', 'Noch nicht eingerichtet'
        ENV = 'env', 'Vom Server vorgegeben (.env)'
        CUSTOM_SMTP = 'smtp', 'Eigener SMTP-Server'

    transport_mode = models.CharField(
        max_length=20,
        choices=TransportMode.choices,
        default=TransportMode.UNCONFIGURED,
        verbose_name="Versandweg",
        help_text=(
            "Woher die Zugangsdaten für den Mailversand kommen. "
            "'Vom Server vorgegeben' nutzt die Konfiguration aus der .env-Datei."
        ),
    )

    sender_email = models.EmailField(
        blank=True,
        default='',
        verbose_name="Absenderadresse",
        help_text=(
            "Adresse, die Gäste als Absender sehen. Muss zu einer bei deinem "
            "Mailanbieter verifizierten Domain gehören."
        ),
    )
    sender_name = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name="Absendername",
        help_text="Anzeigename, z. B. 'LAN-Party Orga-Team'.",
    )
    reply_to_email = models.EmailField(
        blank=True,
        default='',
        verbose_name="Antwort E-Mail-Adresse (Reply-To)",
        help_text="Ziel-Adresse, wenn Gäste auf System-E-Mails antworten (z. B. support@verein.de). Leer lassen = Absender-Adresse.",
    )
    domain_name = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name="E-Mail Versand-Domain",
        help_text="Eure Haupt-Domain für den DNS-Health Check (z. B. lan-party.de).",
    )

    is_enabled = models.BooleanField(
        default=True,
        verbose_name="Gäste erhalten E-Mails",
        help_text=(
            "Steuert Registrierungsbestätigung, Tickets und Passwort-Reset. "
            "Ausgeschaltet können sich keine neuen Gäste registrieren, "
            "da die Bestätigungsmail nicht zugestellt wird."
        ),
    )

    is_sandbox = models.BooleanField(
        default=False,
        verbose_name="Sandbox-Modus aktivieren",
        help_text="Im Sandbox-Modus werden ALLE E-Mails an die unten angegebene Weiterleitungsadresse gesendet.",
    )
    sandbox_redirect_email = models.EmailField(
        blank=True,
        default='',
        verbose_name="Sandbox Weiterleitungs-Adresse",
        help_text="Empfängeradresse im Sandbox-Modus (z. B. orga-test@example.com).",
    )

    # Optionales benutzerdefiniertes SMTP-Server-Setup
    smtp_host = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name="SMTP Host (optional)",
        help_text="Z. B. smtp.mailgun.org oder smtp.gmail.com. Leer lassen für Django-Standard.",
    )
    smtp_port = models.PositiveIntegerField(
        default=587, verbose_name="SMTP Port"
    )
    smtp_username = models.CharField(
        max_length=150, blank=True, default='', verbose_name="SMTP Benutzername"
    )
    smtp_password = models.TextField(
        blank=True,
        default='',
        verbose_name="SMTP Passwort",
        help_text="Wird in der Datenbank verschlüsselt gespeichert.",
    )
    smtp_use_tls = models.BooleanField(
        default=True, verbose_name="TLS Verschlüsselung nutzen"
    )
    smtp_use_ssl = models.BooleanField(
        default=False,
        verbose_name="SSL statt STARTTLS (Port 465)",
        help_text="Für Port 465. Bei Port 587 stattdessen TLS aktivieren.",
    )
    smtp_timeout = models.PositiveIntegerField(
        default=10,
        verbose_name="Zeitlimit in Sekunden",
        help_text="Abbruch, wenn der Mailserver nicht antwortet. Empfohlen: 10.",
    )

    # Statusfelder für die Admin-Anzeige
    last_test_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Letzter Verbindungstest",
    )
    last_test_ok = models.BooleanField(
        null=True, blank=True, verbose_name="Letzter Test erfolgreich",
    )
    last_test_message = models.TextField(
        blank=True, default='', verbose_name="Ergebnis des letzten Tests",
    )
    last_send_error_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Letzter Versandfehler",
    )
    last_send_error = models.TextField(
        blank=True, default='', verbose_name="Fehlermeldung",
    )
    credentials_broken = models.BooleanField(
        default=False,
        verbose_name="Passwort nicht entschlüsselbar",
        help_text=(
            "Wird gesetzt, wenn das gespeicherte SMTP-Passwort nicht gelesen "
            "werden kann — meist nach Änderung von FIELD_ENCRYPTION_KEY."
        ),
    )

    class Meta:
        verbose_name = "Allgemeine E-Mail Einstellung"
        verbose_name_plural = "Allgemeine E-Mail Einstellungen"

    def __str__(self):
        if self.transport_mode == self.TransportMode.UNCONFIGURED:
            return "Allgemeine E-Mail Einstellungen: Noch nicht eingerichtet"
        status = "Aktiv" if self.is_enabled else "Inaktiv"
        sandbox = " (SANDBOX MODUS)" if self.is_sandbox else ""
        return f"Allgemeine E-Mail Einstellungen: {status}{sandbox}"

    def clean(self):
        errors = {}

        if self.smtp_use_tls and self.smtp_use_ssl:
            errors['smtp_use_ssl'] = (
                "TLS und SSL schließen sich aus. Port 587 nutzt TLS, Port 465 nutzt SSL."
            )

        if self.transport_mode == self.TransportMode.CUSTOM_SMTP and not self.smtp_host:
            errors['smtp_host'] = "Für einen eigenen SMTP-Server ist die Serveradresse nötig."

        if self.is_sandbox and not self.sandbox_redirect_email:
            errors['sandbox_redirect_email'] = (
                "Im Testmodus braucht das System eine Adresse, an die alle Mails gehen."
            )

        if self.is_enabled:
            if self.transport_mode == self.TransportMode.UNCONFIGURED:
                errors['transport_mode'] = (
                    "Wähle einen Versandweg, bevor du den E-Mail-Versand einschaltest."
                )
            if not self.sender_email:
                errors['sender_email'] = (
                    "Ohne Absenderadresse lehnen Mailanbieter den Versand ab."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def is_operational(self) -> bool:
        """True, wenn eine Konfiguration vorliegt, die Versand grundsätzlich erlaubt."""
        broken_creds = (
            self.credentials_broken
            if self.transport_mode == self.TransportMode.CUSTOM_SMTP
            else False
        )
        return bool(
            self.is_enabled
            and self.transport_mode != self.TransportMode.UNCONFIGURED
            and self.sender_email
            and not broken_creds
        )

    @property
    def blocking_reason(self) -> str | None:
        """Klartext-Grund, warum aktuell nichts versendet wird. None = alles in Ordnung."""
        if self.transport_mode == self.TransportMode.UNCONFIGURED:
            return "Der Versandweg ist noch nicht eingerichtet."
        if not self.is_enabled:
            return "Der E-Mail-Versand ist ausgeschaltet. Gäste können sich nicht registrieren."
        if not self.sender_email:
            return "Es ist keine Absenderadresse hinterlegt."
        if self.transport_mode == self.TransportMode.CUSTOM_SMTP and self.credentials_broken:
            return "Das gespeicherte SMTP-Passwort kann nicht gelesen werden. Bitte neu eingeben."
        if self.is_sandbox:
            return f"Testmodus aktiv: alle Mails gehen an {self.sandbox_redirect_email}."
        return None

    def get_smtp_password(self) -> str:
        """
        Gibt das entschlüsselte SMTP-Passwort zurück.

        Setzt bei Lesefehler credentials_broken=True, damit das Admin einen
        klaren Hinweis anzeigen kann, und wirft weiter.
        """
        from .crypto import SecretUnreadable, decrypt_secret
        try:
            password = decrypt_secret(self.smtp_password)
        except SecretUnreadable:
            if not self.credentials_broken:
                type(self).objects.filter(pk=self.pk).update(credentials_broken=True)
                self.credentials_broken = True
            raise
        if self.credentials_broken:
            type(self).objects.filter(pk=self.pk).update(credentials_broken=False)
            self.credentials_broken = False
        return password

    def set_smtp_password(self, raw_password: str) -> None:
        """Verschlüsselt und setzt das SMTP-Passwort. Einziger legitimer Schreibweg."""
        from .crypto import encrypt_secret
        self.smtp_password = encrypt_secret(raw_password) if raw_password else ''
        self.credentials_broken = False

    def save(self, *args, **kwargs):
        # Erzwinge Singleton (nur 1 Datensatz)
        self.pk = 1
        # Schutz vor Klartext-Passwörtern bei direkter Zuweisung
        if self.smtp_password and not self.smtp_password.startswith('gAAAAA'):
            from .crypto import encrypt_secret
            logger.warning(
                "smtp_password wurde im Klartext zugewiesen. "
                "Bitte set_smtp_password() verwenden."
            )
            self.smtp_password = encrypt_secret(self.smtp_password)
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class EmailTemplate(models.Model):
    """Modell für einzelne E-Mail Templates (Zahlungsbestätigung etc.)"""

    key = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Template Schlüssel",
        help_text="Eindeutiger System-Key (z. B. payment_confirmation)",
    )
    name = models.CharField(
        max_length=100,
        verbose_name="Name der Vorlage",
        help_text="Name für die Anzeige im Backend",
    )
    subject = models.CharField(
        max_length=200,
        verbose_name="Betreffzeile",
        help_text="Unterstützt Platzhalter wie {username}, {event_title} etc.",
    )
    content = HTMLField(
        verbose_name="E-Mail Inhalt (HTML)",
        help_text="Formatierbarer HTML-Inhalt mit Platzhaltern",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Aktiv",
        help_text="Deaktivierte Vorlagen werden beim Triggern ignoriert.",
    )
    placeholder_info = models.TextField(
        blank=True,
        verbose_name="Verfügbare Platzhalter",
        help_text="Beschreibung der Platzhalter für den Editor",
    )

    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Zuletzt geändert"
    )

    class Meta:
        ordering = ['name']
        verbose_name = "E-Mail Template"
        verbose_name_plural = "E-Mail Templates"

    def __str__(self):
        status = "Aktiv" if self.is_active else "Inaktiv"
        return f"{self.name} ({self.key}) - {status}"


class OutgoingEmail(models.Model):
    """
    Persistente Versandwarteschlange (Transactional Outbox) für ausgehende System-E-Mails.
    Garantiert Transaktionssicherheit, Entkopplung vom Web-Request und automatische
    Wiederholungen bei temporären SMTP-Ausfällen.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Ausstehend'
        PROCESSING = 'PROCESSING', 'Wird gesendet'
        SENT = 'SENT', 'Erfolgreich gesendet'
        FAILED = 'FAILED', 'Fehlgeschlagen'
        EXPIRED = 'EXPIRED', 'Abgelaufen'

    template_key = models.CharField(
        max_length=50,
        verbose_name="Template Schlüssel",
        help_text="Zugehöriger E-Mail-Template-Key (z. B. email_verification)",
    )
    recipient_email = models.EmailField(
        verbose_name="Empfängeradresse",
        help_text="Zieladresse der Nachricht",
    )
    subject = models.CharField(
        max_length=255,
        verbose_name="Betreffzeile",
    )
    body_text = models.TextField(
        verbose_name="Textinhalt",
        help_text="Reiner Textinhalt der Nachricht",
    )
    body_html = models.TextField(
        verbose_name="HTML-Inhalt",
        help_text="HTML-formatierter Inhalt der Nachricht",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name="Versandstatus",
    )
    attempts = models.PositiveIntegerField(
        default=0,
        verbose_name="Bisherige Sendeversuche",
    )
    max_attempts = models.PositiveIntegerField(
        default=5,
        verbose_name="Max. Sendeversuche",
    )
    last_error = models.TextField(
        blank=True,
        default='',
        verbose_name="Letzte Fehlermeldung",
    )
    scheduled_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Geplanter Versandzeitpunkt",
        help_text="Zeitpunkt, ab dem die E-Mail zur Verarbeitung ansteht (für Backoff-Wiederholungen).",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Gültig bis",
        help_text="Optionales Ablaufdatum für zeitkritische Nachrichten (z. B. Verifizierungscodes).",
    )
    worker_id = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        verbose_name="Worker-Kennung",
        help_text="Eindeutige ID des verarbeitenden Worker-Prozesses.",
    )
    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Lease läuft ab um",
        help_text="Zeitpunkt, bis zu dem der Worker die exklusive Sperre besitzt.",
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Erfolgreich gesendet am",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Erstellt am",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_index=True,
        verbose_name="Zuletzt geändert",
    )

    class Meta:
        ordering = ['scheduled_at', 'created_at']
        verbose_name = "Ausgehende E-Mail"
        verbose_name_plural = "Ausgehende E-Mails"
        indexes = [
            models.Index(fields=['status', 'scheduled_at'], name='email_queue_status_sched_idx'),
            models.Index(fields=['status', 'updated_at'], name='email_queue_status_upd_idx'),
            models.Index(fields=['status', 'lease_expires_at'], name='email_queue_status_lease_idx'),
        ]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.template_key} an {self.recipient_email} (#{self.pk})"

    def mark_processing(self, worker_id='', lease_seconds=300):
        now = timezone.now()
        self.status = self.Status.PROCESSING
        self.worker_id = worker_id
        self.lease_expires_at = now + timedelta(seconds=lease_seconds)
        self.updated_at = now
        self.save(update_fields=['status', 'worker_id', 'lease_expires_at', 'updated_at'])

    def mark_sent(self, worker_id=None):
        now = timezone.now()
        qs = OutgoingEmail.objects.filter(pk=self.pk, status=self.Status.PROCESSING)
        if worker_id:
            qs = qs.filter(worker_id=worker_id)
        rows = qs.update(
            status=self.Status.SENT,
            sent_at=now,
            last_error='',
            worker_id='',
            lease_expires_at=None,
            updated_at=now,
        )
        if rows:
            self.status = self.Status.SENT
            self.sent_at = now
            self.last_error = ''
            self.worker_id = ''
            self.lease_expires_at = None
            self.updated_at = now
        return bool(rows)

    def mark_expired(self, reason="Nachricht vor Versand abgelaufen."):
        now = timezone.now()
        self.status = self.Status.EXPIRED
        self.last_error = reason
        self.worker_id = ''
        self.lease_expires_at = None
        self.updated_at = now
        self.save(update_fields=['status', 'last_error', 'worker_id', 'lease_expires_at', 'updated_at'])

    def mark_paused(self, reason="E-Mail-Versand ist vorübergehend deaktiviert.", delay_seconds=30):
        """Pausiert den Sendeversuch ohne Fehlversuche (attempts) hochzuzählen."""
        now = timezone.now()
        self.status = self.Status.PENDING
        self.last_error = reason[:2000]
        self.scheduled_at = now + timedelta(seconds=delay_seconds)
        self.worker_id = ''
        self.lease_expires_at = None
        self.updated_at = now
        self.save(update_fields=['status', 'last_error', 'scheduled_at', 'worker_id', 'lease_expires_at', 'updated_at'])

    def mark_failed_attempt(self, error_message: str, is_pause: bool = False):
        if is_pause:
            self.mark_paused(error_message)
            return
        now = timezone.now()
        self.attempts += 1
        self.last_error = error_message[:2000]
        self.worker_id = ''
        self.lease_expires_at = None
        if self.attempts >= self.max_attempts:
            self.status = self.Status.FAILED
        else:
            self.status = self.Status.PENDING
            backoff_seconds = 60 * (2 ** (self.attempts - 1))
            self.scheduled_at = now + timedelta(seconds=backoff_seconds)
        self.updated_at = now
        self.save(update_fields=['attempts', 'last_error', 'status', 'scheduled_at', 'worker_id', 'lease_expires_at', 'updated_at'])

    def mark_stale_recovered(self, timeout_seconds: int):
        """Atomares Zurücksetzen auf PENDING oder FAILED, nur wenn noch PROCESSING und ungesendet."""
        now = timezone.now()
        new_attempts = self.attempts + 1
        err = f"Timeout nach {timeout_seconds}s im Status PROCESSING (Worker abgebrochen/stale)."
        if new_attempts >= self.max_attempts:
            new_status = self.Status.FAILED
            new_scheduled = self.scheduled_at
        else:
            new_status = self.Status.PENDING
            new_scheduled = now

        rows = OutgoingEmail.objects.filter(
            pk=self.pk,
            status=self.Status.PROCESSING,
            sent_at__isnull=True,
        ).update(
            attempts=new_attempts,
            last_error=err,
            status=new_status,
            scheduled_at=new_scheduled,
            worker_id='',
            lease_expires_at=None,
            updated_at=now,
        )
        if rows:
            self.attempts = new_attempts
            self.last_error = err
            self.status = new_status
            self.scheduled_at = new_scheduled
            self.worker_id = ''
            self.lease_expires_at = None
            self.updated_at = now
        return bool(rows)

    def reset_for_retry(self, reset_attempts: bool = True):
        """Setzt die E-Mail für einen sofortigen erneuten Sendeversuch zurück."""
        now = timezone.now()
        self.status = self.Status.PENDING
        self.scheduled_at = now
        self.worker_id = ''
        self.lease_expires_at = None
        self.updated_at = now
        update_fields = ['status', 'scheduled_at', 'worker_id', 'lease_expires_at', 'updated_at']
        if reset_attempts:
            self.attempts = 0
            update_fields.append('attempts')
        self.save(update_fields=update_fields)

