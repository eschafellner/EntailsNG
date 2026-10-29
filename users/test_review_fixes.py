from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, RequestFactory
from django.urls import reverse

from .auth_backends import EmailOrUsernameBackend
from .models import User, EmailVerificationCode
from .rate_limits import reserve_rate_limit


class RateReservationTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_parallel_reservations_admit_exactly_the_limit(self):
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _: reserve_rate_limit('review-limit', limit=3, timeout=60), range(80)))
        self.assertEqual(sum(results), 3)
        self.assertEqual(cache.get('review-limit'), 80)

    def test_expiry_between_add_and_incr_retries_without_overwriting(self):
        with patch('users.rate_limits.cache.add', side_effect=[False, False]), \
             patch('users.rate_limits.cache.incr', side_effect=[ValueError(), 4]), \
             patch('users.rate_limits.cache.set') as overwrite:
            self.assertFalse(reserve_rate_limit('review-expiry', limit=3, timeout=60))
            overwrite.assert_not_called()


class ActivationPrivacyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('privateguest', 'private@example.org', 'Password123!', is_active=False)
        EmailVerificationCode.generate_for_user(self.user)

    def test_public_activation_has_uniform_response_and_does_not_create_session(self):
        for identifier in ['privateguest', 'private@example.org', 'unknown']:
            with self.subTest(identifier=identifier):
                response = self.client.post(reverse('request_activation_code'), {'email': identifier})
                self.assertRedirects(response, reverse('login'))
                self.assertNotIn('pending_verification_user_id', self.client.session)
                verification = self.client.get(reverse('verify_email'))
                self.assertEqual(verification.status_code, 302)
                self.assertNotIn(b'private@example.org', verification.content)

    def test_inactive_password_failures_lock_account_and_count_ip(self):
        backend = EmailOrUsernameBackend()
        request = RequestFactory().post('/login/')
        for _ in range(5):
            self.assertIsNone(backend.authenticate(request, username='privateguest', password='wrong'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked())
        self.assertEqual(cache.get('ip_failed_logins_127.0.0.1'), 5)
        request = RequestFactory().post('/login/')
        self.assertIsNone(backend.authenticate(request, username='privateguest', password='Password123!'))
        self.assertTrue(request.account_locked)
        self.assertFalse(hasattr(request, 'unverified_user'))

    def test_correct_password_can_still_resume_verification(self):
        self.client.post(reverse('login'), {'username': 'privateguest', 'password': 'Password123!'})
        self.assertEqual(self.client.session['pending_verification_user_id'], self.user.pk)


class UsernameCaseCollisionTests(TestCase):
    """F-015: Registrierung lehnt Benutzernamen ab, die sich nur in der Schreibweise unterscheiden."""

    def setUp(self):
        User.objects.create_user('ReviewBob', 'bob@example.com', 'StrongPass123!')

    def form(self, username):
        from .forms import CustomUserCreationForm
        return CustomUserCreationForm(data={
            'username': username, 'email': f'{username.strip().lower()}-new@example.com',
            'first_name': 'Max', 'last_name': 'Mustermann', 'birthday': '1990-01-01',
            'password1': 'StrongPass123!', 'password2': 'StrongPass123!',
        })

    def test_case_variant_of_existing_username_is_rejected(self):
        for username in ('reviewbob', 'REVIEWBOB', ' reviewBob '):
            with self.subTest(username=username):
                form = self.form(username)
                self.assertFalse(form.is_valid())
                self.assertIn('username', form.errors)

    def test_new_username_and_own_checks_still_apply(self):
        self.assertTrue(self.form('ReviewAlice').is_valid())
        form = self.form('bob@example')
        self.assertFalse(form.is_valid())
        self.assertIn('@', str(form.errors['username']))
