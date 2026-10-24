from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events.exceptions import RegistrationError
from events.models import Event, EventRegistration
from events.payment_qr import generate_epc_qr_payload
from events.services import RegistrationService
from seating.models import SeatingCell, SeatingPlan
from .forms import CustomUserCreationForm, UserProfileForm, validate_real_name

User = get_user_model()


def signup_data(**overrides):
    data = {
        'username': 'newgamer', 'first_name': 'Anna', 'last_name': 'Müller',
        'email': 'newgamer@example.com', 'birthday': '2000-01-01',
        'password1': 'Sup3r-Secret-Pass!', 'password2': 'Sup3r-Secret-Pass!',
    }
    data.update(overrides)
    return data


class RealNameValidationTests(TestCase):
    def test_accepts_international_names_and_normalizes_whitespace(self):
        for raw, expected in [('Müller-Lüdenscheidt', 'Müller-Lüdenscheidt'), ("O'Brien", "O'Brien"),
                              ('José  María', 'José María'), ('  Anna ', 'Anna'), ('St. Clair', 'St. Clair')]:
            self.assertEqual(validate_real_name(raw), expected)

    def test_rejects_empty_short_digits_markup_and_overlong(self):
        for raw in ['', '   ', 'A', 'R2D2', '<script>', 'Anna_Lena', 'a' * 151, '--']:
            with self.assertRaises(forms.ValidationError, msg=raw):
                validate_real_name(raw)


class SignupRealNameTests(TestCase):
    def test_signup_requires_both_names(self):
        for missing in ('first_name', 'last_name'):
            form = CustomUserCreationForm(data=signup_data(**{missing: ''}))
            self.assertFalse(form.is_valid())
            self.assertIn(missing, form.errors)

    def test_signup_rejects_invalid_name(self):
        form = CustomUserCreationForm(data=signup_data(last_name='<b>Hacker</b>'))
        self.assertFalse(form.is_valid())
        self.assertIn('last_name', form.errors)

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_signup_view_stores_normalized_names(self):
        from emails.models import GeneralEmailSettings
        settings = GeneralEmailSettings.load()
        settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        settings.sender_email = 'noreply@example.com'
        settings.is_enabled = True
        settings.save()
        response = self.client.post(reverse('register'), signup_data(first_name='  Anna  Lena '))
        self.assertRedirects(response, reverse('verify_email'))
        user = User.objects.get(username='newgamer')
        self.assertEqual((user.first_name, user.last_name), ('Anna Lena', 'Müller'))
        self.assertTrue(user.has_real_name)


class ProfileRealNameTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('profilegamer', 'profile@example.com', 'pw',
                                             first_name='Anna', last_name='Alt')
        now = timezone.now()
        self.event = Event.objects.create(title='LAN', slug='lan', is_active=True, status=Event.Status.REGISTRATION_OPEN,
                                          start_date=now + timedelta(days=5), end_date=now + timedelta(days=7))

    def form(self, **names):
        data = {'email': self.user.email, 'birthday': '', 'first_name': 'Anna', 'last_name': 'Neu'}
        data.update(names)
        return UserProfileForm(data=data, instance=User.objects.get(pk=self.user.pk))

    def test_name_editable_without_paid_registration(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, 'Neu')

    def test_name_required_in_profile(self):
        self.assertFalse(self.form(last_name='').is_valid())

    def test_name_locked_after_payment_on_active_event(self):
        EventRegistration.objects.create(user=self.user, event=self.event,
                                         payment_status=EventRegistration.PaymentStatus.PAID)
        self.assertTrue(self.user.is_real_name_locked)
        form = self.form()
        self.assertTrue(form.real_name_locked)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, 'Alt')

    def test_name_locked_after_check_in(self):
        EventRegistration.objects.create(user=self.user, event=self.event, is_checked_in=True)
        self.assertTrue(self.user.is_real_name_locked)

    def test_unpaid_or_inactive_event_does_not_lock(self):
        EventRegistration.objects.create(user=self.user, event=self.event)
        self.assertFalse(self.user.is_real_name_locked)
        self.event.is_active = False
        self.event.save()
        EventRegistration.objects.filter(user=self.user).update(payment_status=EventRegistration.PaymentStatus.PAID)
        self.assertFalse(self.user.is_real_name_locked)

    def test_legacy_account_without_name_can_add_it_despite_payment(self):
        legacy = User.objects.create_user('legacy', 'legacy@example.com', 'pw')
        EventRegistration.objects.create(user=legacy, event=self.event, payment_status=EventRegistration.PaymentStatus.PAID)
        self.assertFalse(legacy.is_real_name_locked)
        form = UserProfileForm(data={'email': legacy.email, 'birthday': '', 'first_name': 'Lea', 'last_name': 'Legacy'},
                               instance=legacy)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        legacy.refresh_from_db()
        self.assertEqual(legacy.get_full_name(), 'Lea Legacy')

    def test_orga_can_change_locked_name_in_admin(self):
        EventRegistration.objects.create(user=self.user, event=self.event,
                                         payment_status=EventRegistration.PaymentStatus.PAID)
        User.objects.create_superuser('orga', 'orga@example.com', 'pw')
        self.client.login(username='orga', password='pw')
        response = self.client.get(reverse('admin:users_user_change', args=[self.user.pk]))
        self.assertContains(response, 'name="last_name"')
        self.user.last_name = 'Korrigiert'
        self.user.save(update_fields=['last_name'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, 'Korrigiert')


@override_settings(SECURE_SSL_REDIRECT=False)
class EventRegistrationRealNameTests(TestCase):
    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.event = Event.objects.create(title='LAN', slug='lan', is_active=True, status=Event.Status.REGISTRATION_OPEN,
                                          start_date=now + timedelta(days=5), end_date=now + timedelta(days=7))

    def test_registration_blocked_without_name(self):
        user = User.objects.create_user('noname', 'noname@example.com', 'pw')
        with self.assertRaisesMessage(RegistrationError, 'echten Namen'):
            RegistrationService.register_user(user, self.event.pk)
        self.assertFalse(EventRegistration.objects.filter(user=user).exists())

    def test_registration_allowed_with_name(self):
        user = User.objects.create_user('withname', 'withname@example.com', 'pw', first_name='Max', last_name='Muster')
        registration, created, _ = RegistrationService.register_user(user, self.event.pk)
        self.assertTrue(created)

    def test_dashboard_shows_hint_only_without_name(self):
        user = User.objects.create_user('noname', 'noname@example.com', 'pw')
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse('dashboard')), reverse('profile'))
        self.assertContains(self.client.get(reverse('dashboard')), 'Bitte ergänze deinen echten Namen')
        user.first_name, user.last_name = 'Max', 'Muster'
        user.save()
        self.assertNotContains(self.client.get(reverse('dashboard')), 'Bitte ergänze deinen echten Namen')


@override_settings(SECURE_SSL_REDIRECT=False)
class PaymentReferenceAndPrivacyTests(TestCase):
    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.event = Event.objects.create(title='LAN', slug='lan', is_active=True, status=Event.Status.REGISTRATION_OPEN,
                                          start_date=now + timedelta(days=5), end_date=now + timedelta(days=7))
        self.user = User.objects.create_user('refgamer', 'ref@example.com', 'pw', first_name='Anna', last_name='Müller')
        self.registration = EventRegistration.objects.create(user=self.user, event=self.event)

    def test_reference_contains_short_code_and_real_name(self):
        self.assertEqual(self.registration.payment_reference, f'{self.registration.short_code} Anna Müller')

    def test_reference_falls_back_to_username_without_name(self):
        legacy = User.objects.create_user('legacyref', 'legacyref@example.com', 'pw')
        registration = EventRegistration.objects.create(user=legacy, event=self.event)
        self.assertEqual(registration.payment_reference, f'{registration.short_code} legacyref')

    def test_qr_payload_uses_same_reference(self):
        lines = generate_epc_qr_payload(self.registration).split('\n')
        self.assertEqual(lines[10], self.registration.payment_reference)

    def test_seating_api_never_exposes_real_name(self):
        plan = SeatingPlan.objects.create(event=self.event, name='Hall', columns=2, rows=1)
        SeatingCell.objects.create(plan=plan, x=1, y=1, cell_type='SEAT', seat_label='A1', registration=self.registration,
                                   reservation_status=SeatingCell.ReservationStatus.PRE_RESERVED)
        other = User.objects.create_user('viewer', 'viewer@example.com', 'pw', first_name='Vera', last_name='Viewer')
        self.client.force_login(other)
        body = self.client.get(reverse('api_event_seating', args=[self.event.pk])).content.decode()
        self.assertIn('refgamer', body)
        self.assertNotIn('Müller', body)
        self.assertNotIn('M\\u00fcller', body)
        self.assertNotIn('Anna', body)
