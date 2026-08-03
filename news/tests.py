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
