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
from emails.models import EmailTemplate, GeneralEmailSettings, OutgoingEmail
from emails.services import (
    process_email_queue,
    queue_system_email,
    safe_format,
    send_system_email,
    send_test_email,
)
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

    def test_is_operational_env_mode_ignores_broken_custom_credentials(self):
        """Wenn transport_mode=ENV aktiv ist, blockieren defekte Custom-SMTP-Zugangsdaten nicht."""
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        self.settings.credentials_broken = True
        self.settings.save()
        self.assertTrue(self.settings.is_operational)
        self.assertIsNone(self.settings.blocking_reason)

        # Im CUSTOM_SMTP-Modus blockieren defekte Zugangsdaten dagegen
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.CUSTOM_SMTP
        self.settings.smtp_host = "mail.example.com"
        self.settings.save()
        self.assertFalse(self.settings.is_operational)
        self.assertIn("SMTP-Passwort kann nicht gelesen werden", self.settings.blocking_reason)

    def test_long_smtp_password_stored_in_text_field(self):
        """Passwörter > 200 Zeichen erzeugen Ciphertexte > 255 Zeichen und werden im TextField ohne Truncation gespeichert."""
        long_pwd = "A" * 200
        self.settings.set_smtp_password(long_pwd)
        self.assertGreater(len(self.settings.smtp_password), 255)
        self.settings.save()
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.get_smtp_password(), long_pwd)


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

    def test_safe_format_escape_html(self):
        text = "<p>User: {username}</p>"
        res = safe_format(text, {'username': '<script>alert(1)</script>'}, escape_html=True)
        self.assertEqual(res, "<p>User: &lt;script&gt;alert(1)&lt;/script&gt;</p>")

        res_plain = safe_format(text, {'username': '<script>alert(1)</script>'}, escape_html=False)
        self.assertEqual(res_plain, "<p>User: <script>alert(1)</script></p>")

    def test_safe_format_single_pass_no_cascading_injection(self):
        """Single-Pass Ersetzung verhindert rekursive/kaskadierende Platzhalter-Injektion."""
        text = "Hello {first_name}, status: {status}"
        context = {
            'first_name': '{secret_code}',
            'secret_code': 'EXPLOIT_LEAK',
            'status': 'active',
        }
        res = safe_format(text, context)
        # {first_name} wird zu {secret_code}, darf aber im selben Durchlauf NICHT zu EXPLOIT_LEAK aufgelöst werden
        self.assertEqual(res, "Hello {secret_code}, status: active")

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

    @patch('emails.backends.SMTPBackend.send_messages')
    def test_send_test_email_zero_messages_fails(self, mock_smtp_send):
        """Wenn backend.send_messages 0 zurückliefert, schlägt der Testversand fehl."""
        mock_smtp_send.return_value = 0
        success, msg = send_test_email('admin@example.com')
        self.assertFalse(success)
        self.assertIn("0 Nachrichten gesendet", msg)

    def test_send_test_email_sandbox_without_redirect_fails(self):
        """Sandbox-Modus ohne hinterlegte Weiterleitungsadresse verweigert Test-Mails."""
        self.settings.is_sandbox = True
        self.settings.sandbox_redirect_email = ""
        self.settings.save()
        success, msg = send_test_email('admin@example.com')
        self.assertFalse(success)
        self.assertIn("Testmodus (Sandbox) ist aktiv", msg)


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

    def test_admin_views_permission_denied_for_unprivileged_staff(self):
        """Staff-Benutzer ohne change_generalemailsettings-Berechtigung erhalten 403 Forbidden."""
        staff_user = User.objects.create_user(
            username='staff_noperm', email='staffnoperm@example.com', password='password', is_staff=True
        )
        self.client.login(username='staff_noperm', password='password')

        resp_test = self.client.get(reverse('admin:emails_send_test_email'))
        self.assertEqual(resp_test.status_code, 403)

        resp_post = self.client.post(reverse('admin:emails_send_test_email'), {'target_email': 'test@example.com'})
        self.assertEqual(resp_post.status_code, 403)

        resp_dns = self.client.get(reverse('admin:emails_check_dns_health'))
        self.assertEqual(resp_dns.status_code, 403)

    def test_admin_views_allowed_for_superuser_and_permitted_staff(self):
        """Superuser und Staff mit change_generalemailsettings-Berechtigung dürfen die Endpunkte aufrufen."""
        from django.contrib.auth.models import Permission
        staff_user = User.objects.create_user(
            username='staff_with_perm', email='staffperm@example.com', password='password', is_staff=True
        )
        perm = Permission.objects.get(codename='change_generalemailsettings')
        staff_user.user_permissions.add(perm)

        self.client.login(username='staff_with_perm', password='password')
        resp_test = self.client.get(reverse('admin:emails_send_test_email'))
        self.assertEqual(resp_test.status_code, 200)

        with patch('emails.admin.check_domain_dns_health') as mock_dns:
            mock_dns.return_value = {'status': 'ok', 'spf': {}, 'dmarc': {}, 'mx': {}, 'dkim': {}}
            resp_dns = self.client.get(reverse('admin:emails_check_dns_health'))
            self.assertEqual(resp_dns.status_code, 200)


