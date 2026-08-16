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
            for y in range(1, 21)
            for x in range(1, 51)
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
        self.registration.mark_as_cancelled()

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

    def test_seating_plan_clone_isolation_between_events(self):
        """Positiver Test: Klonen eines Sitzplans für ein neues Event isoliert die Belegungen vollständig."""
        user_new = User.objects.create_user(
            username='seatuser1', email='seat1@example.com', password='password'
        )
        event_2027 = Event.objects.create(
            title="Haag-networX 2027",
            slug="haag-networx-2027",
            is_active=False,
            start_date=timezone.now() + timedelta(days=365),
            end_date=timezone.now() + timedelta(days=367),
        )

        # Klonen für 2027
        cloned_plan = self.plan.clone_for_event(new_event=event_2027, new_name="Halle 1 (2027)")
        self.assertEqual(cloned_plan.event, event_2027)
        self.assertEqual(cloned_plan.columns, self.plan.columns)
        self.assertEqual(cloned_plan.rows, self.plan.rows)

        # 2. Im geklonten Plan müssen alle Plätze frei sein
        cloned_cell = cloned_plan.cells.get(x=1, y=1)
        self.assertIsNone(cloned_cell.registration)
        self.assertEqual(cloned_cell.reservation_status, SeatingCell.ReservationStatus.FREE)

        # 3. Im Original-Plan 2026 ist Platz (1,1) unverändert belegt
        original_cell = self.plan.cells.get(x=1, y=1)
        self.assertIsNotNone(original_cell.registration)
        self.assertEqual(original_cell.registration.user.username, 'seatuser2')

        # 4. User 1 bucht Platz (1,1) auf dem neuen Event 2027
        reg_2027 = EventRegistration.objects.create(
            event=event_2027,
            user=user_new,
            payment_status=EventRegistration.PaymentStatus.PAID
        )
        cloned_cell.registration = reg_2027
        cloned_cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
        cloned_cell.save()

        # Beide Events müssen unabhängig voneinander ihre eigenen User haben
        original_cell.refresh_from_db()
        cloned_cell.refresh_from_db()
        self.assertEqual(original_cell.registration.user.username, 'seatuser2')
        self.assertEqual(cloned_cell.registration.user.username, 'seatuser1')

    def test_negative_cannot_repoint_occupied_seating_plan_to_different_event(self):
        """Negativer Test: Ein belegter Sitzplan darf nicht einfach einem anderen Event zugewiesen werden."""
        from django.core.exceptions import ValidationError

        event_2027 = Event.objects.create(
            title="Haag-networX 2027",
            slug="haag-2027-neg",
            is_active=False,
            start_date=timezone.now() + timedelta(days=365),
            end_date=timezone.now() + timedelta(days=367),
        )

        # self.plan gehört zu self.event (2026) und hat belegte Plätze
        self.plan.event = event_2027
        with self.assertRaises(ValidationError) as ctx:
            self.plan.save()

        self.assertIn('bereits Teilnehmer-Reservierungen', str(ctx.exception))

    def test_negative_cannot_assign_cross_event_registration_to_cell(self):
        """Negativer Test: Kacheln dürfen keine Registrierungen eines fremden Events zugewiesen bekommen."""
        from django.core.exceptions import ValidationError

        event_other = Event.objects.create(
            title="Anderes Event",
            slug="anderes-event",
            is_active=False,
            start_date=timezone.now() + timedelta(days=100),
            end_date=timezone.now() + timedelta(days=102),
        )
        reg_other = EventRegistration.objects.create(
            event=event_other,
            user=self.user,
            payment_status=EventRegistration.PaymentStatus.PAID
        )

        # self.plan gehört zu self.event
        free_cell = SeatingCell.objects.create(
            plan=self.plan, x=2, y=2, cell_type=SeatingCell.CellType.SEAT,
            reservation_status=SeatingCell.ReservationStatus.FREE
        )
        free_cell.registration = reg_other
        with self.assertRaises(ValidationError) as ctx:
            free_cell.save()

        self.assertIn('Die Registrierung gehört zu Event', str(ctx.exception))

    def test_api_ignores_cross_event_legacy_registrations(self):
        """Negativer Test: Falls Altdaten existieren, ignoriert die API Registrierungen fremder Events."""
        # Kachel manuell über QuerySet.update() mit fremder Registrierung manipulieren (umgeht Model.save())
        event_other = Event.objects.create(
            title="Legacy Event",
            slug="legacy-event",
            is_active=False,
            start_date=timezone.now() + timedelta(days=200),
            end_date=timezone.now() + timedelta(days=202),
        )
        reg_other = EventRegistration.objects.create(
            event=event_other,
            user=self.user,
            payment_status=EventRegistration.PaymentStatus.PAID
        )
        cell_2_2 = SeatingCell.objects.create(
            plan=self.plan, x=2, y=2, cell_type=SeatingCell.CellType.SEAT,
            reservation_status=SeatingCell.ReservationStatus.FREE
        )
        SeatingCell.objects.filter(pk=cell_2_2.pk).update(registration=reg_other)

        self.client.login(username='seatuser2', password='password')
        res = self.client.get(reverse('api_event_seating', kwargs={'event_id': self.event.id}))
        self.assertEqual(res.status_code, 200)
        data = res.json()

        cell_data = next(c for c in data['cells'] if c['x'] == 2 and c['y'] == 2)
        # Muss FREE sein, weil reg_other nicht zu self.event gehört!
        self.assertEqual(cell_data['status'], 'FREE')
        self.assertIsNone(cell_data['occupied_by'])

    def test_failed_seat_change_preserves_original_seat(self):
        """Negativer Test: Schlägt ein Sitzplatzwechsel fehl, bleibt der bisherige Platz garantiert erhalten."""
        # 1. User sitzt sicher auf Platz (1,1)
        self.seat_cell.registration = self.registration
        self.seat_cell.reservation_status = SeatingCell.ReservationStatus.PRE_RESERVED
        self.seat_cell.save()

        # 2. Zweiter Platz (2,2) ist blockiert
        blocked_cell = SeatingCell.objects.create(
            plan=self.plan, x=2, y=2, cell_type=SeatingCell.CellType.SEAT,
            reservation_status=SeatingCell.ReservationStatus.BLOCKED
        )

        self.client.force_login(self.user)

        # 3. Wechselversuch auf den blockierten Platz
        response = self.client.post(
            reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
            data=json.dumps({'x': 2, 'y': 2}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

        # 4. Prüfen: Ursprünglicher Platz (1,1) darf NICHT freigegeben worden sein!
        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.registration, self.registration)
        self.assertEqual(self.seat_cell.reservation_status, SeatingCell.ReservationStatus.PRE_RESERVED)

    def test_concurrent_reservation_rejection_for_second_caller(self):
        """Regressionstest: Zwei Anmeldungen konkurrieren um denselben Platz -> Zweiter Aufrufer wird abgewiesen."""
        user_rival = User.objects.create_user(username='rival_gamer', password='password')
        reg_rival = EventRegistration.objects.create(user=user_rival, event=self.event)

        # 1. Erster Gast reserviert Platz (1,1)
        self.client.force_login(self.user)
        res1 = self.client.post(
            reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
            data=json.dumps({'x': 1, 'y': 1}),
            content_type='application/json',
        )
        self.assertEqual(res1.status_code, 200)

        # 2. Zweiter Gast versucht denselben Platz zu reservieren -> Abweisung
        self.client.force_login(user_rival)
        res2 = self.client.post(
            reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
            data=json.dumps({'x': 1, 'y': 1}),
            content_type='application/json',
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("bereits", res2.json()['message'].lower())

        # 3. Platz bleibt sicher beim ersten Gast
        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.registration, self.registration)

    def test_admin_force_assignment_displaces_previous_user_cleanly(self):
        """Regressionstest: Admin Force-Zuweisung entkoppelt verdrängten Gast sauber ohne Inkonsistenzen."""
        admin_user = User.objects.create_superuser(username='superadmin', password='password')
        user_b = User.objects.create_user(username='gamer_b', password='password')
        reg_b = EventRegistration.objects.create(
            user=user_b, event=self.event, payment_status=EventRegistration.PaymentStatus.PAID
        )

        # 1. Platz (1,1) gehört Gast A
        self.seat_cell.registration = self.registration
        self.seat_cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat_cell.save()

        # 2. Admin erzwingt Zuweisung an Gast B mit force=True
        self.client.force_login(admin_user)
        res = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': reg_b.id, 'x': 1, 'y': 1, 'force': True}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200)

        # 3. Kachel gehört jetzt Gast B
        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.registration, reg_b)

        # 4. Gast A hat keinen Platz mehr zugewiesen
        self.assertEqual(self.registration.seats.count(), 0)

    def test_api_500_error_sanitization_no_information_leak(self):
        """Sicherheitstest: Unerwartete Server-Exceptions leaken keine internen Traceback- oder Tabellendetails."""
        from unittest.mock import patch

        self.client.force_login(self.user)
        sensitive_error = "SQL syntax error in table auth_user_passwords_secret_leak"

        with patch.object(SeatingCell, 'reserve_for_user', side_effect=RuntimeError(sensitive_error)):
            res = self.client.post(
                reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
                data=json.dumps({'x': 1, 'y': 1}),
                content_type='application/json',
            )
            self.assertEqual(res.status_code, 500)
            data = res.json()
            self.assertEqual(data['status'], 'error')
            self.assertEqual(data['message'], 'Die Aktion konnte nicht ausgeführt werden. Bitte versuche es erneut.')
            # Sicherstellen, dass interne Details NICHT in der Antwort enthalten sind
            self.assertNotIn("auth_user_passwords", res.content.decode())
            self.assertNotIn("SQL", res.content.decode())


