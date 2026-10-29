from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Event, EventRegistration

User = get_user_model()


class PaymentCheckRedirectTests(TestCase):
    """F-026: Redirect nur auf eigene Hosts, nicht auf einen beliebigen Referer."""

    def setUp(self):
        self.staff = User.objects.create_superuser('redir-orga', 'redir@example.org', 'password')
        start = timezone.now() + timedelta(days=2)
        self.event = Event.objects.create(title='Redirect LAN', slug='redirect-lan',
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=1))
        self.client.force_login(self.staff)
        self.url = reverse('api_update_payment_check', args=[self.event.pk])

    def test_foreign_referer_is_ignored(self):
        for data in ({}, {'custom_date': 'kein-datum'}):
            with self.subTest(data=data):
                response = self.client.post(self.url, data, HTTP_REFERER='https://attacker.example/phish')
                self.assertRedirects(response, reverse('guest_list'), fetch_redirect_response=False)

    def test_own_referer_is_kept(self):
        own = 'http://testserver' + reverse('guest_list_slug', args=[self.event.slug])
        response = self.client.post(self.url, {}, HTTP_REFERER=own)
        self.assertRedirects(response, own, fetch_redirect_response=False)


class OverbookingWarningTests(TestCase):
    """F-026: Stornierte Anmeldungen zählen nicht als Überbuchung."""

    def test_cancelled_registrations_do_not_trigger_warning(self):
        admin_user = User.objects.create_superuser('over-orga', 'over@example.org', 'password')
        start = timezone.now() + timedelta(days=2)
        event = Event.objects.create(title='Voll LAN', slug='voll-lan', is_active=True, max_guests=1,
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=1))
        EventRegistration.objects.create(user=User.objects.create_user('over-a'), event=event,
            payment_status=EventRegistration.PaymentStatus.CANCELLED)
        EventRegistration.objects.create(user=User.objects.create_user('over-b'), event=event)
        self.client.force_login(admin_user)
        response = self.client.get(reverse('admin:events_event_changelist'))
        self.assertFalse([m for m in get_messages(response.wsgi_request) if 'mehr Plätze gebucht' in str(m)])
        EventRegistration.objects.create(user=User.objects.create_user('over-c'), event=event)
        response = self.client.get(reverse('admin:events_event_changelist'))
        warnings = [str(m) for m in get_messages(response.wsgi_request) if 'mehr Plätze gebucht' in str(m)]
        self.assertEqual(len(warnings), 1)
        self.assertIn('(2/1 Plätze)', warnings[0])


class GuestListToastTests(TestCase):
    """F-035: API-Meldungen (Systemtexte) erscheinen im Toast nur als Text."""

    def test_toast_uses_text_content(self):
        staff = User.objects.create_superuser('toast-orga', 'toast@example.org', 'password')
        start = timezone.now() + timedelta(days=2)
        Event.objects.create(title='Toast LAN', slug='toast-lan', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=1))
        self.client.force_login(staff)
        content = self.client.get(reverse('guest_list')).content.decode()
        self.assertIn('function showToast', content)
        self.assertNotIn('toast.innerHTML', content)
        self.assertIn("toast.textContent = (isError ? '⚠️ ' : '✓ ') + message;", content)
