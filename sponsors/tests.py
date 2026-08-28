import datetime
from io import BytesIO
from PIL import Image

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from sponsors.models import Sponsor
from sponsors.services import get_active_sponsors, get_random_active_sponsor

User = get_user_model()


def create_dummy_image(name='test.png'):
    """Erzeugt ein minimales Test-Bild im Speicher."""
    file = BytesIO()
    image = Image.new('RGB', (100, 100), color=(73, 109, 137))
    image.save(file, 'png')
    file.seek(0)
    return SimpleUploadedFile(name, file.read(), content_type='image/png')


class SponsorModelStatusTests(TestCase):
    """Testet die Aktiv-Statusberechnung (ist_aktiv) für alle 4 Modi."""

    def setUp(self):
        self.image = create_dummy_image()
        now = timezone.now()
        self.active_event = Event.objects.create(
            title="LAN Party Alpha",
            slug="lan-alpha",
            is_active=True,
            status=Event.Status.RUNNING,
            start_date=now - datetime.timedelta(days=1),
            end_date=now + datetime.timedelta(days=2),
        )
        self.inactive_event = Event.objects.create(
            title="LAN Party Beta",
            slug="lan-beta",
            is_active=False,
            status=Event.Status.DRAFT,
            start_date=now + datetime.timedelta(days=10),
            end_date=now + datetime.timedelta(days=12),
        )
        self.cancelled_event = Event.objects.create(
            title="LAN Party Gamma",
            slug="lan-gamma",
            is_active=False,
            status=Event.Status.CANCELLED,
            start_date=now - datetime.timedelta(days=1),
            end_date=now + datetime.timedelta(days=2),
        )
        self.expired_event = Event.objects.create(
            title="LAN Party Delta",
            slug="lan-delta",
            is_active=False,
            status=Event.Status.FINISHED,
            start_date=now - datetime.timedelta(days=5),
            end_date=now - datetime.timedelta(days=1),
        )

    def test_dauerhaft_aktiv(self):
        """Modus 'dauerhaft' ist immer aktiv."""
        sponsor = Sponsor.objects.create(
            name="Dauerhafter Sponsor",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image(),
        )
        self.assertTrue(sponsor.ist_aktiv)
        self.assertIn(sponsor, Sponsor.objects.aktiv())

    def test_inaktiv_modus(self):
        """Modus 'inaktiv' ist immer inaktiv."""
        sponsor = Sponsor.objects.create(
            name="Inaktiver Sponsor",
            aktiv_modus=Sponsor.AktivModus.INAKTIV,
            bild=create_dummy_image(),
        )
        self.assertFalse(sponsor.ist_aktiv)
        self.assertNotIn(sponsor, Sponsor.objects.aktiv())

    def test_datum_modus(self):
        """Modus 'datum': aktiv bis einschließlich aktiv_bis, danach inaktiv."""
        today = timezone.localdate()

        # 1. Heute als Stichtag -> AKTIV
        sponsor_today = Sponsor.objects.create(
            name="Sponsor bis heute",
            aktiv_modus=Sponsor.AktivModus.DATUM,
            aktiv_bis=today,
            bild=create_dummy_image(),
        )
        self.assertTrue(sponsor_today.ist_aktiv)
        self.assertIn(sponsor_today, Sponsor.objects.aktiv())

        # 2. Morgen als Stichtag -> AKTIV
        sponsor_future = Sponsor.objects.create(
            name="Sponsor bis morgen",
            aktiv_modus=Sponsor.AktivModus.DATUM,
            aktiv_bis=today + datetime.timedelta(days=1),
            bild=create_dummy_image(),
        )
        self.assertTrue(sponsor_future.ist_aktiv)
        self.assertIn(sponsor_future, Sponsor.objects.aktiv())

        # 3. Gestern als Stichtag (Folgetag erreicht) -> INAKTIV
        sponsor_past = Sponsor.objects.create(
            name="Sponsor bis gestern",
            aktiv_modus=Sponsor.AktivModus.DATUM,
            aktiv_bis=today - datetime.timedelta(days=1),
            bild=create_dummy_image(),
        )
        self.assertFalse(sponsor_past.ist_aktiv)
        self.assertNotIn(sponsor_past, Sponsor.objects.aktiv())

        # 4. Kein Datum gesetzt -> INAKTIV
        sponsor_no_date = Sponsor(
            name="Sponsor ohne Datum",
            aktiv_modus=Sponsor.AktivModus.DATUM,
            aktiv_bis=None,
            bild=create_dummy_image(),
        )
        self.assertFalse(sponsor_no_date.ist_aktiv)

    def test_veranstaltung_modus(self):
        """Modus 'veranstaltung': aktiv solange verknüpftes Event aktiv & laufend ist."""
        # 1. Verknüpft mit aktiver, laufender Veranstaltung -> AKTIV
        sponsor_active = Sponsor.objects.create(
            name="Sponsor Event Aktiv",
            aktiv_modus=Sponsor.AktivModus.VERANSTALTUNG,
            veranstaltung=self.active_event,
            bild=create_dummy_image(),
        )
        self.assertTrue(sponsor_active.ist_aktiv)
        self.assertIn(sponsor_active, Sponsor.objects.aktiv())

        # 2. Verknüpft mit inaktiver Veranstaltung (is_active=False) -> INAKTIV
        sponsor_inactive_evt = Sponsor.objects.create(
            name="Sponsor Event Inaktiv",
            aktiv_modus=Sponsor.AktivModus.VERANSTALTUNG,
            veranstaltung=self.inactive_event,
            bild=create_dummy_image(),
        )
        self.assertFalse(sponsor_inactive_evt.ist_aktiv)
        self.assertNotIn(sponsor_inactive_evt, Sponsor.objects.aktiv())

        # 3. Verknüpft mit abgesagter Veranstaltung -> INAKTIV
        sponsor_cancelled = Sponsor.objects.create(
            name="Sponsor Event Abgesagt",
            aktiv_modus=Sponsor.AktivModus.VERANSTALTUNG,
            veranstaltung=self.cancelled_event,
            bild=create_dummy_image(),
        )
        self.assertFalse(sponsor_cancelled.ist_aktiv)
        self.assertNotIn(sponsor_cancelled, Sponsor.objects.aktiv())

        # 4. Verknüpft mit beendeter Veranstaltung (Enddatum überschritten) -> INAKTIV
        sponsor_expired = Sponsor.objects.create(
            name="Sponsor Event Beendet",
            aktiv_modus=Sponsor.AktivModus.VERANSTALTUNG,
            veranstaltung=self.expired_event,
            bild=create_dummy_image(),
        )
        self.assertFalse(sponsor_expired.ist_aktiv)
        self.assertNotIn(sponsor_expired, Sponsor.objects.aktiv())

        # 5. Modus 'veranstaltung', aber keine verknüpft -> INAKTIV
        sponsor_no_evt = Sponsor(
            name="Sponsor ohne Event",
            aktiv_modus=Sponsor.AktivModus.VERANSTALTUNG,
            veranstaltung=None,
            bild=create_dummy_image(),
        )
        self.assertFalse(sponsor_no_evt.ist_aktiv)


