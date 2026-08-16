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

