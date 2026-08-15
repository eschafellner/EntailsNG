from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from users.forms import CustomUserCreationForm

User = get_user_model()


class UserModelTests(TestCase):

    def test_create_user(self):
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='Password123!',
            birthday=date(2000, 1, 1),
        )
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.role, User.Roles.USER)
        self.assertEqual(user.birthday, date(2000, 1, 1))
        self.assertIn('testuser', str(user))


class RegistrationViewTests(TestCase):

    def test_registration_page_get(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'auth/register.html')
        self.assertIsInstance(response.context['form'], CustomUserCreationForm)

    def test_registration_page_post_success(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'newuser',
                'email': 'newuser@example.com',
                'birthday': '2000-05-15',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )
        self.assertRedirects(response, reverse('verify_email'))
        self.assertTrue(User.objects.filter(username='newuser').exists())
        user = User.objects.get(username='newuser')
        self.assertFalse(user.is_active)  # Inaktiv bis zur Double Opt-In Verifizierung!
        self.assertTrue(user.verification_codes.exists())


class DoubleOptInTests(TestCase):

    def setUp(self):
        self.client.post(
            reverse('register'),
            {
                'username': 'optuser',
                'email': 'opt@example.com',
                'birthday': '1998-04-10',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )
        self.user = User.objects.get(username='optuser')
        self.code_obj = self.user.verification_codes.first()

    def test_verify_email_get(self):
        response = self.client.get(reverse('verify_email'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'auth/verify_email.html')

    def test_verify_email_post_success(self):
        response = self.client.post(
            reverse('verify_email'),
            {'code': self.code_obj.code},
        )
        self.assertRedirects(response, reverse('dashboard'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.code_obj.refresh_from_db()
        self.assertTrue(self.code_obj.is_used)

    def test_verify_email_post_invalid_code(self):
        response = self.client.post(
            reverse('verify_email'),
            {'code': '000000'},
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.code_obj.refresh_from_db()
        self.assertEqual(self.code_obj.failed_attempts, 1)

    def test_verify_email_brute_force_lockout_after_5_attempts(self):
        # 5 falsche Versuche durchführen
        for i in range(5):
            response = self.client.post(
                reverse('verify_email'),
                {'code': f'99999{i}'},
            )
            self.assertEqual(response.status_code, 200)

        self.code_obj.refresh_from_db()
        self.assertEqual(self.code_obj.failed_attempts, 5)
        self.assertTrue(self.code_obj.is_used)  # Code gesperrt/entwertet

        # Selbst mit dem korrekten Code schlägt die Verifizierung nun fehl
        response = self.client.post(
            reverse('verify_email'),
            {'code': self.code_obj.code},
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_resend_code_cooldown(self):
        # Versuche sofort erneut einen Code zu senden
        response = self.client.post(reverse('resend_verification_code'))
        self.assertRedirects(response, reverse('verify_email'))
        # Da Cooldown aktiv, wurde kein neuer Code erzeugt
        self.assertEqual(self.user.verification_codes.count(), 1)



class PasswordResetTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='resetuser',
            email='reset@example.com',
            password='Password123!',
        )

    def test_password_reset_get(self):
        response = self.client.get(reverse('password_reset'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'auth/password_reset.html')

    def test_password_reset_post(self):
        response = self.client.post(
            reverse('password_reset'),
            {'email': 'reset@example.com'},
        )
        self.assertRedirects(response, reverse('password_reset_done'))


class ProfileViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='profuser',
            email='old@example.com',
            password='OldPassword123!',
            birthday=date(1995, 3, 10),
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 302)

    def test_profile_get(self):
        self.client.login(username='profuser', password='OldPassword123!')
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/profile.html')
        self.assertContains(response, 'profuser')

    def test_update_profile(self):
        self.client.login(username='profuser', password='OldPassword123!')
        response = self.client.post(
            reverse('profile'),
            {
                'update_profile': '1',
                'email': 'new@example.com',
                'birthday': '1995-03-12',
            },
        )
        self.assertRedirects(response, reverse('profile'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertEqual(self.user.birthday, date(1995, 3, 12))

    def test_change_password(self):
        self.client.login(username='profuser', password='OldPassword123!')
        response = self.client.post(
            reverse('profile'),
            {
                'change_password': '1',
                'old_password': 'OldPassword123!',
                'new_password1': 'BrandNewPass123!',
                'new_password2': 'BrandNewPass123!',
            },
        )
        self.assertRedirects(response, reverse('profile'))
        self.client.logout()
        # Verify user can login with new password
        login_success = self.client.login(username='profuser', password='BrandNewPass123!')
        self.assertTrue(login_success)


class AuthBackendAndLockoutTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='authuser',
            email='authuser@example.com',
            password='CorrectPassword123!',
        )

    def test_login_via_username(self):
        login_success = self.client.login(username='authuser', password='CorrectPassword123!')
        self.assertTrue(login_success)

    def test_login_via_email(self):
        login_success = self.client.login(username='authuser@example.com', password='CorrectPassword123!')
        self.assertTrue(login_success)

    def test_unique_email_registration(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'anotheruser',
                'email': 'authuser@example.com',  # Bereits vergeben!
                'birthday': '2000-01-01',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'],
            'email',
            'Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet.',
        )

    def test_account_lockout_after_5_failed_attempts(self):
        # 4 fehlgeschlagene Logins durchführen
        for _ in range(4):
            self.client.login(username='authuser', password='WrongPassword')
            self.user.refresh_from_db()
            self.assertEqual(self.user.failed_login_attempts, _ + 1)
            self.assertFalse(self.user.is_locked())

        # 5. fehlgeschlagener Versuch -> Konto wird für 15 Minuten gesperrt
        response = self.client.post(
            reverse('login'),
            {'username': 'authuser', 'password': 'WrongPassword'},
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 5)
        self.assertTrue(self.user.is_locked())

        # Selbst mit richtigem Passwort schlägt der Login während der Sperre fehl
        login_during_lock = self.client.login(username='authuser', password='CorrectPassword123!')
        self.assertFalse(login_during_lock)

    def test_lockout_auto_reset_on_expiration(self):
        from datetime import timedelta
        from django.utils import timezone
        self.user.failed_login_attempts = 5
        self.user.locked_until = timezone.now() - timedelta(minutes=1)  # Abgelaufen!
        self.user.save()

        # is_locked() muss False liefern und den Zähler automatisch zurücksetzen
        self.assertFalse(self.user.is_locked())
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertIsNone(self.user.locked_until)

    def test_admin_unlock_action(self):
        from datetime import timedelta
        from django.utils import timezone
        from users.admin import CustomUserAdmin

        self.user.failed_login_attempts = 5
        self.user.locked_until = timezone.now() + timedelta(minutes=15)
        self.user.save()

        # Admin reset_lockout aufrufen
        self.user.reset_lockout()
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertFalse(self.user.is_locked())

    def test_ip_rate_limiting_25_attempts(self):
        from django.core.cache import cache
        from users.auth_backends import _record_ip_failed_attempt
        cache.clear()

        # 25 Fehlversuche für IP registrieren
        for _ in range(25):
            _record_ip_failed_attempt('192.168.1.100')

        # 26. Versuch löst IP-Rate-Limit aus und blockiert selbst korrekte Logins von dieser IP
        response = self.client.post(
            reverse('login'),
            {'username': 'authuser', 'password': 'CorrectPassword123!'},
            REMOTE_ADDR='192.168.1.100',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Zu viele fehlgeschlagene Anmeldeversuche')

        # Von einer anderen IP kann sich der User jedoch weiterhin normal einloggen!
        response_other_ip = self.client.post(
            reverse('login'),
            {'username': 'authuser', 'password': 'CorrectPassword123!'},
            REMOTE_ADDR='192.168.1.200',
        )
        self.assertEqual(response_other_ip.status_code, 302)

    def test_registration_rejects_non_4_digit_birthday_year(self):
        """Negativ-Test: Geburtsdatum mit nicht 4-stelligem Jahr wird von der Form abgewiesen."""
        # 1. 5-stelliges Jahr wird von Django DateField abgewiesen
        form1 = CustomUserCreationForm(data={
            'username': 'yearuser1',
            'email': 'year1@example.com',
            'birthday': '20005-01-01',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertFalse(form1.is_valid())
        self.assertIn('birthday', form1.errors)

        # 2. Unplausibles Jahr (< 1900 oder > 2099) wird von clean_birthday abgewiesen
        form2 = CustomUserCreationForm(data={
            'username': 'yearuser2',
            'email': 'year2@example.com',
            'birthday': '1850-01-01',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertFalse(form2.is_valid())
        self.assertIn('birthday', form2.errors)
        self.assertIn('4-stellig', str(form2.errors['birthday']))


    def test_profile_form_rejects_non_4_digit_birthday_year(self):
        """Negativ-Test: UserProfileForm lehnt unplausible/überlange Jahreszahlen ab."""
        from users.forms import UserProfileForm
        form = UserProfileForm(data={'email': 'update@example.com', 'birthday': '1850-01-01'}, instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('birthday', form.errors)


