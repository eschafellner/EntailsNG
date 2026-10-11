from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import EventInfo


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class InfoContentSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.editor = get_user_model().objects.create_user('review-info-editor', is_staff=True)
        self.editor.user_permissions.add(Permission.objects.get(codename='add_eventinfo'))

    def test_editor_admin_post_is_safe_through_public_render(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('admin:info_eventinfo_add'), {
            'title': 'Review Page', 'slug': 'review-page', 'page_type': 'TEXT',
            'content': '<p>Welcome</p><<x><<x>x>img src=x onerror=alert(1)>',
            'embed_profile': 'GALLERY', 'embed_height': 800, 'embed_wide': 'on',
            'order': 0, 'nav_icon': 'info', 'is_active': 'on', '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        page = EventInfo.objects.get(slug='review-page')
        self.assertNotIn('<img', page.content)
        self.client.logout()
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, '<p>Welcome</p>', html=True)
        self.assertNotContains(response, '<img')

    def test_existing_unsanitized_content_is_safe_without_resaving(self):
        page = EventInfo.objects.create(title='Legacy', slug='legacy-review', is_active=True)
        EventInfo.objects.filter(pk=page.pk).update(content='<img src=x onerror=alert(1)><p>Legacy</p>')
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, '<p>Legacy</p>', html=True)
        self.assertNotContains(response, '<img')
