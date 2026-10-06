from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import signing
from django.db import close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import OutgoingEmail


class CleanupFixtures:
    def setUp(self):
        self.now = timezone.now()
        self.user = get_user_model().objects.create_superuser(
            username='cleanup_admin', email='cleanup@example.com', password='test-password',
        )
        self.client.force_login(self.user)
        self.url = reverse('admin:emails_outgoingemail_changelist')

    def email(self, age, status=OutgoingEmail.Status.SENT, **kwargs):
        email = OutgoingEmail.objects.create(
            recipient_email='recipient@example.com', subject='Alte Nachricht',
            body_text='Text', body_html='<p>Text</p>', status=status, **kwargs,
        )
        OutgoingEmail.objects.filter(pk=email.pk).update(created_at=self.now - age)
        return email

    def preview(self, days=30, **kwargs):
        with patch('emails.admin.timezone.now', return_value=self.now):
            return self.client.post(kwargs.pop('url', self.url), {
                'action': f'delete_older_than_{days}_days', 'index': '0', **kwargs,
            })

    def confirm(self, preview, **kwargs):
        return self.client.post(kwargs.pop('url', self.url), {
            'action': preview.context_data['action'],
            'cleanup_token': preview.context_data['cleanup_token'],
            'confirm_cleanup': 'yes', **kwargs,
        })


