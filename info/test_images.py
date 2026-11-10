from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .content import sanitize_info_html
from .models import EventInfo

UPLOAD_URL = 'admin:info_eventinfo_upload_image'


def image_file(name='bild.png', image_format='PNG', exif=None):
    buffer = BytesIO()
    image = Image.new('RGB', (40, 30), (200, 30, 30))
    options = {'exif': exif} if exif else {}
    image.save(buffer, format=image_format, **options)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='application/octet-stream')


class InfoImageUploadTests(TestCase):
    def setUp(self):
        self.editor = get_user_model().objects.create_user('info-image-editor', is_staff=True)
        self.editor.user_permissions.add(Permission.objects.get(codename='change_eventinfo'))
        self.client.force_login(self.editor)

    def stored_path(self, location):
        return Path(settings.MEDIA_ROOT) / location.removeprefix(settings.MEDIA_URL)

    def test_upload_stores_reencoded_image_without_metadata(self):
        exif = Image.Exif()
        exif[0x010F] = 'Kamera mit GPS'
        response = self.client.post(reverse(UPLOAD_URL), {'file': image_file('foto.jpg', 'JPEG', exif)})
        self.assertEqual(response.status_code, 200)
        location = response.json()['location']
        self.assertRegex(location, r'^/media/info/images/[0-9a-f]{32}\.jpg$')
        with Image.open(self.stored_path(location)) as stored:
            self.assertEqual(stored.format, 'JPEG')
            self.assertEqual(len(stored.getexif()), 0)

    def test_upload_rejects_non_images_and_mismatched_data(self):
        for upload in (SimpleUploadedFile('x.png', b'<svg onload=alert(1)>'),
                       SimpleUploadedFile('x.gif', b'GIF89a' + b'\0' * 20)):
            response = self.client.post(reverse(UPLOAD_URL), {'file': upload})
            self.assertEqual(response.status_code, 400)
            self.assertIn('error', response.json())
        self.assertEqual(self.client.post(reverse(UPLOAD_URL)).status_code, 400)

    def test_upload_requires_info_permission_and_post(self):
        self.assertEqual(self.client.get(reverse(UPLOAD_URL)).status_code, 405)
        other = get_user_model().objects.create_user('info-image-other', is_staff=True)
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse(UPLOAD_URL), {'file': image_file()}).status_code, 403)
        self.client.logout()
        response = self.client.post(reverse(UPLOAD_URL), {'file': image_file()})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin:login'), response['Location'])

    def test_uploaded_image_survives_save_and_is_rendered(self):
        location = self.client.post(reverse(UPLOAD_URL), {'file': image_file()}).json()['location']
        page = EventInfo.objects.create(title='Anfahrt', slug='anfahrt', is_active=True,
            content=f'<p>Plan</p><img src="{location}" alt="Lageplan" width="400" height="300" onerror="alert(1)">')
        page.refresh_from_db()
        self.assertIn(f'<img src="{location}" alt="Lageplan" width="400" height="300">', page.content)
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, f'<img src="{location}" alt="Lageplan" width="400" height="300">', html=True)

    def test_editor_is_configured_for_uploads(self):
        self.editor.user_permissions.add(Permission.objects.get(codename='add_eventinfo'))
        response = self.client.get(reverse('admin:info_eventinfo_add'))
        self.assertContains(response, 'infoUploadImage')
        self.assertContains(response, 'js/admin-info-images.js')


class InfoImageSanitizerTests(TestCase):
    def test_only_uploaded_local_images_are_kept(self):
        local = '/media/info/images/' + 'a' * 32 + '.png'
        self.assertEqual(sanitize_info_html(f'<img src="{local}" style="x" alt="ok"/>'), f'<img src="{local}" alt="ok">')
        for source in ('https://tracker.example/pixel.png', 'data:image/png;base64,AAAA', 'javascript:alert(1)',
                       '/media/sponsors/logo.png', f'{local}?x=1', '//evil.example' + local, f'{local}/../../../secret.png', local.upper()):
            self.assertNotIn('<img', sanitize_info_html(f'<p>Text</p><img src="{source}">'), source)

    def test_other_html_is_still_sanitized(self):
        cleaned = sanitize_info_html('<p onclick="x">Hi</p><script>alert(1)</script><iframe src="x"></iframe>')
        self.assertEqual(cleaned, '<p>Hi</p>')
