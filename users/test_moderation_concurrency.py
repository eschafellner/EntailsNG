"""Real PostgreSQL races between bans, registration, activation and check-in."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from events.models import Event, EventRegistration
from events.services import CheckInService
from tournaments import test_swiss_concurrency as swiss
from users.exceptions import RegistrationBlockedError
from users.forms import CustomUserCreationForm
from users.moderation import ban_user, ban_email, is_email_banned
from users.services import UserService
from users.models import EmailVerificationCode


@skipUnlessDBFeature('has_select_for_update')
@override_settings(USER_BAN_HMAC_KEY='concurrency-tests-only-key-longer-than-32-characters',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ModerationConcurrencyTests(TransactionTestCase):
    separate_connection = staticmethod(swiss.SwissConcurrencyTests.separate_connection)
    compete = swiss.SwissConcurrencyTests.compete

    def setUp(self):
        User = get_user_model()
        self.actor = User.objects.create_superuser('orga', 'orga@example.com', 'Password123!')
        self.user = User.objects.create_user('guest', 'guest@example.com', 'Password123!')
        now = timezone.now()
        self.event = Event.objects.create(title='Race LAN', is_active=True, start_date=now,
            end_date=now+timedelta(days=2), status=Event.Status.REGISTRATION_OPEN)
        self.registration = EventRegistration.objects.create(user=self.user, event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID)

    def ban(self):
        return ban_user(self.user.pk, actor=self.actor, reason='Verweis')

    def form(self):
        form = CustomUserCreationForm({'username': 'new-guest', 'email': 'new@example.com',
            'birthday': '2000-01-01', 'password1': 'Password123!', 'password2': 'Password123!'})
        self.assertTrue(form.is_valid(), form.errors)
        return form

    def test_ban_before_service_checkin_rejects_checkin(self):
        self.compete(self.ban, lambda: CheckInService.check_in(self.registration.pk), ValidationError)
        self.registration.refresh_from_db()
        self.assertFalse(self.registration.is_checked_in)

    def test_ban_before_model_checkin_rejects_checkin(self):
        self.compete(self.ban, lambda: self.registration.check_in(), ValidationError)
        self.registration.refresh_from_db()
        self.assertFalse(self.registration.is_checked_in)

    def test_checkin_before_ban_gets_checked_out_and_ticket_invalidated(self):
        old_token = self.registration.checkin_token
        self.compete(lambda: CheckInService.check_in(self.registration.pk), self.ban)
        self.registration.refresh_from_db()
        self.assertFalse(self.registration.is_checked_in)
        self.assertNotEqual(old_token, self.registration.checkin_token)

    def test_email_ban_before_registration_rejects_stale_valid_form(self):
        form = self.form()
        self.compete(lambda: ban_email('new@example.com', actor=self.actor, reason='Bekannte Adresse'),
            lambda: UserService.register_user(form), RegistrationBlockedError)
        self.assertFalse(get_user_model().objects.filter(username='new-guest').exists())

    def test_registration_before_email_ban_disables_the_new_account(self):
        form = self.form()
        with patch('users.services._dispatch_email'):
            self.compete(lambda: UserService.register_user(form),
                lambda: ban_email('new@example.com', actor=self.actor, reason='Bekannte Adresse'))
        user = get_user_model().objects.get(username='new-guest')
        self.assertTrue(user.is_banned)
        self.assertFalse(user.is_active)
        self.assertTrue(is_email_banned(user.email))

    def test_ban_before_email_verification_prevents_identity_change(self):
        code = EmailVerificationCode.generate_for_user(self.user, new_email='changed@example.com')
        def verify():
            self.assertEqual(UserService.confirm_email_change(self.user, code.code)[0], 'invalid_or_expired')
        self.compete(self.ban, verify)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'guest@example.com')
        self.assertTrue(self.user.is_banned)
