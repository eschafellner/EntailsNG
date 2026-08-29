import os
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from emails.admin import GeneralEmailSettingsForm
from emails.backends import ConfiguredSMTPBackend
from emails.context_processors import email_status
from emails.crypto import (
    SecretUnreadable,
    _get_fernet_key,
    decrypt_secret,
    encrypt_secret,
    is_readable,
)
from emails.models import EmailTemplate, GeneralEmailSettings
from emails.services import safe_format, send_system_email, send_test_email
from events.models import Event, EventRegistration

User = get_user_model()


class CryptoTests(TestCase):
    """Testet die kryptografischen Funktionen in emails/crypto.py."""

    def test_encrypt_decrypt_roundtrip(self):
        raw = "GeheimesPasswort123!?"
        cipher = encrypt_secret(raw)
        self.assertTrue(cipher.startswith("gAAAAA"))
        self.assertNotEqual(cipher, raw)
        self.assertEqual(decrypt_secret(cipher), raw)

    def test_encrypt_idempotency(self):
        raw = "AnotherSecretPassword"
        cipher1 = encrypt_secret(raw)
        cipher2 = encrypt_secret(cipher1)
        self.assertEqual(cipher1, cipher2)

    def test_decrypt_unreadable_raises_exception(self):
        """D3: Ungültiges Token darf nicht den Ciphertext stillschweigend zurückgeben."""
        invalid_cipher = "gAAAAABnzFakeCipherToken1234567890abcdef=="
        with self.assertRaises(SecretUnreadable):
            decrypt_secret(invalid_cipher)

    def test_decrypt_legacy_plaintext(self):
        """Altbestand ohne Fernet-Prefix wird mit Warning zurückgegeben."""
        plaintext = "legacy_unencrypted_password"
        self.assertEqual(decrypt_secret(plaintext), plaintext)

    @override_settings(SECRET_KEY="old-secret-key")
    def test_field_encryption_key_isolation(self):
        """D2: Mit FIELD_ENCRYPTION_KEY bleibt das Passwort bei SECRET_KEY-Wechsel lesbar."""
        with patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": "persistent-field-encryption-key-12345"}):
            raw = "MySecret123"
            cipher = encrypt_secret(raw)

            # Jetzt SECRET_KEY ändern
            with override_settings(SECRET_KEY="completely-new-rotated-secret-key"):
                decrypted = decrypt_secret(cipher)
                self.assertEqual(decrypted, raw)

    def test_is_readable(self):
        raw = "TestSecret"
        cipher = encrypt_secret(raw)
        self.assertTrue(is_readable(cipher))
        self.assertTrue(is_readable(""))
        self.assertFalse(is_readable("gAAAAABinvalidBrokenToken=="))


