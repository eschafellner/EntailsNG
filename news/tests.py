from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from news.models import NewsArticle

PUBLISH_NOW = {'publish_at_0': '2026-01-01', 'publish_at_1': '12:00:00'}


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
            'title': 'LAN-News', 'content': content, 'image_fit': 'cover', 'is_published': 'on', '_save': 'Speichern', **PUBLISH_NOW,
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
            'title': article.title, 'content': updated_content, 'image_fit': 'cover', 'is_published': 'on', '_save': 'Speichern', **PUBLISH_NOW,
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
        """Testet, dass get_latest_news nach -is_pinned, -publish_at sortiert statt nach -id."""
        from news.services import get_latest_news
        news = get_latest_news(limit=2)
        # News 2 ist angepinnt -> muss an erster Stelle sein
        self.assertEqual(news[0].title, 'News 2')
        self.assertEqual(news[1].title, 'News 1')


class NewsCarouselTests(TestCase):
    def test_pinned_banner_without_event_is_not_duplicated_and_links_to_article(self):
        pinned = NewsArticle.objects.create(title='Kritische Durchsage', content='Einlass verschoben', is_pinned=True)
        other = NewsArticle.objects.create(title='Turnierstart', content='Ab 20 Uhr')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['pinned_news'], pinned)
        self.assertEqual(response.context['latest_news'], [other])
        self.assertContains(response, 'Kritische Durchsage', count=1)
        self.assertContains(response, reverse('news_detail', args=[pinned.pk]))
        self.assertContains(response, reverse('news_detail', args=[other.pk]))
        self.assertNotContains(response, 'data-news-next')

    def test_dashboard_shows_five_other_articles_and_no_drafts(self):
        pinned = NewsArticle.objects.create(title='Hinweis', content='C', is_pinned=True)
        articles = [NewsArticle.objects.create(title=f'News {i}', content='C') for i in range(7)]
        NewsArticle.objects.create(title='Geheimer Entwurf', content='C', is_published=False)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual([a.pk for a in response.context['latest_news']], [a.pk for a in articles[::-1][:5]])
        self.assertNotIn(pinned, response.context['latest_news'])
        self.assertNotContains(response, 'Geheimer Entwurf')
        self.assertContains(response, 'data-news-next')
        self.assertContains(response, '1 von 5')

    def test_only_pinned_news_keeps_banner_and_empty_carousel(self):
        NewsArticle.objects.create(title='Wichtiger Hinweis', content='C', is_pinned=True)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Wichtiger Hinweis')
        self.assertEqual(response.context['latest_news'], [])
        self.assertNotContains(response, 'data-news-track')

    def test_cover_image_overrides_embedded_image_and_uses_description(self):
        article = NewsArticle.objects.create(
            title='LAN', content='<p>Hallo<img src="/media/old.png" alt="Alt"></p>',
            cover_image='news/cover.webp', cover_image_alt='Turnierbühne', image_fit='contain',
        )
        for name, args in [('dashboard', []), ('news_list', []), ('news_detail', [article.pk])]:
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=args))
                self.assertContains(response, '/media/news/cover.webp')
                self.assertContains(response, 'alt="Turnierbühne"')
                self.assertContains(response, 'news-image-contain')

    def test_existing_local_content_image_becomes_preview_without_duplicate_in_detail(self):
        article = NewsArticle.objects.create(title='Altbestand', content='<p><img src="/media/lan.png" alt="Halle">LAN</p>')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'src="/media/lan.png"', count=1)
        self.assertContains(response, 'alt="Halle"')
        response = self.client.get(reverse('news_detail', args=[article.pk]))
        self.assertContains(response, 'src="/media/lan.png"', count=1)

    def test_news_detail_hides_unpublished_articles_even_from_staff(self):
        article = NewsArticle.objects.create(title='Entwurf', content='Privat', is_published=False)
        self.assertEqual(self.client.get(reverse('news_detail', args=[article.pk])).status_code, 404)
        user = get_user_model().objects.create_superuser('preview-admin', 'preview@example.com', 'test-password')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('news_detail', args=[article.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('news_detail', args=[999999])).status_code, 404)

    def test_news_detail_renders_existing_rich_text_and_plain_text(self):
        article = NewsArticle.objects.create(title='Beitrag', content='<p><strong>Formatierter Text</strong></p>')
        response = self.client.get(reverse('news_detail', args=[article.pk]))
        self.assertContains(response, article.content, html=True)
        article.content = 'Tickets & Check-in\nab 18 Uhr'
        article.save()
        response = self.client.get(reverse('news_detail', args=[article.pk]))
        self.assertContains(response, '<p>Tickets &amp; Check-in<br>ab 18 Uhr</p>', html=True)

    def test_image_fallback_rejects_external_and_unsafe_urls(self):
        from news.images import get_embedded_image
        for source in ['https://tracker.example/a.png', '//tracker.example/a.png', 'data:image/png;base64,x',
                       'javascript:alert(1)', '/\\tracker.example/a.png', 'https://[invalid/a.png']:
            with self.subTest(source=source):
                self.assertIsNone(get_embedded_image(f'<img src="{source}">'))
        self.assertEqual(get_embedded_image('<img src="media/a.png?a=1&amp;b=2" alt="LAN &amp; Party">'),
                         {'url': '/media/a.png?a=1&b=2', 'alt': 'LAN & Party'})

    def test_preview_preserves_word_boundaries_and_decodes_entities_as_text(self):
        article = NewsArticle.objects.create(title='Text', content='<p>Tickets &amp; Check-in</p><p>&lt;18 Uhr&gt;<br>Turniere</p>')
        self.assertEqual(article.preview_text, 'Tickets & Check-in <18 Uhr> Turniere')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'Tickets &amp; Check-in &lt;18 Uhr&gt; Turniere')


class NewsSchedulingTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.future = self.now + timedelta(days=2)
        self.scheduled = NewsArticle.objects.create(title='Geplante News', content='C', publish_at=self.future)
        self.detail_url = reverse('news_detail', args=[self.scheduled.pk])

    def test_scheduled_article_hidden_everywhere_for_guests(self):
        self.assertFalse(NewsArticle.objects.visible().exists())
        self.assertNotContains(self.client.get(reverse('news_list')), 'Geplante News')
        self.assertNotContains(self.client.get(reverse('dashboard')), 'Geplante News')
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)

    def test_scheduled_article_appears_when_time_is_reached(self):
        with patch('django.utils.timezone.now', return_value=self.future):
            self.assertContains(self.client.get(reverse('news_list')), 'Geplante News')
            self.assertContains(self.client.get(reverse('dashboard')), 'Geplante News')
            response = self.client.get(self.detail_url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'news-preview-notice')

    def test_scheduled_pinned_article_has_no_banner_before_time(self):
        NewsArticle.objects.filter(pk=self.scheduled.pk).update(is_pinned=True)
        self.assertIsNone(self.client.get(reverse('dashboard')).context['pinned_news'])
        with patch('django.utils.timezone.now', return_value=self.future):
            self.assertEqual(self.client.get(reverse('dashboard')).context['pinned_news'], self.scheduled)

    def test_draft_stays_hidden_after_publish_time(self):
        NewsArticle.objects.filter(pk=self.scheduled.pk).update(is_published=False)
        with patch('django.utils.timezone.now', return_value=self.future):
            self.assertFalse(NewsArticle.objects.visible().exists())

    def test_order_and_date_follow_publish_at(self):
        NewsArticle.objects.filter(pk=self.scheduled.pk).update(publish_at=self.now - timedelta(days=5))
        NewsArticle.objects.create(title='Neuer', content='C', publish_at=self.now - timedelta(days=1))
        response = self.client.get(reverse('news_list'))
        self.assertEqual([a.title for a in response.context['articles']], ['Neuer', 'Geplante News'])
        shown = timezone.localtime(self.now - timedelta(days=5)).strftime('%d.%m.%Y %H:%M')
        self.assertContains(response, shown)

    def test_staff_with_news_permission_gets_marked_uncached_preview(self):
        editor = get_user_model().objects.create_user('news-editor', is_staff=True)
        editor.user_permissions.add(Permission.objects.get(codename='change_newsarticle'))
        self.client.force_login(editor)
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'Vorschau: Für Gäste sichtbar ab')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertNotContains(self.client.get(reverse('news_list')), 'Geplante News')

    def test_preview_denied_without_staff_or_permission(self):
        member = get_user_model().objects.create_user('news-member')
        member.user_permissions.add(Permission.objects.get(codename='change_newsarticle'))
        staff = get_user_model().objects.create_user('other-staff', is_staff=True)
        for user in (member, staff):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.detail_url).status_code, 404)

    def test_admin_schedules_article_and_lists_status(self):
        admin_user = get_user_model().objects.create_superuser('schedule-admin', 'schedule@example.com', 'test-password')
        self.client.force_login(admin_user)
        local = timezone.localtime(self.future)
        response = self.client.post(reverse('admin:news_newsarticle_add'), {
            'title': 'Per Admin geplant', 'content': 'C', 'image_fit': 'cover', 'is_published': 'on', '_save': 'Speichern',
            'publish_at_0': local.strftime('%Y-%m-%d'), 'publish_at_1': local.strftime('%H:%M:%S'),
        })
        self.assertEqual(response.status_code, 302)
        article = NewsArticle.objects.get(title='Per Admin geplant')
        self.assertTrue(article.is_scheduled)
        NewsArticle.objects.create(title='Sofort', content='C')
        NewsArticle.objects.create(title='Entwurf', content='C', is_published=False)
        listing = self.client.get(reverse('admin:news_newsarticle_changelist'))
        self.assertContains(listing, 'Vorschau</a>')
        self.assertContains(listing, reverse('news_detail', args=[article.pk]))
        self.assertContains(listing, 'Entwurf')
        self.assertContains(listing, 'Veröffentlicht')

    def test_admin_add_form_prefills_current_time(self):
        admin_user = get_user_model().objects.create_superuser('prefill-admin', 'prefill@example.com', 'test-password')
        self.client.force_login(admin_user)
        response = self.client.get(reverse('admin:news_newsarticle_add'))
        self.assertContains(response, 'name="publish_at_0"')
        self.assertContains(response, f'value="{timezone.localtime().strftime("%d.%m.%Y")}"')


