from django.db import models
from tinymce.models import HTMLField


class GeneralEmailSettings(models.Model):
    """Singleton-Modell für Allgemeine E-Mail Einstellungen"""

    sender_email = models.EmailField(
        default='noreply@entailsng.de',
        verbose_name="Absender E-Mail-Adresse",
        help_text="Absenderadresse für alle ausgehenden System-E-Mails.",
    )
    sender_name = models.CharField(
        max_length=100,
        default='EntailsNG Event-Team',
        verbose_name="Absender Name",
        help_text="Anzeigename des Absenders (z. B. EntailsNG Team).",
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
        verbose_name="E-Mail-Versand aktivieren",
        help_text="Schaltet den automatischen E-Mail-Versand im System ein oder aus.",
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
    smtp_password = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name="SMTP Passwort",
        help_text="Wird in der Datenbank verschlüsselt gespeichert.",
    )
    smtp_use_tls = models.BooleanField(
        default=True, verbose_name="TLS Verschlüsselung nutzen"
    )

    class Meta:
        verbose_name = "Allgemeine E-Mail Einstellung"
        verbose_name_plural = "Allgemeine E-Mail Einstellungen"

    def __str__(self):
        status = "Aktiv" if self.is_enabled else "Inaktiv"
        sandbox = " (SANDBOX MODUS)" if self.is_sandbox else ""
        return f"Allgemeine E-Mail Einstellungen: {status}{sandbox}"

    def get_smtp_password(self) -> str:
        """Gibt das entschlüsselte SMTP-Passwort für den Versand zurück."""
        from .crypto import decrypt_smtp_password
        return decrypt_smtp_password(self.smtp_password)

    def set_smtp_password(self, raw_password: str) -> None:
        """Verschlüsselt und setzt das SMTP-Passwort."""
        from .crypto import encrypt_smtp_password
        self.smtp_password = encrypt_smtp_password(raw_password)

    def save(self, *args, **kwargs):
        # Erzwinge Singleton (nur 1 Datensatz)
        self.pk = 1
        # Passwort automatisch verschlüsseln, falls es im Klartext gesetzt wurde
        if self.smtp_password:
            from .crypto import encrypt_smtp_password
            self.smtp_password = encrypt_smtp_password(self.smtp_password)
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
