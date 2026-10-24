from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, RequestFactory
from django.urls import reverse

from .models import GeneralConfiguration, SiteCustomization, ClanSeatConfiguration
from .sanitizer import sanitize_html
from .themes import build_css_variables


class SanitizerAndColorRegressionTests(SimpleTestCase):
    def test_text_fragments_cannot_reconstruct_tags_even_after_repeated_sanitizing(self):
        for payload in ['<<x>img src=x onerror=alert(1)>', '<<x><<x>x>img src=x onerror=alert(1)>',
                        '<<x>svg onload=alert(1)>', '&lt;img src=x onerror=alert(1)&gt;']:
            cleaned = sanitize_html(payload)
            self.assertNotIn('<img', cleaned)
            self.assertNotIn('<svg', cleaned)
            self.assertEqual(sanitize_html(cleaned), cleaned)

    def test_short_hex_and_alpha_colors_have_consistent_theme_calculations(self):
        short = build_css_variables('WARM_AMBER', 'MD', primary_color='#fff', secondary_color='#000', background_color='#000')
        full = build_css_variables('WARM_AMBER', 'MD', primary_color='#ffffff', secondary_color='#000000', background_color='#000000')
        self.assertEqual('#' + ''.join(c * 2 for c in short['--signal-ink'][1:]), full['--signal-ink'])
        self.assertEqual(short['--warning-text'], full['--warning-text'])
        alpha = build_css_variables('WARM_AMBER', 'MD', primary_color='#ffffff00', secondary_color='#000000ff', background_color='#000000ff')
        self.assertEqual(alpha['--signal-ink'], '#ffffff')
        self.assertEqual(alpha['--warning-text'], short['--warning-text'])

    def test_small_accent_text_follows_paper_brightness(self):
        light = build_css_variables('WARM_AMBER', 'MD')
        dark = build_css_variables('CYBERPUNK', 'MD')
        self.assertEqual(light['--eyebrow-color'], 'var(--signal-deep)')
        self.assertEqual(dark['--eyebrow-color'], 'var(--signal)')
        self.assertEqual(light['--seat-key-pre'], '#a16207')
        self.assertEqual(dark['--seat-key-pre'], '#eab308')


class SingletonAndLegacyContentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = get_user_model().objects.create_user('review-config-staff', is_staff=True)

    def test_all_singleton_add_permissions_require_model_permission(self):
        for model in [GeneralConfiguration, SiteCustomization, ClanSeatConfiguration]:
            model.objects.all().delete()
            request = RequestFactory().get('/admin/')
            request.user = self.staff
            self.assertFalse(admin.site._registry[model].has_add_permission(request))
            permission = Permission.objects.get(content_type__app_label=model._meta.app_label,
                                                 codename=f'add_{model._meta.model_name}')
            self.staff.user_permissions.add(permission)
            request.user = get_user_model().objects.get(pk=self.staff.pk)
            self.assertTrue(admin.site._registry[model].has_add_permission(request))

    def test_legacy_legal_content_is_sanitized_at_render(self):
        custom = SiteCustomization.objects.create()
        SiteCustomization.objects.filter(pk=custom.pk).update(impressum_content='<script>alert(1)</script><p>Legal</p>')
        response = self.client.get(reverse('impressum'))
        self.assertContains(response, '<p>Legal</p>', html=True)
        self.assertNotContains(response, '<script>alert(1)</script>')
