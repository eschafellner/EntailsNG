import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Event, EventRegistration, TicketType


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EventReviewTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.staff = User.objects.create_superuser('review-orga', 'orga@example.org', 'password')
        self.guest = User.objects.create_user('review-guest')
        start = timezone.now() + timedelta(days=1)
        self.event = Event.objects.create(title='Review LAN', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=2), max_guests=1)
        self.ticket = TicketType.objects.create(event=self.event, name='Standard', price=10)
        self.reg = EventRegistration.objects.create(user=self.guest, event=self.event, ticket_type=self.ticket,
            payment_status=EventRegistration.PaymentStatus.PAID)
        self.client.force_login(self.staff)

    def test_head_is_read_only_and_other_methods_are_rejected(self):
        url = reverse('process_checkin', args=[self.reg.pk, self.reg.checkin_token])
        self.assertEqual(self.client.head(url).status_code, 200)
        self.assertEqual(self.client.options(url).status_code, 405)
        self.reg.refresh_from_db()
        self.assertFalse(self.reg.is_checked_in)

    def test_scanner_json_requires_object_and_typed_fields(self):
        for name in ['api_toggle_check_in', 'api_scan_qr']:
            for data in [[], None, 3, 'code', {'registration_id': True}, {'registration_id': {}},
                         {'registration_id': '²'}, {'registration_id': 2**64}, {'code': []}, {'code': True}]:
                with self.subTest(endpoint=name, body=data):
                    response = self.client.post(reverse(name), json.dumps(data), content_type='application/json')
                    self.assertEqual(response.status_code, 400)
            for raw in ('{"registration_id":' + '9' * 5000 + '}', b'\xff'):
                response = self.client.post(reverse(name), raw, content_type='application/json')
                self.assertEqual(response.status_code, 400)

    def test_locked_result_syncs_stale_instance_and_identifies_repeat(self):
        stale = EventRegistration.objects.get(pk=self.reg.pk)
        self.assertTrue(self.reg.check_in(target_event=self.event))
        self.assertFalse(stale.check_in(target_event=self.event))
        self.assertTrue(stale.is_checked_in)
        self.assertEqual(stale.checked_in_at, self.reg.checked_in_at)

    def test_scan_reports_repeat_when_another_scan_wins_after_lookup(self):
        original = EventRegistration.check_in
        def concurrent_winner(registration, **kwargs):
            original(EventRegistration.objects.get(pk=registration.pk), **kwargs)
            return original(registration, **kwargs)
        with patch.object(EventRegistration, 'check_in', concurrent_winner):
            response = self.client.post(reverse('api_scan_qr'), {'code': self.reg.short_code}, content_type='application/json')
        self.assertEqual(response.json()['status'], 'already_checked_in')
        self.assertTrue(response.json()['already_checked_in'])

    def test_admin_cannot_reactivate_cancelled_ticket_in_full_event(self):
        second = get_user_model().objects.create_user('review-cancelled')
        cancelled = EventRegistration.objects.create(user=second, event=self.event, ticket_type=self.ticket,
            payment_status=EventRegistration.PaymentStatus.CANCELLED)
        url = reverse('admin:events_eventregistration_change', args=[cancelled.pk])
        data = {'user': second.pk, 'event': self.event.pk, 'ticket_type': self.ticket.pk,
                'booking_price': '10.00', 'payment_status': 'PAID', 'paid_amount': '10.00', '_save': 'Speichern'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ausgebucht')
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.payment_status, 'CANCELLED')
        self.assertEqual(self.event.active_registrations_count, 1)
        # Free the existing slot and the exact same form can reactivate safely.
        self.reg.mark_as_cancelled()
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.payment_status, 'PAID')
        self.assertIsNotNone(cancelled.paid_at)
