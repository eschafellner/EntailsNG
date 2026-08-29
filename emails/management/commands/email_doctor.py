import os
import socket
import sys
from django.conf import settings as dj_settings
from django.core.management.base import BaseCommand

from emails.crypto import is_readable
from emails.diagnostics import explain_smtp_error
from emails.models import EmailTemplate, GeneralEmailSettings
from emails.services import send_test_email


class Command(BaseCommand):
    help = "Diagnostiziert die E-Mail-Konfiguration und prüft Versandfähigkeit und Erreichbarkeit."

    def add_arguments(self, parser):
        parser.add_argument(
            '--send-to',
            dest='send_to',
            default='',
            help='Optionale E-Mail-Adresse für einen echten Testversand.',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== EntailsNG E-Mail Doctor ==="))
        is_healthy = True

        # 1. GeneralEmailSettings prüfen
        try:
            cfg = GeneralEmailSettings.load()
            self.stdout.write(self.style.SUCCESS(f"✓ Einstellungen geladen (ID: {cfg.pk})"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ E-Mail-Einstellungen nicht ladbar: {e}"))
            sys.exit(1)

        self.stdout.write(f"  - Versandweg: {cfg.get_transport_mode_display()} [{cfg.transport_mode}]")
        self.stdout.write(f"  - E-Mail-Versand aktiv (Kill-Switch): {'Ja' if cfg.is_enabled else 'NEIN (Versand blockiert)'}")
        self.stdout.write(f"  - Testmodus (Sandbox): {'Aktiv -> ' + cfg.sandbox_redirect_email if cfg.is_sandbox else 'Aus'}")

        if cfg.transport_mode == cfg.TransportMode.UNCONFIGURED:
            self.stdout.write(self.style.ERROR("✗ Versandweg ist noch nicht eingerichtet."))
            is_healthy = False

        if not cfg.is_enabled:
            self.stdout.write(self.style.WARNING("! E-Mail-Versand ist in den Einstellungen deaktiviert."))
            is_healthy = False

        # 2. Absenderadresse prüfen
        if cfg.sender_email:
            self.stdout.write(self.style.SUCCESS(f"✓ Absenderadresse: {cfg.sender_name} <{cfg.sender_email}>"))
        else:
            self.stdout.write(self.style.ERROR("✗ Keine Absenderadresse hinterlegt."))
            is_healthy = False

        # 3. Krypto & FIELD_ENCRYPTION_KEY prüfen
        field_key = os.environ.get('FIELD_ENCRYPTION_KEY') or getattr(dj_settings, 'FIELD_ENCRYPTION_KEY', '')
        if field_key:
            self.stdout.write(self.style.SUCCESS("✓ FIELD_ENCRYPTION_KEY ist in der Umgebung gesetzt."))
        else:
            self.stdout.write(self.style.WARNING("! FIELD_ENCRYPTION_KEY ist nicht gesetzt (nutzt SECRET_KEY als Fallback)."))

        # 4. Bei eigenem SMTP-Server Passwort-Lesbarkeit prüfen
        if cfg.transport_mode == cfg.TransportMode.CUSTOM_SMTP:
            if cfg.smtp_password:
                if is_readable(cfg.smtp_password):
                    self.stdout.write(self.style.SUCCESS("✓ Gespeichertes SMTP-Passwort ist erfolgreich entschlüsselbar."))
                else:
                    self.stdout.write(self.style.ERROR("✗ Gespeichertes SMTP-Passwort kann nicht entschlüsselt werden."))
                    is_healthy = False
            else:
                self.stdout.write(self.style.NOTICE("ℹ Kein SMTP-Passwort hinterlegt."))

        # 5. Aktive Transportparameter & TCP-Check
        if cfg.transport_mode == cfg.TransportMode.CUSTOM_SMTP:
            host = cfg.smtp_host
            port = cfg.smtp_port
            user = cfg.smtp_username or "(kein Benutzer)"
            tls = cfg.smtp_use_tls
            ssl = cfg.smtp_use_ssl
        else:
            host = getattr(dj_settings, 'EMAIL_HOST', '')
            port = getattr(dj_settings, 'EMAIL_PORT', 587)
            user = getattr(dj_settings, 'EMAIL_HOST_USER', '') or "(kein Benutzer)"
            tls = getattr(dj_settings, 'EMAIL_USE_TLS', True)
            ssl = getattr(dj_settings, 'EMAIL_USE_SSL', False)

        self.stdout.write(self.style.MIGRATE_LABEL("\nAktive Transportparameter:"))
        self.stdout.write(f"  - Server: {host}:{port}")
        self.stdout.write(f"  - Benutzer: {user}")
        self.stdout.write(f"  - Verschlüsselung: {'SSL' if ssl else ('TLS' if tls else 'Keine')}")

        if host and port:
            try:
                sock = socket.create_connection((host, int(port)), timeout=5)
                sock.close()
                self.stdout.write(self.style.SUCCESS(f"✓ TCP-Verbindung zu {host}:{port} erfolgreich aufgebaut."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ TCP-Verbindung zu {host}:{port} fehlgeschlagen: {e}"))
                is_healthy = False
        elif cfg.transport_mode != cfg.TransportMode.UNCONFIGURED:
            self.stdout.write(self.style.ERROR("✗ Serveradresse oder Port fehlen."))
            is_healthy = False

        # 6. E-Mail-Templates prüfen
        self.stdout.write(self.style.MIGRATE_LABEL("\nE-Mail-Templates:"))
        expected_keys = ['payment_confirmation', 'email_verification', 'password_reset']
        existing = {t.key: t for t in EmailTemplate.objects.all()}

        for k in expected_keys:
            if k in existing:
                t = existing[k]
                status_str = "aktiv" if t.is_active else "DEAKTIVIERT"
                color = self.style.SUCCESS if t.is_active else self.style.WARNING
                self.stdout.write(color(f"  ✓ Template '{k}' vorhanden ({status_str})"))
            else:
                self.stdout.write(self.style.ERROR(f"  ✗ Template '{k}' FEHLT in der Datenbank!"))
                is_healthy = False

        # 7. Optionaler Testversand
        send_to = options.get('send_to')
        if send_to:
            self.stdout.write(self.style.MIGRATE_LABEL(f"\nFühre Testversand an {send_to} durch..."))
            success, msg = send_test_email(send_to)
            if success:
                self.stdout.write(self.style.SUCCESS(f"✓ {msg}"))
            else:
                self.stdout.write(self.style.ERROR(f"✗ {msg}"))
                is_healthy = False

        # 8. Fazit
        self.stdout.write("\n" + "=" * 35)
        if is_healthy:
            self.stdout.write(self.style.SUCCESS("✓ Diagnose erfolgreich: E-Mail-System ist betriebsbereit."))
            sys.exit(0)
        else:
            self.stdout.write(self.style.ERROR("✗ Diagnose abgeschlossen: Es liegen Konfigurations- oder Erreichbarkeitsprobleme vor."))
            sys.exit(1)