class SponsorValidationTests(TestCase):
    """Testet die Model-Validierung clean()."""

    def test_clean_validation_veranstaltung_required(self):
        """Bei aktiv_modus='veranstaltung' muss veranstaltung gewählt sein."""
        sponsor = Sponsor(
            name="Ungültig Event",
            aktiv_modus=Sponsor.AktivModus.VERANSTALTUNG,
            veranstaltung=None,
            bild=create_dummy_image(),
        )
        with self.assertRaises(ValidationError) as ctx:
            sponsor.clean()
        self.assertIn('veranstaltung', ctx.exception.message_dict)

    def test_clean_validation_datum_required(self):
        """Bei aktiv_modus='datum' muss aktiv_bis gesetzt sein."""
        sponsor = Sponsor(
            name="Ungültig Datum",
            aktiv_modus=Sponsor.AktivModus.DATUM,
            aktiv_bis=None,
            bild=create_dummy_image(),
        )
        with self.assertRaises(ValidationError) as ctx:
            sponsor.clean()
        self.assertIn('aktiv_bis', ctx.exception.message_dict)

    def test_clean_validation_dauerhaft_success(self):
        """Bei aktiv_modus='dauerhaft' sind weder veranstaltung noch aktiv_bis nötig."""
        sponsor = Sponsor(
            name="Gültig Dauerhaft",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image(),
        )
        sponsor.clean()  # darf keinen Fehler werfen

    def test_image_file_size_validation(self):
        """Dateien über 10 MB werden abgewiesen, Dateien <= 10 MB sind erlaubt."""
        from sponsors.models import validate_sponsor_image_file_size

        # Kleines Bild (<10MB) -> erlaubt
        small_file = SimpleUploadedFile("small.png", b"x" * 1024, content_type="image/png")
        validate_sponsor_image_file_size(small_file)

        # Zu großes Bild (>10MB) -> ValidationError
        large_file = SimpleUploadedFile("large.png", b"x" * (11 * 1024 * 1024), content_type="image/png")
        with self.assertRaises(ValidationError) as ctx:
            validate_sponsor_image_file_size(large_file)
        self.assertIn("10 MB", str(ctx.exception))


