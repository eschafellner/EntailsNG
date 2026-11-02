import shutil
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Clan, ClanMembership

MEDIA_ROOT = tempfile.mkdtemp()


def upload(size=(1200, 600), fmt='PNG', name='logo.png', mode='RGB', color='red', **save_options):
    buffer = BytesIO()
    Image.new(mode, size, color).save(buffer, format=fmt, **save_options)
    return SimpleUploadedFile(name, buffer.getvalue())


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class ClanLogoUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.clan = Clan.objects.create(name='Logo Clan', password='Geheim123!xy')
        leader = get_user_model().objects.create_user('leader', 'leader@example.com', 'StrongPass123!')
        ClanMembership.objects.create(user=leader, clan=self.clan, role=ClanMembership.Role.ADMIN,
                                      status=ClanMembership.Status.ACCEPTED)
        self.client.force_login(leader)

    def post(self, logo=None):
        data = {'name': 'Logo Clan'}
        if logo:
            data['logo'] = logo
        response = self.client.post(reverse('clan_edit', kwargs={'slug': self.clan.slug}), data)
        self.clan.refresh_from_db()
        return response

    def assert_rejected(self, logo):
        response = self.post(logo)
        self.assertTrue(response.context['form'].has_error('logo'))
        self.assertFalse(self.clan.logo)

    def stored(self):
        with self.clan.logo.open('rb') as stored, Image.open(stored) as image:
            image.load()
            return image

    def test_large_image_is_scaled_down_keeping_its_proportions(self):
        self.post(upload(size=(1200, 600)))
        self.assertEqual(self.stored().size, (500, 250))

    def test_small_image_is_not_enlarged(self):
        self.post(upload(size=(64, 32)))
        self.assertEqual(self.stored().size, (64, 32))

    def test_transparency_survives(self):
        self.post(upload(mode='RGBA', color=(255, 0, 0, 0)))
        image = self.stored()
        self.assertEqual(image.format, 'PNG')
        self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_webp_is_stored_as_png_and_jpeg_stays_jpeg(self):
        self.post(upload(fmt='WEBP', name='logo.webp'))
        self.assertTrue(self.clan.logo.name.endswith('.png'))
        self.assertEqual(self.stored().format, 'PNG')
        self.post(upload(fmt='JPEG', name='foto.jpeg'))
        self.assertTrue(self.clan.logo.name.endswith('.jpg'))
        self.assertEqual(self.stored().format, 'JPEG')

    def test_metadata_is_removed_and_orientation_applied(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # 90 Grad gedreht
        exif[0x010F] = 'Geheime Kamera'
        for fmt, name in (('JPEG', 'foto.jpg'), ('PNG', 'foto.png')):
            with self.subTest(fmt=fmt):
                self.post(upload(size=(100, 50), fmt=fmt, name=name, exif=exif))
                image = self.stored()
                self.assertEqual(image.size, (50, 100))
                self.assertEqual(dict(image.getexif()), {})
                with self.clan.logo.open('rb') as stored:
                    self.assertNotIn(b'Geheime Kamera', stored.read())

    def test_unchanged_logo_is_not_processed_again_when_editing(self):
        self.post(upload())
        name = self.clan.logo.name
        with patch('clans.forms.normalize_clan_logo') as normalize:
            self.assertEqual(self.post().status_code, 302)
        normalize.assert_not_called()
        self.assertEqual(self.clan.logo.name, name)

    def test_saved_logo_missing_on_disk_does_not_break_editing(self):
        self.post(upload())
        self.clan.logo.storage.delete(self.clan.logo.name)
        self.assertEqual(self.post().status_code, 302)

    def test_file_over_the_size_limit_is_rejected(self):
        with patch('clans.forms.MAX_LOGO_SIZE_BYTES', 10):
            self.assert_rejected(upload())

    def test_image_over_the_pixel_limit_is_rejected(self):
        with patch('clans.forms.MAX_LOGO_PIXELS', 100):
            self.assert_rejected(upload())

    def test_disallowed_format_with_image_extension_is_rejected(self):
        self.assert_rejected(upload(fmt='GIF', name='logo.png'))

    def test_broken_image_is_rejected(self):
        self.assert_rejected(SimpleUploadedFile('logo.png', b'kein Bild'))

    def test_truncated_image_is_rejected(self):
        data = upload(size=(800, 800), fmt='JPEG', name='logo.jpg').read()
        self.assert_rejected(SimpleUploadedFile('logo.jpg', data[:len(data) // 2]))
