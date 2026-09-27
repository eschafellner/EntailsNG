"""Scannerabfragen bleiben auch bei größeren Veranstaltungen begrenzt."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clans.models import Clan, ClanMembership
from events.models import Event, EventRegistration, TicketType
from seating.models import SeatingCell, SeatingPlan


class ScannerPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user(username='scanner_staff', password='secret', is_staff=True)
        start = timezone.now() + timedelta(days=3)
        cls.event = Event.objects.create(
            title='Scanner Test LAN', slug='scanner-test-lan', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=start,
            end_date=start + timedelta(days=2), max_guests=100,
        )
        cls.ticket = TicketType.objects.create(event=cls.event, name='Standard', price=0)
        users = User.objects.bulk_create([
            User(username=f'scanner_guest_{index:03}', email=f'scanner_{index:03}@example.invalid', first_name='LAN',
                 last_name=f'Guest{index:03}', password='!')
            for index in range(75)
        ])
        cls.registrations = EventRegistration.objects.bulk_create([
            EventRegistration(user=user, event=cls.event, ticket_type=cls.ticket,
                              payment_status=(EventRegistration.PaymentStatus.PAID if index % 2 == 0
                                              else EventRegistration.PaymentStatus.UNPAID),
                              is_checked_in=index < 5)
            for index, user in enumerate(users)
        ])
        clan = Clan.objects.create(name='Scanner Clan', tag='SC', password='')
        ClanMembership.objects.create(user=users[-1], clan=clan, status=ClanMembership.Status.ACCEPTED)
        seating = SeatingPlan.objects.create(event=cls.event, name='Saal', columns=1, rows=1)
        SeatingCell.objects.create(
            plan=seating, x=1, y=1, cell_type=SeatingCell.CellType.SEAT,
            seat_label='Z-99', registration=cls.registrations[-1],
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_initial_page_and_next_page_are_limited(self):
        response = self.client.get(reverse('checkin_scanner'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['registrations']), 30)
        self.assertContains(response, 'data-next-page="2"')
        self.assertNotContains(response, 'scanner_guest_074')

        next_page = self.client.get(reverse('checkin_scanner'), {
            'partial': '1', 'page': '2',
        }).json()
        self.assertEqual(next_page['match_count'], 75)
        self.assertEqual(next_page['next_page'], 3)
        self.assertEqual(next_page['remaining'], 15)
        self.assertEqual(next_page['rows_html'].count('class="guest-row"'), 30)

    def test_search_reaches_last_guest_and_combined_name(self):
        for query in ('scanner_guest_074', 'LAN Guest074', 'Z-99', self.registrations[-1].short_code):
            data = self.client.get(reverse('checkin_scanner'), {
                'partial': '1', 'q': query,
            }).json()
            self.assertEqual(data['match_count'], 1)
            self.assertIn('scanner_guest_074', data['rows_html'])
            self.assertIn('[SC]', data['rows_html'])
            self.assertIsNone(data['next_page'])

    def test_status_filter_and_permission(self):
        data = self.client.get(reverse('checkin_scanner'), {
            'partial': '1', 'filter': 'checked-in',
        }).json()
        self.assertEqual(data['match_count'], 5)
        self.assertEqual(data['stats']['total'], 75)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('checkin_scanner'), {
            'partial': '1',
        }).status_code, 302)