class GeneralEmailSettingsModelTests(TestCase):
    """Testet das Singleton-Modell GeneralEmailSettings."""

    def setUp(self):
        self.settings = GeneralEmailSettings.load()
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        self.settings.sender_email = "orga@example.com"
        self.settings.is_enabled = True
        self.settings.is_sandbox = False
        self.settings.save()

    def test_singleton_pk_enforced(self):
        s2 = GeneralEmailSettings(pk=99, sender_email="other@example.com")
        s2.save()
        self.assertEqual(s2.pk, 1)
        self.assertEqual(GeneralEmailSettings.objects.count(), 1)

    def test_set_smtp_password_and_save(self):
        self.settings.set_smtp_password("SuperSecret123")
        self.settings.save()
        self.settings.refresh_from_db()
        self.assertTrue(self.settings.smtp_password.startswith("gAAAAA"))
        self.assertEqual(self.settings.get_smtp_password(), "SuperSecret123")

    def test_multiple_saves_do_not_double_encrypt(self):
        """D4: Mehrfaches Speichern darf Passwörter nicht unlesbar machen."""
        self.settings.set_smtp_password("DoubleSaveCheck")
        self.settings.save()
        self.settings.save()
        self.settings.save()
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.get_smtp_password(), "DoubleSaveCheck")

    def test_clean_validation_tls_and_ssl_mutual_exclusion(self):
        self.settings.smtp_use_tls = True
        self.settings.smtp_use_ssl = True
        with self.assertRaises(ValidationError) as ctx:
            self.settings.clean()
        self.assertIn("smtp_use_ssl", ctx.exception.message_dict)

    def test_clean_validation_custom_smtp_requires_host(self):
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.CUSTOM_SMTP
        self.settings.smtp_host = ""
        with self.assertRaises(ValidationError) as ctx:
            self.settings.clean()
        self.assertIn("smtp_host", ctx.exception.message_dict)

    def test_clean_validation_sandbox_requires_redirect(self):
        self.settings.is_sandbox = True
        self.settings.sandbox_redirect_email = ""
        with self.assertRaises(ValidationError) as ctx:
            self.settings.clean()
        self.assertIn("sandbox_redirect_email", ctx.exception.message_dict)

    def test_clean_validation_enabled_requires_transport_mode_and_sender(self):
        self.settings.is_enabled = True
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.UNCONFIGURED
        self.settings.sender_email = ""
        with self.assertRaises(ValidationError) as ctx:
            self.settings.clean()
        self.assertIn("transport_mode", ctx.exception.message_dict)
        self.assertIn("sender_email", ctx.exception.message_dict)

    def test_is_operational_and_blocking_reason(self):
        # 1. Nicht eingerichtet
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.UNCONFIGURED
        self.assertFalse(self.settings.is_operational)
        self.assertIn("Versandweg", self.settings.blocking_reason)

        # 2. Deaktiviert
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        self.settings.is_enabled = False
        self.assertFalse(self.settings.is_operational)
        self.assertIn("ausgeschaltet", self.settings.blocking_reason)

        # 3. Keine Absenderadresse
        self.settings.is_enabled = True
        self.settings.sender_email = ""
        self.assertFalse(self.settings.is_operational)
        self.assertIn("Absenderadresse", self.settings.blocking_reason)

        # 4. Funktionsfähig
        self.settings.sender_email = "orga@lan.de"
        self.assertTrue(self.settings.is_operational)
        self.assertIsNone(self.settings.blocking_reason)

        # 5. Sandbox aktiv (operational=True, blocking_reason liefert Hinweis)
        self.settings.is_sandbox = True
        self.settings.sandbox_redirect_email = "test@sandbox.de"
        self.assertTrue(self.settings.is_operational)
        self.assertIn("Testmodus aktiv", self.settings.blocking_reason)

    def test_get_smtp_password_broken_key_sets_credentials_broken(self):
        self.settings.smtp_password = "gAAAAABinvalidBrokenToken1234=="
        self.settings.save()
        with self.assertRaises(SecretUnreadable):
            self.settings.get_smtp_password()
        self.settings.refresh_from_db()
        self.assertTrue(self.settings.credentials_broken)


