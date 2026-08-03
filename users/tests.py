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
        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(User.objects.filter(username='newuser').exists())
        user = User.objects.get(username='newuser')
        self.assertEqual(user.birthday, date(2000, 5, 15))


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
