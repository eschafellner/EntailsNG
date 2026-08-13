from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from events.models import Event, EventRegistration, TicketType
from events.services import RegistrationService
from events.exceptions import (
    EventNotOpenError,
    EventFullError,
    RegistrationDeadlinePassedError,
    InvalidTicketTypeError,
)

User = get_user_model()



class EventDashboardTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='gamer1', email='gamer1@example.com', password='password'
        )
        self.staff_user = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='password'
        )
        self.event = Event.objects.create(
            title='LAN Party 2026',
            slug='lan-party-2026',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=12),
        )

    def test_dashboard_view_anonymous(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['event'], self.event)
        self.assertIn('event_total_seats', response.context)
        self.assertContains(response, 'Saalbelegung')

    def test_dashboard_saalbelegung_always_visible(self):
        # 1. Anonymer Gast
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Saalbelegung')

        # 2. Angemeldeter User, der NOCH NICHT registriert ist
        self.client.login(username='gamer1', password='password')
        response_user = self.client.get(reverse('dashboard'))
        self.assertContains(response_user, 'Saalbelegung')

    def test_register_for_event(self):
        self.client.login(username='gamer1', password='password')
        response = self.client.post(
            reverse('register_for_event', kwargs={'event_id': self.event.id})
        )
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(
            EventRegistration.objects.filter(
                user=self.user, event=self.event
            ).exists()
        )

    def test_process_checkin_unpaid(self):
        registration = EventRegistration.objects.create(
            user=self.user, event=self.event
        )
        self.client.login(username='admin', password='password')
        response = self.client.get(
            reverse(
                'process_checkin',
                kwargs={
                    'registration_id': registration.id,
                    'token': registration.checkin_token,
                },
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, 'events/checkin_failed.html')

    def test_process_checkin_get_does_not_mutate_state(self):
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )
        self.client.login(username='admin', password='password')

        # GET Request renders confirmation template and MUST NOT mutate check-in state
        response = self.client.get(
            reverse(
                'process_checkin',
                kwargs={
                    'registration_id': registration.id,
                    'token': registration.checkin_token,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'events/checkin_confirm.html')
        registration.refresh_from_db()
        self.assertFalse(registration.is_checked_in)

    def test_process_checkin_post_mutates_state(self):
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )
        self.client.login(username='admin', password='password')

        # POST Request performs check-in mutation
        response = self.client.post(
            reverse(
                'process_checkin',
                kwargs={
                    'registration_id': registration.id,
                    'token': registration.checkin_token,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'events/checkin_success.html')
        registration.refresh_from_db()
        self.assertTrue(registration.is_checked_in)

    def test_admin_csv_export(self):
        registration = EventRegistration.objects.create(
            user=self.user, event=self.event
        )
        self.client.login(username='admin', password='password')
        response = self.client.post(
            reverse('admin:events_eventregistration_changelist'),
            {
                'action': 'export_as_csv',
                '_selected_action': [registration.id],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        content = response.content.decode('utf-8')
        self.assertIn('gamer1', content)
        self.assertIn('LAN Party 2026', content)

    def test_checkin_scanner_view_permissions(self):
        # 1. Anonym
        response = self.client.get(reverse('checkin_scanner'))
        self.assertEqual(response.status_code, 302)

        # 2. Normaler User (kein Staff)
        self.client.login(username='gamer1', password='password')
        response = self.client.get(reverse('checkin_scanner'))
        self.assertEqual(response.status_code, 302)

        # 3. Staff User
        self.client.login(username='admin', password='password')
        response = self.client.get(reverse('checkin_scanner'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'events/checkin_scanner.html')

    def test_scan_qr_api(self):
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )

        # Normaler User darf API nicht aufrufen
        self.client.login(username='gamer1', password='password')
        res_user = self.client.post(
            reverse('api_scan_qr'),
            data={'code': str(registration.checkin_token)},
            content_type='application/json',
        )
        self.assertEqual(res_user.status_code, 302)

        # Staff User scannt gültiges Token
        self.client.login(username='admin', password='password')
        res_staff = self.client.post(
            reverse('api_scan_qr'),
            data={'code': str(registration.checkin_token)},
            content_type='application/json',
        )
        self.assertEqual(res_staff.status_code, 200)
        data = res_staff.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['user'], 'gamer1')
        registration.refresh_from_db()
        self.assertTrue(registration.is_checked_in)

        # Zweiter Scan -> bereits eingecheckt
        res_repeat = self.client.post(
            reverse('api_scan_qr'),
            data={'code': str(registration.checkin_token)},
            content_type='application/json',
        )
        self.assertEqual(res_repeat.status_code, 200)
        self.assertEqual(res_repeat.json()['status'], 'already_checked_in')


class RegistrationRulesTests(TestCase):

    def setUp(self):
        self.user1 = User.objects.create_user(username='user1', email='u1@example.com', password='password')
        self.user2 = User.objects.create_user(username='user2', email='u2@example.com', password='password')
        self.event = Event.objects.create(
            title='Lan 2026',
            slug='lan-2026',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            max_guests=1,
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=7),
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='Standard Ticket',
            price=25.00,
            is_active=True
        )

    def test_registration_success(self):
        reg, created = RegistrationService.register_user(
            user=self.user1,
            event_id=self.event.id,
            ticket_type_id=self.ticket_type.id
        )
        self.assertTrue(created)
        self.assertEqual(reg.user, self.user1)
        self.assertEqual(reg.ticket_type, self.ticket_type)

    def test_registration_rejected_when_draft(self):
        self.event.status = Event.Status.DRAFT
        self.event.save()
        with self.assertRaises(EventNotOpenError):
            RegistrationService.register_user(user=self.user1, event_id=self.event.id)

    def test_registration_rejected_when_cancelled(self):
        self.event.status = Event.Status.CANCELLED
        self.event.save()
        with self.assertRaises(EventNotOpenError):
            RegistrationService.register_user(user=self.user1, event_id=self.event.id)

    def test_registration_rejected_when_finished(self):
        self.event.status = Event.Status.FINISHED
        self.event.save()
        with self.assertRaises(EventNotOpenError):
            RegistrationService.register_user(user=self.user1, event_id=self.event.id)

    def test_registration_rejected_when_expired(self):
        self.event.end_date = timezone.now() - timedelta(hours=1)
        self.event.save()
        with self.assertRaises(RegistrationDeadlinePassedError):
            RegistrationService.register_user(user=self.user1, event_id=self.event.id)

    def test_registration_rejected_when_full(self):
        # Erste Anmeldung füllt die Kapazität (max_guests=1)
        RegistrationService.register_user(user=self.user1, event_id=self.event.id)
        # Zweite Anmeldung muss fehlschlagen
        with self.assertRaises(EventFullError):
            RegistrationService.register_user(user=self.user2, event_id=self.event.id)

    def test_registration_invalid_ticket_type(self):
        with self.assertRaises(InvalidTicketTypeError):
            RegistrationService.register_user(user=self.user1, event_id=self.event.id, ticket_type_id=999999)


class EventStateAndLifecycleTests(TestCase):

    def setUp(self):
        self.event1 = Event.objects.create(
            title='Main Event 1',
            slug='main-event-1',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=3),
        )

    def test_single_active_event_guarantee(self):
        event2 = Event.objects.create(
            title='Main Event 2',
            slug='main-event-2',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=12),
        )
        self.event1.refresh_from_db()
        self.assertFalse(self.event1.is_active)
        self.assertTrue(event2.is_active)
        self.assertEqual(Event.objects.get_active(), event2)

    def test_effective_status_running_and_finished(self):
        running_event = Event.objects.create(
            title='Running Event',
            slug='running-event',
            is_active=False,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() - timedelta(hours=2),
            end_date=timezone.now() + timedelta(hours=2),
        )
        self.assertEqual(running_event.effective_status, Event.Status.RUNNING)

        expired_event = Event.objects.create(
            title='Expired Event',
            slug='expired-event',
            is_active=False,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() - timedelta(days=5),
            end_date=timezone.now() - timedelta(days=2),
        )
        self.assertEqual(expired_event.status, Event.Status.FINISHED)
        self.assertEqual(expired_event.effective_status, Event.Status.FINISHED)

    def test_clean_validation_draft_cannot_be_active(self):
        from django.core.exceptions import ValidationError
        draft_event = Event(
            title='Draft Event',
            slug='draft-event',
            is_active=True,
            status=Event.Status.DRAFT,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=2),
        )
        with self.assertRaises(ValidationError):
            draft_event.clean()

    def test_clean_validation_end_date_before_start_date(self):
        from django.core.exceptions import ValidationError
        invalid_event = Event(
            title='Invalid Event',
            slug='invalid-event',
            is_active=False,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=2),
        )
        with self.assertRaises(ValidationError):
            invalid_event.clean()


class EventRegistrationValidationTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='gamer1', password='password')
        self.event = Event.objects.create(
            title='Main Event',
            slug='main-event',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=3),
        )

    def test_registration_blocked_when_full(self):
        self.event.max_guests = 1
        self.event.save()

        # Erste Registrierung erfolgreich
        EventRegistration.objects.create(user=self.user, event=self.event)

        # Zweite Registrierung muss fehlschlagen
        user2 = User.objects.create_user(username='gamer2', password='password')
        self.client.login(username='gamer2', password='password')
        response = self.client.post(reverse('register_for_event', args=[self.event.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EventRegistration.objects.filter(user=user2, event=self.event).exists())

    def test_registration_blocked_when_cancelled_or_draft(self):
        self.event.status = Event.Status.CANCELLED
        self.event.is_active = False
        self.event.save()

        self.client.login(username='gamer1', password='password')
        response = self.client.post(reverse('register_for_event', args=[self.event.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EventRegistration.objects.filter(user=self.user, event=self.event).exists())

    def test_ticket_type_from_other_event_validation(self):
        from django.core.exceptions import ValidationError
        from events.models import TicketType

        other_event = Event.objects.create(
            title='Other Event',
            slug='other-event',
            is_active=False,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=12),
        )
        other_ticket = TicketType.objects.create(
            event=other_event, name='Vip Ticket', price=99.00
        )

        reg = EventRegistration(user=self.user, event=self.event, ticket_type=other_ticket)
        with self.assertRaises(ValidationError):
            reg.clean()

    def test_paid_at_auto_population(self):
        reg = EventRegistration.objects.create(
            user=self.user, event=self.event, payment_status=EventRegistration.PaymentStatus.UNPAID
        )
        self.assertIsNone(reg.paid_at)

        reg.mark_as_paid()
        reg.refresh_from_db()
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertIsNotNone(reg.paid_at)

    def test_overbooking_warning_ignored_for_inactive_or_finished_events(self):
        from events.admin import _check_overbooking
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        self.event.is_active = False
        self.event.status = Event.Status.FINISHED
        self.event.max_guests = 1
        self.event.save()

        user2 = User.objects.create_user(username='gamer_extra', password='password')
        EventRegistration.objects.create(user=self.user, event=self.event)
        EventRegistration.objects.create(user=user2, event=self.event)

        rf = RequestFactory()
        req = rf.get('/admin/events/event/')
        setattr(req, 'session', 'session')
        messages_store = FallbackStorage(req)
        setattr(req, '_messages', messages_store)

        _check_overbooking(req)

        warnings = [m.message for m in messages_store if 'mehr Plätze gebucht' in str(m.message)]
        self.assertEqual(len(warnings), 0)






