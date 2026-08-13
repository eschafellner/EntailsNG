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
