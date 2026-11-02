import re
from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from configuration.models import GeneralConfiguration
from events.models import Event, EventRegistration, TicketType
from sponsors.models import Sponsor
from users.models import GuestPhoto
from users.services import GuestPhotoService

User = get_user_model()


def image_upload(name='bild.png', fmt='PNG'):
    stream = BytesIO()
    Image.new('RGB', (40, 40), 'green').save(stream, format=fmt)
    return SimpleUploadedFile(name, stream.getvalue(), content_type=f'image/{fmt.lower()}')


class CheckinQrSponsorTests(TestCase):
    """Sponsor im Check-in-QR-Fenster, ohne QR-Code, Ticket-Code oder Gastfoto zu verdrängen."""

    @classmethod
    def setUpTestData(cls):
        cls.guest = User.objects.create_user(username='QrGast', password='pw', first_name='Qr', last_name='Gast')
        start = timezone.now() + timedelta(days=1)
        cls.event = Event.objects.create(
            title='QR LAN', slug='qr-lan', is_active=True, max_guests=100,
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=2),
        )
        ticket = TicketType.objects.create(event=cls.event, name='Weekend', price=0)
        cls.registration = EventRegistration.objects.create(
            user=cls.guest, event=cls.event, ticket_type=ticket,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.force_login(self.guest)

    def configure(self, **values):
        config = GeneralConfiguration.load()
        for name, value in values.items():
            setattr(config, name, value)
        config.save()
        cache.clear()

    def create_sponsor(self, logo_typ=Sponsor.LogoTyp.BANNER):
        return Sponsor.objects.create(
            name='Hauptsponsor GmbH', logo_typ=logo_typ, url='https://sponsor.example.com',
            aktiv_modus=Sponsor.AktivModus.DAUERHAFT, bild=image_upload(),
        )

    def qr_modal(self):
        html = self.client.get(reverse('dashboard')).content.decode()
        match = re.search(r'<div id="qr-modal".*?<!-- RECHTER BEREICH', html, re.S)
        self.assertIsNotNone(match, 'Check-in-QR-Fenster fehlt im Dashboard')
        return match.group(0)

    def assert_checkin_essentials(self, modal):
        self.assertIn(reverse('registration_checkin_qr', args=[self.registration.pk]), modal)
        self.assertIn(self.registration.short_code, modal)

    def test_banner_sponsor_shown_without_link(self):
        sponsor = self.create_sponsor()
        modal = self.qr_modal()
        self.assertIn('qr-modal-sponsor', modal)
        self.assertIn('qr-modal-sponsor-banner', modal)
        self.assertIn(sponsor.bild.url, modal)
        self.assertNotIn('sponsor.example.com', modal)
        self.assert_checkin_essentials(modal)

    def test_logo_sponsor_shows_name(self):
        self.create_sponsor(logo_typ=Sponsor.LogoTyp.LOGO)
        modal = self.qr_modal()
        self.assertIn('qr-modal-sponsor-logo', modal)
        self.assertIn('Hauptsponsor GmbH', modal)
        self.assertNotIn('sponsor.example.com', modal)

    def test_no_sponsor_section_without_active_sponsor(self):
        modal = self.qr_modal()
        self.assertNotIn('qr-modal-sponsor', modal)
        self.assert_checkin_essentials(modal)

    def test_sponsor_section_can_be_disabled(self):
        self.create_sponsor()
        self.configure(checkin_qr_sponsor_enabled=False)
        modal = self.qr_modal()
        self.assertNotIn('qr-modal-sponsor', modal)
        self.assert_checkin_essentials(modal)

    def test_guest_photo_stays_above_sponsor_with_extended_checkin(self):
        self.configure(extended_checkin_enabled=True)
        with self.captureOnCommitCallbacks(execute=True):
            GuestPhotoService.save_photo(
                user=self.guest, upload=image_upload('foto.jpg', 'JPEG'), actor=self.guest,
                source=GuestPhoto.Source.SELF,
            )
        self.create_sponsor()
        modal = self.qr_modal()
        photo_url = reverse('guest_photo', args=[self.guest.pk])
        self.assert_checkin_essentials(modal)
        self.assertIn(photo_url, modal)
        self.assertLess(modal.index(photo_url), modal.index('qr-modal-sponsor'))
        self.assertLess(
            modal.index(reverse('registration_checkin_qr', args=[self.registration.pk])),
            modal.index('qr-modal-sponsor'),
        )