class SponsorSortingAndServicesTests(TestCase):
    """Testet Rang-Sortierung, Tie-Breaking und Service-Methoden."""

    def test_sorting_rang_and_tie_breaking(self):
        """Sortierung aufsteigend nach rang, bei gleichem Rang älterer Eintrag (erstellt_am) zuerst."""
        s1 = Sponsor.objects.create(
            name="Rang 200",
            rang=200,
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image(),
        )
        s2 = Sponsor.objects.create(
            name="Rang 50 A",
            rang=50,
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image(),
        )
        s3 = Sponsor.objects.create(
            name="Rang 50 B",
            rang=50,
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image(),
        )

        sponsors = list(get_active_sponsors())
        self.assertEqual(len(sponsors), 3)
        self.assertEqual(sponsors[0], s2)
        self.assertEqual(sponsors[1], s3)
        self.assertEqual(sponsors[2], s1)

    def test_get_random_active_sponsor(self):
        """get_random_active_sponsor liefert genau einen aktiven Sponsor oder None."""
        self.assertIsNone(get_random_active_sponsor())

        Sponsor.objects.create(
            name="Inaktiv",
            aktiv_modus=Sponsor.AktivModus.INAKTIV,
            bild=create_dummy_image(),
        )
        self.assertIsNone(get_random_active_sponsor())

        active_s = Sponsor.objects.create(
            name="Aktiv",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image(),
        )
        random_s = get_random_active_sponsor()
        self.assertEqual(random_s, active_s)