class OutgoingEmailQueueTests(TestCase):
    """Testet die persistente E-Mail-Versandwarteschlange (Transactional Outbox)."""

    def setUp(self):
        self.settings = GeneralEmailSettings.load()
        self.settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        self.settings.sender_email = "noreply@example.com"
        self.settings.is_enabled = True
        self.settings.save()

        self.template = EmailTemplate.objects.create(
            key='queue_test_tpl',
            name='Queue Test Template',
            subject='Hallo {username}',
            content='<p>Hallo {username}, Willkommen!</p>',
            is_active=True,
        )

    def test_queue_system_email_creates_pending_record(self):
        """queue_system_email legt einen Datensatz mit Status PENDING und gerendertem Inhalt an."""
        outgoing = queue_system_email(
            'queue_test_tpl',
            'player@example.com',
            {'username': 'PixelHero'},
            trigger_worker=False,
        )
        self.assertIsNotNone(outgoing)
        self.assertEqual(outgoing.status, OutgoingEmail.Status.PENDING)
        self.assertEqual(outgoing.recipient_email, 'player@example.com')
        self.assertEqual(outgoing.subject, 'Hallo PixelHero')
        self.assertIn('Hallo PixelHero, Willkommen!', outgoing.body_html)
        self.assertIn('Hallo PixelHero, Willkommen!', outgoing.body_text)
        self.assertEqual(outgoing.attempts, 0)
        self.assertEqual(outgoing.max_attempts, 5)

    def test_send_system_email_immediate_false_queues_email(self):
        """send_system_email mit immediate=False legt die Mail in die Warteschlange."""
        success = send_system_email(
            'queue_test_tpl',
            'player2@example.com',
            {'username': 'Player2'},
            immediate=False,
        )
        self.assertTrue(success)
        self.assertTrue(OutgoingEmail.objects.filter(recipient_email='player2@example.com').exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_process_email_queue_success(self):
        """Fällige E-Mails werden versendet und als SENT markiert."""
        outgoing = queue_system_email(
            'queue_test_tpl',
            'sent@example.com',
            {'username': 'SentUser'},
            trigger_worker=False,
        )
        sent, failed = process_email_queue(limit=10)
        self.assertEqual(sent, 1)
        self.assertEqual(failed, 0)

        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.SENT)
        self.assertIsNotNone(outgoing.sent_at)
        self.assertEqual(outgoing.last_error, '')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    @patch('emails.services.EmailMultiAlternatives.send')
    def test_process_email_queue_temporary_failure_backoff(self, mock_send):
        """Temporäre Fehler erhöhen den Zähler und setzen scheduled_at per exponentiellem Backoff."""
        mock_send.side_effect = Exception("SMTP-Timeout beim Verbindungsaufbau")

        outgoing = queue_system_email(
            'queue_test_tpl',
            'retry@example.com',
            {'username': 'RetryUser'},
            trigger_worker=False,
        )
        sent, failed = process_email_queue(limit=10)
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 1)

        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.PENDING)
        self.assertEqual(outgoing.attempts, 1)
        self.assertIn("SMTP-Timeout", outgoing.last_error)
        self.assertGreater(outgoing.scheduled_at, timezone.now())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    @patch('emails.services.EmailMultiAlternatives.send')
    def test_process_email_queue_max_attempts_fails(self, mock_send):
        """Nach Erreichen von max_attempts wird der Status auf FAILED gesetzt."""
        mock_send.side_effect = Exception("Permanent gesperrter Server")

        outgoing = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='fail@example.com',
            subject='Fail Test',
            body_text='Fail',
            body_html='<p>Fail</p>',
            status=OutgoingEmail.Status.PENDING,
            attempts=4,
            max_attempts=5,
            scheduled_at=timezone.now() - timedelta(minutes=1),
        )

        sent, failed = process_email_queue(limit=10)
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 1)

        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.FAILED)
        self.assertEqual(outgoing.attempts, 5)

    def test_management_command_process_email_queue(self):
        """Management-Command 'process_email_queue' läuft ohne Fehler durch."""
        from django.core.management import call_command
        queue_system_email(
            'queue_test_tpl',
            'cmd@example.com',
            {'username': 'CmdUser'},
            trigger_worker=False,
        )
        call_command('process_email_queue', limit=5)
        outgoing = OutgoingEmail.objects.get(recipient_email='cmd@example.com')
        self.assertEqual(outgoing.status, OutgoingEmail.Status.SENT)

    def test_admin_badge_and_retry_action(self):
        """Admin-Badges und Retry-Action funktionieren wie erwartet."""
        from django.contrib.admin.sites import AdminSite
        from emails.admin import OutgoingEmailAdmin, retry_outgoing_emails

        admin_instance = OutgoingEmailAdmin(OutgoingEmail, AdminSite())
        outgoing = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='admin_test@example.com',
            subject='Admin Test',
            body_text='Admin',
            body_html='<p>Admin</p>',
            status=OutgoingEmail.Status.FAILED,
            attempts=5,
            max_attempts=5,
        )

        badge_html = admin_instance.status_badge(outgoing)
        self.assertIn("Fehlgeschlagen", badge_html)
        self.assertEqual(admin_instance.attempts_display(outgoing), "5 / 5")

        # Retry Action
        rf = RequestFactory()
        req = rf.post('/admin/emails/outgoingemail/')
        from django.contrib.messages.middleware import MessageMiddleware
        from django.contrib.sessions.middleware import SessionMiddleware
        SessionMiddleware(lambda r: None).process_request(req)
        MessageMiddleware(lambda r: None).process_request(req)

        retry_outgoing_emails(admin_instance, req, OutgoingEmail.objects.filter(pk=outgoing.pk))
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.PENDING)

    def test_recover_stale_processing_emails_resets_to_pending(self):
        """E-Mails im Status PROCESSING, die älter als der Lease-Timeout sind, werden auf PENDING zurückgesetzt."""
        from emails.services import recover_stale_processing_emails

        outgoing = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='stale@example.com',
            subject='Stale Test',
            body_text='Stale',
            body_html='<p>Stale</p>',
            status=OutgoingEmail.Status.PROCESSING,
            attempts=1,
            max_attempts=3,
        )
        # Manuell in die Vergangenheit datieren
        OutgoingEmail.objects.filter(pk=outgoing.pk).update(
            updated_at=timezone.now() - timedelta(seconds=400)
        )

        recovered = recover_stale_processing_emails(timeout_seconds=300)
        self.assertEqual(recovered, 1)

        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.PENDING)
        self.assertEqual(outgoing.attempts, 2)
        self.assertIn("Timeout nach 300s", outgoing.last_error)

    def test_recover_stale_processing_emails_marks_failed_on_max_attempts(self):
        """Stale PROCESSING E-Mails, die max_attempts erreichen, werden auf FAILED gesetzt."""
        from emails.services import recover_stale_processing_emails

        outgoing = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='stale_fail@example.com',
            subject='Stale Fail Test',
            body_text='Stale Fail',
            body_html='<p>Stale Fail</p>',
            status=OutgoingEmail.Status.PROCESSING,
            attempts=2,
            max_attempts=3,
        )
        OutgoingEmail.objects.filter(pk=outgoing.pk).update(
            updated_at=timezone.now() - timedelta(seconds=400)
        )

        recovered = recover_stale_processing_emails(timeout_seconds=300)
        self.assertEqual(recovered, 1)

        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.FAILED)
        self.assertEqual(outgoing.attempts, 3)

    def test_recover_stale_processing_emails_ignores_recent_processing(self):
        """Laufende PROCESSING-Einträge innerhalb des Timeouts werden nicht angerührt."""
        from emails.services import recover_stale_processing_emails

        outgoing = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='active_proc@example.com',
            subject='Active Proc',
            body_text='Active',
            body_html='<p>Active</p>',
            status=OutgoingEmail.Status.PROCESSING,
            attempts=0,
            max_attempts=3,
        )
        # updated_at ist jetzt (frisch angelegt)
        recovered = recover_stale_processing_emails(timeout_seconds=300)
        self.assertEqual(recovered, 0)

        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.PROCESSING)
        self.assertEqual(outgoing.attempts, 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_process_email_queue_recovers_and_sends_stale_email(self):
        """process_email_queue stellt verwaiste PROCESSING-Einträge wieder her und versendet sie im selben Lauf."""
        outgoing = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='recovered_send@example.com',
            subject='Recovered Send',
            body_text='Recovered Body',
            body_html='<p>Recovered Body</p>',
            status=OutgoingEmail.Status.PROCESSING,
            attempts=0,
            max_attempts=3,
        )
        OutgoingEmail.objects.filter(pk=outgoing.pk).update(
            updated_at=timezone.now() - timedelta(seconds=600)
        )

        sent, failed = process_email_queue(limit=10)
        self.assertEqual(sent, 1)
        self.assertEqual(failed, 0)

        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.SENT)
        self.assertEqual(outgoing.attempts, 1)

    @override_settings(FORCE_EMAIL_ASYNC_QUEUE=True, EMAIL_ASYNC_QUEUE=True)
    def test_send_system_email_default_uses_async_queue_when_configured(self):
        """send_system_email legt die Mail standardmäßig in die Warteschlange, wenn EMAIL_ASYNC_QUEUE aktiv ist."""
        success = send_system_email(
            'queue_test_tpl',
            'async_default@example.com',
            {'username': 'AsyncUser'},
            immediate=None,
        )
        self.assertTrue(success)
        self.assertTrue(OutgoingEmail.objects.filter(recipient_email='async_default@example.com').exists())

    @override_settings(
        FORCE_EMAIL_ASYNC_QUEUE=True,
        EMAIL_ASYNC_QUEUE=False,
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
    )
    def test_send_system_email_default_uses_sync_when_async_disabled(self):
        """send_system_email versendet synchron, wenn EMAIL_ASYNC_QUEUE=False konfiguriert ist."""
        from django.core import mail
        success = send_system_email(
            'queue_test_tpl',
            'sync_default@example.com',
            {'username': 'SyncUser'},
            immediate=None,
        )
        self.assertTrue(success)
        self.assertFalse(OutgoingEmail.objects.filter(recipient_email='sync_default@example.com').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['sync_default@example.com'])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_process_email_queue_filters_by_email_ids(self):
        """process_email_queue mit email_ids verarbeitet ausschließlich die angegebenen IDs."""
        e1 = queue_system_email('queue_test_tpl', 'filter1@example.com', {'username': 'U1'}, trigger_worker=False)
        e2 = queue_system_email('queue_test_tpl', 'filter2@example.com', {'username': 'U2'}, trigger_worker=False)
        e3 = queue_system_email('queue_test_tpl', 'filter3@example.com', {'username': 'U3'}, trigger_worker=False)

        sent, failed = process_email_queue(email_ids=[e1.pk, e3.pk])
        self.assertEqual(sent, 2)
        self.assertEqual(failed, 0)

        e1.refresh_from_db()
        e2.refresh_from_db()
        e3.refresh_from_db()
        self.assertEqual(e1.status, OutgoingEmail.Status.SENT)
        self.assertEqual(e2.status, OutgoingEmail.Status.PENDING)
        self.assertEqual(e3.status, OutgoingEmail.Status.SENT)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_admin_action_process_now_respects_selected_ids(self):
        """Admin-Aktion 'Ausgewählte E-Mails jetzt sofort versenden' versendet nur selektierte IDs."""
        from django.contrib.admin.sites import AdminSite
        from emails.admin import OutgoingEmailAdmin, process_outgoing_emails_now

        admin_instance = OutgoingEmailAdmin(OutgoingEmail, AdminSite())
        e1 = queue_system_email('queue_test_tpl', 'sel1@example.com', {'username': 'U1'}, trigger_worker=False)
        e2 = queue_system_email('queue_test_tpl', 'sel2@example.com', {'username': 'U2'}, trigger_worker=False)

        rf = RequestFactory()
        req = rf.post('/admin/emails/outgoingemail/')
        from django.contrib.messages.middleware import MessageMiddleware
        from django.contrib.sessions.middleware import SessionMiddleware
        SessionMiddleware(lambda r: None).process_request(req)
        MessageMiddleware(lambda r: None).process_request(req)

        process_outgoing_emails_now(admin_instance, req, OutgoingEmail.objects.filter(pk=e1.pk))

        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertEqual(e1.status, OutgoingEmail.Status.SENT)
        self.assertEqual(e2.status, OutgoingEmail.Status.PENDING)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_admin_action_retry_outgoing_emails_respects_selected_ids(self):
        """Admin-Aktion 'Ausgewählte E-Mails erneut in Warteschlange einreihen' verarbeitet nur selektierte IDs."""
        from django.contrib.admin.sites import AdminSite
        from emails.admin import OutgoingEmailAdmin, retry_outgoing_emails

        admin_instance = OutgoingEmailAdmin(OutgoingEmail, AdminSite())
        e1 = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='retry1@example.com',
            subject='Retry 1',
            body_text='Retry 1',
            status=OutgoingEmail.Status.FAILED,
            attempts=5,
            max_attempts=5,
        )
        e2 = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='retry2@example.com',
            subject='Retry 2',
            body_text='Retry 2',
            status=OutgoingEmail.Status.FAILED,
            attempts=5,
            max_attempts=5,
        )

        rf = RequestFactory()
        req = rf.post('/admin/emails/outgoingemail/')
        from django.contrib.messages.middleware import MessageMiddleware
        from django.contrib.sessions.middleware import SessionMiddleware
        SessionMiddleware(lambda r: None).process_request(req)
        MessageMiddleware(lambda r: None).process_request(req)

        retry_outgoing_emails(admin_instance, req, OutgoingEmail.objects.filter(pk=e1.pk))

        e1.refresh_from_db()
        e2.refresh_from_db()
        self.assertEqual(e1.status, OutgoingEmail.Status.PENDING)
        self.assertEqual(e1.attempts, 0)
        self.assertEqual(e2.status, OutgoingEmail.Status.FAILED)
        self.assertEqual(e2.attempts, 5)

    def test_process_email_queue_marks_expired(self):
        """E-Mails, deren expires_at in der Vergangenheit liegt, werden als EXPIRED markiert und nicht gesendet."""
        e = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='expired@example.com',
            subject='Expired Test',
            body_text='Expired Body',
            status=OutgoingEmail.Status.PENDING,
            expires_at=timezone.now() - timedelta(minutes=5),
        )

        sent, failed = process_email_queue()
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 0)

        e.refresh_from_db()
        self.assertEqual(e.status, OutgoingEmail.Status.EXPIRED)
        self.assertIn("abgelaufen", e.last_error)
        self.assertEqual(e.attempts, 0)

    def test_recover_stale_processing_emails_does_not_overwrite_already_sent(self):
        """Wenn eine E-Mail bereits als gesendet markiert ist (sent_at gesetzt), darf Stale Recovery sie nicht auf PENDING zurücksetzen."""
        from emails.services import recover_stale_processing_emails

        outgoing = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='alreadysent@example.com',
            subject='Already Sent',
            body_text='Already Sent',
            status=OutgoingEmail.Status.PROCESSING,
            sent_at=timezone.now(),
            attempts=1,
            max_attempts=3,
        )
        OutgoingEmail.objects.filter(pk=outgoing.pk).update(
            updated_at=timezone.now() - timedelta(seconds=600)
        )

        recovered = recover_stale_processing_emails(timeout_seconds=300)
        self.assertEqual(recovered, 0)

        outgoing.refresh_from_db()
        self.assertIsNotNone(outgoing.sent_at)

    def test_mark_sent_rejects_mismatched_worker_or_missing_lease(self):
        """mark_sent verweigert das Update, wenn ein anderer Worker den Lease übernommen hat."""
        outgoing = OutgoingEmail.objects.create(
            template_key='queue_test_tpl',
            recipient_email='workerlease@example.com',
            subject='Lease Test',
            body_text='Lease',
            status=OutgoingEmail.Status.PENDING,
        )
        outgoing.mark_processing(worker_id="worker-A", lease_seconds=60)
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.PROCESSING)
        self.assertEqual(outgoing.worker_id, "worker-A")

        # Worker B versucht mark_sent auszuführen -> Fehlschlag
        res_b = outgoing.mark_sent(worker_id="worker-B")
        self.assertFalse(res_b)
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.PROCESSING)

        # Worker A führt mark_sent aus -> Erfolg
        res_a = outgoing.mark_sent(worker_id="worker-A")
        self.assertTrue(res_a)
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.SENT)

    def test_process_email_queue_paused_when_not_operational(self):
        """Wenn das E-Mail-System pausiert/deaktiviert ist, bricht process_email_queue ab ohne attempts zu erhöhen."""
        self.settings.is_enabled = False
        self.settings.save()

        e = queue_system_email('queue_test_tpl', 'paused@example.com', {'username': 'P'}, trigger_worker=False)
        # Normaler Durchlauf bricht sofort ab, E-Mail bleibt PENDING und unberührt
        sent, failed = process_email_queue()
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 0)

        e.refresh_from_db()
        self.assertEqual(e.status, OutgoingEmail.Status.PENDING)
        self.assertEqual(e.attempts, 0)

        # Gezielter Durchlauf mit expliziten email_ids markiert die E-Mail als pausiert
        sent, failed = process_email_queue(email_ids=[e.pk])
        self.assertEqual(sent, 0)
        self.assertEqual(failed, 0)
        e.refresh_from_db()
        self.assertEqual(e.status, OutgoingEmail.Status.PENDING)
        self.assertEqual(e.attempts, 0)
        self.assertIn("pausiert", e.last_error)


