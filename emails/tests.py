from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.utils import timezone
from events.models import Event, EventRegistration
from emails.models import EmailTemplate, GeneralEmailSettings
from emails.services import send_system_email

User = get_user_model()


class EmailSystemTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='emailuser',
            email='testguest@example.com',
            first_name='Max',
            last_name='Mustermann',
            password='password',
        )
        self.event = Event.objects.create(
            title='E-Mail LAN 2026',
            slug='email-lan-2026',
            is_active=True,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=2),
        )

        self.settings = GeneralEmailSettings.load()
        self.settings.sender_email = 'orga@entailsng.de'
        self.settings.is_enabled = True
        self.settings.is_sandbox = False
        self.settings.save()

        self.template, _ = EmailTemplate.objects.get_or_create(
            key='payment_confirmation',
            defaults={
                'name': 'Zahlungsbestätigung',
                'subject': 'Zahlungseingang für {event_title}',
                'content': '<p>Hallo {full_name}, danke für {amount} €!</p>',
                'is_active': True,
            },
        )
        self.template.subject = 'Zahlungseingang für {event_title}'
        self.template.content = '<p>Hallo {full_name}, danke für {amount} €!</p>'
        self.template.is_active = True
        self.template.save()


    def test_send_system_email_normal(self):
        success = send_system_email(
            'payment_confirmation',
            'testguest@example.com',
            {'full_name': 'Max Mustermann', 'event_title': 'E-Mail LAN 2026', 'amount': '25.00'},
        )
        self.assertTrue(success)
        self.assertEqual(len(mail.outbox), 1)
        sent_msg = mail.outbox[0]
        self.assertIn('testguest@example.com', sent_msg.to)
        self.assertIn('Zahlungseingang für E-Mail LAN 2026', sent_msg.subject)
        self.assertIn('Hallo Max Mustermann, danke für 25.00 €!', sent_msg.body)

    def test_sandbox_mode_redirection(self):
        self.settings.is_sandbox = True
        self.settings.sandbox_redirect_email = 'sandbox-orga@example.com'
        self.settings.save()

        success = send_system_email(
            'payment_confirmation',
            'testguest@example.com',
            {'full_name': 'Max Mustermann', 'event_title': 'E-Mail LAN 2026', 'amount': '25.00'},
        )
        self.assertTrue(success)
        self.assertEqual(len(mail.outbox), 1)
        sent_msg = mail.outbox[0]

        # Die E-Mail muss an die Sandbox-Weiterleitungsadresse gesendet worden sein!
        self.assertIn('sandbox-orga@example.com', sent_msg.to)
        self.assertNotIn('testguest@example.com', sent_msg.to)
        self.assertIn('[SANDBOX', sent_msg.subject)

    def test_disabled_email_sending(self):
        self.settings.is_enabled = False
        self.settings.save()

        success = send_system_email(
            'payment_confirmation',
            'testguest@example.com',
            {'full_name': 'Max Mustermann', 'event_title': 'E-Mail LAN 2026', 'amount': '25.00'},
        )
        self.assertFalse(success)
        self.assertEqual(len(mail.outbox), 0)

    def test_payment_status_change_triggers_email(self):
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
            paid_amount=29.90,
        )
        self.assertEqual(len(mail.outbox), 0)

        # Status auf PAID ändern mit captureOnCommitCallbacks
        with self.captureOnCommitCallbacks(execute=True):
            registration.mark_as_paid()

        # E-Mail muss erst nach Commit getriggert werden!
        self.assertEqual(len(mail.outbox), 1)
        sent_msg = mail.outbox[0]
        self.assertIn('testguest@example.com', sent_msg.to)
        self.assertIn('E-Mail LAN 2026', sent_msg.subject)

    def test_email_timeout_setting_configured(self):
        """Prüft, dass EMAIL_TIMEOUT in Django-Settings konfiguriert ist (Schutz vor hängenden Webserver-Threads)."""
        from django.conf import settings
        self.assertTrue(hasattr(settings, 'EMAIL_TIMEOUT'))
        self.assertGreater(settings.EMAIL_TIMEOUT, 0)

    def test_send_system_email_passes_timeout(self):
        """Prüft, dass send_system_email timeout an get_connection weiterreicht."""
        from unittest.mock import patch
        with patch('emails.services.get_connection') as mock_get_conn:
            mock_conn_instance = mock_get_conn.return_value
            send_system_email(
                'payment_confirmation',
                'testguest@example.com',
                {'full_name': 'Max', 'event_title': 'LAN', 'amount': '10'},
            )
            mock_get_conn.assert_called()
            call_kwargs = mock_get_conn.call_args[1]
            self.assertIn('timeout', call_kwargs)
            self.assertEqual(call_kwargs['timeout'], 10)

    def test_smtp_password_encrypted_in_db(self):
        """Prüft, dass das SMTP-Passwort verschlüsselt in der DB gespeichert und korrekt entschlüsselt wird."""
        raw_pwd = "SuperSecretSMTPPassword123!"
        self.settings.smtp_password = raw_pwd
        self.settings.save()

        # In der Datenbank darf NIEMALS das Klartext-Passwort stehen
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT smtp_password FROM emails_generalemailsettings WHERE id = %s", [self.settings.id])
            db_value = cursor.fetchone()[0]

        self.assertNotEqual(db_value, raw_pwd)
        self.assertTrue(db_value.startswith("gAAAAA"))  # Fernet Ciphertext Prefix

        # get_smtp_password() muss das Klartext-Passwort liefern
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.get_smtp_password(), raw_pwd)

    def test_send_system_email_passes_decrypted_smtp_password(self):
        """Prüft, dass der Mailservice bei eigenem SMTP-Server das entschlüsselte Passwort an get_connection übergibt."""
        from unittest.mock import patch
        raw_pwd = "RelayPassword456!"
        self.settings.smtp_host = "smtp.relay.example.com"
        self.settings.smtp_port = 587
        self.settings.smtp_username = "relayuser"
        self.settings.set_smtp_password(raw_pwd)
        self.settings.save()

        with patch('emails.services.get_connection') as mock_get_conn:
            send_system_email(
                'payment_confirmation',
                'testguest@example.com',
                {'full_name': 'Max', 'event_title': 'LAN', 'amount': '10'},
            )
            mock_get_conn.assert_called()
            call_kwargs = mock_get_conn.call_args[1]
            self.assertEqual(call_kwargs['host'], "smtp.relay.example.com")
            self.assertEqual(call_kwargs['username'], "relayuser")
            self.assertEqual(call_kwargs['password'], raw_pwd)

    def test_admin_form_retains_and_clears_smtp_password(self):
        """Prüft das Verhalten des Admin-Formulars beim Beibehalten, Aktualisieren und Löschen des Passworts."""
        from emails.admin import GeneralEmailSettingsForm

        self.settings.set_smtp_password("InitialPassword123")
        self.settings.save()
        self.settings.refresh_from_db()

        # 1. Formular ohne Passworteingabe abgesendet -> Altes Passwort muss erhalten bleiben
        form = GeneralEmailSettingsForm(
            data={
                'sender_email': 'test@example.com',
                'sender_name': 'Test',
                'is_enabled': True,
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_username': 'user',
                'smtp_password': '',  # Leer gelassen
            },
            instance=self.settings,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        saved.refresh_from_db()
        self.assertEqual(saved.get_smtp_password(), "InitialPassword123")

        # 2. Formular mit neuem Passwort abgesendet -> Neues Passwort muss verschlüsselt gespeichert werden
        form2 = GeneralEmailSettingsForm(
            data={
                'sender_email': 'test@example.com',
                'sender_name': 'Test',
                'is_enabled': True,
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_username': 'user',
                'smtp_password': 'BrandNewPassword789!',
            },
            instance=self.settings,
        )
        self.assertTrue(form2.is_valid(), form2.errors)
        saved2 = form2.save()
        saved2.refresh_from_db()
        self.assertEqual(saved2.get_smtp_password(), "BrandNewPassword789!")

        # 3. Formular mit Lösch-Checkbox -> Passwort wird geleert
        form3 = GeneralEmailSettingsForm(
            data={
                'sender_email': 'test@example.com',
                'sender_name': 'Test',
                'is_enabled': True,
                'smtp_host': 'smtp.test.com',
                'smtp_port': 587,
                'smtp_username': 'user',
                'smtp_password': '',
                'clear_smtp_password': 'on',
            },
            instance=saved2,
        )
        self.assertTrue(form3.is_valid(), form3.errors)
        saved3 = form3.save()
        saved3.refresh_from_db()
        self.assertEqual(saved3.get_smtp_password(), "")

