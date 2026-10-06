from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import modelform_factory
from django.test import TestCase, override_settings
from django.urls import reverse

from configuration.models import NavigationItem
from info.embedding import https_origin
from info.models import EmbedProvider, EventInfo


class ExternalEmbeddingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.provider = EmbedProvider.objects.create(name='Galerie', origin='https://gallery.example.com')
        cls.user = get_user_model().objects.create_user(username='viewer', email='viewer@example.com')
        cls.admin = get_user_model().objects.create_superuser(username='editor', email='editor@example.com')

    def page(self, **kwargs):
        values = dict(title='Bilder & Galerie', slug='gallery', page_type=EventInfo.PageType.EMBED,
                      embed_provider=self.provider, embed_url='https://gallery.example.com/album?sort=date&view=grid')
        values.update(kwargs)
        return EventInfo.objects.create(**values)

    def test_gallery_loads_directly_with_safe_attributes_and_fallback(self):
        page = self.page(content='<p>Fotos der LAN</p>')
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, '<iframe ')
        self.assertContains(response, 'src="https://gallery.example.com/album?sort=date&amp;view=grid"')
        self.assertContains(response, 'title="Bilder &amp; Galerie"')
        self.assertContains(response, 'sandbox="allow-scripts allow-same-origin allow-downloads"')
        self.assertContains(response, 'allow="fullscreen"')
        self.assertContains(response, 'referrerpolicy="no-referrer"')
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertContains(response, 'Externe Seite separat öffnen')
        self.assertContains(response, 'Fotos der LAN')
        self.assertNotContains(response, 'keine Informationen hinterlegt')
        self.assertEqual(response.headers['Content-Security-Policy'],
                         "frame-src https://gallery.example.com; object-src 'none'")
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')

    def test_root_renders_embed_and_applies_frame_policy(self):
        self.page()
        response = self.client.get(reverse('event_info_detail'))
        self.assertContains(response, '<iframe ')
        self.assertIn('https://gallery.example.com', response.headers['Content-Security-Policy'])

    def test_static_profile_and_standard_width(self):
        page = self.page(embed_profile=EventInfo.EmbedProfile.STATIC, embed_wide=False, embed_height=480)
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, 'sandbox=""')
        self.assertNotContains(response, 'allow="fullscreen"')
        self.assertContains(response, 'max-width: 900px')
        self.assertContains(response, 'height: 480px')

    def test_login_required_protects_direct_url_and_menu(self):
        page = self.page(login_required=True, show_in_nav=True)
        self.assertEqual(page.nav_item.visibility, NavigationItem.Visibility.AUTHENTICATED)
        response = self.client.get(page.get_absolute_url())
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('Content-Security-Policy', response.headers)
        self.assertEqual(self.client.get(reverse('event_info_detail')).status_code, 302)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(page.get_absolute_url()), '<iframe ')
        page.login_required = False
        page.save()
        page.nav_item.refresh_from_db()
        self.assertEqual(page.nav_item.visibility, NavigationItem.Visibility.PUBLIC)

    def test_draft_and_navigation_lifecycle(self):
        page = self.page(is_active=False, show_in_nav=True)
        self.assertFalse(page.nav_item.is_active)
        self.assertEqual(self.client.get(page.get_absolute_url()).status_code, 404)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(page.get_absolute_url()), '<iframe ')
        page.is_active = True
        page.slug = 'photos'
        page.save()
        page.nav_item.refresh_from_db()
        self.assertTrue(page.nav_item.is_active)
        self.assertEqual(page.nav_item.url_name, '/info/photos/')

    def test_existing_staff_menu_restriction_is_preserved(self):
        page = self.page(show_in_nav=True)
        page.nav_item.visibility = NavigationItem.Visibility.STAFF
        page.nav_item.save()
        page.login_required = True
        page.save()
        page.nav_item.refresh_from_db()
        self.assertEqual(page.nav_item.visibility, NavigationItem.Visibility.STAFF)

    def test_unsafe_urls_are_rejected_by_direct_save(self):
        for url in ('http://gallery.example.com/', 'javascript:alert(1)', '//gallery.example.com/',
                    'https://user:pass@gallery.example.com/', 'https://evil.example.com/',
                    'https://gallery.example.com.evil.com/', 'https://gallery.example.com:8443/',
                    'https://gallery.example.com/\nfoo', 'https://gallery.example.com\\@evil.com/'):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                self.page(embed_url=url)

    def test_provider_requires_exact_https_origin(self):
        for origin in ('http://gallery.example.com', 'https://gallery.example.com/',
                       'https://gallery.example.com/path', 'https://gallery.example.com?x=1',
                       'https://user@gallery.example.com', 'https://gallery.example.com#fragment'):
            with self.subTest(origin=origin), self.assertRaises(ValidationError):
                EmbedProvider.objects.create(name='Bad', origin=origin)

    def test_origin_normalizes_default_port_and_hostname(self):
        self.assertEqual(https_origin('https://GALLERY.example.com:443/album'), self.provider.origin)
        provider = EmbedProvider.objects.create(name='Port', origin='https://gallery.example.com:8443')
        page = self.page(embed_provider=provider, embed_url='https://gallery.example.com:8443/')
        self.assertContains(self.client.get(page.get_absolute_url()), '<iframe ')

    def test_missing_provider_invalid_profile_and_height_are_rejected(self):
        for values in ({'embed_provider': None}, {'embed_url': ''}, {'embed_profile': 'unsafe'},
                       {'embed_height': 319}, {'embed_height': 2001}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.page(**values)

    def test_disabled_provider_revokes_existing_iframe_and_link(self):
        page = self.page()
        self.provider.is_active = False
        self.provider.save()
        response = self.client.get(page.get_absolute_url())
        self.assertNotContains(response, '<iframe')
        self.assertNotContains(response, 'href="https://gallery.example.com')
        self.assertContains(response, 'derzeit nicht freigegeben')
        self.assertEqual(response.headers['Content-Security-Policy'], "frame-src 'none'; object-src 'none'")

    def test_provider_origin_change_revokes_existing_iframe(self):
        page = self.page()
        self.provider.origin = 'https://other.example.com'
        self.provider.save()
        self.assertNotContains(self.client.get(page.get_absolute_url()), '<iframe')

    def test_bulk_written_untrusted_address_is_not_rendered(self):
        page = self.page()
        EventInfo.objects.filter(pk=page.pk).update(embed_url='https://evil.example.com/')
        response = self.client.get(page.get_absolute_url())
        self.assertNotContains(response, '<iframe')
        self.assertNotContains(response, 'https://evil.example.com')

    @override_settings(ALLOWED_HOSTS=['testserver.example.com'])
    def test_same_origin_embed_is_not_rendered(self):
        provider = EmbedProvider.objects.create(name='Own origin', origin='https://testserver.example.com')
        page = self.page(embed_provider=provider, embed_url='https://testserver.example.com/anything')
        response = self.client.get(page.get_absolute_url(), secure=True, HTTP_HOST='testserver.example.com')
        self.assertNotContains(response, '<iframe')
        self.assertEqual(response.headers['Content-Security-Policy'], "frame-src 'none'; object-src 'none'")

    def test_text_page_keeps_html_sanitizer_and_does_not_render_embed(self):
        page = EventInfo.objects.create(title='Info', slug='info',
                                       content='<p>Text</p><iframe src="https://gallery.example.com"></iframe>',
                                       embed_provider=self.provider, embed_url='https://gallery.example.com/')
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, '<p>Text</p>')
        self.assertNotContains(response, '<iframe')
        self.assertNotIn('Content-Security-Policy', response.headers)

    def test_admin_form_allows_embed_without_text_and_requires_text_for_text_page(self):
        form_class = modelform_factory(EventInfo, fields=[
            'title', 'slug', 'content', 'page_type', 'embed_provider', 'embed_url',
            'embed_profile', 'embed_height', 'embed_wide',
        ])
        data = {'title': 'Gallery', 'slug': 'gallery', 'page_type': 'EMBED',
                'embed_provider': self.provider.pk, 'embed_url': 'https://gallery.example.com/',
                'embed_profile': 'GALLERY', 'embed_height': 800, 'embed_wide': True, 'content': ''}
        form = form_class(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        data['page_type'] = 'TEXT'
        form = form_class(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('content', form.errors)

    def test_admin_can_create_embedding_page(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin:info_eventinfo_add'), {
            'title': 'Gallery', 'slug': 'admin-gallery', 'page_type': 'EMBED', 'content': '',
            'embed_provider': self.provider.pk, 'embed_url': 'https://gallery.example.com/',
            'embed_profile': 'GALLERY', 'embed_height': 800, 'embed_wide': 'on',
            'order': 1, 'is_active': 'on', 'show_in_nav': 'on', 'nav_icon': 'info', '_save': 'Speichern',
        })
        self.assertEqual(response.status_code, 302)
        page = EventInfo.objects.get(slug='admin-gallery')
        self.assertTrue(page.is_embed)
        self.assertEqual(page.nav_item.url_name, '/info/admin-gallery/')

    def test_invalid_admin_height_returns_form_error(self):
        self.client.force_login(self.admin)
        for height in ('', 'invalid', '319', '2001'):
            with self.subTest(height=height):
                response = self.client.post(reverse('admin:info_eventinfo_add'), {
                    'title': 'Gallery', 'slug': 'bad-gallery', 'page_type': 'EMBED',
                    'embed_provider': self.provider.pk, 'embed_url': 'https://gallery.example.com/',
                    'embed_profile': 'GALLERY', 'embed_height': height,
                    'order': 1, 'nav_icon': 'info', '_save': 'Speichern',
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn('embed_height', response.context['adminform'].form.errors)
