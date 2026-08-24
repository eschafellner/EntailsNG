import json
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventRegistration, TicketType
from events.services import RegistrationService
from seating.models import SeatingPlan, SeatingCell

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

    def test_scan_qr_api_with_short_code(self):
        """Prüft, dass der Check-in per 8-stelligem Ticket-Code (short_code) erfolgreich funktioniert."""
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )
        self.assertTrue(bool(registration.short_code))
        self.assertEqual(len(registration.short_code), 8)

        self.client.login(username='admin', password='password')

        # Test mit formatiertem / lowercase Code (z.B. manuelle Helfer-Eingabe)
        formatted_code = f"{registration.short_code[:4]}-{registration.short_code[4:]}".lower()
        response = self.client.post(
            reverse('api_scan_qr'),
            data={'code': formatted_code},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['user'], 'gamer1')
        registration.refresh_from_db()
        self.assertTrue(registration.is_checked_in)

    def test_scan_qr_api_rejects_integer_pk_fallback(self):
        """
        NEGATIV-TEST: Stellt sicher, dass das bloße Übergeben des fortlaufenden Primärschlüssels (z. B. "1", "2")
        strikt mit 404 abgewiesen wird und KEIN unbefugter Check-in erfolgt.
        """
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )
        self.client.login(username='admin', password='password')

        # Versuch mit reinem Integer-PK
        pk_input = str(registration.pk)
        response = self.client.post(
            reverse('api_scan_qr'),
            data={'code': pk_input},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['status'], 'error')

        # Verifiziere, dass der Gast NICHT eingecheckt wurde
        registration.refresh_from_db()
        self.assertFalse(registration.is_checked_in)


    def test_toggle_check_in_api_unpaid_rejected(self):
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )
        self.client.login(username='admin', password='password')
        response = self.client.post(
            reverse('api_toggle_check_in'),
            data=json.dumps({'registration_id': registration.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json().get('is_checked_in', False))
        registration.refresh_from_db()
        self.assertFalse(registration.is_checked_in)

    def test_toggle_check_in_api_paid_success(self):
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )
        self.client.login(username='admin', password='password')
        # 1. Einchecken
        response = self.client.post(
            reverse('api_toggle_check_in'),
            data=json.dumps({'registration_id': registration.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        registration.refresh_from_db()
        self.assertTrue(registration.is_checked_in)

        # 2. Auschecken
        response_out = self.client.post(
            reverse('api_toggle_check_in'),
            data=json.dumps({'registration_id': registration.id}),
            content_type='application/json',
        )
        self.assertEqual(response_out.status_code, 200)
        registration.refresh_from_db()
        self.assertFalse(registration.is_checked_in)

    def test_model_check_in_raises_validation_error_when_unpaid(self):
        from django.core.exceptions import ValidationError
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )
        with self.assertRaises(ValidationError):
            registration.check_in()



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
        self.event.start_date = timezone.now() - timedelta(days=2)
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
        self.assertEqual(expired_event.status, Event.Status.REGISTRATION_OPEN)
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

    def test_database_level_single_active_event_unique_constraint(self):
        from django.db import IntegrityError
        # Erstelle ein zweites inaktives Event
        event2 = Event.objects.create(
            title='Second Event',
            slug='second-event',
            is_active=False,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=7),
        )
        # Wenn wir die Event.save() Logik via ORM bulk .update umgehen, muss die DB-Constraint greifen
        with self.assertRaises(IntegrityError):
            Event.objects.filter(id=event2.id).update(is_active=True)




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

    def test_can_register_and_clean_consistency(self):
        from django.core.exceptions import ValidationError

        # 1. Event voll
        self.event.max_guests = 1
        self.event.save()
        EventRegistration.objects.create(user=self.user, event=self.event)

        can_reg, reason = self.event.can_register()
        self.assertFalse(can_reg)
        self.assertIn("maximale teilnehmerzahl", reason.lower())


        user2 = User.objects.create_user(username='gamer_new', password='password')
        reg_full = EventRegistration(user=user2, event=self.event)
        with self.assertRaises(ValidationError):
            reg_full.clean()

        # 2. Event abgelaufen
        self.event.max_guests = 50
        self.event.start_date = timezone.now() - timedelta(days=5)
        self.event.end_date = timezone.now() - timedelta(days=2)
        self.event.save()

        can_reg_exp, reason_exp = self.event.can_register()
        self.assertFalse(can_reg_exp)

        reg_expired = EventRegistration(user=user2, event=self.event)
        with self.assertRaises(ValidationError):
            reg_expired.clean()

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

    def test_paid_at_and_paid_amount_auto_population(self):
        ticket = TicketType.objects.create(event=self.event, name='Standard', price=35.50)
        reg = EventRegistration.objects.create(
            user=self.user, event=self.event, ticket_type=ticket, payment_status=EventRegistration.PaymentStatus.UNPAID
        )
        self.assertIsNone(reg.paid_at)
        self.assertEqual(reg.paid_amount, 0.00)

        # 1. Bezahlung markieren -> Übernahme von Ticketpreis & Zeitstempel
        reg.mark_as_paid()
        reg.refresh_from_db()
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertIsNotNone(reg.paid_at)
        self.assertEqual(float(reg.paid_amount), 35.50)
        self.assertIsNone(reg.cancelled_at)

        # 2. Check-in durchführen
        reg.check_in()
        reg.refresh_from_db()
        self.assertTrue(reg.is_checked_in)
        self.assertIsNotNone(reg.checked_in_at)

        # 3. Stornierung durchführen -> Check-in zurücksetzen, cancelled_at setzen
        reg.mark_as_cancelled()
        reg.refresh_from_db()
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.CANCELLED)
        self.assertFalse(reg.is_checked_in)
        self.assertIsNone(reg.checked_in_at)
        self.assertIsNotNone(reg.cancelled_at)


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

    def test_event_admin_clone_seating_on_creation(self):
        from django.contrib.admin.sites import AdminSite
        from events.admin import EventAdmin
        from seating.models import SeatingPlan, SeatingCell

        # Master Template Plan erstellen
        master_plan = SeatingPlan.objects.create(
            event=None,
            name="Turnhalle Master",
            columns=10,
            rows=10,
        )
        SeatingCell.objects.create(plan=master_plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label="A1")
        SeatingCell.objects.create(plan=master_plan, x=2, y=1, cell_type=SeatingCell.CellType.WALL)

        event_admin = EventAdmin(Event, AdminSite())

        new_event = Event.objects.create(
            title="Haag-networX 2029",
            slug="haag-2029",
            is_active=False,
            start_date=timezone.now() + timedelta(days=500),
            end_date=timezone.now() + timedelta(days=502),
        )

        class DummyForm:
            cleaned_data = {'clone_seating_from': master_plan}

        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        rf = RequestFactory()
        req = rf.post('/admin/events/event/add/')
        setattr(req, 'session', 'session')
        setattr(req, '_messages', FallbackStorage(req))

        event_admin.save_model(req, new_event, DummyForm(), change=False)

        new_event.refresh_from_db()
        self.assertTrue(hasattr(new_event, 'seating_plan'))
        self.assertEqual(new_event.seating_plan.columns, 10)
        self.assertEqual(new_event.seating_plan.cells.count(), 2)
        seat_a1 = new_event.seating_plan.cells.get(x=1, y=1)
        self.assertEqual(seat_a1.seat_label, "A1")
        self.assertIsNone(seat_a1.registration)
        self.assertEqual(seat_a1.reservation_status, SeatingCell.ReservationStatus.FREE)

    def test_cancelled_registration_reactivation_positive(self):
        """Positiver Test: Stornierte Registrierung wird bei erneuter Anmeldung reaktiviert statt Duplikat zu erzeugen."""
        ticket = TicketType.objects.create(event=self.event, name="Regular", price=25.00)
        reg, created = RegistrationService.register_user(self.user, self.event.id, ticket.id)
        self.assertTrue(created)
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.UNPAID)

        # Registrierung stornieren
        reg.mark_as_cancelled()
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.CANCELLED)
        self.assertIsNotNone(reg.cancelled_at)

        # Erneute Anmeldung für dasselbe Event (darf keinen IntegrityError werfen!)
        new_reg, new_created = RegistrationService.register_user(self.user, self.event.id, ticket.id)
        self.assertTrue(new_created)
        self.assertEqual(new_reg.pk, reg.pk)
        self.assertEqual(new_reg.payment_status, EventRegistration.PaymentStatus.UNPAID)
        self.assertIsNone(new_reg.cancelled_at)
        self.assertEqual(EventRegistration.objects.filter(user=self.user, event=self.event).count(), 1)

    def test_negative_event_end_date_before_start_date_fails(self):
        """Negativer Test: Ein Event mit Enddatum vor Startdatum wirft ValidationError."""
        from django.core.exceptions import ValidationError
        bad_event = Event(
            title="Broken Dates LAN",
            is_active=False,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=5),
        )
        with self.assertRaises(ValidationError):
            bad_event.save()

    def test_negative_ticket_event_mismatch_fails_clean(self):
        """Negativer Test: Zuweisung eines Tickets eines fremden Events wird von clean() blockiert."""
        from django.core.exceptions import ValidationError
        other_event = Event.objects.create(
            title="Other LAN",
            slug="other-lan",
            is_active=False,
            start_date=timezone.now() + timedelta(days=20),
            end_date=timezone.now() + timedelta(days=22),
        )
        foreign_ticket = TicketType.objects.create(event=other_event, name="Foreign", price=30.00)

        reg = EventRegistration(
            user=self.user,
            event=self.event,
            ticket_type=foreign_ticket
        )
        with self.assertRaises(ValidationError):
            reg.save()

    def test_explicit_domain_methods_isolate_side_effects(self):
        """Architektur-Test: mark_as_paid() und mark_as_cancelled() führen gezielt Seiteneffekte aus."""
        ticket = TicketType.objects.create(event=self.event, name="VIP", price=50.00)
        reg = EventRegistration.objects.create(user=self.user, event=self.event, ticket_type=ticket)

        plan = SeatingPlan.objects.create(event=self.event, name="Hall", columns=5, rows=5)
        seat = SeatingCell.objects.create(
            plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT,
            registration=reg, reservation_status=SeatingCell.ReservationStatus.PRE_RESERVED
        )

        # 1. Zahlung bestätigen über Domain-Methode
        reg.mark_as_paid()
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertEqual(reg.paid_amount, 50.00)
        self.assertIsNotNone(reg.paid_at)
        seat.refresh_from_db()
        self.assertEqual(seat.reservation_status, SeatingCell.ReservationStatus.RESERVED)

        # 2. Stornierung über Domain-Methode
        reg.mark_as_cancelled()
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.CANCELLED)
        self.assertIsNotNone(reg.cancelled_at)
        self.assertFalse(reg.is_checked_in)
        seat.refresh_from_db()
        self.assertIsNone(seat.registration)
        self.assertEqual(seat.reservation_status, SeatingCell.ReservationStatus.FREE)

    def test_reregister_after_cancellation_reactivates_cleanly(self):
        """Funktionaler Test: Nach Storno kann sich der Gast problemlos erneut anmelden ohne IntegrityError."""
        reg = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.CANCELLED,
            cancelled_at=timezone.now()
        )

        # Erneute Registrierung über Service
        reactivated_reg, created = RegistrationService.register_user(
            user=self.user,
            event_id=self.event.id
        )

        self.assertTrue(created)
        self.assertEqual(reactivated_reg.id, reg.id)
        self.assertEqual(reactivated_reg.payment_status, EventRegistration.PaymentStatus.UNPAID)
        self.assertIsNone(reactivated_reg.cancelled_at)
        self.assertIsNone(reactivated_reg.paid_at)

    def test_event_effective_status_does_not_mutate_db_status_on_save(self):
        """Architektur-Test: Event.save() überschreibt den Redakteurs-Status in der DB nicht still."""
        past_event = Event.objects.create(
            title="Old Event",
            slug="old-event",
            is_active=False,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() - timedelta(days=10),
            end_date=timezone.now() - timedelta(days=5),
        )

        self.assertEqual(past_event.status, Event.Status.REGISTRATION_OPEN)
        self.assertEqual(past_event.effective_status, Event.Status.FINISHED)
        self.assertEqual(past_event.get_effective_status_display(), "Beendet")

        # Bearbeitung (z.B. Tippfehler-Korrektur)
        past_event.title = "Old Event (Korrektur)"
        past_event.save()
        past_event.refresh_from_db()

        # DB-Status bleibt REGISTRATION_OPEN, effective_status bleibt FINISHED
        self.assertEqual(past_event.status, Event.Status.REGISTRATION_OPEN)
        self.assertEqual(past_event.effective_status, Event.Status.FINISHED)

    def test_event_db_constraint_rejects_end_before_start(self):
        """Sicherheitstest: DB CheckConstraint verhindert inkonsistente Event-Zeiträume."""
        from django.db import IntegrityError
        with self.assertRaises((IntegrityError, Exception)):
            Event.objects.create(
                title="Invalid Date Event",
                slug="invalid-date",
                is_active=False,
                start_date=timezone.now() + timedelta(days=10),
                end_date=timezone.now() + timedelta(days=5),
            )


class AdmissionAndPaymentHardeningTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_superuser(
            username='scanner_staff', email='scanner@example.com', password='password'
        )
        self.user = User.objects.create_user(
            username='player1', email='player1@example.com', password='password'
        )
        self.event = Event.objects.create(
            title='Hardening LAN',
            slug='hardening-lan',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            max_guests=2,
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=7),
        )

    def test_can_register_matrix(self):
        """Umfassende Matrix-Prüfung aller Status-, Kapazitäts- und Voranmeldungs-Zustände."""
        # 1. Normal geöffnet, Plätze frei
        can, reason = self.event.can_register(user=self.user)
        self.assertTrue(can)

        # 2. Bereits angemeldet
        EventRegistration.objects.create(user=self.user, event=self.event)
        can, reason = self.event.can_register(user=self.user)
        self.assertFalse(can)
        self.assertIn("bereits", reason)

        # 3. Anderer User, aber Event voll
        user2 = User.objects.create_user(username='player2', email='player2@example.com', password='password')
        EventRegistration.objects.create(user=user2, event=self.event)
        user3 = User.objects.create_user(username='player3', email='player3@example.com', password='password')
        can, reason = self.event.can_register(user=user3)
        self.assertFalse(can)
        self.assertIn("erreicht", reason.lower())

        # 4. Status Draft
        self.event.status = Event.Status.DRAFT
        can, reason = self.event.can_register(user=user3)
        self.assertFalse(can)

        # 5. Status Cancelled
        self.event.status = Event.Status.CANCELLED
        can, reason = self.event.can_register(user=user3)
        self.assertFalse(can)

        # 6. Status Finished
        self.event.status = Event.Status.FINISHED
        can, reason = self.event.can_register(user=user3)
        self.assertFalse(can)

    def test_check_in_rejection_rules(self):
        """Testet Check-in Regeln: Ablehnung bei unbezahlt und storniert."""
        reg = EventRegistration.objects.create(user=self.user, event=self.event)

        # 1. Unbezahlt -> Fehler
        with self.assertRaises(ValidationError):
            reg.check_in(actor=self.staff_user)

        # 2. Bezahlt -> Erfolgreich
        reg.mark_as_paid()
        reg.check_in(actor=self.staff_user)
        self.assertTrue(reg.is_checked_in)
        self.assertIsNotNone(reg.checked_in_at)

        # 3. Storniert -> Check-in unmöglich
        reg.mark_as_cancelled()
        with self.assertRaises(ValidationError):
            reg.check_in(actor=self.staff_user)

    def test_scan_qr_api_rejections_and_valid_scans(self):
        """Testet scan_qr_api: Ablehnung von ungültigen/fremden Codes, Erst-Scan und Zweit-Scan."""
        self.client.login(username='scanner_staff', password='password')

        # 1. Ungültiger Token / Fake UUID
        res = self.client.post(
            reverse('api_scan_qr'),
            data=json.dumps({'code': '00000000-0000-0000-0000-000000000000'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 404)

        # 2. Integer PK Attack Versuch (z. B. "1" oder "999") -> muss 404 liefern
        res_pk = self.client.post(
            reverse('api_scan_qr'),
            data=json.dumps({'code': '1'}),
            content_type='application/json'
        )
        self.assertEqual(res_pk.status_code, 404)

        # 3. Unbezahlte Registrierung gescannt -> 400 unpaid
        unpaid_reg = EventRegistration.objects.create(user=self.user, event=self.event)
        res_unpaid = self.client.post(
            reverse('api_scan_qr'),
            data=json.dumps({'code': str(unpaid_reg.checkin_token)}),
            content_type='application/json'
        )
        self.assertEqual(res_unpaid.status_code, 400)
        self.assertEqual(res_unpaid.json()['status'], 'unpaid')

        # 4. Bezahlt -> Erst-Scan liefert status: success
        unpaid_reg.mark_as_paid()
        res_valid = self.client.post(
            reverse('api_scan_qr'),
            data=json.dumps({'code': str(unpaid_reg.checkin_token)}),
            content_type='application/json'
        )
        self.assertEqual(res_valid.status_code, 200)
        self.assertEqual(res_valid.json()['status'], 'success')
        self.assertFalse(res_valid.json()['already_checked_in'])

        # 5. Zweiter Scan desselben Gastes -> status: already_checked_in
        res_second = self.client.post(
            reverse('api_scan_qr'),
            data=json.dumps({'code': str(unpaid_reg.checkin_token)}),
            content_type='application/json'
        )
        self.assertEqual(res_second.status_code, 200)
        self.assertEqual(res_second.json()['status'], 'already_checked_in')
        self.assertTrue(res_second.json()['already_checked_in'])


class MultiEventTicketAndCheckinTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_superuser(
            username='staff_scanner', email='staff@example.com', password='password'
        )
        self.guest = User.objects.create_user(
            username='multi_guest', email='guest@example.com', password='password'
        )

        # Event 1: Vorjahr (inaktiv)
        self.past_event = Event.objects.create(
            title='LAN Party 2025',
            slug='lan-party-2025',
            is_active=False,
            status=Event.Status.FINISHED,
            start_date=timezone.now() - timedelta(days=365),
            end_date=timezone.now() - timedelta(days=363),
            price=30.00,
        )
        self.past_ticket = TicketType.objects.create(
            event=self.past_event,
            name="Frühbucher 2025",
            price=25.00,
            is_active=True,
        )
        self.past_reg = EventRegistration.objects.create(
            user=self.guest,
            event=self.past_event,
            ticket_type=self.past_ticket,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )

        # Event 2: Aktuelles Jahr (aktiv)
        self.active_event = Event.objects.create(
            title='LAN Party 2026',
            slug='lan-party-2026',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=30),
            end_date=timezone.now() + timedelta(days=32),
            price=35.00,
        )
        self.active_ticket = TicketType.objects.create(
            event=self.active_event,
            name="Standard 2026",
            price=35.00,
            is_active=True,
        )

    def test_scan_qr_api_rejects_inactive_event_ticket(self):
        """Scanner verweigert Einlass, wenn der gescannte QR-Code zu einem alten / inaktiven Event gehört."""
        self.client.login(username='staff_scanner', password='password')
        res = self.client.post(
            reverse('api_scan_qr'),
            data=json.dumps({'code': str(self.past_reg.checkin_token)}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['status'], 'event_mismatch')
        self.assertIn('LAN Party 2025', data['message'])
        self.assertIn('LAN Party 2026', data['message'])

        # Historische Registrierung darf NICHT eingecheckt worden sein
        self.past_reg.refresh_from_db()
        self.assertFalse(self.past_reg.is_checked_in)

    def test_process_checkin_rejects_inactive_event_ticket(self):
        """process_checkin View verweigert Tickets vergangener Events."""
        self.client.login(username='staff_scanner', password='password')
        response = self.client.get(
            reverse('process_checkin', kwargs={'registration_id': self.past_reg.id, 'token': self.past_reg.checkin_token})
        )
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, 'events/checkin_failed.html')
        self.assertContains(response, 'LAN Party 2025', status_code=400)

    def test_can_check_in_model_method_validates_active_event(self):
        """Model-Methode can_check_in schlägt für inaktive Events fehl."""
        can_ci, reason = self.past_reg.can_check_in()
        self.assertFalse(can_ci)
        self.assertIn("LAN Party 2025", reason)

    def test_event_admin_clone_tickets(self):
        """Beim Speichern eines neuen Events können Ticketkategorien eines Quell-Events geklont werden."""
        from events.admin import EventAdmin, EventAdminForm
        from django.contrib.admin.sites import AdminSite

        site = AdminSite()
        admin_instance = EventAdmin(Event, site)

        new_event = Event(
            title='LAN Party 2027',
            slug='lan-party-2027',
            is_active=False,
            status=Event.Status.DRAFT,
            start_date=timezone.now() + timedelta(days=400),
            end_date=timezone.now() + timedelta(days=402),
            price=40.00,
        )
        new_event.save()

        form = EventAdminForm(data={
            'title': new_event.title,
            'slug': new_event.slug,
            'status': new_event.status,
            'start_date': new_event.start_date,
            'end_date': new_event.end_date,
            'price': new_event.price,
            'max_guests': 100,
            'clone_tickets_from': self.past_event.id,
        }, instance=new_event)
        self.assertTrue(form.is_valid())

        request = self.client.get('/').wsgi_request
        request.user = self.staff_user
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        admin_instance.save_model(request, new_event, form, change=True)
        self.assertTrue(new_event.ticket_types.filter(name="Frühbucher 2025").exists())

    def test_event_admin_auto_creates_default_ticket(self):
        """Wird ein Event ohne Tickets gespeichert, wird automatisch ein Standard-Ticket erzeugt."""
        from events.admin import EventAdmin, EventAdminForm
        from django.contrib.admin.sites import AdminSite

        site = AdminSite()
        admin_instance = EventAdmin(Event, site)

        event_no_tickets = Event(
            title='Auto Ticket Event',
            slug='auto-ticket-event',
            is_active=False,
            status=Event.Status.DRAFT,
            start_date=timezone.now() + timedelta(days=200),
            end_date=timezone.now() + timedelta(days=202),
            price=45.00,
        )
        event_no_tickets.save()

        form = EventAdminForm(data={
            'title': event_no_tickets.title,
            'slug': event_no_tickets.slug,
            'status': event_no_tickets.status,
            'start_date': event_no_tickets.start_date,
            'end_date': event_no_tickets.end_date,
            'price': event_no_tickets.price,
            'max_guests': 100,
        }, instance=event_no_tickets)
        self.assertTrue(form.is_valid())

        request = self.client.get('/').wsgi_request
        request.user = self.staff_user
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        admin_instance.save_model(request, event_no_tickets, form, change=True)
        self.assertTrue(event_no_tickets.ticket_types.filter(name="Standard", price=45.00).exists())

    def test_dashboard_displays_past_event_notice_when_not_registered(self):
        """Gast mit Registrierung aus dem Vorjahr sieht den Hinweis auf erforderliche Neuanmeldung."""
        self.client.login(username='multi_guest', password='password')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LAN Party 2025')
        self.assertContains(response, 'LAN Party 2026')
        self.assertContains(response, 'neue Anmeldung erforderlich')