class ConfiguredSMTPBackendTests(TestCase):
    """Testet das E-Mail-Backend ConfiguredSMTPBackend."""

    def setUp(self):
        self.settings = GeneralEmailSettings.load()
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        self.settings.sender_email = "system@entailsng.de"
        self.settings.sender_name = "EntailsNG Orga"
        self.settings.reply_to_email = "support@entailsng.de"
        self.settings.is_enabled = True
        self.settings.is_sandbox = False
        self.settings.save()

    @patch('emails.backends.SMTPBackend')
    def test_send_message_env_mode(self, mock_smtp_cls):
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.send_messages.return_value = 1
        mock_smtp_cls.return_value = mock_smtp_instance

        backend = ConfiguredSMTPBackend()
        msg = mail.EmailMessage(
            subject="Test Mail",
            body="Hello World",
            to=["guest@example.com"],
        )
        sent = backend.send_messages([msg])

        self.assertEqual(sent, 1)
        mock_smtp_cls.assert_called_once()
        # Absender und Reply-To müssen überschrieben worden sein
        self.assertEqual(msg.from_email, "EntailsNG Orga <system@entailsng.de>")
        self.assertEqual(msg.reply_to, ["support@entailsng.de"])

    @patch('emails.backends.SMTPBackend')
    def test_send_message_custom_smtp_mode(self, mock_smtp_cls):
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.CUSTOM_SMTP
        self.settings.smtp_host = "smtp.custom-mail.com"
        self.settings.smtp_port = 465
        self.settings.smtp_username = "smtpuser"
        self.settings.set_smtp_password("DecryptedSecret123")
        self.settings.smtp_use_tls = False
        self.settings.smtp_use_ssl = True
        self.settings.smtp_timeout = 15
        self.settings.save()

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.send_messages.return_value = 1
        mock_smtp_cls.return_value = mock_smtp_instance

        backend = ConfiguredSMTPBackend()
        msg = mail.EmailMessage(
            subject="Custom SMTP Test",
            body="Content",
            to=["recipient@example.com"],
        )
        sent = backend.send_messages([msg])

        self.assertEqual(sent, 1)
        mock_smtp_cls.assert_called_once_with(
            host="smtp.custom-mail.com",
            port=465,
            username="smtpuser",
            password="DecryptedSecret123",
            use_tls=False,
            use_ssl=True,
            timeout=15,
            fail_silently=False,
        )

    @patch('emails.backends.SMTPBackend')
    def test_kill_switch_blocks_send(self, mock_smtp_cls):
        self.settings.is_enabled = False
        self.settings.save()

        backend = ConfiguredSMTPBackend()
        msg = mail.EmailMessage(
            subject="Blocked", body="Content", to=["test@example.com"]
        )
        sent = backend.send_messages([msg])

        self.assertEqual(sent, 0)
        mock_smtp_cls.assert_not_called()

    @patch('emails.backends.SMTPBackend')
    def test_unconfigured_mode_blocks_send(self, mock_smtp_cls):
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.UNCONFIGURED
        self.settings.save()

        backend = ConfiguredSMTPBackend()
        msg = mail.EmailMessage(
            subject="Blocked", body="Content", to=["test@example.com"]
        )
        sent = backend.send_messages([msg])

        self.assertEqual(sent, 0)
        mock_smtp_cls.assert_not_called()

    @patch('emails.backends.SMTPBackend')
    def test_sandbox_mode_redirection_and_headers(self, mock_smtp_cls):
        self.settings.is_sandbox = True
        self.settings.sandbox_redirect_email = "dev-orga@example.com"
        self.settings.save()

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.send_messages.return_value = 1
        mock_smtp_cls.return_value = mock_smtp_instance

        backend = ConfiguredSMTPBackend()
        msg = mail.EmailMessage(
            subject="Willkommen",
            body="Registrierung",
            to=["realguest@example.com"],
            cc=["cc@example.com"],
        )
        sent = backend.send_messages([msg])

        self.assertEqual(sent, 1)
        self.assertEqual(msg.to, ["dev-orga@example.com"])
        self.assertEqual(msg.cc, [])
        self.assertTrue(msg.subject.startswith("[TESTMODUS]"))
        self.assertEqual(msg.extra_headers.get('X-EntailsNG-Original-To'), "realguest@example.com")

    @patch('emails.backends.SMTPBackend')
    def test_smtp_error_recording_and_clearing(self, mock_smtp_cls):
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.send_messages.side_effect = TimeoutError("Connection timed out")
        mock_smtp_cls.return_value = mock_smtp_instance

        backend = ConfiguredSMTPBackend(fail_silently=True)
        msg = mail.EmailMessage(subject="Fail", body="Text", to=["guest@example.com"])
        sent = backend.send_messages([msg])

        self.assertEqual(sent, 0)
        self.settings.refresh_from_db()
        self.assertIsNotNone(self.settings.last_send_error_at)
        self.assertIn("Zeitlimit", self.settings.last_send_error)

        # Bei nachfolgendem Erfolg wird der Fehler geleert
        mock_smtp_instance.send_messages.side_effect = None
        mock_smtp_instance.send_messages.return_value = 1
        sent2 = backend.send_messages([msg])
        self.assertEqual(sent2, 1)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.last_send_error, "")
        self.assertIsNone(self.settings.last_send_error_at)

    @override_settings(EMAIL_BACKEND='emails.backends.ConfiguredSMTPBackend')
    @patch('emails.backends.SMTPBackend')
    def test_django_password_reset_form_uses_db_configuration(self, mock_smtp_cls):
        """D7: Django PasswordResetForm nutzt das ConfiguredSMTPBackend."""
        user = User.objects.create_user(username="resetuser", email="reset@example.com", password="password")
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.send_messages.return_value = 1
        mock_smtp_cls.return_value = mock_smtp_instance

        rf = RequestFactory()
        request = rf.get('/auth/password_reset/')

        form = PasswordResetForm(data={'email': 'reset@example.com'})
        self.assertTrue(form.is_valid())
        form.save(request=request, use_https=False, from_email=None)

        self.assertTrue(mock_smtp_instance.send_messages.called)
        sent_messages = mock_smtp_instance.send_messages.call_args[0][0]
        self.assertEqual(len(sent_messages), 1)
        msg = sent_messages[0]
        self.assertEqual(msg.from_email, "EntailsNG Orga <system@entailsng.de>")


