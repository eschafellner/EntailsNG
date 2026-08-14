from datetime import timedelta
import json
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from events.models import Event, EventRegistration
from seating.models import SeatingCell, SeatingPlan

User = get_user_model()


class SeatingPlanTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='seatuser', email='seat@example.com', password='password'
        )
        self.event = Event.objects.create(
            title='Seating LAN',
            slug='seating-lan',
            is_active=True,
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=7),
        )
        self.plan = SeatingPlan.objects.create(
            event=self.event, name='Main Hall', columns=10, rows=10
        )
        self.seat_cell = SeatingCell.objects.create(
            plan=self.plan,
            x=1,
            y=1,
            cell_type=SeatingCell.CellType.SEAT,
            seat_label='A1',
        )
        self.registration = EventRegistration.objects.create(
            user=self.user, event=self.event
        )

    def test_get_event_seating_api(self):
        response = self.client.get(
            reverse('api_event_seating', kwargs={'event_id': self.event.id})
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['columns'], 10)
        self.assertEqual(len(data['cells']), 1)
        self.assertEqual(data['cells'][0]['seat_label'], 'A1')

    def test_reserve_seat_api(self):
        self.client.login(username='seatuser', password='password')
        response = self.client.post(
            reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
            data=json.dumps({'x': 1, 'y': 1}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.registration, self.registration)
        self.assertEqual(
            self.seat_cell.reservation_status,
            SeatingCell.ReservationStatus.PRE_RESERVED,
        )

    def test_release_seat_api(self):
        self.seat_cell.reserve_for_user(self.registration)
        self.client.login(username='seatuser', password='password')
        response = self.client.post(
            reverse('api_release_seat', kwargs={'event_id': self.event.id}),
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.seat_cell.refresh_from_db()
        self.assertIsNone(self.seat_cell.registration)
        self.assertEqual(
            self.seat_cell.reservation_status,
            SeatingCell.ReservationStatus.FREE,
        )

    def test_1000_seats_performance(self):
        # Erstelle 1000 Sitzplatz-Kacheln (50x20)
        large_event = Event.objects.create(
            title='Mega LAN',
            slug='mega-lan',
            is_active=True,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=2),
        )
        large_plan = SeatingPlan.objects.create(
            event=large_event, name='Arena 1000', columns=50, rows=20
        )
        cells = [
            SeatingCell(
                plan=large_plan,
                x=x,
                y=y,
                cell_type=SeatingCell.CellType.SEAT,
                seat_label=f"S-{x}-{y}",
            )
            for y in range(20)
            for x in range(50)
        ]
        SeatingCell.objects.bulk_create(cells)

        # Teste API Performance & Query Count für 1000 Kacheln (anonym: 2 Queries; eingeloggt: 3 Queries)
        with self.assertNumQueries(2):  # Plan fetch, Cells with select_related
            response = self.client.get(
                reverse('api_event_seating', kwargs={'event_id': large_event.id})
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['cells']), 1000)



class SeatingConsistencyAndSignalTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='seatuser2', email='seat2@example.com', password='password'
        )
        self.event = Event.objects.create(
            title='Seating LAN 2',
            slug='seating-lan-2',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=7),
        )
        self.plan = SeatingPlan.objects.create(
            event=self.event, name='Hall B', columns=5, rows=5
        )
        self.seat_cell = SeatingCell.objects.create(
            plan=self.plan,
            x=1,
            y=1,
            cell_type=SeatingCell.CellType.SEAT,
            seat_label='B1',
        )
        self.registration = EventRegistration.objects.create(
            user=self.user, event=self.event
        )
        self.seat_cell.reserve_for_user(self.registration)

    def test_seat_released_when_registration_cancelled(self):
        self.registration.payment_status = EventRegistration.PaymentStatus.CANCELLED
        self.registration.save()

        self.seat_cell.refresh_from_db()
        self.assertIsNone(self.seat_cell.registration)
        self.assertEqual(self.seat_cell.reservation_status, SeatingCell.ReservationStatus.FREE)

    def test_seat_released_when_registration_deleted(self):
        self.registration.delete()

        self.seat_cell.refresh_from_db()
        self.assertIsNone(self.seat_cell.registration)
        self.assertEqual(self.seat_cell.reservation_status, SeatingCell.ReservationStatus.FREE)

    def test_save_seating_plan_bulk_update(self):
        admin_user = User.objects.create_user(
            username='seating_admin', email='admin@example.com', password='password', is_staff=True
        )
        self.client.login(username='seating_admin', password='password')

        cells_payload = [
            {'x': 1, 'y': 1, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': 'B1-Updated', 'text_label': ''},
            {'x': 1, 'y': 2, 'cell_type': SeatingCell.CellType.WALL, 'seat_label': '', 'text_label': 'Wand'},
            {'x': 2, 'y': 1, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': 'B2', 'text_label': ''},
        ]
        response = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': cells_payload}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.plan.cells.count(), 3)
        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.seat_label, 'B1-Updated')

    def test_save_seating_plan_editor_validations(self):
        admin_user = User.objects.create_user(
            username='seating_validator', email='val@example.com', password='password', is_staff=True
        )
        self.client.login(username='seating_validator', password='password')

        # 1. Out-of-bounds Koordinaten (x=999 übersteigt columns=10)
        res_oob = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': [{'x': 999, 'y': 1, 'cell_type': 'SEAT'}]}),
            content_type='application/json'
        )
        self.assertEqual(res_oob.status_code, 400)
        self.assertIn("außerhalb des Rasters", res_oob.json()['message'])

        # 2. Ungültiger Zelltyp
        res_type = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': [{'x': 1, 'y': 1, 'cell_type': 'INVALID_TYPE'}]}),
            content_type='application/json'
        )
        self.assertEqual(res_type.status_code, 400)
        self.assertIn("Ungültiger Zelltyp", res_type.json()['message'])

        # 3. Schutz belegter Zellen: self.seat_cell (1,1) ist belegt durch self.registration.
        # Versuch A: Kachel (1,1) beim Speichern weglassen (Löschen) -> 400
        res_del = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': [{'x': 2, 'y': 2, 'cell_type': 'SEAT'}]}),
            content_type='application/json'
        )
        self.assertEqual(res_del.status_code, 400)
        self.assertIn("kann nicht gelöscht werden", res_del.json()['message'])

        # Versuch B: Belegten Sitzplatz in eine WAND umwandeln -> 400
        res_wall = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': [{'x': 1, 'y': 1, 'cell_type': 'WALL'}]}),
            content_type='application/json'
        )
        self.assertEqual(res_wall.status_code, 400)
        self.assertIn("kann nicht in \"WALL\" umgewandelt werden", res_wall.json()['message'])


    def test_admin_assign_seat_validations(self):
        admin_user = User.objects.create_user(
            username='staff_seating', email='staff@example.com', password='password', is_staff=True
        )
        user_c = User.objects.create_user(
            username='gamer_c', email='c@example.com', password='password'
        )
        reg_c = EventRegistration.objects.create(user=user_c, event=self.event)

        # 1. Wand-Kachel erstellen
        wall_cell = SeatingCell.objects.create(
            plan=self.plan, x=3, y=3, cell_type=SeatingCell.CellType.WALL
        )
        # 2. Blockierten Sitz erstellen
        blocked_cell = SeatingCell.objects.create(
            plan=self.plan, x=4, y=4, cell_type=SeatingCell.CellType.SEAT,
            reservation_status=SeatingCell.ReservationStatus.BLOCKED
        )

        self.client.login(username='staff_seating', password='password')

        # Versuch 1: Zuweisung auf Wand -> Fehler 400
        res_wall = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': reg_c.id, 'x': 3, 'y': 3}),
            content_type='application/json'
        )
        self.assertEqual(res_wall.status_code, 400)
        self.assertIn("kein Sitzplatz", res_wall.json()['message'])

        # Versuch 2: Zuweisung auf blockierten Platz -> Fehler 400
        res_blocked = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': reg_c.id, 'x': 4, 'y': 4}),
            content_type='application/json'
        )
        self.assertEqual(res_blocked.status_code, 400)
        self.assertIn("gesperrt", res_blocked.json()['message'])

        # Versuch 3: Zuweisung auf belegten Platz (self.seat_cell ist durch self.user belegt) -> Fehler 400
        res_occupied = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': reg_c.id, 'x': 1, 'y': 1}),
            content_type='application/json'
        )
        self.assertEqual(res_occupied.status_code, 400)
        self.assertIn("bereits von 'seatuser2' belegt", res_occupied.json()['message'])

        # Versuch 4: Freier Platz -> Erfolg
        free_cell = SeatingCell.objects.create(
            plan=self.plan, x=5, y=5, cell_type=SeatingCell.CellType.SEAT,
            reservation_status=SeatingCell.ReservationStatus.FREE
        )
        res_free = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': reg_c.id, 'x': 5, 'y': 5}),
            content_type='application/json'
        )
        self.assertEqual(res_free.status_code, 200)
        free_cell.refresh_from_db()
        self.assertEqual(free_cell.registration, reg_c)

    def test_get_event_seating_api_privacy_protection(self):
        # 1. Unauthentifizierter Request -> Keine PII (Benutzernamen, Clan, Check-in)
        self.client.logout()
        res_anon = self.client.get(reverse('api_event_seating', kwargs={'event_id': self.event.id}))
        self.assertEqual(res_anon.status_code, 200)
        data_anon = res_anon.json()

        # Finde die belegte Kachel
        occupied_cell_anon = next(c for c in data_anon['cells'] if c['x'] == 1 and c['y'] == 1)
        self.assertEqual(occupied_cell_anon['status'], 'PRE_RESERVED')
        self.assertIsNone(occupied_cell_anon['occupied_by'])
        self.assertIsNone(occupied_cell_anon['clan_name'])
        self.assertFalse(occupied_cell_anon['is_checked_in'])

        # 2. Authentifizierter Request -> PII sichtbar
        self.client.login(username='seatuser2', password='password')
        res_auth = self.client.get(reverse('api_event_seating', kwargs={'event_id': self.event.id}))
        self.assertEqual(res_auth.status_code, 200)
        data_auth = res_auth.json()

        occupied_cell_auth = next(c for c in data_auth['cells'] if c['x'] == 1 and c['y'] == 1)
        self.assertEqual(occupied_cell_auth['status'], 'PRE_RESERVED')
        self.assertEqual(occupied_cell_auth['occupied_by'], 'seatuser2')







