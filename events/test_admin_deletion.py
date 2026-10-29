from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Event, EventRegistration, TicketType

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AdminDeletionKeepsRegistrationsTests(TestCase):
    """F-024: Admin-Löschen darf Anmeldungen samt Zahlungshistorie nicht mitlöschen."""

    def setUp(self):
        self.admin = User.objects.create_superuser('del-orga', 'del-orga@example.org', 'password')
        self.guest = User.objects.create_user('del-guest', 'del-guest@example.org', 'password')
        self.idle = User.objects.create_user('del-idle', 'del-idle@example.org', 'password')
        start = timezone.now() + timedelta(days=3)
        self.event = Event.objects.create(title='Löschtest LAN', slug='loeschtest-lan',
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=1))
        self.empty_event = Event.objects.create(title='Leeres Event', slug='leeres-event',
            status=Event.Status.DRAFT, start_date=start, end_date=start + timedelta(days=1))
        ticket = TicketType.objects.create(event=self.event, name='Standard', price=10)
        self.reg = EventRegistration.objects.create(user=self.guest, event=self.event, ticket_type=ticket,
            payment_status=EventRegistration.PaymentStatus.PAID)
        self.client.force_login(self.admin)

    def test_database_protects_registrations(self):
        with self.assertRaises(ProtectedError):
            self.guest.delete()
        with self.assertRaises(ProtectedError):
            self.event.delete()
        self.assertTrue(EventRegistration.objects.filter(pk=self.reg.pk).exists())

    def test_admin_delete_only_without_registrations(self):
        self.assertEqual(self.client.get(reverse('admin:users_user_delete', args=[self.guest.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:events_event_delete', args=[self.event.pk])).status_code, 403)
        self.client.post(reverse('admin:users_user_delete', args=[self.idle.pk]), {'post': 'yes'})
        self.client.post(reverse('admin:events_event_delete', args=[self.empty_event.pk]), {'post': 'yes'})
        self.assertFalse(User.objects.filter(pk=self.idle.pk).exists())
        self.assertFalse(Event.objects.filter(pk=self.empty_event.pk).exists())

    def test_bulk_delete_keeps_users_with_registrations(self):
        self.client.post(reverse('admin:users_user_changelist'), {
            'action': 'delete_selected', '_selected_action': [self.guest.pk], 'post': 'yes',
        })
        self.assertTrue(User.objects.filter(pk=self.guest.pk).exists())
        self.assertTrue(EventRegistration.objects.filter(pk=self.reg.pk).exists())


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AdminAnonymizeAccountTests(TestCase):
    """F-024: Admin-Aktion „Konto anonymisieren“ nutzt den Löschservice ohne Passwort."""

    def setUp(self):
        self.admin = User.objects.create_superuser('anon-orga', 'anon-orga@example.org', 'password')
        self.guest = User.objects.create_user('anon-guest', 'anon-guest@example.org', 'password',
                                              first_name='Max', last_name='Muster')
        self.payer = User.objects.create_user('anon-payer', 'anon-payer@example.org', 'password')
        self.staff = User.objects.create_user('anon-staff', 'anon-staff@example.org', 'password', is_staff=True)
        start = timezone.now() + timedelta(days=3)
        self.event = Event.objects.create(title='Anon LAN', slug='anon-lan',
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=1))
        ticket = TicketType.objects.create(event=self.event, name='Standard', price=10)
        self.open_reg = EventRegistration.objects.create(user=self.guest, event=self.event, ticket_type=ticket)
        self.paid_reg = EventRegistration.objects.create(user=self.payer, event=self.event, ticket_type=ticket,
            payment_status=EventRegistration.PaymentStatus.PAID)
        self.client.force_login(self.admin)
        self.url = reverse('admin:users_user_changelist')

    def run_action(self, users, confirm):
        data = {'action': 'action_anonymize_accounts', '_selected_action': [u.pk for u in users]}
        if confirm:
            data['confirm'] = 'yes'
        return self.client.post(self.url, data, follow=confirm)

    def test_confirmation_page_changes_nothing(self):
        response = self.run_action([self.guest], confirm=False)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'anon-guest')
        self.guest.refresh_from_db()
        self.assertIsNone(self.guest.deleted_at)

    def test_anonymizes_and_keeps_registration_history(self):
        self.run_action([self.guest], confirm=True)
        self.guest.refresh_from_db()
        self.assertIsNotNone(self.guest.deleted_at)
        self.assertTrue(self.guest.username.startswith('deleted_'))
        self.assertEqual((self.guest.first_name, self.guest.last_name), ('', ''))
        self.assertFalse(self.guest.has_usable_password())
        self.open_reg.refresh_from_db()
        self.assertEqual(self.open_reg.user_id, self.guest.pk)
        self.assertEqual(self.open_reg.payment_status, EventRegistration.PaymentStatus.CANCELLED)

    def test_blockers_and_self_are_respected(self):
        response = self.run_action([self.payer, self.staff, self.admin], confirm=True)
        for user in (self.payer, self.staff, self.admin):
            user.refresh_from_db()
            self.assertIsNone(user.deleted_at)
        self.paid_reg.refresh_from_db()
        self.assertEqual(self.paid_reg.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertContains(response, 'anon-payer')

    def test_requires_delete_permission(self):
        from django.contrib.auth.models import Permission
        clerk = User.objects.create_user('anon-clerk', 'clerk@example.org', 'password', is_staff=True)
        clerk.user_permissions.add(*Permission.objects.filter(codename__in=['view_user', 'change_user']))
        self.client.force_login(clerk)
        self.run_action([self.guest], confirm=True)
        self.guest.refresh_from_db()
        self.assertIsNone(self.guest.deleted_at)