class EmailServicesTests(TestCase):
    """Testet emails/services.py."""

    def setUp(self):
        self.settings = GeneralEmailSettings.load()
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        self.settings.sender_email = "orga@entailsng.de"
        self.settings.is_enabled = True
        self.settings.is_sandbox = False
        self.settings.save()

        self.template = EmailTemplate.objects.create(
            key='test_template',
            name='Test Vorlage',
            subject='Hallo {username} zu {event_title}',
            content='<p>Hallo <strong>{username}</strong>, dein Betrag ist {amount} Euro.</p>',
            is_active=True,
        )

    def test_safe_format_placeholders_and_none(self):
        text = "Hello {name}, score: {score}, missing: {missing}"
        res = safe_format(text, {'name': 'Max', 'score': None})
        self.assertEqual(res, "Hello Max, score: , missing: {missing}")

    @override_settings(EMAIL_BACKEND='emails.backends.ConfiguredSMTPBackend')
    @patch('emails.backends.SMTPBackend')
    def test_send_system_email_success(self, mock_smtp_cls):
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.send_messages.return_value = 1
        mock_smtp_cls.return_value = mock_smtp_instance

        success = send_system_email(
            'test_template',
            'guest@example.com',
            {'username': 'Gamer1', 'event_title': 'LAN 2026', 'amount': '15'},
        )
        self.assertTrue(success)
        mock_smtp_instance.send_messages.assert_called_once()
        sent_msgs = mock_smtp_instance.send_messages.call_args[0][0]
        self.assertEqual(len(sent_msgs), 1)
        msg = sent_msgs[0]
        self.assertEqual(msg.subject, "Hallo Gamer1 zu LAN 2026")
        self.assertIn("Hallo Gamer1, dein Betrag ist 15 Euro.", msg.body)

    def test_send_system_email_missing_template(self):
        success = send_system_email('non_existing_key', 'guest@example.com', {})
        self.assertFalse(success)

    def test_send_system_email_inactive_template(self):
        self.template.is_active = False
        self.template.save()
        success = send_system_email('test_template', 'guest@example.com', {})
        self.assertFalse(success)

    @patch('emails.backends.SMTPBackend.send_messages')
    def test_send_test_email_bypasses_kill_switch(self, mock_smtp_send):
        """Verbindungstest funktioniert auch bei is_enabled=False."""
        self.settings.is_enabled = False
        self.settings.save()
        mock_smtp_send.return_value = 1

        success, msg = send_test_email('admin@example.com')
        self.assertTrue(success)
        self.assertIn("Testnachricht an admin@example.com gesendet", msg)

        self.settings.refresh_from_db()
        self.assertTrue(self.settings.last_test_ok)
        self.assertIsNotNone(self.settings.last_test_at)


