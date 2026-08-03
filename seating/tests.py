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

        # Teste API Performance & Query Count für 1000 Kacheln
        with self.assertNumQueries(3):  # Plan fetch, ClanMembership map, Cells with select_related
            response = self.client.get(
                reverse('api_event_seating', kwargs={'event_id': large_event.id})
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['cells']), 1000)


