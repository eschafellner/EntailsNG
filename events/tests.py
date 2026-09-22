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

    def test_dashboard_query_budget(self):
        """Dashboard-Abfragen für eingeloggten User mit aktiver Registrierung bleiben innerhalb des Budgets."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.login(username='gamer1', password='password')
        # Cache-Aufwärmung
        self.client.get(reverse('dashboard'))

        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse('dashboard'))
            self.assertEqual(resp.status_code, 200)

        # Dashboard muss unter 15 Queries bleiben (keine N+1 Schleifen)
        self.assertLessEqual(len(ctx.captured_queries), 15)

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
        reg, created, reactivated = RegistrationService.register_user(
            user=self.user1,
            event_id=self.event.id,
            ticket_type_id=self.ticket_type.id
        )
        self.assertTrue(created)
        self.assertFalse(reactivated)
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
        reg, created, reactivated = RegistrationService.register_user(self.user, self.event.id, ticket.id)
        self.assertTrue(created)
        self.assertFalse(reactivated)
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.UNPAID)

        # Registrierung stornieren
        reg.mark_as_cancelled()
        self.assertEqual(reg.payment_status, EventRegistration.PaymentStatus.CANCELLED)
        self.assertIsNotNone(reg.cancelled_at)

        # Erneute Anmeldung für dasselbe Event (darf keinen IntegrityError werfen!)
        new_reg, new_created, new_reactivated = RegistrationService.register_user(self.user, self.event.id, ticket.id)
        self.assertFalse(new_created)
        self.assertTrue(new_reactivated)
        self.assertEqual(new_reg.pk, reg.pk)
        self.assertEqual(new_reg.payment_status, EventRegistration.PaymentStatus.UNPAID)
        self.assertIsNone(new_reg.cancelled_at)
        self.assertEqual(EventRegistration.objects.filter(user=self.user, event=self.event).count(), 1)


    def test_negative_event_end_date_before_start_date_fails(self):
        """Negativer Test: Ein Event mit Enddatum vor Startdatum wirft ValidationError in clean() und IntegrityError bei save()."""
        from django.core.exceptions import ValidationError
        from django.db.utils import IntegrityError
        bad_event = Event(
            title="Broken Dates LAN",
            is_active=False,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=5),
        )
        with self.assertRaises(ValidationError):
            bad_event.clean()
        with self.assertRaises(IntegrityError):
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
            reg.full_clean()

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
        reactivated_reg, created, reactivated = RegistrationService.register_user(
            user=self.user,
            event_id=self.event.id
        )

        self.assertFalse(created)
        self.assertTrue(reactivated)
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


class PaymentQrAndDashboardEventInfoTests(TestCase):

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

    def test_epc_qr_payload_generation(self):
        """Testet die normgerechte Zusammensetzung des EPC069-12 GiroCode Payloads."""
        from configuration.models import GeneralConfiguration
        from events.payment_qr import generate_epc_qr_payload, generate_epc_qr_png

        config = GeneralConfiguration.load()
        config.kontoinhaber = 'LAN e.V.'
        config.iban = 'DE89370400440532013000'
        config.bic = 'GENODEF1S01'
        config.save()

        ticket = TicketType.objects.create(event=self.event, name='VIP', price=35.50)
        reg_with_ticket = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            ticket_type=ticket,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )

        payload = generate_epc_qr_payload(reg_with_ticket, config=config)
        lines = payload.split('\n')
        self.assertEqual(len(lines), 12)
        self.assertEqual(lines[0], 'BCD')
        self.assertEqual(lines[1], '002')
        self.assertEqual(lines[2], '1')
        self.assertEqual(lines[3], 'SCT')
        self.assertEqual(lines[4], 'GENODEF1S01')
        self.assertEqual(lines[5], 'LAN e.V.')
        self.assertEqual(lines[6], 'DE89370400440532013000')
        self.assertEqual(lines[7], 'EUR35.50')
        self.assertEqual(lines[8], '')
        self.assertEqual(lines[9], '')
        self.assertTrue(lines[10].startswith('gamer1'))
        # Ohne Ticket -> Betrag bleibt leer
        user_no_ticket = User.objects.create_user(username='gamer_no_ticket', password='password')
        reg_no_ticket = EventRegistration.objects.create(
            user=user_no_ticket,
            event=self.event,
            ticket_type=None,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )
        payload_no_ticket = generate_epc_qr_payload(reg_no_ticket, config=config)
        lines_no_ticket = payload_no_ticket.split('\n')
        self.assertEqual(lines_no_ticket[7], '')  # Betrag leer
        self.assertTrue(lines_no_ticket[10].startswith('gamer_no_ticket'))

        # Prüfung gegen Zeilenumbruch-Injection im Kontoinhaber
        config.kontoinhaber = 'LAN e.V.\r\nATTACKER'
        config.save()
        payload_injected = generate_epc_qr_payload(reg_with_ticket, config=config)
        self.assertEqual(len(payload_injected.split('\n')), 12)
        self.assertEqual(payload_injected.split('\n')[5], 'LAN e.V. ATTACKER')

        # PNG Erzeugung liefert valide Bild-Bytes
        png_bytes = generate_epc_qr_png(reg_with_ticket, config=config)
        self.assertTrue(len(png_bytes) > 100)
        self.assertTrue(png_bytes.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_registration_payment_qr_view_access_control(self):
        """Zugriffsschutz auf Payment-QR: Anonym -> 302, Fremder -> 403, Eigentümer/Staff -> 200."""
        from configuration.models import GeneralConfiguration

        config = GeneralConfiguration.load()
        config.kontoinhaber = 'LAN e.V.'
        config.iban = 'DE89370400440532013000'
        config.save()

        ticket = TicketType.objects.create(event=self.event, name='Standard', price=20.00)
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            ticket_type=ticket,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )

        other_user = User.objects.create_user(username='stranger', password='password')
        url = reverse('registration_payment_qr', kwargs={'registration_id': registration.id})

        # 1. Anonym -> Redirect zu Login
        resp_anon = self.client.get(url)
        self.assertEqual(resp_anon.status_code, 302)

        # 2. Fremder Benutzer -> 403 Forbidden
        self.client.login(username='stranger', password='password')
        resp_other = self.client.get(url)
        self.assertEqual(resp_other.status_code, 403)

        # 3. Eigentümer -> 200 OK PNG
        self.client.login(username='gamer1', password='password')
        resp_owner = self.client.get(url)
        self.assertEqual(resp_owner.status_code, 200)
        self.assertEqual(resp_owner['Content-Type'], 'image/png')
        self.assertIn('private, no-store', resp_owner['Cache-Control'])

        # 4. Staff -> 200 OK PNG
        self.client.login(username='admin', password='password')
        resp_staff = self.client.get(url)
        self.assertEqual(resp_staff.status_code, 200)
        self.assertEqual(resp_staff['Content-Type'], 'image/png')

    def test_registration_payment_qr_view_paid_or_free_rejected(self):
        """Bereits bezahlte oder kostenlose Registrierungen erhalten keinen Zahlungs-QR (400)."""
        from configuration.models import GeneralConfiguration

        config = GeneralConfiguration.load()
        config.kontoinhaber = 'LAN e.V.'
        config.iban = 'DE89370400440532013000'
        config.save()

        user_free = User.objects.create_user(username='user_free', password='password')
        ticket_free = TicketType.objects.create(event=self.event, name='Free', price=0.00)
        reg_free = EventRegistration.objects.create(
            user=user_free,
            event=self.event,
            ticket_type=ticket_free,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )

        user_paid = User.objects.create_user(username='user_paid', password='password')
        ticket_paid = TicketType.objects.create(event=self.event, name='Paid', price=25.00)
        reg_already_paid = EventRegistration.objects.create(
            user=user_paid,
            event=self.event,
            ticket_type=ticket_paid,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )

        # Free Ticket -> 400
        self.client.login(username='user_free', password='password')
        url_free = reverse('registration_payment_qr', kwargs={'registration_id': reg_free.id})
        resp_free = self.client.get(url_free)
        self.assertEqual(resp_free.status_code, 400)

        # Already Paid -> 400
        self.client.login(username='user_paid', password='password')
        url_paid = reverse('registration_payment_qr', kwargs={'registration_id': reg_already_paid.id})
        resp_paid = self.client.get(url_paid)
        self.assertEqual(resp_paid.status_code, 400)

    def test_registration_checkin_qr_view_access_control(self):
        """Zugriffsschutz auf Check-In-QR: Anonym -> 302, Fremder -> 403, Unbezahlt -> 400, Bezahlt/Staff -> 200 PNG."""
        from events.payment_qr import generate_checkin_qr_png

        # Direkte Prüfung der Bild-Generierung
        test_png = generate_checkin_qr_png('https://example.com/test')
        self.assertTrue(test_png.startswith(b'\x89PNG\r\n\x1a\n'))

        ticket = TicketType.objects.create(event=self.event, name='Standard', price=20.00)
        reg = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            ticket_type=ticket,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )

        other_user = User.objects.create_user(username='qr_stranger', password='password')
        url = reverse('registration_checkin_qr', kwargs={'registration_id': reg.id})

        # 1. Anonym -> Redirect zu Login
        resp_anon = self.client.get(url)
        self.assertEqual(resp_anon.status_code, 302)

        # 2. Fremder Benutzer -> 403 Forbidden
        self.client.login(username='qr_stranger', password='password')
        resp_other = self.client.get(url)
        self.assertEqual(resp_other.status_code, 403)

        # 3. Eigentümer bei unbezahlt -> 400 Bad Request
        self.client.login(username='gamer1', password='password')
        resp_unpaid = self.client.get(url)
        self.assertEqual(resp_unpaid.status_code, 400)

        # 4. Status auf BEZAHLT ändern
        reg.payment_status = EventRegistration.PaymentStatus.PAID
        reg.save()

        # Eigentümer bei bezahlt -> 200 OK PNG
        resp_owner = self.client.get(url)
        self.assertEqual(resp_owner.status_code, 200)
        self.assertEqual(resp_owner['Content-Type'], 'image/png')
        self.assertIn('private, no-store', resp_owner['Cache-Control'])
        self.assertTrue(resp_owner.content.startswith(b'\x89PNG\r\n\x1a\n'))

        # 5. Staff -> 200 OK PNG
        self.client.login(username='admin', password='password')
        resp_staff = self.client.get(url)
        self.assertEqual(resp_staff.status_code, 200)
        self.assertEqual(resp_staff['Content-Type'], 'image/png')

    def test_dashboard_renders_local_checkin_qr_no_external_leak(self):
        """Dashboard rendert lokalen Check-In QR-Link und enthält keinen Verweis auf externe APIs."""
        ticket = TicketType.objects.create(event=self.event, name='Standard', price=20.00)
        reg_paid = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            ticket_type=ticket,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )

        self.client.login(username='gamer1', password='password')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

        local_qr_url = reverse('registration_checkin_qr', kwargs={'registration_id': reg_paid.id})
        self.assertContains(response, local_qr_url)
        self.assertNotContains(response, 'api.qrserver.com')


    def test_dashboard_event_info_and_single_day_date(self):
        """Dashboard zeigt Veranstaltungsinformationen über der Sitzplan-Preview; 1-Tages-Events zeigen nur ein Datum."""
        # 1. Mehrtägiges Event (Start != Ende)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LAN Party 2026')
        start_fmt = self.event.start_date.strftime('%d.%m.%Y')
        end_fmt = self.event.end_date.strftime('%d.%m.%Y')
        self.assertContains(response, f'{start_fmt} – {end_fmt}')

        # 2. Eintägiges Event (Start und Ende am selben Tag)
        now = timezone.now()
        single_day_event = Event.objects.create(
            title='1-Day Cup 2026',
            slug='1-day-cup-2026',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=now.replace(hour=10, minute=0, second=0),
            end_date=now.replace(hour=22, minute=0, second=0),
        )
        resp_single = self.client.get(reverse('dashboard'))
        self.assertEqual(resp_single.status_code, 200)
        self.assertContains(resp_single, '1-Day Cup 2026')
        single_fmt = single_day_event.start_date.strftime('%d.%m.%Y')
        self.assertContains(resp_single, f'📅 {single_fmt}')
        self.assertNotContains(resp_single, f'{single_fmt} – {single_fmt}')


    def test_event_and_registration_properties(self):
        """Testet die Model-Properties is_expired, status_step, seat_label, can_show_payment_qr."""
        # 1. Event.is_expired
        self.assertFalse(self.event.is_expired)
        past_event = Event.objects.create(
            title='Past Event',
            slug='past-event',
            is_active=False,
            start_date=timezone.now() - timedelta(days=10),
            end_date=timezone.now() - timedelta(days=8),
        )
        self.assertTrue(past_event.is_expired)

        # 2. EventRegistration.status_step
        reg = EventRegistration.objects.create(
            event=self.event,
            user=self.user,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )
        self.assertEqual(reg.status_step, 2)

        reg.payment_status = EventRegistration.PaymentStatus.PAID
        reg.save()
        self.assertEqual(reg.status_step, 3)

        reg.is_checked_in = True
        reg.save()
        self.assertEqual(reg.status_step, 4)

        # 3. EventRegistration.seat_label
        self.assertIsNone(reg.seat_label)
        plan = SeatingPlan.objects.create(event=self.event, name="Halle", columns=5, rows=5)
        cell = SeatingCell.objects.create(
            plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT,
            seat_label="Reihe 1 / Platz 1", registration=reg
        )
        self.assertEqual(reg.seat_label, "Reihe 1 / Platz 1")

    def test_short_code_generation_and_collision_retry(self):
        """Testet die automatische Generierung des Ticket-Kurzcodes."""
        reg1 = EventRegistration.objects.create(event=self.event, user=self.user)
        self.assertTrue(bool(reg1.short_code))
        self.assertEqual(len(reg1.short_code), 8)

    def test_toggle_check_in_api_rejects_inactive_event(self):
        """Testet, dass toggle_check_in_api Anmeldungen für nicht-aktive Events ablehnt."""
        other_event = Event.objects.create(
            title='Inaktives Event',
            slug='inaktives-event',
            is_active=False,
            start_date=timezone.now() + timedelta(days=20),
            end_date=timezone.now() + timedelta(days=22),
        )
        reg_other = EventRegistration.objects.create(
            event=other_event,
            user=self.user,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )
        self.client.force_login(self.staff_user)
        response = self.client.post(
            reverse('api_toggle_check_in'),
            data=json.dumps({'registration_id': reg_other.id}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('nicht zur aktuellen Veranstaltung', response.json()['message'])


class EventRegistrationAdminPaymentEmailTests(TestCase):
    def setUp(self):
        from emails.models import EmailTemplate, GeneralEmailSettings
        email_settings = GeneralEmailSettings.load()
        email_settings.is_enabled = True
        email_settings.transport_mode = 'env'
        email_settings.sender_email = 'noreply@example.com'
        email_settings.save()
        EmailTemplate.objects.get_or_create(
            key='payment_confirmation',
            defaults={
                'name': 'Zahlungsbestätigung',
                'subject': 'Zahlung bestätigt für {event_title}',
                'content': 'Hallo {username}, Betrag: {amount}',
                'is_active': True,
            },
        )
        self.staff_user = User.objects.create_superuser(username='super_admin', email='super@example.com', password='password')
        self.user = User.objects.create_user(username='player1', email='player1@example.com', password='password')
        self.event = Event.objects.create(
            title='LAN Party 2026',
            slug='lan-2026',
            is_active=True,
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=7),
            price=35.00,
        )
        self.ticket = TicketType.objects.create(event=self.event, name='Standard', price=35.00)
        self.reg = EventRegistration.objects.create(
            event=self.event,
            user=self.user,
            ticket_type=self.ticket,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )

    def test_admin_save_model_sends_email_when_payment_status_changed_to_paid(self):
        from events.admin import EventRegistrationAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from unittest.mock import patch

        admin = EventRegistrationAdmin(EventRegistration, AdminSite())
        rf = RequestFactory()
        request = rf.post('/admin/events/eventregistration/')
        request.user = self.staff_user
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.middleware import MessageMiddleware
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)

        class DummyForm:
            changed_data = ['payment_status']

        self.reg.payment_status = EventRegistration.PaymentStatus.PAID

        with patch('events.models.send_system_email') as mock_send:
            with self.captureOnCommitCallbacks(execute=True):
                admin.save_model(request, self.reg, DummyForm(), change=True)

            mock_send.assert_called_once()
            self.assertEqual(mock_send.call_args[0][0], 'payment_confirmation')
            self.assertEqual(mock_send.call_args[0][1], 'player1@example.com')
            self.reg.refresh_from_db()
            self.assertIsNotNone(self.reg.paid_at)
            self.assertEqual(self.reg.paid_amount, 35.00)

    def test_admin_action_mark_as_paid_sends_email(self):
        from events.admin import EventRegistrationAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from unittest.mock import patch

        admin = EventRegistrationAdmin(EventRegistration, AdminSite())
        rf = RequestFactory()
        request = rf.post('/admin/events/eventregistration/')
        request.user = self.staff_user
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.middleware import MessageMiddleware
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)

        qs = EventRegistration.objects.filter(pk=self.reg.pk)

        with patch('events.models.send_system_email') as mock_send:
            with self.captureOnCommitCallbacks(execute=True):
                admin.action_mark_as_paid(request, qs)

            mock_send.assert_called_once()
            self.assertEqual(mock_send.call_args[0][0], 'payment_confirmation')
            self.assertEqual(mock_send.call_args[0][1], 'player1@example.com')
            self.reg.refresh_from_db()
            self.assertIsNotNone(self.reg.paid_at)

    def test_admin_save_model_cancels_registration(self):
        from events.admin import EventRegistrationAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        admin = EventRegistrationAdmin(EventRegistration, AdminSite())
        rf = RequestFactory()
        request = rf.post('/admin/events/eventregistration/')
        request.user = self.staff_user
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.middleware import MessageMiddleware
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)

        class DummyForm:
            changed_data = ['payment_status']

        self.reg.is_checked_in = True
        self.reg.checked_in_at = timezone.now()
        self.reg.save()

        self.reg.payment_status = EventRegistration.PaymentStatus.CANCELLED
        admin.save_model(request, self.reg, DummyForm(), change=True)

        self.reg.refresh_from_db()
        self.assertEqual(self.reg.payment_status, EventRegistration.PaymentStatus.CANCELLED)
        self.assertFalse(self.reg.is_checked_in)
        self.assertIsNone(self.reg.checked_in_at)
        self.assertIsNotNone(self.reg.cancelled_at)

    def test_admin_save_model_creates_new_registration_with_paid_status(self):
        """
        Regressionstest: Ein im Backend neu angelegter Benutzer wird manuell
        über das Admin-Formular (change=False) für ein Event mit Bezahlstatus 'PAID' registriert.
        Darf nicht zu EventRegistration.DoesNotExist führen!
        """
        from events.admin import EventRegistrationAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from unittest.mock import patch

        new_user = User.objects.create_user(username='manualuser', email='manual@example.com', password='password')
        new_reg = EventRegistration(
            event=self.event,
            user=new_user,
            ticket_type=self.ticket,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )
        self.assertIsNone(new_reg.pk)

        admin = EventRegistrationAdmin(EventRegistration, AdminSite())
        rf = RequestFactory()
        request = rf.post('/admin/events/eventregistration/add/')
        request.user = self.staff_user
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.middleware import MessageMiddleware
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)

        class DummyForm:
            changed_data = []

        with patch('events.models.send_system_email') as mock_send:
            with self.captureOnCommitCallbacks(execute=True):
                # change=False simuliert das Hinzufügen eines neuen Objekts im Django Admin
                admin.save_model(request, new_reg, DummyForm(), change=False)

            mock_send.assert_called_once()
            self.assertEqual(mock_send.call_args[0][0], 'payment_confirmation')
            self.assertEqual(mock_send.call_args[0][1], 'manual@example.com')

        self.assertIsNotNone(new_reg.pk)
        new_reg.refresh_from_db()
        self.assertEqual(new_reg.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertIsNotNone(new_reg.paid_at)
        self.assertEqual(new_reg.paid_amount, 35.00)

    def test_admin_save_model_creates_new_registration_with_unpaid_status(self):
        """
        Regressionstest: Ein im Backend neu angelegter Benutzer wird manuell
        über das Admin-Formular (change=False) mit Status 'UNPAID' registriert.
        """
        from events.admin import EventRegistrationAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        new_user = User.objects.create_user(username='unpaiduser', email='unpaid@example.com', password='password')
        new_reg = EventRegistration(
            event=self.event,
            user=new_user,
            ticket_type=self.ticket,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )
        self.assertIsNone(new_reg.pk)

        admin = EventRegistrationAdmin(EventRegistration, AdminSite())
        rf = RequestFactory()
        request = rf.post('/admin/events/eventregistration/add/')
        request.user = self.staff_user
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.middleware import MessageMiddleware
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)

        class DummyForm:
            changed_data = []

        admin.save_model(request, new_reg, DummyForm(), change=False)

        self.assertIsNotNone(new_reg.pk)
        new_reg.refresh_from_db()
        self.assertEqual(new_reg.payment_status, EventRegistration.PaymentStatus.UNPAID)
        self.assertIsNone(new_reg.paid_at)

    def test_payment_service_mark_paid_on_unsaved_registration(self):
        """
        Defensiver Test: PaymentService.mark_paid speichert ein noch ungespeichertes
        EventRegistration-Objekt atomar, bevor der DB-Row-Lock angefordert wird.
        """
        from events.services import PaymentService

        new_user = User.objects.create_user(username='defensiveuser', email='defensive@example.com', password='password')
        unsaved_reg = EventRegistration(
            event=self.event,
            user=new_user,
            ticket_type=self.ticket,
        )
        self.assertIsNone(unsaved_reg.pk)

        saved_reg = PaymentService.mark_paid(unsaved_reg, amount=25.00, send_email=False)
        self.assertIsNotNone(saved_reg.pk)
        self.assertEqual(saved_reg.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertEqual(saved_reg.paid_amount, 25.00)
        self.assertIsNotNone(saved_reg.paid_at)


class ActiveEventCachingTests(TestCase):
    """
    Tests für das Caching von Event.objects.get_active() (Punkt 2 der Performance-Optimierung).
    Stellt sicher, dass mehrfache get_active()-Aufrufe im selben Request keine redundanten
    SQL-Abfragen ausführen und Änderungen am Event den Cache sauber invalidieren.
    """

    def setUp(self):
        from django.core.cache import cache
        from configuration.cache import clear_request_cache
        cache.clear()
        clear_request_cache()

        self.event = Event.objects.create(
            title="Aktives Sommer-Event",
            slug="aktives-sommer-event",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )

    def tearDown(self):
        from configuration.cache import clear_request_cache
        clear_request_cache()

    def test_repeated_get_active_in_same_request_executes_only_one_query(self):
        from configuration.cache import init_request_cache
        init_request_cache()

        # Beim ersten Aufruf: 1 SQL-Query (bzw. Cache-Fill)
        # Bei den Folgeaufrufen im selben Request: 0 weitere SQL-Queries!
        with self.assertNumQueries(1):
            event1 = Event.objects.get_active()
            event2 = Event.objects.get_active()
            event3 = Event.objects.get_active()

        self.assertEqual(event1.id, self.event.id)
        self.assertEqual(event2.id, self.event.id)
        self.assertEqual(event3.id, self.event.id)

    def test_save_event_invalidates_active_event_cache(self):
        from configuration.cache import init_request_cache
        init_request_cache()

        # 1. Cache befüllen
        active = Event.objects.get_active()
        self.assertEqual(active.id, self.event.id)

        # 2. Event deaktivieren
        self.event.is_active = False
        self.event.save()

        # 3. get_active() muss nun None liefern (Cache wurde invalidiert)
        active_after = Event.objects.get_active()
        self.assertIsNone(active_after)

    def test_delete_event_invalidates_active_event_cache(self):
        from configuration.cache import init_request_cache
        init_request_cache()

        # 1. Cache befüllen
        active = Event.objects.get_active()
        self.assertEqual(active.id, self.event.id)

        # 2. Event löschen
        self.event.delete()

        # 3. get_active() muss nun None liefern
        active_after = Event.objects.get_active()
        self.assertIsNone(active_after)


class GuestListAndPaymentCheckTests(TestCase):
    """Tests für die Gästeliste, Such- und Clanfilter, sowie die Kontocheck-Aktualisierung und Berechtigungen."""

    def setUp(self):
        from django.contrib.auth.models import Permission
        from clans.models import Clan, ClanMembership
        from seating.models import SeatingPlan, SeatingCell

        self.event = Event.objects.create(
            title="NorthLAN 2026",
            slug="northlan-2026",
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=14),
            end_date=timezone.now() + timedelta(days=16),
            max_guests=100,
        )

        self.user1 = User.objects.create_user(username="alice", email="alice@example.com", password="password")
        self.user2 = User.objects.create_user(username="bob", email="bob@example.com", password="password")
        self.user3 = User.objects.create_user(username="charlie", email="charlie@example.com", password="password")
        self.user4 = User.objects.create_user(username="dave_cancelled", email="dave@example.com", password="password")

        # Orga-User mit expliziter Berechtigung can_update_payment_check
        self.orga_user = User.objects.create_user(username="orga_officer", email="orga@example.com", password="password")
        perm = Permission.objects.get(codename="can_update_payment_check")
        self.orga_user.user_permissions.add(perm)

        # Staff Admin
        self.staff_admin = User.objects.create_superuser(username="sadmin", email="admin@example.com", password="password")

        # Clan anlegen & User1 zuweisen
        self.clan = Clan.objects.create(name="Team Apex", tag="APX", slug="team-apex")
        ClanMembership.objects.create(user=self.user1, clan=self.clan, status=ClanMembership.Status.ACCEPTED)

        # Sitzplan anlegen
        self.plan = SeatingPlan.objects.create(event=self.event, name="Halle 1", columns=10, rows=10)

        # Anmeldungen anlegen
        self.reg1 = EventRegistration.objects.create(
            user=self.user1,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
            paid_amount=35.00,
        )
        self.seat1 = SeatingCell.objects.create(
            plan=self.plan,
            x=1,
            y=1,
            cell_type=SeatingCell.CellType.SEAT,
            seat_label="A-01",
            registration=self.reg1,
            reservation_status=SeatingCell.ReservationStatus.RESERVED,
        )

        self.reg2 = EventRegistration.objects.create(
            user=self.user2,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )

        self.reg3 = EventRegistration.objects.create(
            user=self.user3,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
            paid_amount=35.00,
        )

        self.reg4_cancelled = EventRegistration.objects.create(
            user=self.user4,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.CANCELLED,
        )

    def test_guest_list_view_renders_correctly(self):
        """Gästeliste ist öffentlich aufrufbar, listet Teilnehmer auf und schließt Stornierte aus."""
        response = self.client.get(reverse('guest_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['event'], self.event)
        self.assertEqual(response.context['total_count'], 3)
        self.assertEqual(response.context['paid_count'], 2)
        self.assertEqual(response.context['unpaid_count'], 1)

        content = response.content.decode('utf-8')
        self.assertIn("alice", content)
        self.assertIn("bob", content)
        self.assertIn("charlie", content)
        self.assertNotIn("dave_cancelled", content)
        self.assertIn("[APX] Team Apex", content)
        self.assertIn("A-01", content)
        self.assertIn("?seat=A-01", content)

    def test_guest_list_search_by_username(self):
        """Suchfilter filtert Teilnehmer nach Benutzernamen."""
        response = self.client.get(reverse('guest_list'), {'q': 'ali'})
        self.assertEqual(response.status_code, 200)
        regs = response.context['registrations']
        self.assertEqual(len(regs), 1)
        self.assertEqual(regs[0].user.username, "alice")

    def test_guest_list_filter_by_clan(self):
        """Clan-Filter liefert nur Mitglieder des gewählten Clans oder Teilnehmer ohne Clan."""
        # 1. Filter nach spezifischem Clan
        resp_clan = self.client.get(reverse('guest_list'), {'clan': 'team-apex'})
        regs_clan = resp_clan.context['registrations']
        self.assertEqual(len(regs_clan), 1)
        self.assertEqual(regs_clan[0].user.username, "alice")

        # 2. Filter nach "none" (ohne Clan)
        resp_none = self.client.get(reverse('guest_list'), {'clan': 'none'})
        regs_none = resp_none.context['registrations']
        self.assertEqual(len(regs_none), 2)
        usernames = {r.user.username for r in regs_none}
        self.assertEqual(usernames, {"bob", "charlie"})

    def test_guest_list_filter_by_payment_status(self):
        """Statusfilter trennt nach bezahlt und unbezahlt."""
        resp_paid = self.client.get(reverse('guest_list'), {'status': 'paid'})
        self.assertEqual(len(resp_paid.context['registrations']), 2)

        resp_unpaid = self.client.get(reverse('guest_list'), {'status': 'unpaid'})
        self.assertEqual(len(resp_unpaid.context['registrations']), 1)
        self.assertEqual(resp_unpaid.context['registrations'][0].user.username, "bob")

    def test_guest_list_without_active_event(self):
        """Wenn kein Event aktiv ist, rendert die Gästeliste sauber ohne Exception."""
        self.event.is_active = False
        self.event.save()
        response = self.client.get(reverse('guest_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['event'])

    def test_update_payment_check_api_permissions(self):
        """Nur Benutzer mit can_update_payment_check oder Staff dürfen den Kontocheck aktualisieren."""
        url = reverse('api_update_payment_check', kwargs={'event_id': self.event.id})

        # 1. Anonymer User -> Login Redirect
        resp_anon = self.client.post(url)
        self.assertEqual(resp_anon.status_code, 302)

        # 2. Normaler User ohne Permission -> 403 Forbidden
        self.client.login(username="alice", password="password")
        resp_user_ajax = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_user_ajax.status_code, 403)
        self.client.logout()

        # 3. Orga-User mit Permission -> 200 OK
        self.client.login(username="orga_officer", password="password")
        self.assertIsNone(self.event.last_payment_check)

        resp_orga = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_orga.status_code, 200)
        data = resp_orga.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('formatted_time', data)

        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.last_payment_check)
        self.client.logout()

        # 4. Staff-Admin -> 200 OK
        self.client.login(username="sadmin", password="password")
        resp_staff = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_staff.status_code, 200)

    def test_update_payment_check_api_custom_datetime(self):
        """Manuelle Angabe eines Datetime-Werts (auch HTML5 datetime-local ohne Sekunden) wird korrekt übernommen."""
        self.client.login(username="orga_officer", password="password")
        url = reverse('api_update_payment_check', kwargs={'event_id': self.event.id})

        # Test mit ISO-String ohne Sekunden (HTML5 input type="datetime-local")
        target_time_str = "2026-09-20T14:30"
        resp = self.client.post(
            url,
            data=json.dumps({'custom_date': target_time_str}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)

        self.event.refresh_from_db()
        local_time = timezone.localtime(self.event.last_payment_check)
        self.assertEqual(local_time.year, 2026)
        self.assertEqual(local_time.month, 9)
        self.assertEqual(local_time.day, 20)
        self.assertEqual(local_time.hour, 14)
        self.assertEqual(local_time.minute, 30)

        # Route-Alias /events/api/event/<id>/update-payment-check/ testen
        alias_url = f"/events/api/event/{self.event.id}/update-payment-check/"
        resp_alias = self.client.post(
            alias_url,
            data=json.dumps({'custom_date': "2026-09-21T16:45:00"}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp_alias.status_code, 200)
        self.event.refresh_from_db()
        local_time2 = timezone.localtime(self.event.last_payment_check)
        self.assertEqual(local_time2.day, 21)
        self.assertEqual(local_time2.hour, 16)
        self.assertEqual(local_time2.minute, 45)

    def test_update_payment_check_api_invalid_date(self):
        """Ungültiger Datumswert liefert HTTP 400 Bad Request."""
        self.client.login(username="orga_officer", password="password")
        url = reverse('api_update_payment_check', kwargs={'event_id': self.event.id})

        resp = self.client.post(
            url,
            data=json.dumps({'custom_date': "ungueltiges-datum"}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('message', data)

    def test_event_admin_action_set_payment_check_now(self):
        """Admin-Aktion 'action_set_payment_check_now' aktualisiert Events im Admin."""
        from events.admin import EventAdmin
        from django.contrib.admin.sites import site

        admin_instance = EventAdmin(Event, site)
        self.assertIsNone(self.event.last_payment_check)

        request = self.client.get('/').wsgi_request
        request.user = self.staff_admin
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        admin_instance.action_set_payment_check_now(request, Event.objects.filter(pk=self.event.pk))

        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.last_payment_check)


















