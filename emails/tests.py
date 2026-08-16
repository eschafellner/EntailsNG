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