class SeatingServiceAndSignalTests(TestCase):

    def setUp(self):
        self.user1 = User.objects.create_user(username='u1', email='u1@test.com', password='pw')
        self.user2 = User.objects.create_user(username='u2', email='u2@test.com', password='pw')
        self.event = Event.objects.create(
            title='LAN 2026',
            slug='lan-2026',
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timezone.timedelta(days=2),
        )
        self.plan = SeatingPlan.objects.create(
            event=self.event, name='Main Hall', columns=10, rows=10
        )
        self.seat1 = SeatingCell.objects.create(
            plan=self.plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label='A1'
        )
        self.seat2 = SeatingCell.objects.create(
            plan=self.plan, x=1, y=2, cell_type=SeatingCell.CellType.SEAT, seat_label='A2'
        )
        self.reg1 = EventRegistration.objects.create(
            event=self.event, user=self.user1, payment_status=EventRegistration.PaymentStatus.UNPAID
        )
        self.reg2 = EventRegistration.objects.create(
            event=self.event, user=self.user2, payment_status=EventRegistration.PaymentStatus.PAID
        )

    def test_signal_releases_seats_when_registration_deleted(self):
        """Testet, dass das pre_delete Signal in seating/signals.py den Platz automatisch freigibt."""
        self.seat1.registration = self.reg1
        self.seat1.reservation_status = SeatingCell.ReservationStatus.PRE_RESERVED
        self.seat1.save()

        self.assertEqual(self.seat1.registration, self.reg1)

        # Löschung der Registrierung
        self.reg1.delete()

        # Platz muss jetzt wieder frei sein
        self.seat1.refresh_from_db()
        self.assertIsNone(self.seat1.registration)
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.FREE)

    def test_get_event_capacity_stats_service(self):
        from seating.services import get_event_capacity_stats, invalidate_event_capacity_cache

        invalidate_event_capacity_cache(self.event.id)
        stats = get_event_capacity_stats(self.event)
        self.assertEqual(stats['total_seats'], 2)
        self.assertEqual(stats['reserved_seats'], 0)

        # 1 Platz belegen
        self.seat1.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat1.save()

        stats2 = get_event_capacity_stats(self.event)
        self.assertEqual(stats2['total_seats'], 2)
        self.assertEqual(stats2['reserved_seats'], 1)
        self.assertEqual(stats2['capacity_percent'], 50)

    def test_get_user_seat_map_service(self):
        from seating.services import get_user_seat_map

        self.seat1.registration = self.reg1
        self.seat1.save()

        self.seat2.registration = self.reg2
        self.seat2.save()

        seat_map = get_user_seat_map(self.event, [self.user1.id, self.user2.id])
        self.assertEqual(seat_map.get(self.user1.id), 'A1')
        self.assertEqual(seat_map.get(self.user2.id), 'A2')

    def test_sync_seat_status_with_payment_service(self):
        from seating.services import sync_seat_status_with_payment

        self.seat1.registration = self.reg1
        self.seat1.reservation_status = SeatingCell.ReservationStatus.FREE
        self.seat1.save()

        # Unbezahlt -> PRE_RESERVED
        sync_seat_status_with_payment(self.reg1)
        self.seat1.refresh_from_db()
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.PRE_RESERVED)

        # Bezahlt -> RESERVED
        self.reg1.payment_status = EventRegistration.PaymentStatus.PAID
        self.reg1.save()
        sync_seat_status_with_payment(self.reg1)
        self.seat1.refresh_from_db()
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.RESERVED)












