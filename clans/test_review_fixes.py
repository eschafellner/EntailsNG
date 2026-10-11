from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .admin import ClanAdminForm
from .forms import ClanForm
from .models import Clan, ClanMembership


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ClanReviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_user('review-clan-admin')
        self.guest = get_user_model().objects.create_user('review-clan-guest')
        self.clan = Clan.objects.create(name='Review Clan', password='OriginalClan123!', seat_limit_override=2)
        ClanMembership.objects.create(user=self.admin, clan=self.clan, status='ACCEPTED', role='ADMIN')

    def tearDown(self):
        cache.clear()

    def test_password_attempts_are_limited_before_hash_comparison(self):
        self.client.force_login(self.guest)
        original = Clan.check_password
        with patch.object(Clan, 'check_password', autospec=True, side_effect=original) as comparison:
            for _ in range(8):
                self.client.post(reverse('clan_join_password', args=[self.clan.slug]), {'password': 'wrong'})
        self.assertEqual(comparison.call_count, 5)
        self.assertFalse(ClanMembership.objects.filter(user=self.guest).exists())

    def test_fresh_locked_form_preserves_quota_updated_after_initial_validation(self):
        self.client.force_login(self.admin)
        original = ClanForm.is_valid
        calls = 0
        def update_after_validation(form):
            nonlocal calls
            result = original(form)
            calls += 1
            if calls == 1:
                Clan.objects.filter(pk=self.clan.pk).update(seat_limit_override=7)
            return result
        with patch.object(ClanForm, 'is_valid', update_after_validation):
            response = self.client.post(reverse('clan_edit', args=[self.clan.slug]), {
                'name': 'Edited Clan', 'tag': 'RC', 'website': '', 'password': '',
            })
        self.assertEqual(response.status_code, 302)
        self.clan.refresh_from_db()
        self.assertEqual(self.clan.seat_limit_override, 7)
        self.assertEqual(self.clan.name, 'Edited Clan')

    def test_new_algorithm_prefix_password_is_hashed_in_frontend_and_admin_forms(self):
        for form_class in [ClanForm, ClanAdminForm]:
            self.clan.refresh_from_db()
            form = form_class(data={'name': self.clan.name, 'tag': '', 'website': '',
                                    'password': 'argon2Secret123', 'slug': self.clan.slug,
                                    'seat_limit_override': 2}, instance=self.clan)
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
            self.clan.refresh_from_db()
            self.assertNotEqual(self.clan.password, 'argon2Secret123')
            self.assertTrue(self.clan.check_password('argon2Secret123'))

    def test_blank_edit_keeps_hash_and_new_weak_password_is_rejected(self):
        original = self.clan.password
        form = ClanForm(data={'name': self.clan.name, 'tag': '', 'website': '', 'password': ''}, instance=self.clan)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(self.clan.password, original)
        form = ClanForm(data={'name': self.clan.name, 'tag': '', 'website': '', 'password': '123'}, instance=self.clan)
        self.assertFalse(form.is_valid())
        self.assertIn('password', form.errors)

    def test_model_does_not_treat_raw_algorithm_prefix_as_hash(self):
        for index, password in enumerate(['argon2Secret123', 'scryptSecret123', 'pbkdf2_sha256$invalid']):
            clan = Clan.objects.create(name=f'Review prefix {index}', password=password)
            self.assertNotEqual(clan.password, password)
            self.assertTrue(clan.check_password(password))
