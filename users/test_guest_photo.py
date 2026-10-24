from datetime import timedelta
from io import BytesIO, StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from configuration.models import GeneralConfiguration
from events.models import Event, EventRegistration
from users.models import GUEST_PHOTO_DIR, GuestPhoto
from users.services import GuestPhotoService, UserService, normalize_guest_photo

User = get_user_model()


def image_upload(size=(40, 20), fmt='JPEG', exif=None, name='photo.jpg'):
    stream = BytesIO()
    kwargs = {'exif': exif} if exif is not None else {}
    Image.new('RGB', size, 'red').save(stream, format=fmt, **kwargs)
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/jpeg')


class NormalizeGuestPhotoTests(TestCase):
    def test_strips_metadata_and_applies_orientation(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # Orientation: 90° gedreht
        exif[0x013B] = 'Geheimer Fotograf'
        content = normalize_guest_photo(image_upload(size=(40, 20), exif=exif))
        with Image.open(content) as result:
            self.assertEqual(result.format, 'JPEG')
            self.assertEqual(result.size, (20, 40))
            self.assertEqual(dict(result.getexif()), {})
            self.assertNotIn(b'Geheimer', content.read())

    def test_downscales_large_photo(self):
        content = normalize_guest_photo(image_upload(size=(2400, 1200), fmt='PNG', name='big.png'))
        with Image.open(content) as result:
            self.assertEqual(result.size, (600, 300))

    def test_rejects_invalid_files(self):
        for upload in (
            SimpleUploadedFile('fake.jpg', b'kein Bild'),
            image_upload(fmt='GIF', name='anim.gif'),
        ):
            with self.subTest(name=upload.name), self.assertRaises(ValidationError):
                normalize_guest_photo(upload)

    def test_rejects_too_large_upload_before_decoding(self):
        upload = image_upload()
        upload.size = 10 * 1024 * 1024 + 1
        with patch('users.services.Image.open') as image_open, self.assertRaises(ValidationError):
            normalize_guest_photo(upload)
        image_open.assert_not_called()

    def test_rejects_too_many_pixels(self):
        with patch('users.services.MAX_GUEST_PHOTO_PIXELS', 100), self.assertRaises(ValidationError):
            normalize_guest_photo(image_upload(size=(20, 20)))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class GuestPhotoServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.guest = User.objects.create_user('guest', 'guest@example.com', 'StrongPass123!')
        self.staff = User.objects.create_user('orga', 'orga@example.com', 'StrongPass123!', is_staff=True)

    def create_event(self, end_in_days, title='LAN'):
        now = timezone.now()
        return Event.objects.create(
            title=title, start_date=now + timedelta(days=end_in_days - 1),
            end_date=now + timedelta(days=end_in_days), max_guests=100,
        )

    def save(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return GuestPhotoService.save_photo(
                user=self.guest, upload=image_upload(), actor=kwargs.get('actor', self.staff),
                source=kwargs.get('source', GuestPhoto.Source.STAFF),
            )

    def test_config_defaults_and_limit(self):
        config = GeneralConfiguration.load()
        self.assertFalse(config.extended_checkin_enabled)
        self.assertEqual(config.guest_photo_retention_days, 14)
        config.guest_photo_retention_days = 366
        with self.assertRaises(ValidationError):
            config.full_clean()

    def test_save_stores_private_jpeg_with_audit_fields(self):
        photo = self.save()
        self.assertTrue(photo.image.name.startswith('guest_photos/'))
        self.assertTrue(photo.image.name.endswith('.jpg'))
        self.assertTrue(photo.image.storage.exists(photo.image.name))
        self.assertEqual(photo.uploaded_by, self.staff)
        self.assertEqual(photo.source, GuestPhoto.Source.STAFF)
        with self.assertRaises(ValueError):
            photo.image.url

    def test_replacing_photo_removes_old_file(self):
        first = self.save().image.name
        second = self.save(actor=self.guest, source=GuestPhoto.Source.SELF)
        self.assertEqual(GuestPhoto.objects.count(), 1)
        self.assertNotEqual(second.image.name, first)
        self.assertFalse(second.image.storage.exists(first))
        self.assertEqual(second.source, GuestPhoto.Source.SELF)

    def test_delete_after_without_registration_counts_from_upload(self):
        photo = self.save()
        self.assertEqual(photo.delete_after, photo.captured_at + timedelta(days=14))

    def test_delete_after_uses_latest_active_registration(self):
        config = GeneralConfiguration.load()
        config.guest_photo_retention_days = 3
        config.save()
        later = self.create_event(20, 'Später')
        cancelled = self.create_event(40, 'Storniert')
        EventRegistration.objects.create(user=self.guest, event=self.create_event(10))
        EventRegistration.objects.create(user=self.guest, event=later)
        EventRegistration.objects.create(
            user=self.guest, event=cancelled, payment_status=EventRegistration.PaymentStatus.CANCELLED,
        )
        photo = self.save()
        self.assertEqual(photo.delete_after, later.end_date + timedelta(days=3))

    def test_refresh_delete_after_follows_new_registration(self):
        photo = self.save()
        event = self.create_event(30)
        EventRegistration.objects.create(user=self.guest, event=event)
        GuestPhotoService.refresh_delete_after(self.guest)
        photo.refresh_from_db()
        self.assertEqual(photo.delete_after, event.end_date + timedelta(days=14))

    def test_delete_photo_removes_row_and_file(self):
        name = self.save().image.name
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(GuestPhotoService.delete_photo(self.guest))
        self.assertFalse(GuestPhoto.objects.exists())
        self.assertFalse(GuestPhoto._meta.get_field('image').storage.exists(name))

    def test_account_deletion_removes_photo_and_blocks_new_one(self):
        name = self.save().image.name
        with self.captureOnCommitCallbacks(execute=True):
            UserService.delete_account(self.guest, 'StrongPass123!')
        self.assertFalse(GuestPhoto.objects.exists())
        self.assertFalse(GuestPhoto._meta.get_field('image').storage.exists(name))
        with self.assertRaises(ValidationError):
            self.save()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class GuestPhotoViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.guest = User.objects.create_user('guest', 'guest@example.com', 'StrongPass123!')
        self.staff = User.objects.create_user('orga', 'orga@example.com', 'StrongPass123!', is_staff=True)
        self.other = User.objects.create_user('other', 'other@example.com', 'StrongPass123!')
        self.set_enabled(True)

    def set_enabled(self, enabled):
        config = GeneralConfiguration.load()
        config.extended_checkin_enabled = enabled
        config.save()

    def upload(self, **data):
        self.client.force_login(self.guest)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('guest_photo_upload'), {
                'photo': image_upload(), 'confirm_notice': 'on', **data,
            })

    def store_photo(self):
        with self.captureOnCommitCallbacks(execute=True):
            return GuestPhotoService.save_photo(
                user=self.guest, upload=image_upload(), actor=self.guest, source=GuestPhoto.Source.SELF,
            )

    def test_upload_stores_own_photo(self):
        response = self.upload()
        self.assertRedirects(response, reverse('profile') + '#guest-photo', fetch_redirect_response=False)
        photo = GuestPhoto.objects.get(user=self.guest)
        self.assertEqual(photo.source, GuestPhoto.Source.SELF)
        self.assertEqual(photo.uploaded_by, self.guest)
        self.assertEqual(photo.notice_confirmed_at, photo.captured_at)

    def test_upload_requires_notice_confirmation_and_valid_image(self):
        self.upload(confirm_notice='')
        self.upload(photo=SimpleUploadedFile('fake.jpg', b'kein Bild'))
        self.assertFalse(GuestPhoto.objects.exists())

    def test_upload_disabled_when_feature_is_off(self):
        self.set_enabled(False)
        self.assertEqual(self.upload().status_code, 404)
        self.assertFalse(GuestPhoto.objects.exists())

    def test_upload_requires_login_and_post(self):
        response = self.client.post(reverse('guest_photo_upload'), {'photo': image_upload(), 'confirm_notice': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse('guest_photo_upload')).status_code, 405)

    def test_delete_works_even_when_feature_is_off(self):
        name = self.store_photo().image.name
        self.set_enabled(False)
        self.client.force_login(self.guest)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('guest_photo_delete'))
        self.assertFalse(GuestPhoto.objects.exists())
        self.assertFalse(GuestPhoto._meta.get_field('image').storage.exists(name))

    def get_photo(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('guest_photo', args=[self.guest.pk]))

    def test_photo_access_rules(self):
        self.store_photo()
        response = self.get_photo(self.guest)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content)[:2], b'\xff\xd8')
        self.assertEqual(self.get_photo(self.staff).status_code, 200)
        self.assertEqual(self.get_photo(self.other).status_code, 404)

        self.set_enabled(False)
        self.assertEqual(self.get_photo(self.staff).status_code, 404)
        self.assertEqual(self.get_photo(self.guest).status_code, 200)

    def test_photo_view_without_photo_or_login(self):
        self.assertEqual(self.client.get(reverse('guest_photo', args=[self.guest.pk])).status_code, 302)
        self.assertEqual(self.get_photo(self.guest).status_code, 404)

    def test_profile_section_follows_feature_and_photo(self):
        self.client.force_login(self.guest)
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'id="guest-photo"')
        self.assertContains(response, f'action="{reverse("guest_photo_upload")}"')
        self.set_enabled(False)
        self.assertNotContains(self.client.get(reverse('profile')), 'id="guest-photo"')
        self.store_photo()
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'id="guest-photo"')
        self.assertContains(response, reverse('guest_photo_delete'))
        self.assertNotContains(response, f'action="{reverse("guest_photo_upload")}"')

    def test_dashboard_ticket_shows_hint_then_photo(self):
        now = timezone.now()
        event = Event.objects.create(
            title='Test LAN', start_date=now + timedelta(days=1), end_date=now + timedelta(days=2),
            status=Event.Status.REGISTRATION_OPEN, is_active=True, max_guests=100,
        )
        EventRegistration.objects.create(
            user=self.guest, event=event, payment_status=EventRegistration.PaymentStatus.PAID,
        )
        self.client.force_login(self.guest)
        response = self.client.get(reverse('dashboard'))
        self.assertTrue(response.context['show_onboarding_ticket'])
        self.assertContains(response, 'ticket-photo-hint')

        self.store_photo()
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, 'ticket-photo-hint')
        self.assertContains(response, reverse('guest_photo', args=[self.guest.pk]))

        self.set_enabled(False)
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, reverse('guest_photo', args=[self.guest.pk]))


class GuestPhotoPurgeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.guest = User.objects.create_user('guest', 'guest@example.com')
        self.storage = GuestPhoto._meta.get_field('image').storage

    def store_photo(self, user=None):
        with self.captureOnCommitCallbacks(execute=True):
            return GuestPhotoService.save_photo(
                user=user or self.guest, upload=image_upload(), actor=self.guest, source=GuestPhoto.Source.SELF,
            )

    def purge(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return GuestPhotoService.purge(**kwargs)

    def test_expired_photo_and_file_are_deleted(self):
        photo = self.store_photo()
        self.assertEqual(self.purge(now=photo.delete_after - timedelta(seconds=1))['expired'], 0)
        self.assertEqual(self.purge(now=photo.delete_after)['expired'], 1)
        self.assertFalse(GuestPhoto.objects.exists())
        self.assertFalse(self.storage.exists(photo.image.name))

    def test_shorter_retention_and_admin_cancellations_take_effect(self):
        photo = self.store_photo()
        now = timezone.now()
        event = Event.objects.create(title='LAN', start_date=now + timedelta(days=9),
                                     end_date=now + timedelta(days=10), max_guests=10)
        EventRegistration.objects.create(user=self.guest, event=event)
        self.purge()
        photo.refresh_from_db()
        self.assertEqual(photo.delete_after, event.end_date + timedelta(days=14))
        EventRegistration.objects.filter(user=self.guest).update(
            payment_status=EventRegistration.PaymentStatus.CANCELLED)
        config = GeneralConfiguration.load()
        config.guest_photo_retention_days = 0
        config.save()
        self.assertEqual(self.purge(now=photo.captured_at + timedelta(seconds=1))['expired'], 1)

    def test_rows_without_file_and_old_orphan_files_are_removed(self):
        missing = self.store_photo()
        self.storage.delete(missing.image.name)
        other = User.objects.create_user('other', 'other@example.com')
        kept = self.store_photo(other)
        orphan = self.storage.save(f'{GUEST_PHOTO_DIR}/orphan.jpg', image_upload())
        fresh = self.storage.save(f'{GUEST_PHOTO_DIR}/uploading.jpg', image_upload())
        result = self.purge(now=timezone.now() + timedelta(hours=2), dry_run=True)
        self.assertEqual((result['missing_files'], result['orphan_files']), (1, 2))
        self.assertTrue(self.storage.exists(orphan))

        result = self.purge()
        self.assertEqual((result['missing_files'], result['orphan_files']), (1, 0))
        self.assertTrue(self.storage.exists(fresh))
        result = self.purge(now=timezone.now() + timedelta(hours=2))
        self.assertEqual(result['orphan_files'], 2)
        self.assertEqual(list(GuestPhoto.objects.values_list('pk', flat=True)), [kept.pk])
        self.assertTrue(self.storage.exists(kept.image.name))
        self.assertFalse(self.storage.exists(orphan))

    def test_command_reports_counts(self):
        out = StringIO()
        # Der Worker schließt Verbindungen nach jedem Lauf; im Test bliebe die Transaktion sonst ohne Verbindung.
        with patch('users.management.commands.purge_guest_photos.connections'):
            call_command('purge_guest_photos', '--dry-run', stdout=out)
        self.assertIn('0 abgelaufen', out.getvalue())


class GuestPhotoAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('photoadmin', 'photoadmin@example.com', 'StrongPass123!')
        self.guest = User.objects.create_user('guest', 'guest@example.com')
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.photo = GuestPhotoService.save_photo(
                user=self.guest, upload=image_upload(), actor=self.admin, source=GuestPhoto.Source.STAFF,
            )

    def set_enabled(self, enabled):
        config = GeneralConfiguration.load()
        config.extended_checkin_enabled = enabled
        config.save()

    def test_changelist_shows_photo_only_when_enabled(self):
        url = reverse('admin:users_guestphoto_changelist')
        self.set_enabled(True)
        response = self.client.get(url)
        self.assertContains(response, reverse('guest_photo', args=[self.guest.pk]))
        self.assertContains(response, reverse('admin:users_guestphoto_delete_all'))
        self.set_enabled(False)
        response = self.client.get(url)
        self.assertNotContains(response, reverse('guest_photo', args=[self.guest.pk]))
        self.assertContains(response, 'Nur bei aktivem erweitertem Check-in sichtbar')

    def test_photos_cannot_be_added_or_changed_in_admin(self):
        self.assertEqual(self.client.get(reverse('admin:users_guestphoto_add')).status_code, 403)
        response = self.client.post(reverse('admin:users_guestphoto_change', args=[self.photo.pk]), {'source': 'SELF'})
        self.assertEqual(response.status_code, 403)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.source, GuestPhoto.Source.STAFF)
        self.assertIsNone(self.photo.notice_confirmed_at)

    def test_delete_all_requires_confirmation_and_removes_files(self):
        url = reverse('admin:users_guestphoto_delete_all')
        self.assertContains(self.client.get(url), 'Es werden 1 Gastfotos')
        self.assertTrue(GuestPhoto.objects.exists())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)
        self.assertRedirects(response, reverse('admin:users_guestphoto_changelist'))
        self.assertFalse(GuestPhoto.objects.exists())
        self.assertFalse(self.photo.image.storage.exists(self.photo.image.name))

    def test_delete_all_requires_delete_permission(self):
        staff = User.objects.create_user('helper', 'helper@example.com', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(reverse('admin:users_guestphoto_delete_all')).status_code, 403)
        self.assertTrue(GuestPhoto.objects.exists())