class NewsPublishAtMigrationTests(TransactionTestCase):
    before = [('news', '0004_newsarticle_cover_image_newsarticle_cover_image_alt_and_more')]
    after = [('news', '0005_newsarticle_publish_at')]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_articles_keep_created_at_as_publish_date(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old_apps = executor.loader.project_state(self.before).apps
        author = get_user_model().objects.create_user('migration-author', email='m@example.test')
        article = old_apps.get_model('news', 'NewsArticle').objects.create(title='Alt', content='C', author_id=author.pk)
        created = timezone.now() - timedelta(days=30)
        old_apps.get_model('news', 'NewsArticle').objects.filter(pk=article.pk).update(created_at=created)
        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        migrated = NewsArticle.objects.get(pk=article.pk)
        self.assertEqual(migrated.publish_at, created)
        self.assertEqual(migrated.created_at, created)
        self.assertIn(migrated, NewsArticle.objects.visible())


class NewsCoverUploadTests(TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        user = get_user_model().objects.create_superuser('upload-admin', 'upload@example.com', 'test-password')
        self.client.force_login(user)

    def post_image(self, image, **extra):
        return self.client.post(reverse('admin:news_newsarticle_add'), {
            'title': 'Bild-News', 'content': 'LAN', 'image_fit': 'contain', 'is_published': 'on',
            'cover_image': image, 'cover_image_alt': 'LAN-Plakat', '_save': 'Speichern', **PUBLISH_NOW, **extra,
        })

    def test_admin_uploads_valid_image_and_saves_display_options(self):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        image = BytesIO()
        Image.new('RGB', (32, 16)).save(image, format='PNG')
        response = self.post_image(SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png'))
        self.assertEqual(response.status_code, 302)
        article = NewsArticle.objects.get(title='Bild-News')
        self.assertTrue(article.cover_image.storage.exists(article.cover_image.name))
        self.assertEqual(article.cover_image_alt, 'LAN-Plakat')
        self.assertEqual(article.image_fit, 'contain')

    def test_admin_rejects_corrupt_or_unsupported_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        for name, content in [('fake.png', b'not an image'), ('cover.svg', b'<svg></svg>')]:
            with self.subTest(name=name):
                response = self.post_image(SimpleUploadedFile(name, content))
                self.assertEqual(response.status_code, 200)
                self.assertIn('cover_image', response.context['adminform'].form.errors)
                self.assertFalse(NewsArticle.objects.exists())

    def test_image_size_limit(self):
        from django.core.exceptions import ValidationError
        from types import SimpleNamespace
        from news.images import validate_news_image_size
        validate_news_image_size(SimpleNamespace(size=10 * 1024 * 1024))
        with self.assertRaises(ValidationError):
            validate_news_image_size(SimpleNamespace(size=10 * 1024 * 1024 + 1))