class AdminAndContextProcessorTests(TestCase):
    """Testet Admin-Formular und den Staff-Context-Processor."""

    def setUp(self):
        self.rf = RequestFactory()
        self.admin_user = User.objects.create_superuser(
            username='adminuser', email='admin@example.com', password='password'
        )
        self.normal_user = User.objects.create_user(
            username='guestuser', email='guest@example.com', password='password'
        )
        self.settings = GeneralEmailSettings.load()
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        self.settings.sender_email = "orga@example.com"
        self.settings.is_enabled = True
        self.settings.save()

    def test_admin_form_password_handling(self):
        self.settings.set_smtp_password("ExistingPassword123")
        self.settings.save()

        # 1. Speichern ohne Passworteingabe -> bestehendes Passwort bleibt erhalten
        form = GeneralEmailSettingsForm(
            data={
                'transport_mode': 'env',
                'sender_email': 'orga@example.com',
                'is_enabled': True,
                'smtp_port': 587,
                'smtp_timeout': 10,
            },
            instance=self.settings,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.get_smtp_password(), "ExistingPassword123")

        # 2. Neues Passwort setzen
        form2 = GeneralEmailSettingsForm(
            data={
                'transport_mode': 'env',
                'sender_email': 'orga@example.com',
                'is_enabled': True,
                'smtp_port': 587,
                'smtp_timeout': 10,
                'smtp_password': 'BrandNewSecretPassword',
            },
            instance=saved,
        )
        self.assertTrue(form2.is_valid(), form2.errors)
        saved2 = form2.save()
        self.assertTrue(saved2.smtp_password.startswith("gAAAAA"))
        self.assertEqual(saved2.get_smtp_password(), "BrandNewSecretPassword")

        # 3. Passwort löschen
        form3 = GeneralEmailSettingsForm(
            data={
                'transport_mode': 'env',
                'sender_email': 'orga@example.com',
                'is_enabled': True,
                'smtp_port': 587,
                'smtp_timeout': 10,
                'clear_smtp_password': 'on',
            },
            instance=saved2,
        )
        self.assertTrue(form3.is_valid(), form3.errors)
        saved3 = form3.save()
        self.assertEqual(saved3.smtp_password, "")

    def test_context_processor_staff_vs_guest(self):
        # Operational und kein Sandbox -> keine Warnung
        req_staff = self.rf.get('/')
        req_staff.user = self.admin_user
        self.assertEqual(email_status(req_staff), {})

        # Deaktiviert -> Warnung für Staff
        self.settings.is_enabled = False
        self.settings.save()
        res_staff = email_status(req_staff)
        self.assertIn('email_warning', res_staff)
        self.assertFalse(res_staff['email_warning_is_info'])

        # Für normalen Gast -> leer
        req_guest = self.rf.get('/')
        req_guest.user = self.normal_user
        self.assertEqual(email_status(req_guest), {})

    def test_original_failure_is_now_visible_and_guarded(self):
        """
        Reproduziert den realen Ausfall:
        is_enabled=False, transport_mode=unconfigured, kein Absender.
        Die Registrierung blockiert das Anlegen inaktiver Phantomkonten.
        """
        self.settings.is_enabled = False
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.UNCONFIGURED
        self.settings.sender_email = ""
        self.settings.save()

        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anmeldung vorübergehend pausiert")
        self.assertContains(response, "E-Mail-Versand")
