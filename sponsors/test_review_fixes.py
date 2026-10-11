from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from sponsors.models import Sponsor
from sponsors.tests import create_dummy_image


class SponsorReviewTests(TestCase):
    def test_delegated_editor_html_is_sanitized_before_storage(self):
        editor = get_user_model().objects.create_user('sponsor-editor', is_staff=True)
        editor.user_permissions.add(Permission.objects.get(codename='add_sponsor'))
        self.client.force_login(editor)
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse('admin:sponsors_sponsor_add'), {
                'name': 'Reviewed sponsor', 'logo_typ': 'logo', 'bild': create_dummy_image(),
                'aktiv_modus': 'dauerhaft', 'rang': 100,
                'beschreibung': '<p onclick="alert(1)">Sponsor</p><script>alert(2)</script>'
                                '<a href="javascript:alert(3)">Link</a><img src=x onerror=alert(4)>',
            })
            self.assertEqual(response.status_code, 302)
            sponsor = Sponsor.objects.get(name='Reviewed sponsor')
            for forbidden in ('onclick', 'onerror', '<script', 'javascript:'):
                self.assertNotIn(forbidden, sponsor.beschreibung)
            self.assertIn('<p>Sponsor</p>', sponsor.beschreibung)
            self.assertNotContains(self.client.get(reverse('sponsor_list')), 'onerror')

    def test_legacy_html_is_sanitized_before_all_truncation_variants(self):
        for logo_typ in ('logo', 'banner'):
            sponsor = Sponsor.objects.create(name=f'Old {logo_typ}', bild='sponsors/old.png', logo_typ=logo_typ)
            for size in (0, 600, 1600):
                raw = '<p>' + 'x' * size + '</p><img src=x onerror="alert(1)"><script>LEGACY_XSS</script>'
                Sponsor.objects.filter(pk=sponsor.pk).update(beschreibung=raw)
                response = self.client.get(reverse('sponsor_list'))
                self.assertNotContains(response, 'onerror')
                self.assertNotContains(response, 'LEGACY_XSS')
                sponsor.refresh_from_db()
                sponsor.save()
                self.assertNotIn('onerror', sponsor.beschreibung)
