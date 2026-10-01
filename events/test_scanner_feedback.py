"""Scanner feedback must describe the registration actually changed by the API."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from configuration.models import SystemTranslation
from events.models import Event, EventRegistration, TicketType
from seating.models import SeatingCell, SeatingPlan


@override_settings(TIME_ZONE='Europe/Berlin', USE_TZ=True)
class ScannerFeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user(username='feedback_staff', is_staff=True)
        cls.guest = User.objects.create_user(username='FeedbackGast', first_name='Test', last_name='Gast')
        start = timezone.now() + timedelta(days=1)
        cls.event = Event.objects.create(
            title='Feedback LAN', slug='feedback-lan', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=2),
        )
        cls.ticket = TicketType.objects.create(event=cls.event, name='Weekend', price=0)
        cls.registration = EventRegistration.objects.create(
            user=cls.guest, event=cls.event, ticket_type=cls.ticket,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )
        plan = SeatingPlan.objects.create(event=cls.event, name='Saal', rows=1, columns=1)
        SeatingCell.objects.create(
            plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT,
            seat_label='A-12', registration=cls.registration,
        )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.staff)

    def toggle(self):
        return self.client.post(reverse('api_toggle_check_in'),
                                {'registration_id': self.registration.pk}, content_type='application/json')

    def assert_guest_details(self, body):
        self.assertEqual(body['registration_id'], self.registration.pk)
        self.assertEqual(body['user'], 'FeedbackGast')
        self.assertEqual(body['full_name'], 'Test Gast')
        self.assertEqual(body['ticket'], 'Weekend')
        self.assertEqual(body['seat'], 'A-12')

    def test_toggle_returns_confirmed_guest_details_and_time_for_both_actions(self):
        response = self.toggle()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assert_guest_details(body)
        self.assertTrue(body['is_checked_in'])
        self.assertRegex(body['checked_in_at'], r'^\d{2}:\d{2}:\d{2}$')
        self.registration.refresh_from_db()
        self.assertTrue(self.registration.is_checked_in)
        self.assertEqual(body['checked_in_at'],
                         timezone.localtime(self.registration.checked_in_at).strftime('%H:%M:%S'))
        body = self.toggle().json()
        self.assert_guest_details(body)
        self.assertFalse(body['is_checked_in'])
        self.assertIsNone(body['checked_in_at'])

    def test_unpaid_rejection_identifies_guest_without_success(self):
        EventRegistration.objects.filter(pk=self.registration.pk).update(payment_status='UNPAID')
        response = self.toggle()
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assert_guest_details(body)
        self.assertEqual(body['status'], 'error')
        self.registration.refresh_from_db()
        self.assertFalse(self.registration.is_checked_in)

    def test_search_scan_never_checks_out_an_already_checked_in_guest(self):
        self.registration.check_in(target_event=self.event)
        before = self.registration.checked_in_at
        response = self.client.post(reverse('api_scan_qr'),
                                    {'code': self.registration.short_code}, content_type='application/json')
        self.assertEqual(response.json()['status'], 'already_checked_in')
        self.assert_guest_details(response.json())
        self.registration.refresh_from_db()
        self.assertTrue(self.registration.is_checked_in)
        self.assertEqual(self.registration.checked_in_at, before)
        self.assertEqual(response.json()['checked_in_at'], timezone.localtime(before).strftime('%H:%M:%S'))

    def test_scanner_uses_configured_texts_and_safe_json_embedding(self):
        SystemTranslation.objects.update_or_create(
            key='scanner_feedback_success', defaults={'text': 'Willkommen </script><script>test</script>'},
        )
        cache.clear()
        response = self.client.get(reverse('checkin_scanner'))
        self.assertContains(response, 'id="scanner-feedback-texts"')
        self.assertEqual(response.context['scanner_feedback_texts']['success'],
                         'Willkommen </script><script>test</script>')
        self.assertNotContains(response, 'Willkommen </script><script>test</script>')
        self.assertContains(response, 'data-code="' + self.registration.short_code + '"')