class SponsorFrontendViewsTests(TestCase):
    """Testet Frontend-Views: Dashboard-Modul und Sponsorenseite."""

    def setUp(self):
        self.client = Client()
        now = timezone.now()
        self.event = Event.objects.create(
            title="Haupt-LAN 2026",
            slug="haupt-lan-2026",
            is_active=True,
            status=Event.Status.RUNNING,
            start_date=now - datetime.timedelta(days=1),
            end_date=now + datetime.timedelta(days=2),
        )

    def test_dashboard_with_no_active_sponsors(self):
        """Wenn keine aktiven Sponsoren existieren, wird kein Sponsoren-Modul auf dem Dashboard gerendert."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'dashboard-sponsor-card')
        self.assertNotContains(response, 'Partner & Sponsoren')

    def test_dashboard_with_active_logo_sponsor(self):
        """Dashboard zeigt aktiven Logo-Sponsor mit Name, Bild und URL."""
        sponsor = Sponsor.objects.create(
            name="HardwareHero",
            logo_typ=Sponsor.LogoTyp.LOGO,
            url="https://hardware-hero.example.com",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image('hero_logo.png'),
        )
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dashboard-sponsor-card')
        self.assertContains(response, 'HardwareHero')
        self.assertContains(response, 'https://hardware-hero.example.com')
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertContains(response, 'alt="HardwareHero Logo"')

    def test_dashboard_with_active_banner_sponsor(self):
        """Dashboard zeigt aktiven Banner-Sponsor."""
        sponsor = Sponsor.objects.create(
            name="MegaEnergy Drink",
            logo_typ=Sponsor.LogoTyp.BANNER,
            url="https://megaenergy.example.com",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image('energy_banner.png'),
        )
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dashboard-sponsor-card')
        self.assertContains(response, 'https://megaenergy.example.com')
        self.assertContains(response, 'alt="MegaEnergy Drink Banner"')

    def test_sponsor_list_view(self):
        """Die Sponsorenseite listet alle aktiven Sponsoren auf und schließt inaktive aus."""
        s_active1 = Sponsor.objects.create(
            name="Gold Sponsor Alpha",
            logo_typ=Sponsor.LogoTyp.BANNER,
            rang=10,
            beschreibung="<p>Wir unterstützen mit bestem Equipment!</p>",
            url="https://alpha.example.com",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image('alpha.png'),
        )
        s_active2 = Sponsor.objects.create(
            name="Silber Sponsor Beta",
            logo_typ=Sponsor.LogoTyp.LOGO,
            rang=20,
            beschreibung="<p>Kühle Drinks für alle Teilnehmer.</p>",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image('beta.png'),
        )
        s_inactive = Sponsor.objects.create(
            name="Ehemaliger Sponsor Gamma",
            rang=5,
            aktiv_modus=Sponsor.AktivModus.INAKTIV,
            bild=create_dummy_image('gamma.png'),
        )

        response = self.client.get(reverse('sponsor_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unsere Sponsoren")
        self.assertContains(response, "Gold Sponsor Alpha")
        self.assertContains(response, "Silber Sponsor Beta")
        self.assertContains(response, "Wir unterstützen mit bestem Equipment!")
        self.assertContains(response, "Kühle Drinks für alle Teilnehmer.")
        self.assertContains(response, 'https://alpha.example.com')
        # Inaktiver Sponsor darf nicht auf der Seite erscheinen:
        self.assertNotContains(response, "Ehemaliger Sponsor Gamma")

    def test_sponsor_list_view_empty_state(self):
        """Wenn keine Sponsoren vorhanden sind, wird ein sauberer Hinweistext angezeigt."""
        response = self.client.get(reverse('sponsor_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aktuell sind keine Sponsoren hinterlegt.")

    def test_sponsor_list_view_description_truncation(self):
        """Beschreibungstexte über 1500 Zeichen werden mit Desktop- und Mobile-Kürzungscontainern gerendert."""
        long_text = "<p>" + ("A" * 1600) + "</p>"
        sponsor_long = Sponsor.objects.create(
            name="Langer Text Sponsor",
            logo_typ=Sponsor.LogoTyp.LOGO,
            beschreibung=long_text,
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image('long.png'),
        )
        response = self.client.get(reverse('sponsor_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="desc-block-{sponsor_long.id}"')
        self.assertContains(response, 'desc-short-desktop')
        self.assertContains(response, 'desc-short-mobile')
        self.assertContains(response, 'desc-full')
        self.assertContains(response, f"toggleSponsorDesc('{sponsor_long.id}')")
        self.assertContains(response, "Mehr anzeigen")

    def test_sponsor_list_view_description_medium_mobile_truncation(self):
        """Beschreibungstexte zwischen 501 und 1500 Zeichen werden für Mobile gekürzt und auf Desktop voll angezeigt."""
        med_text = "<p>" + ("B" * 800) + "</p>"
        sponsor_med = Sponsor.objects.create(
            name="Mittellanger Text Sponsor",
            logo_typ=Sponsor.LogoTyp.BANNER,
            beschreibung=med_text,
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image('med.png'),
        )
        response = self.client.get(reverse('sponsor_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="desc-block-{sponsor_med.id}"')
        self.assertContains(response, 'desc-desktop-full')
        self.assertContains(response, 'desc-short-mobile')
        self.assertContains(response, 'desc-btn-mobile-only')
        self.assertContains(response, f"toggleSponsorDesc('{sponsor_med.id}')")

    def test_seed_translations_creates_sponsor_keys(self):
        """seed_translations legt alle Sponsoren-Übersetzungsschlüssel in der DB an."""
        from django.core.management import call_command
        from configuration.models import SystemTranslation

        call_command('seed_translations')

        self.assertTrue(SystemTranslation.objects.filter(key='dash_sponsors_eyebrow').exists())
        self.assertTrue(SystemTranslation.objects.filter(key='dash_sponsors_title').exists())
        self.assertTrue(SystemTranslation.objects.filter(key='sponsors_read_more').exists())


class SponsorAdminTests(TestCase):
    """Testet die Django Admin Integration."""

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='secretpassword123',
        )
        self.client.force_login(self.admin_user)

    def test_admin_changelist_loads(self):
        """Admin Changelist für Sponsoren lädt mit HTTP 200."""
        Sponsor.objects.create(
            name="Admin Test Sponsor",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image(),
        )
        response = self.client.get('/admin/sponsors/sponsor/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin Test Sponsor")
        self.assertContains(response, "Dauerhaft aktiv")

    def test_admin_add_form_loads(self):
        """Admin Add-Formular lädt und bindet das Media-JS ein."""
        response = self.client.get('/admin/sponsors/sponsor/add/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "js/admin_sponsor.js")


class SponsorNavigationAndSeedFeaturesTests(TestCase):
    """Testet Menüpunkt- und Seed-Integration."""

    def test_seed_features_creates_sponsor_nav_item(self):
        """seed_features legt den Menüpunkt Sponsoren an."""
        from django.core.management import call_command
        from configuration.models import NavigationItem

        call_command('seed_features')

        nav_item = NavigationItem.objects.filter(url_name='sponsor_list').first()
        self.assertIsNotNone(nav_item)
        self.assertEqual(nav_item.title, 'Sponsoren')
        self.assertEqual(nav_item.get_url(), reverse('sponsor_list'))

    def test_dashboard_and_list_sponsor_without_url(self):
        """Sponsor ohne URL wird auf Dashboard und Sponsorenseite ohne Klick-Link gerendert."""
        sponsor = Sponsor.objects.create(
            name="No URL Sponsor",
            logo_typ=Sponsor.LogoTyp.LOGO,
            url="",
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT,
            bild=create_dummy_image('nourl.png'),
        )
        response_dash = self.client.get(reverse('dashboard'))
        self.assertEqual(response_dash.status_code, 200)
        self.assertContains(response_dash, "No URL Sponsor")
        self.assertContains(response_dash, 'alt="No URL Sponsor Logo"')

        response_list = self.client.get(reverse('sponsor_list'))
        self.assertEqual(response_list.status_code, 200)
        self.assertContains(response_list, "No URL Sponsor")
        self.assertNotContains(response_list, "🌐 Website besuchen")

    def test_active_event_without_end_date(self):
        """Ein aktives Event ohne end_date gilt ebenfalls als aktiv."""
        now = timezone.now()
        event_no_end = Event.objects.create(
            title="Open End LAN",
            slug="open-end-lan",
            is_active=False,
            status=Event.Status.RUNNING,
            start_date=now - datetime.timedelta(days=1),
            end_date=now + datetime.timedelta(days=1),  # CheckConstraint requires end_date > start_date
        )
        # Jetzt als einziges aktives Event setzen
        Event.objects.filter(is_active=True).update(is_active=False)
        event_no_end.is_active = True
        event_no_end.save()

        sponsor = Sponsor.objects.create(
            name="Open End Sponsor",
            aktiv_modus=Sponsor.AktivModus.VERANSTALTUNG,
            veranstaltung=event_no_end,
            bild=create_dummy_image(),
        )
        self.assertTrue(sponsor.ist_aktiv)
        self.assertIn(sponsor, Sponsor.objects.aktiv())

