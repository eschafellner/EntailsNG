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
from events.services import PaymentService, RegistrationService
from users.models import GuestPhoto
from users.services import GuestPhotoService

User = get_user_model()


def image_upload(name='checkin.jpg'):
    stream = BytesIO()
    Image.new('RGB', (40, 40), 'green').save(stream, format='JPEG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/jpeg')


class ExtendedCheckInTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='photo_staff', is_staff=True)
        cls.guest = User.objects.create_user(username='PhotoGast', first_name='Foto', last_name='Gast')
        start = timezone.now() + timedelta(days=1)
        cls.event = Event.objects.create(
            title='Foto LAN', slug='foto-lan', is_active=True, max_guests=100,
            status=Event.Status.REGISTRATION_OPEN, start_date=start, end_date=start + timedelta(days=2),
        )
        cls.ticket = TicketType.objects.create(event=cls.event, name='Weekend', price=0)
        cls.registration = EventRegistration.objects.create(
            user=cls.guest, event=cls.event, ticket_type=cls.ticket,
            payment_status=EventRegistration.PaymentStatus.PAID,
        )

    def setUp(self):
        cache.clear()
        self.set_enabled(True)
        self.client.force_login(self.staff)

    def set_enabled(self, enabled):
        config = GeneralConfiguration.load()
        config.extended_checkin_enabled = enabled
        config.save()

    def store_photo(self):
        with self.captureOnCommitCallbacks(execute=True):
            return GuestPhotoService.save_photo(
                user=self.guest, upload=image_upload(), actor=self.guest, source=GuestPhoto.Source.SELF,
            )

    def scan(self):
        return self.client.post(reverse('api_scan_qr'), {'code': self.registration.short_code},
                                content_type='application/json')

    def toggle(self):
        return self.client.post(reverse('api_toggle_check_in'), {'registration_id': self.registration.pk},
                                content_type='application/json')

    def upload(self, registration_id=None, **files):
        data = {'registration_id': str(registration_id or self.registration.pk), **files}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('api_checkin_photo'), data)

    def assert_checked_in(self, expected):
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.is_checked_in, expected)

    def test_rule_requires_photo_only_when_enabled_and_not_yet_checked_in(self):
        result = self.registration.can_check_in(target_event=self.event)
        self.assertEqual((result.allowed, result.code), (False, 'photo_required'))
        self.assertIn('PhotoGast', result.reason)
        self.set_enabled(False)
        self.assertTrue(self.registration.can_check_in(target_event=self.event).allowed)
        self.set_enabled(True)
        self.store_photo()
        self.assertTrue(self.registration.can_check_in(target_event=self.event).allowed)

    def test_other_rejections_take_precedence(self):
        EventRegistration.objects.filter(pk=self.registration.pk).update(
            payment_status=EventRegistration.PaymentStatus.UNPAID)
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.can_check_in(target_event=self.event).code, 'unpaid')

    def test_scan_without_photo_is_blocked_and_names_the_registration(self):
        response = self.scan()
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body['status'], 'photo_required')
        self.assertEqual(body['registration_id'], self.registration.pk)
        self.assertIsNone(body['photo_url'])
        self.assert_checked_in(False)

    def test_scan_with_photo_returns_photo_url(self):
        photo = self.store_photo()
        body = self.scan().json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(
            body['photo_url'],
            f"{reverse('guest_photo', args=[self.guest.pk])}?v={int(photo.captured_at.timestamp())}",
        )
        self.assertEqual(self.client.get(body['photo_url']).status_code, 200)
        self.assert_checked_in(True)

    def test_disabled_feature_hides_photo_and_allows_check_in(self):
        self.store_photo()
        self.set_enabled(False)
        body = self.scan().json()
        self.assertEqual(body['status'], 'success')
        self.assertIsNone(body['photo_url'])

    def test_already_checked_in_guest_without_photo_is_not_blocked(self):
        EventRegistration.objects.filter(pk=self.registration.pk).update(
            is_checked_in=True, checked_in_at=timezone.now())
        self.assertEqual(self.scan().json()['status'], 'already_checked_in')

    def test_toggle_blocks_check_in_but_allows_check_out(self):
        response = self.toggle()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'][:22], 'Check-in nicht möglich')
        self.assert_checked_in(False)
        EventRegistration.objects.filter(pk=self.registration.pk).update(
            is_checked_in=True, checked_in_at=timezone.now())
        self.assertEqual(self.toggle().json()['is_checked_in'], False)

    def test_checkin_link_is_blocked_without_photo(self):
        url = reverse('process_checkin', args=[self.registration.pk, self.registration.checkin_token])
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assert_checked_in(False)

    def test_photo_endpoint_saves_staff_photo_and_checks_in(self):
        response = self.upload(photo=image_upload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['status'], 'success')
        self.assertTrue(body['photo_url'])
        photo = GuestPhoto.objects.get(user=self.guest)
        self.assertEqual((photo.source, photo.uploaded_by), (GuestPhoto.Source.STAFF, self.staff))
        self.assertIsNone(photo.notice_confirmed_at)
        self.assert_checked_in(True)

    def test_photo_endpoint_rejects_without_saving(self):
        EventRegistration.objects.filter(pk=self.registration.pk).update(
            payment_status=EventRegistration.PaymentStatus.UNPAID)
        self.assertEqual(self.upload(photo=image_upload()).json()['status'], 'unpaid')
        EventRegistration.objects.filter(pk=self.registration.pk).update(
            payment_status=EventRegistration.PaymentStatus.PAID)
        self.assertEqual(self.upload().status_code, 400)
        self.assertEqual(self.upload(photo=SimpleUploadedFile('x.jpg', b'kein Bild')).status_code, 400)
        self.assertEqual(self.upload(registration_id='abc', photo=image_upload()).status_code, 400)
        self.assertFalse(GuestPhoto.objects.exists())
        self.assert_checked_in(False)

    def test_photo_endpoint_requires_staff_post_and_enabled_feature(self):
        self.assertEqual(self.client.get(reverse('api_checkin_photo')).status_code, 405)
        self.set_enabled(False)
        self.assertEqual(self.upload(photo=image_upload()).status_code, 404)
        self.set_enabled(True)
        self.client.force_login(self.guest)
        self.assertEqual(self.upload(photo=image_upload()).status_code, 302)
        self.assertFalse(GuestPhoto.objects.exists())

    def test_guest_list_marks_missing_photos(self):
        url = reverse('checkin_scanner')
        self.assertContains(self.client.get(url), 'scanner-badge-nophoto')
        self.assertIn('scanner-badge-nophoto', self.client.get(url, {'partial': '1'}).json()['rows_html'])
        self.store_photo()
        self.assertNotContains(self.client.get(url), 'scanner-badge-nophoto')
        GuestPhoto.objects.all().delete()
        self.set_enabled(False)
        self.assertNotContains(self.client.get(url), 'scanner-badge-nophoto')

    def test_scanner_page_contains_photo_capture(self):
        response = self.client.get(reverse('checkin_scanner'))
        self.assertContains(response, 'id="scan-photo-capture"')
        self.assertContains(response, 'capture="environment"')

    def test_registration_and_cancellation_refresh_photo_deadline(self):
        photo = self.store_photo()
        Event.objects.filter(pk=self.event.pk).update(is_active=False)
        cache.clear()
        later = Event.objects.create(
            title='Spätere LAN', slug='spaetere-lan', is_active=True, max_guests=100,
            status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=30), end_date=timezone.now() + timedelta(days=32),
        )
        TicketType.objects.create(event=later, name='Weekend', price=0)
        registration, _, _ = RegistrationService.register_user(self.guest, later.pk)
        photo.refresh_from_db()
        self.assertEqual(photo.delete_after, later.end_date + timedelta(days=14))
        PaymentService.mark_cancelled(registration)
        photo.refresh_from_db()
        self.assertEqual(photo.delete_after, self.event.end_date + timedelta(days=14))
