from datetime import timedelta
import json
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from events.models import Event, EventRegistration
from seating.models import SeatingCell, SeatingPlan
from seating.services import SeatingPlanService, SeatingPlanValidationError

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
            status=Event.Status.REGISTRATION_OPEN,
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

    def test_seating_page_renders_modular_script_and_config(self):
        self.client.login(username='seatuser', password='password')
        response = self.client.get(reverse('seating_plan'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="seating-config"')
        self.assertContains(response, 'static/js/seating.js')
        self.assertContains(response, f'"eventId": "{self.event.id}"')
        self.assertContains(response, '"isUserLoggedIn": true')
        self.assertContains(response, '"username": "seatuser"')
        # Whitelabeling: kein hardcodiertes "Haag-networX" im Titel
        self.assertNotContains(response, 'Haag-networX')
        # Offline Fonts: Lokales fonts.css statt externer Google Fonts CDN-Links
        self.assertContains(response, 'static/css/fonts.css')
        self.assertNotContains(response, 'fonts.googleapis.com')
        self.assertNotContains(response, 'fonts.gstatic.com')

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

    def test_seating_plan_page_renders_translation_texts(self):
        """Testet, dass die Übersetzungs-Tags auf der Sitzplan-Seite ordnungsgemäß mit Text gerendert werden."""
        self.client.login(username='seatuser', password='password')
        response = self.client.get(reverse('seating_plan'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Prüfe, dass Titel und Legende gerendert werden
        self.assertIn('Sitzplan', content)
        self.assertIn('Frei', content)
        self.assertIn('Vorgemerkt', content)
        self.assertIn('Reserviert (Bezahlt)', content)
        self.assertIn('Dein Platz', content)

        # Prüfe Modal-Texte
        self.assertIn('SITZPLATZ RESERVIEREN', content)
        self.assertIn('Abbrechen', content)
        self.assertIn('Ja, reservieren', content)
        self.assertIn('verbindlich reservieren', content)



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
        admin_user = User.objects.create_superuser(
            username='seating_admin', email='admin@example.com', password='password'
        )
        self.client.login(username='seating_admin', password='password')

        cells_payload = [
            {'x': 1, 'y': 1, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': 'B1-Updated', 'text_label': ''},
            {'x': 1, 'y': 2, 'cell_type': SeatingCell.CellType.WALL, 'seat_label': '', 'text_label': 'Wand'},
            {'x': 2, 'y': 1, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': 'B2', 'text_label': ''},
        ]
        response = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': cells_payload, 'version': self.plan.version}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.plan.cells.count(), 3)
        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.seat_label, 'B1-Updated')

    def test_save_seating_plan_blocked_cells(self):
        admin_user = User.objects.create_superuser(
            username='seating_admin_block', email='sablock@example.com', password='password'
        )
        self.client.login(username='seating_admin_block', password='password')

        cells_payload = [
            {'x': 1, 'y': 1, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': 'A1', 'text_label': ''},
            {'x': 2, 'y': 2, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': 'X1', 'text_label': '', 'reservation_status': 'BLOCKED'},
        ]
        response = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': cells_payload, 'version': self.plan.version}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        blocked_cell = self.plan.cells.get(x=2, y=2)
        self.assertEqual(blocked_cell.reservation_status, SeatingCell.ReservationStatus.BLOCKED)

    def test_save_seating_plan_editor_validations(self):
        admin_user = User.objects.create_superuser(
            username='seating_validator', email='val@example.com', password='password'
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
        admin_user = User.objects.create_superuser(
            username='staff_seating', email='staff@example.com', password='password'
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
            self.plan.clean()

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
            free_cell.clean()

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

    def test_failed_seat_change_on_exception_preserves_original_seat(self):
        """
        Kritischer Bugfix: Tritt beim Sitzplatzwechsel eine Exception während cell.reserve_for_user
        oder beim Commit auf, MUSS die Freigabe des bisherigen Platzes per Rollback rückgängig gemacht werden.
        """
        from unittest.mock import patch

        # 1. User sitzt sicher auf Platz (1,1)
        self.seat_cell.registration = self.registration
        self.seat_cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat_cell.save()

        # 2. Zweiter Platz (2,2) ist frei
        target_cell = SeatingCell.objects.create(
            plan=self.plan, x=2, y=2, cell_type=SeatingCell.CellType.SEAT,
            reservation_status=SeatingCell.ReservationStatus.FREE
        )

        self.client.force_login(self.user)

        # 3. Wechselversuch auf Platz (2,2) mit simulierter Exception in reserve_for_user
        with patch.object(SeatingCell, 'reserve_for_user', side_effect=RuntimeError("Simulierte DB-Exception")):
            response = self.client.post(
                reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
                data=json.dumps({'x': 2, 'y': 2}),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 500)

        # 4. Prüfen: Ursprünglicher Platz (1,1) MUSS per Rollback erhalten geblieben sein!
        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.registration, self.registration)
        self.assertEqual(self.seat_cell.reservation_status, SeatingCell.ReservationStatus.RESERVED)

        # Zielplatz bleibt frei
        target_cell.refresh_from_db()
        self.assertIsNone(target_cell.registration)
        self.assertEqual(target_cell.reservation_status, SeatingCell.ReservationStatus.FREE)

    def test_admin_assign_seat_exception_preserves_original_seat(self):
        """
        Admin-Zuweisung: Tritt beim Speichern des neuen Platzes eine Exception auf,
        wird der bisherige Platz des Benutzers per Rollback nicht gelöscht.
        """
        from unittest.mock import patch

        admin_user = User.objects.create_superuser(username='admin_rb_test', password='password')

        # 1. User sitzt auf Platz (1,1)
        self.seat_cell.registration = self.registration
        self.seat_cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat_cell.save()

        # 2. Zielplatz (2,2) ist frei
        target_cell = SeatingCell.objects.create(
            plan=self.plan, x=2, y=2, cell_type=SeatingCell.CellType.SEAT,
            reservation_status=SeatingCell.ReservationStatus.FREE
        )

        self.client.force_login(admin_user)

        # 3. Zuweisung mit simulierter Exception beim Speichern des Zielplatzes
        with patch.object(SeatingCell, 'save', side_effect=RuntimeError("Simulierter Speicherfehler")):
            response = self.client.post(
                reverse('admin_assign_seat'),
                data=json.dumps({'registration_id': self.registration.id, 'x': 2, 'y': 2}),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 500)

        # 4. Prüfen: Bisheriger Platz (1,1) ist erhalten
        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.registration, self.registration)
        self.assertEqual(self.seat_cell.reservation_status, SeatingCell.ReservationStatus.RESERVED)

    def test_release_seat_api_exception_rolls_back(self):
        """
        Freigabe-API: Tritt bei der Freigabe eine Exception auf,
        bleibt der Sitzplatz per Rollback erhalten.
        """
        from unittest.mock import patch

        self.seat_cell.registration = self.registration
        self.seat_cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat_cell.save()

        self.client.force_login(self.user)

        with patch.object(SeatingCell, 'release_seat', side_effect=RuntimeError("Fehler bei Freigabe")):
            response = self.client.post(
                reverse('api_release_seat', kwargs={'event_id': self.event.id}),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 500)

        self.seat_cell.refresh_from_db()
        self.assertEqual(self.seat_cell.registration, self.registration)
        self.assertEqual(self.seat_cell.reservation_status, SeatingCell.ReservationStatus.RESERVED)


class SeatingServiceAndSignalTests(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

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

        with self.captureOnCommitCallbacks(execute=True):
            invalidate_event_capacity_cache(self.event.id)

        stats = get_event_capacity_stats(self.event)
        self.assertEqual(stats['total_seats'], 2)
        self.assertEqual(stats['reserved_seats'], 0)

        # 1 Platz belegen
        with self.captureOnCommitCallbacks(execute=True):
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

    def test_seating_cell_rejects_cancelled_registration(self):
        """Sicherheitstest: Stornierte Anmeldungen können keine Sitzplätze reservieren."""
        self.reg1.payment_status = EventRegistration.PaymentStatus.CANCELLED
        self.reg1.save()

        can_res, msg = self.seat1.can_reserve_for_user(self.reg1)
        self.assertFalse(can_res)
        self.assertIn("storniert", msg)

        res, msg2 = self.seat1.reserve_for_user(self.reg1)
        self.assertFalse(res)

    def test_seating_cell_rejects_reservation_for_finished_event(self):
        """Sicherheitstest: Für beendete Events können keine Plätze mehr gewählt werden."""
        past_event = Event.objects.create(
            title="Past Event",
            slug="past-event",
            is_active=False,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() - timedelta(days=10),
            end_date=timezone.now() - timedelta(days=5),
        )
        past_reg = EventRegistration.objects.create(user=self.user1, event=past_event)
        can_res, msg = self.seat1.can_reserve_for_user(past_reg)
        self.assertFalse(can_res)
        self.assertIn("keine Plätze mehr", msg)

    def test_seating_plan_is_template_flag(self):
        """Testet die automatische Erkennung von Vorlagen-Plänen vs Live-Event-Plänen."""
        template_plan = SeatingPlan.objects.create(name="Default 100 Template", columns=10, rows=10)
        self.assertTrue(template_plan.is_template)

        other_event = Event.objects.create(
            title="Other Event",
            slug="other-event",
            is_active=False,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=12),
        )
        event_plan = SeatingPlan.objects.create(event=other_event, name="Event Live Plan", columns=10, rows=10)
        self.assertFalse(event_plan.is_template)

    def test_save_seating_plan_rejects_deleting_occupied_cell(self):
        """Sicherheitstest: Editor-API verhindert das Löschen belegter Kacheln."""
        admin_user = User.objects.create_superuser(username='staff_editor', email='staff@example.com', password='password')
        self.client.login(username='staff_editor', password='password')
        # seat1 (1,1) ist belegt durch reg1
        self.seat1.registration = self.reg1
        self.seat1.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat1.save()

        # Versuch, nur Kachel (1,2) zu senden -> Kachel (1,1) würde gelöscht werden
        payload = {
            'cells': [
                {'x': 1, 'y': 2, 'cell_type': 'SEAT', 'seat_label': 'A2', 'text_label': ''}
            ]
        }
        response = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("nicht gelöscht werden", response.json()['message'])

    def test_cache_invalidation_executes_on_commit_and_ignores_rollback(self):
        """Testet, dass Cache-Invalidierung über transaction.on_commit erst nach Commit feuert und bei Rollback nicht."""
        from django.core.cache import cache
        from django.db import transaction

        cache_key = f'event_capacity_stats_{self.event.id}'
        cache.set(cache_key, {'total_seats': 100, 'reserved_seats': 50, 'capacity_percent': 50})

        # 1. Rollback Fall
        try:
            with transaction.atomic():
                self.seat1.reservation_status = SeatingCell.ReservationStatus.RESERVED
                self.seat1.save()
                # Während der Transaktion sollte der Cache noch vorhanden sein (wird erst on_commit gelöscht)
                self.assertIsNotNone(cache.get(cache_key))
                raise ValueError("Simulierter Rollback")
        except ValueError:
            pass

        # Nach Rollback darf der Cache NICHT gelöscht worden sein (auch wenn on_commit callbacks abgefragt werden)
        self.captureOnCommitCallbacks(execute=True)
        self.assertIsNotNone(cache.get(cache_key))

        # 2. Commit Fall
        with self.captureOnCommitCallbacks(execute=True):
            self.seat1.reservation_status = SeatingCell.ReservationStatus.RESERVED
            self.seat1.save()

        # Nach erfolgreichem Commit muss der Cache invalidiert sein
        self.assertIsNone(cache.get(cache_key))

    def test_seating_plan_service_save_grid_direct(self):
        """Testet den SeatingPlanService direkt."""
        from seating.services import SeatingPlanService, SeatingPlanValidationError

        # 1. Ungültiges Datenformat
        with self.assertRaises(SeatingPlanValidationError):
            SeatingPlanService.save_grid(self.plan, "nicht_eine_liste")

        # 2. Ungültige Koordinaten
        with self.assertRaises(SeatingPlanValidationError):
            SeatingPlanService.save_grid(self.plan, [{'x': 'ungültig', 'y': 1}])

        # 3. Außerhalb des Rasters
        with self.assertRaises(SeatingPlanValidationError):
            SeatingPlanService.save_grid(self.plan, [{'x': 999, 'y': 999, 'cell_type': 'SEAT'}])

        # 4. Ungültiger Zelltyp
        with self.assertRaises(SeatingPlanValidationError):
            SeatingPlanService.save_grid(self.plan, [{'x': 1, 'y': 1, 'cell_type': 'INVALID_TYPE'}])

        # 5. Erfolgreiches Speichern
        success, msg = SeatingPlanService.save_grid(self.plan, [
            {'x': 1, 'y': 1, 'cell_type': 'SEAT', 'seat_label': 'A1', 'text_label': ''},
            {'x': 1, 'y': 2, 'cell_type': 'SEAT', 'seat_label': 'A2', 'text_label': ''},
        ])
        self.assertTrue(success)

    def test_reserve_seat_api_bad_request_status_code(self):
        """Testet, dass fehlerhafte Client-Eingaben in reserve_seat_api als 400 (nicht 500) zurückgegeben werden."""
        self.client.login(username='u1', password='pw')

        # Ungültiges JSON
        response = self.client.post(
            reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
            data='ungültiges json',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'error')

        # Nicht-numerische Koordinaten
        response = self.client.post(
            reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
            data=json.dumps({'x': 'abc', 'y': None}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'error')

    def test_seating_plan_template_with_event_validation_in_clean(self):
        """Testet, dass ein Plan nicht gleichzeitig ein Event haben und als Vorlage markiert sein darf."""
        from django.core.exceptions import ValidationError
        plan = SeatingPlan(event=self.event, name="Ungültig", columns=5, rows=5, is_template=True)
        with self.assertRaises(ValidationError):
            plan.clean()

    def test_seating_plan_admin_changelist_without_events(self):
        """Testet, dass die Sitzplan-Adminliste fehlerfrei rendert, wenn keine Events existieren oder Vorlagen angezeigt werden."""
        admin_user = User.objects.create_superuser(username='seating_admin', email='sadmin@example.com', password='password')
        self.client.force_login(admin_user)
        template_plan = SeatingPlan.objects.create(name='Vorlage 1', columns=10, rows=10, is_template=True, event=None)
        response = self.client.get('/admin/seating/seatingplan/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Master-Vorlage')

    def test_unpaid_seat_overwrite_disabled(self):
        """Wenn allow_unpaid_seat_overwrite=False, kann ein zahlender Gast den vorgemerkten Platz nicht überschreiben."""
        self.event.status = Event.Status.REGISTRATION_OPEN
        self.event.allow_unpaid_seat_overwrite = False
        self.event.save()

        user_unpaid = User.objects.create_user(username='unpaid_guest', password='password')
        reg_unpaid = EventRegistration.objects.create(
            user=user_unpaid, event=self.event, payment_status=EventRegistration.PaymentStatus.UNPAID
        )
        success, msg = self.seat1.reserve_for_user(reg_unpaid)
        self.assertTrue(success)
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.PRE_RESERVED)

        # Zahlender Gast versucht zu reservieren
        user_paid = User.objects.create_user(username='paid_guest', password='password')
        reg_paid = EventRegistration.objects.create(
            user=user_paid, event=self.event, payment_status=EventRegistration.PaymentStatus.PAID
        )
        can_res, msg = self.seat1.can_reserve_for_user(reg_paid)
        self.assertFalse(can_res)
        self.assertIn("nicht gestattet", msg)

    def test_unpaid_seat_overwrite_enabled_sends_email(self):
        """Wenn allow_unpaid_seat_overwrite=True, überschreibt der zahlende Gast und der unbezahlte Gast erhält eine E-Mail."""
        from django.core import mail
        from django.core.management import call_command
        from emails.models import GeneralEmailSettings

        call_command('seed_email_templates')
        email_settings = GeneralEmailSettings.load()
        email_settings.is_enabled = True
        email_settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        email_settings.sender_email = 'noreply@example.com'
        email_settings.save()

        self.event.status = Event.Status.REGISTRATION_OPEN
        self.event.allow_unpaid_seat_overwrite = True
        self.event.save()

        user_unpaid = User.objects.create_user(username='unpaid_guest2', email='unpaid2@example.com', password='password')
        reg_unpaid = EventRegistration.objects.create(
            user=user_unpaid, event=self.event, payment_status=EventRegistration.PaymentStatus.UNPAID
        )
        success, msg = self.seat1.reserve_for_user(reg_unpaid)
        self.assertTrue(success)
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.PRE_RESERVED)

        # Zahlender Gast überschreibt
        user_paid = User.objects.create_user(username='paid_guest2', email='paid2@example.com', password='password')
        reg_paid = EventRegistration.objects.create(
            user=user_paid, event=self.event, payment_status=EventRegistration.PaymentStatus.PAID
        )

        with self.captureOnCommitCallbacks(execute=True):
            success, msg = self.seat1.reserve_for_user(reg_paid)

        self.assertTrue(success)
        self.seat1.refresh_from_db()
        self.assertEqual(self.seat1.registration, reg_paid)
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.RESERVED)

        # E-Mail an unpaid2@example.com prüfen
        self.assertTrue(any('unpaid2@example.com' in m.to for m in mail.outbox))
        email = [m for m in mail.outbox if 'unpaid2@example.com' in m.to][0]
        self.assertIn(self.seat1.seat_label, email.subject)


class SeatingConcurrencyAndConstraintTests(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

        self.user = User.objects.create_user(
            username='constraint_user', email='constraint@example.com', password='password123'
        )
        self.event = Event.objects.create(
            title='Constraint LAN',
            slug='constraint-lan',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=3),
        )
        self.plan = SeatingPlan.objects.create(
            event=self.event, name='Hall 1', columns=10, rows=10
        )
        self.seat1 = SeatingCell.objects.create(
            plan=self.plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label='A1'
        )
        self.seat2 = SeatingCell.objects.create(
            plan=self.plan, x=2, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label='A2'
        )
        self.registration = EventRegistration.objects.create(
            user=self.user, event=self.event, payment_status=EventRegistration.PaymentStatus.PAID
        )

    def test_unique_constraint_prevents_multiple_seats_per_registration(self):
        """Prüft, dass die Datenbank strikt verhindert, dass eine Registrierung zwei Plätze belegt."""
        from django.db import IntegrityError, transaction

        self.seat1.registration = self.registration
        self.seat1.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat1.save()

        self.seat2.registration = self.registration
        self.seat2.reservation_status = SeatingCell.ReservationStatus.RESERVED
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.seat2.save()

    def test_unique_constraint_allows_multiple_unoccupied_seats(self):
        """Prüft, dass beliebig viele Plätze registration=None haben dürfen."""
        self.seat1.registration = None
        self.seat1.reservation_status = SeatingCell.ReservationStatus.FREE
        self.seat1.save()

        self.seat2.registration = None
        self.seat2.reservation_status = SeatingCell.ReservationStatus.FREE
        self.seat2.save()

        self.assertIsNone(self.seat1.registration)
        self.assertIsNone(self.seat2.registration)

    def test_seat_change_preserves_unique_constraint_and_updates_cleanly(self):
        """Prüft, dass der reguläre Platzwechsel über die API die UniqueConstraint nicht verletzt."""
        self.client.login(username='constraint_user', password='password123')

        # 1. Platz A1 reservieren
        resp1 = self.client.post(
            reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
            data=json.dumps({'x': 1, 'y': 1}),
            content_type='application/json',
        )
        self.assertEqual(resp1.status_code, 200)
        self.seat1.refresh_from_db()
        self.assertEqual(self.seat1.registration, self.registration)
        self.assertEqual(self.registration.seats.count(), 1)

        # 2. Platzwechsel auf A2
        resp2 = self.client.post(
            reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
            data=json.dumps({'x': 2, 'y': 1}),
            content_type='application/json',
        )
        self.assertEqual(resp2.status_code, 200)

        self.seat1.refresh_from_db()
        self.seat2.refresh_from_db()

        self.assertIsNone(self.seat1.registration)
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.FREE)
        self.assertEqual(self.seat2.registration, self.registration)
        self.assertEqual(self.seat2.reservation_status, SeatingCell.ReservationStatus.RESERVED)
        self.assertEqual(self.registration.seats.count(), 1)

    def test_reserve_seat_api_handles_integrity_error_with_clean_response(self):
        """Prüft, dass ein IntegrityError mit HTTP 400 und Rollback behandelt wird."""
        from unittest.mock import patch
        from django.db import IntegrityError

        self.client.login(username='constraint_user', password='password123')

        with patch.object(SeatingCell, 'reserve_for_user', side_effect=IntegrityError("Duplicate registration")):
            resp = self.client.post(
                reverse('api_reserve_seat', kwargs={'event_id': self.event.id}),
                data=json.dumps({'x': 1, 'y': 1}),
                content_type='application/json',
            )
            self.assertEqual(resp.status_code, 400)
            data = resp.json()
            self.assertEqual(data['status'], 'error')
            self.assertIn('nur einen Sitzplatz', data['message'])

        # Platz bleibt unberührt
        self.seat1.refresh_from_db()
        self.assertIsNone(self.seat1.registration)

    def test_payment_service_mark_paid_and_cancelled_with_seating(self):
        """Prüft die abgestimmte Sperrhierarchie und Konsistenz bei Zahlung und Stornierung."""
        from events.services import PaymentService

        self.registration.payment_status = EventRegistration.PaymentStatus.UNPAID
        self.registration.save()

        # Platz vorreservieren
        self.seat1.registration = self.registration
        self.seat1.reservation_status = SeatingCell.ReservationStatus.PRE_RESERVED
        self.seat1.save()

        # Zahlung markieren
        PaymentService.mark_paid(self.registration, send_email=False)
        self.registration.refresh_from_db()
        self.seat1.refresh_from_db()
        self.assertEqual(self.registration.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.RESERVED)

        # Stornierung markieren
        PaymentService.mark_cancelled(self.registration)
        self.registration.refresh_from_db()
        self.seat1.refresh_from_db()
        self.assertEqual(self.registration.payment_status, EventRegistration.PaymentStatus.CANCELLED)
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.FREE)
        self.assertIsNone(self.seat1.registration)

    def test_admin_assign_seat_reassigns_cleanly_with_unique_constraint(self):
        """Prüft, dass der Admin-Platzwechsel sauber funktioniert und die Ein-Platz-Regel gewahrt bleibt."""
        admin_user = User.objects.create_superuser(
            username='adminuser', email='admin@example.com', password='adminpassword'
        )
        self.client.login(username='adminuser', password='adminpassword')

        # Erste Zuweisung auf A1
        resp1 = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': self.registration.id, 'x': 1, 'y': 1}),
            content_type='application/json',
        )
        self.assertEqual(resp1.status_code, 200)
        self.seat1.refresh_from_db()
        self.assertEqual(self.seat1.registration, self.registration)
        self.assertEqual(self.registration.seats.count(), 1)

        # Zweite Zuweisung auf A2
        resp2 = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': self.registration.id, 'x': 2, 'y': 1}),
            content_type='application/json',
        )
        self.assertEqual(resp2.status_code, 200)
        self.seat1.refresh_from_db()
        self.seat2.refresh_from_db()
        self.assertIsNone(self.seat1.registration)
        self.assertEqual(self.seat2.registration, self.registration)
        self.assertEqual(self.registration.seats.count(), 1)


class SeatingEditorConcurrencyAndLockingTests(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

        self.staff_user = User.objects.create_superuser(
            username='staff_editor', email='staff@example.com', password='adminpassword'
        )
        self.guest_user = User.objects.create_user(
            username='guest_booker', email='guest@example.com', password='password123'
        )
        self.event = Event.objects.create(
            title='Editor Test LAN',
            slug='editor-test-lan',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=2),
            end_date=timezone.now() + timedelta(days=4),
        )
        self.plan = SeatingPlan.objects.create(
            event=self.event, name='Main Hall', columns=10, rows=10, version=1
        )
        self.seat1 = SeatingCell.objects.create(
            plan=self.plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label='A1'
        )
        self.seat2 = SeatingCell.objects.create(
            plan=self.plan, x=2, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label='A2'
        )
        self.registration = EventRegistration.objects.create(
            user=self.guest_user, event=self.event, payment_status=EventRegistration.PaymentStatus.PAID
        )

    def test_save_grid_increments_version(self):
        """Prüft, dass jede erfolgreiche Ausführung von save_grid die Planversion inkrementiert."""
        self.assertEqual(self.plan.version, 1)

        cells_data = [
            {'x': 1, 'y': 1, 'cell_type': 'SEAT', 'seat_label': 'A1'},
            {'x': 2, 'y': 1, 'cell_type': 'SEAT', 'seat_label': 'A2'},
        ]
        success, msg = SeatingPlanService.save_grid(self.plan, cells_data)
        self.assertTrue(success)
        self.assertEqual(self.plan.version, 2)

        self.plan.refresh_from_db()
        self.assertEqual(self.plan.version, 2)

    def test_save_grid_optimistic_locking_rejects_stale_version(self):
        """Prüft, dass ein veralteter Versionsstand im Editor (konkurrierende Bearbeitung) abgewiesen wird."""
        cells_data = [
            {'x': 1, 'y': 1, 'cell_type': 'SEAT', 'seat_label': 'A1'},
            {'x': 2, 'y': 1, 'cell_type': 'SEAT', 'seat_label': 'A2'},
        ]

        # Admin 1 speichert erfolgreich mit Version 1 -> Version wird 2
        success, msg = SeatingPlanService.save_grid(self.plan, cells_data, expected_version=1)
        self.assertTrue(success)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.version, 2)

        # Admin 2 versucht zeitgleich mit alter Version 1 zu speichern -> Konflikt
        with self.assertRaises(SeatingPlanValidationError) as cm:
            SeatingPlanService.save_grid(self.plan, cells_data, expected_version=1)

        self.assertIn("zwischenzeitlich von einem anderen Administrator geändert", str(cm.exception))
        self.assertIn("aktuelle Version 2 vs. gesendete Version 1", str(cm.exception))

        # Admin 2 aktualisiert auf Version 2 und speichert erneut -> Erfolg
        success, msg = SeatingPlanService.save_grid(self.plan, cells_data, expected_version=2)
        self.assertTrue(success)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.version, 3)

    def test_save_seating_plan_api_version_conflict_and_recovery(self):
        """Testet die HTTP-API save_seating_plan auf Versionsüberprüfung und Rückgabe der neuen Version."""
        self.client.login(username='staff_editor', password='adminpassword')

        payload = {
            'cells': [
                {'x': 1, 'y': 1, 'cell_type': 'SEAT', 'seat_label': 'A1'},
            ],
            'version': 1,
        }

        # 1. Erfolgreicher Save mit Version 1
        resp = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['version'], 2)

        # 2. Zweiter Aufruf mit veralteter Version 1 -> HTTP 400
        resp_conflict = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(resp_conflict.status_code, 400)
        conflict_data = resp_conflict.json()
        self.assertEqual(conflict_data['status'], 'error')
        self.assertIn("zwischenzeitlich", conflict_data['message'])

        # 3. Aufruf mit aktueller Version 2 -> HTTP 200 mit Version 3
        payload['version'] = 2
        resp_recovered = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(resp_recovered.status_code, 200)
        self.assertEqual(resp_recovered.json()['version'], 3)

    def test_save_grid_protects_concurrently_occupied_cell_from_deletion(self):
        """Prüft, dass eine Kachel, die während des Editor-Vorgangs belegt wird, nicht gelöscht werden kann."""
        # Gast bucht Sitzplatz A1
        self.seat1.registration = self.registration
        self.seat1.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat1.save()

        # Editor sendet Layout ohne Kachel A1 (Löschung beabsichtigt)
        cells_data = [
            {'x': 2, 'y': 1, 'cell_type': 'SEAT', 'seat_label': 'A2'},
        ]

        with self.assertRaises(SeatingPlanValidationError) as cm:
            SeatingPlanService.save_grid(self.plan, cells_data)

        self.assertIn("kann nicht gelöscht werden", str(cm.exception))
        self.assertIn(self.guest_user.username, str(cm.exception))

        # Sitzplatz A1 in DB muss unversehrt bleiben
        self.seat1.refresh_from_db()
        self.assertEqual(self.seat1.registration, self.registration)
        self.assertEqual(self.seat1.reservation_status, SeatingCell.ReservationStatus.RESERVED)

    def test_clone_for_event_sets_version_one(self):
        """Prüft, dass ein geklonter Sitzplan initial mit Version 1 startet."""
        self.plan.version = 5
        self.plan.save()

        cloned_plan = self.plan.clone_for_event(new_name="Cloned Plan")
        self.assertEqual(cloned_plan.version, 1)


