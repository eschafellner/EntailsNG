"""Global bans, neutral registration and preservation of account/ticket history."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Permission
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from configuration.translations import get_translation as tr
from emails.models import GeneralEmailSettings
from events.models import Event, EventRegistration
from events.services import CheckInService, RegistrationService
from users.exceptions import RegistrationBlockedError, UserBanError
from users.forms import CustomUserCreationForm, UserProfileForm
from users.models import BannedEmail, EmailVerificationCode, UserBan, UserBanLog
from users.moderation import ban_user, ban_email, revoke_ban, is_email_banned, ban_state
from users.services import UserService

User = get_user_model()


@override_settings(USER_BAN_HMAC_KEY='moderation-tests-only-key-with-at-least-32-characters',
    SECURE_SSL_REDIRECT=False, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class UserModerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organizer = User.objects.create_superuser('ban-orga', 'orga@example.com', 'Password123!')
        cls.user = User.objects.create_user('ban-target', 'target@example.com', 'Password123!')
        cls.staff = User.objects.create_user('ban-helper', 'helper@example.com', 'Password123!', is_staff=True)
        cls.staff.user_permissions.add(Permission.objects.get(codename='manage_user_bans'))
        now = timezone.now()
        cls.event = Event.objects.create(title='Moderation LAN', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, max_guests=100, start_date=now, end_date=now+timedelta(days=2))
        cls.registration = EventRegistration.objects.create(user=cls.user, event=cls.event,
            payment_status=EventRegistration.PaymentStatus.PAID, is_checked_in=True, checked_in_at=now)

    def setUp(self):
        cache.clear()
        settings = GeneralEmailSettings.load()
        settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        settings.sender_email = 'noreply@example.com'
        settings.is_enabled = True
        settings.save()

    def ban(self, **kwargs):
        return ban_user(self.user.pk, actor=self.organizer, reason='Veranstaltungsverweis', **kwargs)

    def registration_data(self, email='target@example.com', username='another-name'):
        return {'username': username, 'email': email, 'birthday': '2000-01-01',
            'password1': 'Password123!', 'password2': 'Password123!'}

    def test_ban_logs_reason_and_preserves_bookings_and_password(self):
        ban = self.ban()
        self.user.refresh_from_db()
        self.registration.refresh_from_db()
        self.assertTrue(self.user.is_banned)
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.check_password('Password123!'))
        self.assertEqual(self.registration.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertFalse(self.registration.is_checked_in)
        self.assertEqual(ban.logs.get().reason, 'Veranstaltungsverweis')
        self.assertEqual(ban.created_by, self.organizer)

    def test_login_and_current_sessions_are_rejected(self):
        self.client.force_login(self.user)
        self.ban()
        self.assertIsNone(authenticate(username='ban-target', password='Password123!'))
        self.assertEqual(self.client.get(reverse('profile')).status_code, 302)

    def test_signed_cookie_sessions_do_not_reappear_after_unban(self):
        with self.settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies'):
            client = Client()
            client.force_login(self.user)
            old_cookie = client.cookies['sessionid'].value
            ban = self.ban()
            revoke_ban(ban.pk, actor=self.organizer, reason='Entscheidung aufgehoben')
            client.cookies['sessionid'] = old_cookie
            self.assertEqual(client.get(reverse('profile')).status_code, 302)
            self.assertIsNotNone(authenticate(username='ban-target', password='Password123!'))

    def test_registration_uses_only_neutral_error_even_for_duplicate_username(self):
        self.ban()
        with patch('users.services._dispatch_email') as dispatch:
            response = self.client.post(reverse('register'), self.registration_data(' TARGET@EXAMPLE.COM ', 'ban-target'))
        self.assertContains(response, tr('ban_registration_failed'))
        self.assertNotContains(response, 'Diese E-Mail-Adresse wird bereits')
        self.assertNotContains(response, 'Veranstaltungsverweis')
        self.assertEqual(response.context['form'].errors.as_data().keys(), {'__all__'})
        dispatch.assert_not_called()
        self.assertFalse(User.objects.filter(username='another-name').exists())

    def test_identity_survives_account_deletion_and_unban_allows_new_account(self):
        self.ban()
        self.registration.payment_status = EventRegistration.PaymentStatus.CANCELLED
        self.registration.save()
        UserService.delete_account(self.user, 'Password123!')
        self.assertTrue(is_email_banned('target@example.com'))
        form = CustomUserCreationForm(self.registration_data())
        self.assertFalse(form.is_valid())
        revoke_ban(UserBan.objects.get(user=self.user).pk, actor=self.organizer, reason='Aufgehoben')
        form = CustomUserCreationForm(self.registration_data())
        self.assertTrue(form.is_valid(), form.errors)
        new, _ = UserService.register_user(form)
        self.assertNotEqual(new.pk, self.user.pk)

    def test_fingerprints_and_ban_survive_hard_deletion(self):
        ban = self.ban()
        self.user.delete()
        ban.refresh_from_db()
        self.assertIsNone(ban.user_id)
        self.assertTrue(is_email_banned('target@example.com'))
        self.assertTrue(ban.logs.exists())

    def test_service_rechecks_form_validated_before_email_ban(self):
        form = CustomUserCreationForm(self.registration_data('new@example.com'))
        self.assertTrue(form.is_valid(), form.errors)
        ban_email('new@example.com', actor=self.organizer, reason='Bekannte weitere Adresse')
        with self.assertRaises(RegistrationBlockedError):
            UserService.register_user(form)
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_manual_email_ban_disables_existing_unverified_account(self):
        user = User.objects.create_user('pending', 'pending@example.com', 'Password123!', is_active=False)
        ban_email(user.email, actor=self.organizer, reason='Adresse ausdrücklich bestätigt')
        user.refresh_from_db()
        self.assertTrue(user.is_banned)
        self.assertTrue(is_email_banned(user.email))

    def test_unverified_email_is_not_automatically_added(self):
        user = User.objects.create_user('unverified', 'unverified@example.com', 'Password123!', is_active=False)
        ban = ban_user(user.pk, actor=self.organizer, reason='Account sperren')
        self.assertFalse(ban.email_identities.exists())
        response = self.client.post(reverse('register'), self.registration_data(user.email))
        self.assertContains(response, tr('ban_registration_failed'))
        ban_email(user.email, actor=self.organizer, reason='Identität manuell bestätigt')
        self.assertTrue(ban.email_identities.exists())
        revoke_ban(ban.pk, actor=self.organizer, reason='Aufheben')
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_no_plain_email_in_sperrlist(self):
        ban = self.ban()
        identity = ban.email_identities.get()
        self.assertEqual(len(identity.fingerprint), 64)
        self.assertNotIn('target', identity.fingerprint)
        self.assertTrue(is_email_banned(' TARGET@example.com '))
        self.assertFalse(is_email_banned('target+another@example.com'))

    def test_no_missing_key_fallback_and_changed_key_fails_closed(self):
        with self.settings(USER_BAN_HMAC_KEY=''):
            with self.assertRaises(UserBanError):
                self.ban()
        self.assertFalse(UserBan.objects.exists())
        self.ban()
        for key in ('', 'a-different-secret-key-with-at-least-32-characters'):
            with self.settings(USER_BAN_HMAC_KEY=key):
                form = CustomUserCreationForm(self.registration_data('innocent@example.com'))
                self.assertFalse(form.is_valid())
                self.assertEqual(form.non_field_errors(), [tr('ban_registration_failed')])

    def test_permissions_reason_and_self_protection(self):
        for actor in (self.user, User.objects.create_user('unprivileged', is_staff=True)):
            with self.assertRaises(PermissionDenied):
                ban_user(self.user.pk, actor=actor, reason='Grund')
        with self.assertRaises(UserBanError):
            ban_user(self.organizer.pk, actor=self.organizer, reason='Selbstsperre')
        with self.assertRaises(UserBanError):
            ban_user(self.organizer.pk, actor=self.staff, reason='Privilegiertes Konto')
        with self.assertRaises(UserBanError):
            ban_user(self.user.pk, actor=self.organizer, reason=' ')
        ban_user(self.user.pk, actor=self.staff, reason='Berechtigte Orga')

    def test_old_unlock_action_and_stale_user_save_cannot_reactivate(self):
        old = User.objects.get(pk=self.user.pk)
        self.ban()
        old.is_active = True
        old.save()
        old.reset_lockout()
        old.refresh_from_db()
        self.assertTrue(old.is_banned)
        self.assertFalse(old.is_active)
        self.assertIsNone(authenticate(username=old.username, password='Password123!'))

    def test_stale_ban_form_does_not_suspend_changed_identity(self):
        state = ban_state(self.user)
        self.user.email = 'changed@example.com'
        self.user.save()
        with self.assertRaises(UserBanError):
            self.ban(expected_state=state)
        self.assertFalse(UserBan.objects.exists())

    def test_tickets_and_short_code_checkin_are_blocked_after_unban_old_qr_stays_invalid(self):
        old_token = self.registration.checkin_token
        ban = self.ban()
        self.assertFalse(self.registration.can_check_in().allowed)
        for action in (lambda: self.registration.check_in(), lambda: CheckInService.check_in(self.registration.pk)):
            with self.assertRaises(ValidationError):
                action()
        self.client.force_login(self.organizer)
        self.assertEqual(self.client.get(reverse('process_checkin', args=[self.registration.pk, old_token])).status_code, 404)
        revoke_ban(ban.pk, actor=self.organizer, reason='Aufheben')
        self.registration.refresh_from_db()
        self.assertNotEqual(old_token, self.registration.checkin_token)
        self.assertTrue(self.registration.can_check_in().allowed)

    def test_event_registration_rejects_stale_user(self):
        self.ban()
        from events.exceptions import RegistrationError
        with self.assertRaises(RegistrationError):
            RegistrationService.register_user(self.user, self.event.pk)

    def test_old_registration_and_email_change_codes_cannot_activate_banned_user(self):
        registration_code = EmailVerificationCode.generate_for_user(self.user, enforce_cooldown=False)
        email_code = EmailVerificationCode.generate_for_user(self.user, new_email='change@example.com', enforce_cooldown=False)
        self.ban()
        self.assertEqual(UserService.verify_registration_code(self.user, registration_code.code)[0], 'invalid_or_expired')
        self.assertEqual(UserService.confirm_email_change(self.user, email_code.code)[0], 'invalid_or_expired')
        with self.assertRaises(ValidationError):
            UserService.resend_registration_code(self.user)
        self.assertFalse(is_email_banned('change@example.com'))

    def test_email_changes_to_banned_address_are_rejected(self):
        ban_email('excluded@example.com', actor=self.organizer, reason='Bekannte Adresse')
        form = UserProfileForm({'email': 'excluded@example.com', 'birthday': '2000-01-01'}, instance=self.user)
        self.assertFalse(form.is_valid())
        with self.assertRaises(ValidationError):
            UserService.request_email_change(self.user, 'excluded@example.com')

    def test_password_reset_tokens_invalidated_without_changing_password(self):
        token = default_token_generator.make_token(self.user)
        ban = self.ban()
        self.user.refresh_from_db()
        from users.tokens import password_reset_token_generator
        self.assertFalse(password_reset_token_generator.check_token(self.user, token))
        self.assertTrue(self.user.is_banned)
        with patch('emails.services.queue_system_email') as mail:
            response = self.client.post(reverse('password_reset'), {'email': self.user.email})
        self.assertEqual(response.status_code, 302)
        mail.assert_not_called()
        revoke_ban(ban.pk, actor=self.organizer, reason='Aufheben')
        self.user.refresh_from_db()
        self.assertFalse(password_reset_token_generator.check_token(self.user, token))

    def test_backend_action_confirmation_history_and_readonly_list(self):
        self.client.force_login(self.organizer)
        url = reverse('admin:users_user_moderation', args=[self.user.pk])
        response = self.client.get(url)
        self.assertContains(response, tr('ban_confirm'))
        self.assertFalse(UserBan.objects.exists())
        state = ban_state(self.user)
        response = self.client.post(url, {'action': 'ban', 'reason': 'Backend-Test', 'expected_state': state})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserBanLog.objects.get().reason, 'Backend-Test')
        response = self.client.get(reverse('admin:users_userban_changelist'))
        self.assertContains(response, 'Bekannte E-Mail-Adresse sperren')
        ban_admin = admin.site._registry[UserBan]
        self.assertFalse(ban_admin.has_delete_permission(response.wsgi_request))
        self.assertFalse(ban_admin.has_change_permission(response.wsgi_request))

    def test_backend_csrf_and_missing_permission(self):
        url = reverse('admin:users_user_moderation', args=[self.user.pk])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.organizer)
        self.assertEqual(secure.post(url, {'action': 'ban', 'reason': 'Test'}).status_code, 403)
        self.assertFalse(UserBan.objects.exists())

    def test_backend_manual_identity_and_revocation(self):
        self.client.force_login(self.organizer)
        response = self.client.post(reverse('admin:users_userban_email'), {
            'email': 'additional@example.com', 'reason': 'Bekannte zusätzliche Adresse'})
        self.assertEqual(response.status_code, 302)
        ban = UserBan.objects.get()
        self.assertTrue(is_email_banned('additional@example.com'))
        response = self.client.post(reverse('admin:users_userban_revoke', args=[ban.pk]),
            {'reason': 'Überprüfung abgeschlossen'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(is_email_banned('additional@example.com'))
        self.assertEqual(list(ban.logs.values_list('action', flat=True)), ['UNBAN', 'BAN'])

    def test_banned_organizer_cannot_use_a_stale_actor_object(self):
        original_actor = User.objects.get(pk=self.staff.pk)
        ban_user(self.staff.pk, actor=self.organizer, reason='Mitarbeiter gesperrt')
        with self.assertRaises(PermissionDenied):
            ban_user(self.user.pk, actor=original_actor, reason='Veralteter Zugriff')
        self.assertFalse(UserBan.objects.filter(user=self.user).exists())