class DNSHealthCheckerTests(TestCase):
    """Testet die DNS-Gesundheitsprüfung in emails/dns_checker.py."""

    @patch('emails.dns_checker.query_dns_json')
    def test_dns_checker_unreachable_status_on_network_error(self, mock_query):
        from emails.dns_checker import check_domain_dns_health

        mock_query.return_value = None
        result = check_domain_dns_health('lanparty.de')
        self.assertEqual(result['status'], 'unreachable')
        self.assertIn('Offline-Betrieb', result['message'])
        self.assertIn('Nicht prüfbar', result['spf']['record'])

    @patch('emails.dns_checker.query_dns_json')
    def test_dns_checker_healthy_records(self, mock_query):
        from emails.dns_checker import check_domain_dns_health

        def query_side_effect(domain, rtype):
            if rtype == 'TXT' and domain == 'lanparty.de':
                return ['v=spf1 mx ~all']
            if rtype == 'TXT' and domain == '_dmarc.lanparty.de':
                return ['v=DMARC1; p=reject;']
            if rtype == 'MX':
                return ['10 mail.lanparty.de']
            if rtype == 'TXT' and 'default._domainkey' in domain:
                return ['v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GN...']
            return []

        mock_query.side_effect = query_side_effect
        result = check_domain_dns_health('lanparty.de')
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result['spf']['valid'])
        self.assertTrue(result['dmarc']['valid'])
        self.assertTrue(result['mx']['valid'])
        self.assertTrue(result['dkim']['valid'])
