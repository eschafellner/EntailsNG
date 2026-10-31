"""Anmeldebestätigung per E-Mail (mit GiroCode) und Ticket-Zahlungsfrist mit automatischer Stornierung."""
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from configuration.models import GeneralConfiguration
from emails.models import EmailTemplate, OutgoingEmail
from emails.services import process_email_queue
from events.exceptions import InvalidTicketTypeError
from events.models import Event, EventRegistration, TicketType
from events.payment_qr import generate_epc_qr_payload
from events.services import PaymentDeadlineService, RegistrationService
from seating.models import SeatingCell, SeatingPlan
from users.models import User


def _image_parts(message):
    return [part for part in message.message().walk() if part.get_content_type() == 'image/png']


class RegistrationMailTestMixin:
    @classmethod
    def setUpTestData(cls):
        call_command('seed_email_templates', stdout=StringIO())
        now = timezone.now()
        cls.event = Event.objects.create(
            title='Herbst LAN', slug='herbst-lan', is_active=True, location='Stadthalle Linz',
            status=Event.Status.REGISTRATION_OPEN, max_guests=20,
            start_date=now + timedelta(days=10), end_date=now + timedelta(days=12),
        )
        cls.paid_ticket = TicketType.objects.create(event=cls.event, name='Standard', price='25.00')
        cls.free_ticket = TicketType.objects.create(event=cls.event, name='Orga-Helfer', price='0.00')

    def setUp(self):
        config = GeneralConfiguration.load()
        config.kontoinhaber = 'LAN e.V.'
        config.iban = 'AT611904300234573201'
        config.bic = 'BKAUATWW'
        config.save()

    def make_user(self, username='gast1'):
        return User.objects.create_user(username, email=f'{username}@example.com', password='pw',
                                        first_name='Max', last_name='Muster')

    def register(self, user, ticket):
        with self.captureOnCommitCallbacks(execute=True):
            return RegistrationService.register_user(user, self.event.pk, ticket.pk)


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_BASE_URL='https://lan.example')
class RegistrationConfirmationMailTests(RegistrationMailTestMixin, TestCase):

    def test_paid_registration_sends_confirmation_with_details_and_inline_qr(self):
        TicketType.objects.filter(pk=self.paid_ticket.pk).update(payment_deadline=timezone.localdate() + timedelta(days=5))
        registration, created, _ = self.register(self.make_user(), self.paid_ticket)
        self.assertTrue(created)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Anmeldebestätigung für Herbst LAN')
        self.assertEqual(message.to, ['gast1@example.com'])
        html = message.alternatives[0][0]
        deadline = (timezone.localdate() + timedelta(days=5)).strftime('%d.%m.%Y')
        for expected in ('gast1', 'Herbst LAN', 'Stadthalle Linz', 'Standard', '25.00 €', 'AT611904300234573201',
                         'BKAUATWW', 'LAN e.V.', registration.payment_reference, deadline,
                         timezone.localtime(self.event.start_date).strftime('%d.%m.%Y, %H:%M Uhr'),
                         'src="cid:payment_qr"', 'https://lan.example/'):
            self.assertIn(expected, html)
        self.assertIn('automatisch storniert', html)
        # Textfassung enthält die Bankdaten, falls Bilder nicht angezeigt werden.
        self.assertIn('AT611904300234573201', message.body)

        self.assertEqual(message.inline_qr_payload, generate_epc_qr_payload(registration))
        images = _image_parts(message)
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]['Content-ID'], '<payment_qr>')
        self.assertTrue(images[0].get_content().startswith(b'\x89PNG'))
        related = [part for part in message.message().walk() if part.get_content_type() == 'multipart/related']
        self.assertEqual(len(related), 1)

    def test_paid_registration_without_deadline_uses_neutral_hint(self):
        self.register(self.make_user(), self.paid_ticket)
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn('rechtzeitig vor der Veranstaltung', html)
        self.assertNotIn('automatisch storniert', html)

    def test_free_ticket_sends_confirmation_without_payment_block(self):
        self.register(self.make_user(), self.free_ticket)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        html = message.alternatives[0][0]
        self.assertIn('Orga-Helfer', html)
        self.assertIn('keine Zahlung nötig', html)
        self.assertNotIn('cid:payment_qr', html)
        self.assertNotIn('AT611904300234573201', html)
        self.assertEqual(_image_parts(message), [])

    def test_missing_bank_details_send_confirmation_without_qr(self):
        GeneralConfiguration.objects.update(iban='', kontoinhaber='')
        self.register(self.make_user(), self.paid_ticket)
        message = mail.outbox[0]
        html = message.alternatives[0][0]
        self.assertIn('Zahlungsdaten erhältst du', html)
        self.assertNotIn('cid:payment_qr', html)
        self.assertEqual(_image_parts(message), [])

    def test_repeated_registration_sends_no_second_mail_but_reactivation_does(self):
        user = self.make_user()
        registration, _, _ = self.register(user, self.paid_ticket)
        self.register(user, self.paid_ticket)
        self.assertEqual(len(mail.outbox), 1)
        registration.mark_as_cancelled()
        _, created, reactivated = self.register(user, self.paid_ticket)
        self.assertFalse(created)
        self.assertTrue(reactivated)
        self.assertEqual(len(mail.outbox), 2)

    def test_inactive_template_sends_nothing(self):
        EmailTemplate.objects.filter(key='event_registration_confirmation').update(is_active=False)
        self.register(self.make_user(), self.paid_ticket)
        self.assertEqual(len(mail.outbox), 0)

    def test_registration_view_triggers_confirmation(self):
        user = self.make_user()
        self.client.force_login(user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('register_for_event', args=[self.event.pk]), {'ticket_type_id': self.paid_ticket.pk})
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(FORCE_EMAIL_ASYNC_QUEUE=True, EMAIL_ASYNC_QUEUE=True)
    def test_queued_mail_keeps_qr_payload_and_worker_embeds_image(self):
        from emails.models import GeneralEmailSettings
        GeneralEmailSettings.objects.update(is_enabled=True)
        registration, _, _ = self.register(self.make_user(), self.paid_ticket)
        outgoing = OutgoingEmail.objects.get(template_key='event_registration_confirmation')
        self.assertEqual(outgoing.inline_qr_payload, generate_epc_qr_payload(registration))
        self.assertEqual(len(mail.outbox), 0)
        process_email_queue(email_ids=[outgoing.pk])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(_image_parts(mail.outbox[0])), 1)

    def test_other_queued_mails_stay_without_image(self):
        from emails.services import send_system_email
        send_system_email('password_reset', 'x@example.com', {'reset_link': 'https://x'}, immediate=True)
        self.assertEqual(_image_parts(mail.outbox[0]), [])