class OutgoingEmailCleanupAdminTests(CleanupFixtures, TestCase):
    def test_all_four_actions_use_strict_creation_age_and_log_deletions(self):
        for days in (30, 90, 180, 365):
            with self.subTest(days=days):
                old = self.email(timedelta(days=days, seconds=1))
                boundary = self.email(timedelta(days=days))
                recent = self.email(timedelta(days=days) - timedelta(seconds=1))
                response = self.preview(days)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context_data['count'], 1)
                self.assertTrue(OutgoingEmail.objects.filter(pk=old.pk).exists())
                self.assertEqual(self.confirm(response).status_code, 302)
                self.assertFalse(OutgoingEmail.objects.filter(pk=old.pk).exists())
                self.assertEqual(OutgoingEmail.objects.filter(pk__in=[boundary.pk, recent.pk]).count(), 2)
                log = LogEntry.objects.get(object_id=str(old.pk), action_flag=DELETION)
                self.assertEqual(log.user_id, self.user.pk)
                OutgoingEmail.objects.all().delete()

    def test_actions_are_available_in_dropdown(self):
        self.email(timedelta(days=1))
        response = self.client.get(self.url)
        for days in (30, 90, 180, 365):
            self.assertContains(response, f'Alle Emails älter als {days} Tage löschen')

    def test_global_cleanup_ignores_selection_search_and_filters(self):
        old = self.email(timedelta(days=31), template_key='outside_filter')
        other_old = self.email(timedelta(days=40), status=OutgoingEmail.Status.FAILED)
        selected = self.email(timedelta(days=1), status=OutgoingEmail.Status.PENDING)
        filtered_url = self.url + '?status__exact=PENDING&q=no-match'
        response = self.preview(url=filtered_url, _selected_action=str(selected.pk))
        self.assertEqual(response.context_data['count'], 2)
        self.assertEqual(self.confirm(response, url=filtered_url).status_code, 302)
        self.assertFalse(OutgoingEmail.objects.filter(pk__in=[old.pk, other_old.pk]).exists())
        self.assertTrue(OutgoingEmail.objects.filter(pk=selected.pk).exists())

    def test_creation_time_determines_age_even_when_sent_recently(self):
        old = self.email(timedelta(days=31), sent_at=self.now)
        recent = self.email(timedelta(days=1), sent_at=self.now - timedelta(days=60))
        self.confirm(self.preview())
        self.assertFalse(OutgoingEmail.objects.filter(pk=old.pk).exists())
        self.assertTrue(OutgoingEmail.objects.filter(pk=recent.pk).exists())

    def test_all_statuses_except_processing_are_removed(self):
        for status in OutgoingEmail.Status.values:
            self.email(timedelta(days=31), status=status)
        response = self.preview()
        self.assertEqual(response.context_data['count'], 4)
        self.assertEqual(response.context_data['processing_count'], 1)
        self.confirm(response)
        self.assertEqual(list(OutgoingEmail.objects.values_list('status', flat=True)), [OutgoingEmail.Status.PROCESSING])

    def test_worker_claim_between_preview_and_confirmation_is_preserved(self):
        old = self.email(timedelta(days=31), status=OutgoingEmail.Status.PENDING)
        response = self.preview()
        OutgoingEmail.objects.filter(pk=old.pk).update(status=OutgoingEmail.Status.PROCESSING)
        self.confirm(response)
        self.assertTrue(OutgoingEmail.objects.filter(pk=old.pk).exists())
        self.assertFalse(LogEntry.objects.filter(action_flag=DELETION).exists())

    def test_confirmation_keeps_original_cutoff_when_time_passes(self):
        old = self.email(timedelta(days=31))
        newer = self.email(timedelta(days=29))
        response = self.preview()
        with patch('emails.admin.timezone.now', return_value=self.now + timedelta(days=3)):
            self.confirm(response)
        self.assertFalse(OutgoingEmail.objects.filter(pk=old.pk).exists())
        self.assertTrue(OutgoingEmail.objects.filter(pk=newer.pk).exists())

    def test_preview_is_limited_to_50_and_escapes_subjects(self):
        for _ in range(51):
            self.email(timedelta(days=31))
        email = self.email(timedelta(days=40))
        OutgoingEmail.objects.filter(pk=email.pk).update(subject='<script>alert(1)</script>')
        response = self.preview()
        self.assertEqual(response.context_data['count'], 52)
        self.assertEqual(len(response.context_data['preview']), 50)
        self.assertContains(response, '(die ersten 50 Einträge)')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_empty_cleanup_shows_message(self):
        self.email(timedelta(days=1))
        response = self.preview()
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertContains(self.client.get(self.url), 'Keine löschbaren E-Mails älter als 30 Tage vorhanden.')

    def test_invalid_or_missing_confirmation_token_does_not_delete(self):
        self.email(timedelta(days=31))
        response = self.preview()
        for token in ('', 'tampered-token'):
            with self.subTest(token=token):
                result = self.confirm(response, cleanup_token=token)
                self.assertEqual(result.status_code, 302)
                self.assertEqual(OutgoingEmail.objects.count(), 1)

    def test_expired_confirmation_does_not_delete(self):
        self.email(timedelta(days=31))
        response = self.preview()
        with patch('django.core.signing.time.time', return_value=signing.time.time() + 3601):
            self.confirm(response)
        self.assertEqual(OutgoingEmail.objects.count(), 1)

    def test_confirmation_cannot_be_reused_for_another_threshold(self):
        self.email(timedelta(days=400))
        self.confirm(self.preview(), action='delete_older_than_365_days')
        self.assertEqual(OutgoingEmail.objects.count(), 1)

    def test_confirmation_cannot_be_reused_by_another_user(self):
        self.email(timedelta(days=31))
        response = self.preview()
        other = get_user_model().objects.create_superuser(username='other_admin', email='other@example.com', password='test-password')
        self.client.force_login(other)
        self.confirm(response)
        self.assertEqual(OutgoingEmail.objects.count(), 1)

    def test_permission_required_for_dropdown_and_direct_post(self):
        self.email(timedelta(days=31))
        staff = get_user_model().objects.create_user(username='viewer', is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename='view_outgoingemail'))
        self.client.force_login(staff)
        response = self.client.get(self.url)
        self.assertNotContains(response, 'delete_older_than_30_days')
        self.assertEqual(self.preview().status_code, 403)
        self.assertEqual(OutgoingEmail.objects.count(), 1)

    def test_view_and_delete_permissions_are_sufficient(self):
        self.email(timedelta(days=31))
        staff = get_user_model().objects.create_user(username='cleanup_staff', is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=['view_outgoingemail', 'delete_outgoingemail']))
        self.client.force_login(staff)
        self.confirm(self.preview())
        self.assertEqual(OutgoingEmail.objects.count(), 0)

    def test_revoked_delete_permission_prevents_confirmation(self):
        self.email(timedelta(days=31))
        staff = get_user_model().objects.create_user(username='revoked_staff', is_staff=True)
        perms = Permission.objects.filter(codename__in=['view_outgoingemail', 'delete_outgoingemail'])
        staff.user_permissions.add(*perms)
        self.client.force_login(staff)
        response = self.preview()
        staff.user_permissions.remove(Permission.objects.get(codename='delete_outgoingemail'))
        self.assertEqual(self.confirm(response).status_code, 403)
        self.assertEqual(OutgoingEmail.objects.count(), 1)

    def test_csrf_is_required(self):
        self.email(timedelta(days=31))
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(self.url, {'action': 'delete_older_than_30_days', 'index': '0'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(OutgoingEmail.objects.count(), 1)

    def test_action_index_uses_clicked_dropdown(self):
        self.email(timedelta(days=100))
        response = self.preview(action=['delete_older_than_30_days', 'delete_older_than_90_days'], index='1')
        self.assertEqual(response.context_data['days'], 90)

    def test_regular_delete_selected_keeps_selection_and_confirmation(self):
        selected = self.email(timedelta(days=1))
        other = self.email(timedelta(days=1))
        response = self.client.post(self.url, {'action': 'delete_selected', 'index': '0', '_selected_action': selected.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(OutgoingEmail.objects.count(), 2)
        self.client.post(self.url, {'action': 'delete_selected', 'post': 'yes', '_selected_action': selected.pk})
        self.assertFalse(OutgoingEmail.objects.filter(pk=selected.pk).exists())
        self.assertTrue(OutgoingEmail.objects.filter(pk=other.pk).exists())

    def test_retry_action_still_requires_selection(self):
        old = self.email(timedelta(days=31), status=OutgoingEmail.Status.FAILED)
        response = self.client.post(self.url, {'action': 'retry_outgoing_emails', 'index': '0'})
        self.assertEqual(response.status_code, 302)
        old.refresh_from_db()
        self.assertEqual(old.status, OutgoingEmail.Status.FAILED)


class OutgoingEmailCleanupLockTests(CleanupFixtures, TransactionTestCase):
    def test_cleanup_skips_worker_locked_rows(self):
        locked = self.email(timedelta(days=31), status=OutgoingEmail.Status.PENDING)
        unlocked = self.email(timedelta(days=31))
        response = self.preview()
        acquired = Event()
        release = Event()

        def hold_worker_lock():
            close_old_connections()
            try:
                with transaction.atomic():
                    OutgoingEmail.objects.select_for_update().get(pk=locked.pk)
                    acquired.set()
                    if not release.wait(timeout=10):
                        raise TimeoutError('Worker lock not released')
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            worker = executor.submit(hold_worker_lock)
            try:
                self.assertTrue(acquired.wait(timeout=5))
                self.assertEqual(self.confirm(response).status_code, 302)
                self.assertTrue(OutgoingEmail.objects.filter(pk=locked.pk).exists())
                self.assertFalse(OutgoingEmail.objects.filter(pk=unlocked.pk).exists())
            finally:
                release.set()
            worker.result(timeout=5)
