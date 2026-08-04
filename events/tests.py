from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from events.models import Event, EventRegistration, TicketType

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

    def test_process_checkin_paid(self):
        registration = EventRegistration.objects.create(
            user=self.user,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
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