class SeatingViewerFrontendTests(TestCase):
    """
    Tests für die Frontend-Logik des Sitzplan-Viewers (static/js/seating.js).
    Stellt sicher, dass Listener nicht bei wiederholtem Laden multipliziert werden.
    """

    def test_seating_js_has_initialization_guard_and_abort_controller(self):
        import os
        from django.conf import settings

        js_path = os.path.join(settings.BASE_DIR, 'static', 'js', 'seating.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Guard gegen mehrfaches Initialisieren
        self.assertIn('let isPanZoomInitialized = false;', content)
        self.assertIn('if (!isPanZoomInitialized)', content)
        # AbortController für Teardown
        self.assertIn('AbortController', content)
        self.assertIn('panZoomAbortController', content)
        self.assertIn('viewerAbortController', content)

    def test_seating_js_listeners_not_duplicated_on_multiple_reloads(self):
        """Führt einen Node.js-Test durch, um zu prüfen, dass nach 3 Reloads genau 1 Wheel-Listener registriert ist."""
        import subprocess
        import shutil

        node_bin = shutil.which('node')
        if not node_bin:
            self.skipTest("Node.js ist nicht installiert.")

        script = """
        const fs = require('fs');
        const content = fs.readFileSync('static/js/seating.js', 'utf8');
        const listeners = { window: {}, document: {}, viewport: {} };

        function makeEmitter(name) {
          return {
            addEventListener: (type, fn, opts) => {
              listeners[name][type] = (listeners[name][type] || 0) + 1;
              if (opts && opts.signal) {
                opts.signal.addEventListener('abort', () => {
                  listeners[name][type]--;
                });
              }
            },
            removeEventListener: (type, fn) => {
              listeners[name][type] = (listeners[name][type] || 1) - 1;
            },
            clientWidth: 1000,
            clientHeight: 800,
            style: {}
          };
        }

        const windowMock = makeEmitter('window');
        windowMock.innerWidth = 1200;
        windowMock.innerHeight = 800;

        const documentMock = makeEmitter('document');
        const elements = {
          'viewport': makeEmitter('viewport'),
          'pan-canvas': { style: {} },
          'zoom-level-badge': { textContent: '' },
          'seating-grid': { style: {}, appendChild: () => {}, innerHTML: '' },
          'seating-status': { style: {} },
          'btn-confirm-reserve': {},
          'btn-zoom-in': {},
          'btn-zoom-out': {},
          'btn-zoom-reset': {}
        };

        documentMock.getElementById = (id) => elements[id] || null;
        documentMock.createDocumentFragment = () => ({ appendChild: () => {} });
        documentMock.createElement = () => ({ style: {} });

        const mockFetch = () => Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ columns: 20, rows: 15, cells: [] })
        });

        const fn = new Function('window', 'document', 'fetch', 'AbortController', content);
        fn(windowMock, documentMock, mockFetch, global.AbortController);

        windowMock.initSeatingViewer({ eventId: '1', csrfToken: 'abc' });

        setTimeout(() => {
          Promise.all([
            windowMock.loadSeatingData(),
            windowMock.loadSeatingData(),
            windowMock.loadSeatingData()
          ]).then(() => {
            setTimeout(() => {
              const wheelCount = listeners.viewport['wheel'] || 0;
              const resizeCount = listeners.window['resize'] || 0;
              if (wheelCount === 1 && resizeCount === 1) {
                process.exit(0);
              } else {
                console.error(`Fehler: wheelCount=${wheelCount}, resizeCount=${resizeCount}`);
                process.exit(1);
              }
            }, 50);
          });
        }, 50);
        """

        result = subprocess.run([node_bin, '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"Node test fehlgeschlagen: {result.stderr or result.stdout}")


class SeatingFeedbackRegressionTests(TestCase):
    """
    Regressionstests für das Feedback zu Sitzplan-Sicherheit, Vorlagen,
    Berechtigungen, Validierung und Statussynchronisation.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user(
            username='xss_tester<script>alert(1)</script>',
            email='xss@test.com',
            password='password',
            first_name='Malicious',
            last_name='User<script>'
        )
        self.superuser = User.objects.create_superuser(
            username='super_admin', email='sa@test.com', password='password'
        )
        self.plain_staff = User.objects.create_user(
            username='plain_staff', email='staff@test.com', password='password', is_staff=True
        )
        self.event = Event.objects.create(
            title='Seating Test Event',
            slug='seating-test-event',
            is_active=True,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.plan = SeatingPlan.objects.create(
            event=self.event, name='Test Plan', columns=10, rows=10
        )
        self.seat_cell = SeatingCell.objects.create(
            plan=self.plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label='R1-P1'
        )
        self.registration = EventRegistration.objects.create(
            user=self.user, event=self.event, payment_status=EventRegistration.PaymentStatus.PAID
        )

    def test_p1_editor_json_script_escaping(self):
        """P1: Editor überträgt Zellen via json_script und bricht Scriptblöcke nicht mit </script> auf."""
        SeatingCell.objects.create(
            plan=self.plan, x=2, y=2, cell_type=SeatingCell.CellType.LABEL,
            text_label='</script><script>alert("XSS")</script>'
        )
        self.client.login(username='super_admin', password='password')
        response = self.client.get(reverse('seating_editor', kwargs={'plan_id': self.plan.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="cells-data"')
        self.assertNotContains(response, '{{ cells_json|safe }}')
        content = response.content.decode('utf-8')
        self.assertNotIn('</script><script>alert("XSS")', content)

    def test_p1_admin_preview_html_escaping_and_data_attributes(self):
        """P1: Admin-Vorschau escaped Usernames/Namen und nutzt data-Attribute statt inline onclick."""
        self.seat_cell.registration = self.registration
        self.seat_cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat_cell.save()

        from seating.admin import SeatingPlanAdmin
        from django.contrib.admin.sites import AdminSite
        admin_instance = SeatingPlanAdmin(SeatingPlan, AdminSite())
        rendered_html = admin_instance.live_occupancy_preview(self.plan)

        self.assertIn('data-action="release"', rendered_html)
        self.assertNotIn('onclick="releaseOccupiedSeat', rendered_html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', rendered_html)
        self.assertNotIn('<script>alert(1)</script>', rendered_html)

    def test_p4_template_assigned_event_in_admin_form(self):
        """P4: Admin-Formular hebt is_template auf, wenn einem Vorlagenplan ein Event zugewiesen wird."""
        from seating.admin import SeatingPlanAdminForm
        event_for_template = Event.objects.create(
            title='Template Event', slug='template-event',
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=12)
        )
        template = SeatingPlan.objects.create(name='Saal-Vorlage', columns=8, rows=8, is_template=True, event=None)
        form = SeatingPlanAdminForm(
            instance=template,
            data={'name': 'Saal-Vorlage', 'columns': 8, 'rows': 8, 'event': event_for_template.id}
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved_plan = form.save()
        self.assertFalse(saved_plan.is_template)
        self.assertEqual(saved_plan.event, event_for_template)

    def test_p5_save_seating_plan_incomplete_payload(self):
        """P5: Speichern mit unvollständigem JSON-Payload ({}) wirft HTTP 400 und löscht keine Zellen."""
        self.client.login(username='super_admin', password='password')
        initial_cell_count = self.plan.cells.count()

        # Leerer Payload ohne 'cells'
        response = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('"cells" fehlt', response.json()['message'])
        self.assertEqual(self.plan.cells.count(), initial_cell_count)

    def test_p6_shrinking_grid_with_occupied_seats_rejected(self):
        """P6: Verkleinern des Rasters lehnt ab, wenn belegte Plätze außerhalb des neuen Rasters liegen."""
        far_seat = SeatingCell.objects.create(
            plan=self.plan, x=9, y=9, cell_type=SeatingCell.CellType.SEAT,
            seat_label='Far-Seat', registration=self.registration
        )
        self.plan.columns = 5
        self.plan.rows = 5
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as ctx:
            self.plan.clean()
        self.assertIn('Far-Seat', str(ctx.exception))

    def test_p7_admin_assign_seat_rejects_cancelled_registration(self):
        """P7: admin_assign_seat lehnt stornierte Registrierungen mit HTTP 400 ab."""
        self.registration.payment_status = EventRegistration.PaymentStatus.CANCELLED
        self.registration.save()

        self.client.login(username='super_admin', password='password')
        response = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': self.registration.id, 'x': 1, 'y': 1}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('storniert', response.json()['message'])

    def test_p7_sync_seat_status_with_payment_releases_cancelled_seats(self):
        """P7: sync_seat_status_with_payment gibt Sitze bei Status CANCELLED frei."""
        from seating.services import sync_seat_status_with_payment
        self.seat_cell.registration = self.registration
        self.seat_cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
        self.seat_cell.save()

        self.registration.payment_status = EventRegistration.PaymentStatus.CANCELLED
        self.registration.save()

        sync_seat_status_with_payment(self.registration)
        self.seat_cell.refresh_from_db()
        self.assertIsNone(self.seat_cell.registration)
        self.assertEqual(self.seat_cell.reservation_status, SeatingCell.ReservationStatus.FREE)

    def test_p9_save_grid_rejects_duplicate_seat_labels(self):
        """P9: save_grid verweigert das Speichern doppelter Sitzplatzbezeichnungen."""
        cells_data = [
            {'x': 1, 'y': 1, 'cell_type': 'SEAT', 'seat_label': 'VIP-1'},
            {'x': 1, 'y': 2, 'cell_type': 'SEAT', 'seat_label': 'VIP-1'},
        ]
        with self.assertRaises(SeatingPlanValidationError) as ctx:
            SeatingPlanService.save_grid(self.plan, cells_data)
        self.assertIn("Doppelte Sitzplatzbezeichnung 'VIP-1'", str(ctx.exception))

    def test_p11_staff_without_permissions_denied(self):
        """P11: Mitarbeiter ohne spezifische Modellberechtigungen erhalten HTTP 403."""
        self.client.login(username='plain_staff', password='password')

        # save_seating_plan erfordert change_seatingplan
        res1 = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': []}),
            content_type='application/json'
        )
        self.assertEqual(res1.status_code, 403)

        # admin_assign_seat erfordert change_seatingcell
        res2 = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({'registration_id': self.registration.id, 'x': 1, 'y': 1}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 403)

    def test_p11_force_boolean_safe_parsing(self):
        """P11: force='false' wird als False interpretiert und überschreibt keine Sperre."""
        self.seat_cell.reservation_status = SeatingCell.ReservationStatus.BLOCKED
        self.seat_cell.registration = None
        self.seat_cell.save()

        other_user = User.objects.create_user(username='other_g', email='og@test.com', password='pw')
        other_reg = EventRegistration.objects.create(
            user=other_user, event=self.event, payment_status=EventRegistration.PaymentStatus.PAID
        )

        self.client.login(username='super_admin', password='password')
        response = self.client.post(
            reverse('admin_assign_seat'),
            data=json.dumps({
                'registration_id': other_reg.id,
                'x': 1,
                'y': 1,
                'force': 'false'  # String 'false' darf nicht zu True gecastet werden!
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('gesperrt', response.json()['message'])

    def test_initial_data_fixture_seating_cells_unique_labels(self):
        """Stellt sicher, dass die Demodaten-Fixture (initial_data.json) keine doppelten Sitzplatzbezeichnungen enthält."""
        import os
        from django.conf import settings

        fixture_path = os.path.join(settings.BASE_DIR, 'initial_data.json')
        if not os.path.exists(fixture_path):
            self.skipTest('initial_data.json nicht vorhanden.')

        with open(fixture_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        plan_seats = {}
        for entry in data:
            if entry.get('model') == 'seating.seatingcell':
                fields = entry.get('fields', {})
                plan_id = fields.get('plan')
                cell_type = fields.get('cell_type')
                seat_label = fields.get('seat_label', '').strip()
                if cell_type == SeatingCell.CellType.SEAT and seat_label:
                    plan_seats.setdefault(plan_id, []).append(seat_label)

        for plan_id, labels in plan_seats.items():
            duplicates = [lbl for lbl in set(labels) if labels.count(lbl) > 1]
            self.assertEqual(
                duplicates,
                [],
                f"Sitzplan {plan_id} in initial_data.json enthält doppelte Sitzplatzbezeichnungen: {duplicates}",
            )

    def test_cleanup_duplicate_seats_command(self):
        """Testet den Management-Befehl cleanup_duplicate_seats inkl. --dry-run."""
        from django.core.management import call_command
        import io

        # 2 Zellen mit identischem seat_label 'P2' anlegen
        c1 = SeatingCell.objects.create(
            plan=self.plan, x=2, y=2, cell_type=SeatingCell.CellType.SEAT, seat_label='P2'
        )
        c2 = SeatingCell.objects.create(
            plan=self.plan, x=5, y=5, cell_type=SeatingCell.CellType.SEAT, seat_label='P2'
        )

        # 1. Dry Run ausführen -> keine DB-Änderung
        out_dry = io.StringIO()
        call_command('cleanup_duplicate_seats', '--dry-run', stdout=out_dry)
        c2.refresh_from_db()
        self.assertEqual(c2.seat_label, 'P2')
        self.assertIn('DRY-RUN', out_dry.getvalue())

        # 2. Reale Bereinigung ausführen -> c2 erhält R5-P5
        out_real = io.StringIO()
        call_command('cleanup_duplicate_seats', stdout=out_real)
        c1.refresh_from_db()
        c2.refresh_from_db()
        self.assertEqual(c1.seat_label, 'P2')
        self.assertEqual(c2.seat_label, 'R5-P5')
        self.assertIn('Bereinigung abgeschlossen', out_real.getvalue())






















