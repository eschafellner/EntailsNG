from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import NewsArticle


class NewsXSSRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.editor = get_user_model().objects.create_user('review-news-editor', is_staff=True)
        self.editor.user_permissions.add(Permission.objects.get(codename='add_newsarticle'))

    def test_editor_admin_post_preserves_safe_image_and_removes_executable_html(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse('admin:news_newsarticle_add'), {
            'title': 'Review News', 'content': '<p>News<img src="/media/lan.png" onerror="alert(1)" alt="LAN"></p><script>alert(2)</script>',
            'image_fit': 'cover', 'is_published': 'on', '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        article = NewsArticle.objects.get(title='Review News')
        self.assertNotIn('onerror', article.content)
        self.assertNotIn('<script', article.content)
        self.client.logout()
        for name, args in [('news_list', []), ('news_detail', [article.pk])]:
            response = self.client.get(reverse(name, args=args))
            self.assertContains(response, 'src="/media/lan.png"')
            self.assertNotContains(response, 'onerror')
            self.assertNotContains(response, '<script>alert')

    def test_legacy_rows_and_text_fragment_payloads_are_safe_at_output(self):
        article = NewsArticle.objects.create(title='Legacy', content='Initial')
        for payload in ['<p>Safe</p><img src=x onerror=alert(1)>', '<<x><<x>x>img src=x onerror=alert(1)>',
                        '<svg onload=alert(1)>', '<img src="data:text/html,unsafe">']:
            NewsArticle.objects.filter(pk=article.pk).update(content=payload)
            response = self.client.get(reverse('news_detail', args=[article.pk]))
            self.assertNotContains(response, '<img src=x onerror')
            self.assertNotContains(response, '<img src="x" onerror')
            self.assertNotContains(response, '<svg onload')
            self.assertNotContains(response, 'src="data:')
