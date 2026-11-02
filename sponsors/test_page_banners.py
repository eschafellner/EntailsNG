from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from configuration.models import GeneralConfiguration
from events.models import Event
from sponsors.models import Sponsor
from sponsors.tests import create_dummy_image


class SponsorPageBannerTests(TestCase):
    """Sponsor-Bereich auf Gästeliste, Teams und Sitzplan."""

    PAGES = ('guest_list', 'team_list', 'seating_plan')

    @classmethod
    def setUpTestData(cls):
        start = timezone.now() + timedelta(days=5)
        cls.event = Event.objects.create(
            title='Sponsor LAN', slug='sponsor-lan', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=2),
        )

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def create_sponsor(self, logo_typ=Sponsor.LogoTyp.BANNER):
        return Sponsor.objects.create(
            name='Seitensponsor AG', logo_typ=logo_typ, url='https://seitensponsor.example.com',
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT, bild=create_dummy_image(),
        )

    def test_sponsor_shown_on_all_pages(self):
        sponsor = self.create_sponsor()
        for name in self.PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, sponsor.bild.url)
                self.assertContains(response, 'https://seitensponsor.example.com')

    def test_no_sponsor_section_without_active_sponsor(self):
        Sponsor.objects.create(
            name='Inaktiv', aktiv_modus=Sponsor.AktivModus.INAKTIV, bild=create_dummy_image(),
        )
        for name in self.PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'sponsor-banner-card')
                self.assertNotContains(response, 'class="sponsor-strip"')

    def test_guest_and_team_pages_use_full_card(self):
        self.create_sponsor(logo_typ=Sponsor.LogoTyp.LOGO)
        for name in ('guest_list', 'team_list'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'sponsor-banner-card')
                self.assertContains(response, 'Seitensponsor AG')

    def test_seating_plan_shrinks_only_with_sponsor(self):
        response = self.client.get(reverse('seating_plan'))
        self.assertContains(response, 'height: calc(100vh - 260px)')
        self.assertNotContains(response, 'class="sponsor-strip"')

        self.create_sponsor()
        response = self.client.get(reverse('seating_plan'))
        self.assertContains(response, 'height: calc(100vh - 360px)')
        self.assertContains(response, 'class="sponsor-strip"')
        html = response.content.decode()
        self.assertLess(html.index('id="viewport"'), html.index('class="sponsor-strip"'))

    def test_switch_disables_sponsor_on_all_pages(self):
        self.create_sponsor()
        config = GeneralConfiguration.load()
        config.subpage_sponsor_enabled = False
        config.save()
        cache.clear()
        for name in self.PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'seitensponsor.example.com')
                self.assertNotContains(response, 'sponsor-banner-card')
                self.assertNotContains(response, 'class="sponsor-strip"')
        # Ohne Sponsor-Leiste behält der Sitzplan seine volle Höhe.
        self.assertContains(self.client.get(reverse('seating_plan')), 'height: calc(100vh - 260px)')