@override_settings(SECURE_SSL_REDIRECT=False)
class TicketPaymentDeadlineTests(RegistrationMailTestMixin, TestCase):

    def set_deadline(self, ticket, days):
        TicketType.objects.filter(pk=ticket.pk).update(payment_deadline=timezone.localdate() + timedelta(days=days))
        ticket.refresh_from_db()

    def test_deadline_after_event_end_is_rejected(self):
        ticket = TicketType(event=self.event, name='Spät', price='10.00',
                            payment_deadline=timezone.localdate(self.event.end_date) + timedelta(days=1))
        with self.assertRaises(ValidationError):
            ticket.full_clean()
        ticket.payment_deadline = timezone.localdate(self.event.end_date)
        ticket.full_clean()

    def test_expired_ticket_is_not_bookable_and_hidden_on_dashboard(self):
        self.set_deadline(self.paid_ticket, -1)
        with self.assertRaises(InvalidTicketTypeError):
            RegistrationService.register_user(self.make_user(), self.event.pk, self.paid_ticket.pk)
        self.client.force_login(self.make_user('gast2'))
        ticket_ids = [ticket.pk for ticket in self.client.get(reverse('dashboard')).context['ticket_types']]
        self.assertNotIn(self.paid_ticket.pk, ticket_ids)
        self.assertIn(self.free_ticket.pk, ticket_ids)

    def test_deadline_day_itself_is_still_bookable(self):
        self.set_deadline(self.paid_ticket, 0)
        registration, created, _ = RegistrationService.register_user(self.make_user(), self.event.pk, self.paid_ticket.pk)
        self.assertTrue(created)
        self.assertEqual(PaymentDeadlineService.cancel_overdue_registrations(), 0)

    def test_default_ticket_skips_expired_and_fails_when_none_bookable(self):
        self.set_deadline(self.paid_ticket, -1)
        registration, _, _ = RegistrationService.register_user(self.make_user(), self.event.pk)
        self.assertEqual(registration.ticket_type, self.free_ticket)
        self.set_deadline(self.free_ticket, -1)
        with self.assertRaises(InvalidTicketTypeError):
            RegistrationService.register_user(self.make_user('gast2'), self.event.pk)

    def test_overdue_unpaid_registration_is_cancelled_with_notice_and_seat_released(self):
        registration, _, _ = self.register(self.make_user(), self.paid_ticket)
        plan = SeatingPlan.objects.create(event=self.event, name='Halle')
        seat = SeatingCell.objects.create(plan=plan, x=1, y=1, cell_type='SEAT', seat_label='A1',
            registration=registration, reservation_status=SeatingCell.ReservationStatus.PRE_RESERVED)
        self.set_deadline(self.paid_ticket, -1)
        mail.outbox.clear()

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(PaymentDeadlineService.cancel_overdue_registrations(), 1)
        registration.refresh_from_db()
        seat.refresh_from_db()
        self.assertEqual(registration.payment_status, EventRegistration.PaymentStatus.CANCELLED)
        self.assertIsNone(seat.registration)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Deine Anmeldung für Herbst LAN wurde storniert')
        self.assertIn(self.paid_ticket.payment_deadline.strftime('%d.%m.%Y'), mail.outbox[0].alternatives[0][0])
        # Zweiter Lauf ist idempotent.
        self.assertEqual(PaymentDeadlineService.cancel_overdue_registrations(), 0)

    def test_paid_free_and_deadline_free_registrations_are_kept(self):
        paid, _, _ = RegistrationService.register_user(self.make_user('bezahlt'), self.event.pk, self.paid_ticket.pk)
        paid.mark_as_paid(send_email=False)
        free, _, _ = RegistrationService.register_user(self.make_user('gratis'), self.event.pk, self.free_ticket.pk)
        self.set_deadline(self.paid_ticket, -1)
        self.set_deadline(self.free_ticket, -1)
        no_deadline_ticket = TicketType.objects.create(event=self.event, name='Ohne Frist', price='30.00')
        open_reg, _, _ = RegistrationService.register_user(self.make_user('offen'), self.event.pk, no_deadline_ticket.pk)

        self.assertEqual(PaymentDeadlineService.cancel_overdue_registrations(), 0)
        for registration in (paid, free, open_reg):
            registration.refresh_from_db()
            self.assertNotEqual(registration.payment_status, EventRegistration.PaymentStatus.CANCELLED)

    def test_finished_events_are_not_touched(self):
        registration, _, _ = RegistrationService.register_user(self.make_user(), self.event.pk, self.paid_ticket.pk)
        self.set_deadline(self.paid_ticket, -1)
        Event.objects.filter(pk=self.event.pk).update(status=Event.Status.FINISHED)
        self.assertEqual(PaymentDeadlineService.cancel_overdue_registrations(), 0)
        registration.refresh_from_db()
        self.assertEqual(registration.payment_status, EventRegistration.PaymentStatus.UNPAID)

    def test_extended_deadline_is_respected(self):
        RegistrationService.register_user(self.make_user(), self.event.pk, self.paid_ticket.pk)
        self.set_deadline(self.paid_ticket, -1)
        self.set_deadline(self.paid_ticket, 3)
        self.assertEqual(PaymentDeadlineService.cancel_overdue_registrations(), 0)

    def test_management_command_and_worker_run_deadline_processing(self):
        RegistrationService.register_user(self.make_user(), self.event.pk, self.paid_ticket.pk)
        self.set_deadline(self.paid_ticket, -1)
        out = StringIO()
        call_command('process_payment_deadlines', stdout=out)
        self.assertIn('1 Anmeldung(en)', out.getvalue())

        RegistrationService.register_user(self.make_user('gast2'), self.event.pk, self.free_ticket.pk)
        other = TicketType.objects.create(event=self.event, name='Spät', price='5.00')
        registration, _, _ = RegistrationService.register_user(self.make_user('gast3'), self.event.pk, other.pk)
        self.set_deadline(other, -1)
        from unittest.mock import patch
        with patch('seating.management.commands.process_clan_seat_holds.connections'):
            call_command('process_clan_seat_holds', stdout=StringIO())
        registration.refresh_from_db()
        self.assertEqual(registration.payment_status, EventRegistration.PaymentStatus.CANCELLED)
