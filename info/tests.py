from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from configuration.models import NavigationItem
from info.models import EventInfo

User = get_user_model()


class EventInfoViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='gamer1', email='gamer@example.com', password='password')
        self.staff = User.objects.create_superuser(username='admin1', email='admin@example.com', password='password')

        self.info = EventInfo.objects.create(
            title='LAN Info & Regeln',
            slug='allgemein',
            subtitle='Alles Wichtige',
            content='<p>WLAN Passwort & Catering Infos</p>',
            order=1,
            is_active=True,
        )

    def test_event_info_detail_view(self):
        response = self.client.get(reverse('event_info_detail'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LAN Info &amp; Regeln')
        self.assertContains(response, 'WLAN Passwort & Catering Infos')

    def test_multiple_pages_and_slug_routing(self):
        page2 = EventInfo.objects.create(
            title='Catering & Bar',
            slug='catering',
            subtitle='Pizza, Burger & Drinks',
            content='<p>Bestellungen direkt an der Theke</p>',
            order=2,
            is_active=True,
        )

        resp1 = self.client.get(reverse('event_info_page', kwargs={'slug': 'allgemein'}))
        self.assertEqual(resp1.status_code, 200)
        self.assertContains(resp1, 'LAN Info &amp; Regeln')

        resp2 = self.client.get(reverse('event_info_page', kwargs={'slug': 'catering'}))
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, 'Catering &amp; Bar')
        self.assertContains(resp2, 'Bestellungen direkt an der Theke')

        # Tab-Navigation vorhanden
        self.assertContains(resp1, 'info-tabs-nav')
        self.assertContains(resp1, 'Catering &amp; Bar')

    def test_show_in_nav_creates_and_syncs_navigation_item(self):
        page = EventInfo.objects.create(
            title='Turnier-Regeln',
            slug='regeln',
            order=3,
            show_in_nav=True,
            nav_icon=NavigationItem.IconChoices.RULES,
            is_active=True,
        )

        self.assertIsNotNone(page.nav_item)
        item = page.nav_item
        self.assertEqual(item.title, 'Turnier-Regeln')
        self.assertEqual(item.url_name, '/info/regeln/')
        self.assertEqual(item.icon_name, NavigationItem.IconChoices.RULES)
        self.assertTrue(item.is_active)

        # Titel & Icon aktualisieren
        page.title = 'Regeln & Fairplay'
        page.nav_icon = NavigationItem.IconChoices.CLANS
        page.order = 5
        page.save()

        item.refresh_from_db()
        self.assertEqual(item.title, 'Regeln & Fairplay')
        self.assertEqual(item.icon_name, NavigationItem.IconChoices.CLANS)
        self.assertEqual(item.order, 15)
        # Auch das SVG muss aktualisiert worden sein
        from configuration.models import SYSTEM_ICONS
        self.assertEqual(item.icon_svg, SYSTEM_ICONS[NavigationItem.IconChoices.CLANS])

        # show_in_nav abwählen -> Menüpunkt wird gelöscht
        item_id = item.id
        page.show_in_nav = False
        page.save()

        self.assertIsNone(page.nav_item)
        self.assertFalse(NavigationItem.objects.filter(id=item_id).exists())

    def test_deleting_info_page_deletes_navigation_item(self):
        page = EventInfo.objects.create(
            title='Anreise & Parken',
            slug='anreise',
            show_in_nav=True,
            is_active=True,
        )
        item_id = page.nav_item.id
        self.assertTrue(NavigationItem.objects.filter(id=item_id).exists())

        # Seite löschen
        page.delete()
        self.assertFalse(NavigationItem.objects.filter(id=item_id).exists())

    def test_bulk_delete_clears_navigation_cache(self):
        """Prüft, dass QuerySet.delete() (wie im Admin) den Navigationscache leert."""
        from django.core.cache import cache
        from configuration.context_processors import NAV_CACHE_KEY

        page1 = EventInfo.objects.create(title='Seite 1', slug='seite-1', show_in_nav=True, is_active=True)
        page2 = EventInfo.objects.create(title='Seite 2', slug='seite-2', show_in_nav=True, is_active=True)

        cache.set(NAV_CACHE_KEY, ['dummy_cached_nav'], 3600)
        self.assertIsNotNone(cache.get(NAV_CACHE_KEY))

        # Sammellöschung über QuerySet
        EventInfo.objects.filter(id__in=[page1.id, page2.id]).delete()

        # Cache muss geleert sein
        self.assertIsNone(cache.get(NAV_CACHE_KEY))

    def test_deleting_navigation_item_updates_info_page(self):
        page = EventInfo.objects.create(
            title='FAQ',
            slug='faq',
            show_in_nav=True,
            is_active=True,
        )
        item = page.nav_item
        item.delete()

        page.refresh_from_db()
        self.assertFalse(page.show_in_nav)
        self.assertIsNone(page.nav_item)

    def test_info_root_public_fallback_when_first_page_requires_login(self):
        """Wenn die erste Seite Login erfordert, zeigt /info/ die erste öffentliche Seite für Gäste."""
        EventInfo.objects.create(
            title='Admin-Hinweise',
            slug='admin-hinweise',
            content='<p>Geheim</p>',
            order=0,
            login_required=True,
            is_active=True,
        )
        # self.info hat order=1 und login_required=False
        response = self.client.get(reverse('event_info_detail'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LAN Info &amp; Regeln')
        self.assertContains(response, 'WLAN Passwort & Catering Infos')

    def test_info_root_redirects_if_only_login_required_pages_exist(self):
        """Wenn alle Seiten loginpflichtig sind, wird ein anonymer Gast zum Login geleitet."""
        EventInfo.objects.all().delete()
        EventInfo.objects.create(
            title='Nur für Teilnehmer',
            slug='geheim',
            content='<p>Streng vertraulich</p>',
            order=1,
            login_required=True,
            is_active=True,
        )
        response = self.client.get(reverse('event_info_detail'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_html_content_is_sanitized_on_save(self):
        """Schädliches HTML wird beim Speichern automatisch herausgefiltert."""
        dirty_html = '<p>Hallo <script>alert("xss")</script><b onclick="evil()">Fett</b></p>'
        page = EventInfo.objects.create(
            title='Sicherheitstest',
            slug='sec-test',
            content=dirty_html,
        )
        self.assertNotIn('<script>', page.content)
        self.assertNotIn('alert', page.content)
        self.assertNotIn('onclick', page.content)
        self.assertIn('<p>Hallo <b>Fett</b></p>', page.content)

    def test_slug_collision_resolution(self):
        """Gleichnamige Seiten erhalten automatisch eindeutige Slugs (-2, -3)."""
        page1 = EventInfo.objects.create(title='Turnierregeln')
        page2 = EventInfo.objects.create(title='Turnierregeln')
        page3 = EventInfo.objects.create(title='Turnierregeln')

        self.assertEqual(page1.slug, 'turnierregeln')
        self.assertEqual(page2.slug, 'turnierregeln-2')
        self.assertEqual(page3.slug, 'turnierregeln-3')

    def test_draft_preview_requires_info_permissions(self):
        """Einfache Staff-Benutzer ohne Info-Berechtigung sehen keine Entwürfe."""
        from django.contrib.auth.models import Permission
        draft_page = EventInfo.objects.create(
            title='Entwurf',
            slug='entwurf',
            content='<p>Entwurfstext</p>',
            is_active=False,
        )

        simple_staff = User.objects.create_user(
            username='staff_simple', email='staff@example.com', password='password', is_staff=True
        )
        self.client.force_login(simple_staff)
        resp_simple = self.client.get(draft_page.get_absolute_url())
        self.assertEqual(resp_simple.status_code, 404)

        # Staff mit Berechtigung
        perm = Permission.objects.get(codename='view_eventinfo')
        simple_staff.user_permissions.add(perm)
        # Erneut abrufen
        resp_permitted = self.client.get(draft_page.get_absolute_url())
        self.assertEqual(resp_permitted.status_code, 200)
        self.assertContains(resp_permitted, 'Entwurfstext')

    def test_login_required_protection(self):
        secret_page = EventInfo.objects.create(
            title='Internes WLAN & Server',
            slug='intern',
            content='<p>WLAN Key: TopSecret123</p>',
            login_required=True,
            is_active=True,
        )

        # Gast versucht Zugriff -> Redirect to Login
        resp_anon = self.client.get(secret_page.get_absolute_url())
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/login/', resp_anon.url)

        # Angemeldeter Benutzer -> 200 OK
        self.client.force_login(self.user)
        resp_user = self.client.get(secret_page.get_absolute_url())
        self.assertEqual(resp_user.status_code, 200)
        self.assertContains(resp_user, 'TopSecret123')

    def test_inactive_page_visibility(self):
        draft_page = EventInfo.objects.create(
            title='Entwurf Speisekarte',
            slug='speisekarte-entwurf',
            content='<p>Noch nicht final</p>',
            is_active=False,
        )

        # Anonym -> 404
        resp_anon = self.client.get(draft_page.get_absolute_url())
        self.assertEqual(resp_anon.status_code, 404)

        # Superuser -> 200 OK (Vorschau)
        self.client.force_login(self.staff)
        resp_staff = self.client.get(draft_page.get_absolute_url())
        self.assertEqual(resp_staff.status_code, 200)
        self.assertContains(resp_staff, 'Noch nicht final')


class InfoServiceTests(TestCase):

    def test_get_event_info_returns_instance(self):
        from info.services import get_event_info
        EventInfo.objects.create(
            title='FAQ & Ablauf',
            slug='faq-ablauf',
            subtitle='Wegbeschreibung',
            content='<p>Parkplätze vorhanden</p>',
        )
        info = get_event_info()
        self.assertIsNotNone(info)
        self.assertEqual(info.title, 'FAQ & Ablauf')

    def test_get_event_info_respects_active_and_login_status(self):
        from info.services import get_event_info
        EventInfo.objects.all().delete()
        EventInfo.objects.create(
            title='Inaktiver Entwurf',
            slug='inaktiv',
            content='<p>Entwurf</p>',
            is_active=False,
            order=1,
        )
        EventInfo.objects.create(
            title='Intern für User',
            slug='intern',
            content='<p>Geheim</p>',
            is_active=True,
            login_required=True,
            order=2,
        )
        public_page = EventInfo.objects.create(
            title='Öffentlich',
            slug='oeffentlich',
            content='<p>Öffentlich</p>',
            is_active=True,
            login_required=False,
            order=3,
        )

        # Anonymer User darf nicht den inaktiven Entwurf und nicht die geschützte Seite bekommen
        anon_user = User.objects.create_user(username='anon', is_active=True)
        from django.contrib.auth.models import AnonymousUser
        result = get_event_info(user=AnonymousUser())
        self.assertEqual(result, public_page)

