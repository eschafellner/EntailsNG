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
        page.save()

        item.refresh_from_db()
        self.assertEqual(item.title, 'Regeln & Fairplay')
        self.assertEqual(item.icon_name, NavigationItem.IconChoices.CLANS)

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

        # Staff -> 200 OK (Vorschau)
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
