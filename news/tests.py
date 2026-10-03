from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from news.models import NewsArticle


class NewsViewTests(TestCase):

    def setUp(self):
        self.article = NewsArticle.objects.create(
            title='Willkommen zur LAN',
            content='Das ist der erste News-Beitrag.',
            is_published=True,
        )

    def test_news_list_view(self):
        response = self.client.get(reverse('news_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Willkommen zur LAN')
        self.assertEqual(len(response.context['articles']), 1)

    def test_news_list_renders_rich_text(self):
        self.article.content = '<h2>LAN-Start</h2><p><strong>Freitag</strong></p><ul><li>Check-in</li></ul>'
        self.article.save()

        response = self.client.get(reverse('news_list'))

        self.assertContains(response, self.article.content, html=True)
        self.assertNotContains(response, '&lt;strong&gt;')

    def test_news_list_preserves_plain_text_line_breaks_and_escaping(self):
        self.article.content = 'Check-in & Tickets\nab 18 Uhr\n\nTurniere: 5 < 10'
        self.article.save()

        response = self.client.get(reverse('news_list'))

        self.assertContains(response, '<p>Check-in &amp; Tickets<br>ab 18 Uhr</p>', html=True)
        self.assertContains(response, '<p>Turniere: 5 &lt; 10</p>', html=True)


class NewsAdminTests(TestCase):

    def test_create_and_edit_rich_text_article(self):
        user = get_user_model().objects.create_superuser(
            username='news-admin', email='news-admin@example.com', password='test-password',
        )
        self.client.force_login(user)
        add_url = reverse('admin:news_newsarticle_add')
        response = self.client.get(add_url)
        self.assertContains(response, '/static/tinymce/tinymce.min.js')
        self.assertContains(response, '/static/django_tinymce/init_tinymce.js')
        self.assertEqual(response.context['adminform'].form.fields['content'].widget.get_mce_config(
            {'id': 'id_content'},
        )['license_key'], 'gpl')

        content = '<p><strong>Willkommen</strong> zur LAN!</p>'
        response = self.client.post(add_url, {
            'title': 'LAN-News', 'content': content, 'is_published': 'on', '_save': 'Speichern',
        })
        self.assertEqual(response.status_code, 302)
        article = NewsArticle.objects.get(title='LAN-News')
        self.assertEqual(article.content, content)
        self.assertEqual(article.author, user)

        change_url = reverse('admin:news_newsarticle_change', args=[article.pk])
        response = self.client.get(change_url)
        self.assertEqual(response.context['adminform'].form.initial['content'], content)
        self.assertContains(response, '/static/tinymce/tinymce.min.js')

        updated_content = '<h2>Update</h2><p><em>Einlass ab 18 Uhr.</em></p>'
        response = self.client.post(change_url, {
            'title': article.title, 'content': updated_content, 'is_published': 'on', '_save': 'Speichern',
        })
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.content, updated_content)
        self.assertEqual(article.author, user)
        response = self.client.get(reverse('news_list'))
        self.assertContains(response, updated_content, html=True)


class NewsServiceTests(TestCase):

    def setUp(self):
        self.a1 = NewsArticle.objects.create(title='News 1', content='C1', is_published=True)
        self.a2 = NewsArticle.objects.create(title='News 2', content='C2', is_published=True, is_pinned=True)
        self.a3 = NewsArticle.objects.create(title='News 3 Draft', content='C3', is_published=False)

    def test_get_latest_news_only_returns_published(self):
        from news.services import get_latest_news
        news = get_latest_news(limit=10)
        titles = [n.title for n in news]
        self.assertIn('News 1', titles)
        self.assertIn('News 2', titles)
        self.assertNotIn('News 3 Draft', titles)

    def test_get_pinned_news(self):
        from news.services import get_pinned_news
        pinned = get_pinned_news()
        self.assertIsNotNone(pinned)
        self.assertEqual(pinned.title, 'News 2')

    def test_get_all_published_news(self):
        from news.services import get_all_published_news
        all_news = list(get_all_published_news())
        self.assertEqual(len(all_news), 2)
        # Angepinnte News muss an erster Stelle stehen
        self.assertEqual(all_news[0].title, 'News 2')

    def test_get_latest_news_respects_ordering_by_pinned_and_date(self):
        """Testet, dass get_latest_news nach -is_pinned, -created_at sortiert statt nach -id."""
        from news.services import get_latest_news
        news = get_latest_news(limit=2)
        # News 2 ist angepinnt -> muss an erster Stelle sein
        self.assertEqual(news[0].title, 'News 2')
        self.assertEqual(news[1].title, 'News 1')

