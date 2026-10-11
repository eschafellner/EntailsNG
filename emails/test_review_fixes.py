from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .models import EmailTemplate, GeneralEmailSettings, OutgoingEmail
from .services import process_email_queue, queue_system_email


class EmailLeaseRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.email = OutgoingEmail.objects.create(template_key='review-mail', recipient_email='review@example.org',
                                                  subject='Review', body_text='Mail')

    def claimed(self, worker='A'):
        email = OutgoingEmail.objects.get(pk=self.email.pk)
        self.assertTrue(email.mark_processing(worker_id=worker))
        return email

    def replace_owner_and_send(self):
        OutgoingEmail.objects.filter(pk=self.email.pk).update(worker_id='B')
        replacement = OutgoingEmail.objects.get(pk=self.email.pk)
        self.assertTrue(replacement.mark_sent(worker_id='B'))

    def test_stale_failure_pause_expiry_and_success_cannot_overwrite_sent(self):
        stale = self.claimed()
        self.replace_owner_and_send()
        for update in [lambda: stale.mark_failed_attempt('old failure'), lambda: stale.mark_paused(),
                       lambda: stale.mark_expired(), lambda: stale.mark_sent(worker_id='A')]:
            self.assertFalse(update())
        self.email.refresh_from_db()
        self.assertEqual(self.email.status, 'SENT')
        self.assertEqual(self.email.attempts, 0)
        self.assertIsNotNone(self.email.sent_at)

    def test_recovery_snapshot_cannot_clear_new_owner_or_renewed_lease(self):
        stale = self.claimed()
        past = timezone.now() - timedelta(seconds=10)
        OutgoingEmail.objects.filter(pk=self.email.pk).update(lease_expires_at=past)
        stale.refresh_from_db()
        self.assertTrue(stale.mark_stale_recovered(300))
        replacement = self.claimed('B')
        before = replacement.lease_expires_at
        self.assertFalse(stale.mark_stale_recovered(300))
        replacement.refresh_from_db()
        self.assertEqual(replacement.worker_id, 'B')
        self.assertEqual(replacement.lease_expires_at, before)

    def test_expired_worker_cannot_renew_or_revive_lease(self):
        owner = self.claimed()
        OutgoingEmail.objects.filter(pk=self.email.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(owner.renew_lease(worker_id='A', lease_seconds=300))

    def test_stale_admin_retry_cannot_reset_processing_or_sent_rows(self):
        snapshot = OutgoingEmail.objects.get(pk=self.email.pk)
        self.claimed()
        self.assertFalse(snapshot.reset_for_retry())
        self.replace_owner_and_send()
        self.assertFalse(snapshot.reset_for_retry())

    def test_late_smtp_failure_is_ignored_and_lease_is_extended_before_send(self):
        cfg = GeneralEmailSettings.load()
        cfg.is_enabled = True
        cfg.save()
        def late_error(*args, **kwargs):
            current = OutgoingEmail.objects.get(pk=self.email.pk)
            self.assertGreater(current.lease_expires_at, timezone.now() + timedelta(seconds=250))
            self.replace_owner_and_send()
            raise TimeoutError('Old worker timed out')
        with patch('emails.services.EmailMultiAlternatives.send', side_effect=late_error):
            self.assertEqual(process_email_queue(email_ids=[self.email.pk]), (0, 0))
        self.email.refresh_from_db()
        self.assertEqual(self.email.status, 'SENT')

    def test_expanded_subject_is_bounded_before_postgresql_insert(self):
        EmailTemplate.objects.create(key='review-subject', name='Review',
                                    subject='{event_title}{event_title}{event_title}', content='<p>Mail</p>')
        queued = queue_system_email('review-subject', 'review@example.org', {'event_title': 'E' * 100}, trigger_worker=False)
        self.assertEqual(queued.subject, 'E' * 255)
        queued.refresh_from_db()
        self.assertEqual(len(queued.subject), 255)
