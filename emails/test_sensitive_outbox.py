from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import OutgoingEmail


class SensitiveOutboxContentTests(TestCase):
    """F-020: Passwort-Reset-Links dürfen weder im Admin lesbar sein noch nach Abschluss gespeichert bleiben."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_user('f020-admin', email='admin@example.org', password='Sehr-sicheres-Passwort-42',
                                              is_staff=True, is_superuser=True)
        self.support = User.objects.create_user('f020-support', email='support@example.org', is_staff=True)
        self.support.user_permissions.add(Permission.objects.get(codename='view_outgoingemail'))

    def tearDown(self):
        cache.clear()

    def request_reset(self):
        self.client.post(reverse('password_reset'), {'email': self.admin.email})
        self.client.logout()
        outgoing = OutgoingEmail.objects.get(template_key='password_reset', recipient_email=self.admin.email)
        self.assertIn('/password-reset-confirm/', outgoing.body_text)
        return outgoing

    def plain(self, **kwargs):
        return OutgoingEmail.objects.create(template_key='payment_confirmation', recipient_email='gast@example.org',
                                            subject='Zahlung', body_text='Normaler Inhalt', body_html='<p>Normaler Inhalt</p>', **kwargs)

    def test_view_only_staff_cannot_read_pending_reset_link(self):
        outgoing = self.request_reset()
        self.client.force_login(self.support)
        response = self.client.get(reverse('admin:emails_outgoingemail_change', args=[outgoing.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '/password-reset-confirm/')
        self.assertNotContains(response, outgoing.body_text.split('/password-reset-confirm/')[1].split('/')[0])

    def test_reset_content_cleared_after_send(self):
        outgoing = self.request_reset()
        self.assertTrue(outgoing.mark_processing(worker_id='w1'))
        self.assertTrue(outgoing.mark_sent(worker_id='w1'))
        outgoing.refresh_from_db()
        self.assertEqual((outgoing.body_text, outgoing.body_html), ('', ''))

    def test_reset_content_cleared_after_expiry_and_final_failure(self):
        expired = self.request_reset()
        self.assertTrue(expired.mark_processing(worker_id='w1'))
        self.assertTrue(expired.mark_expired(worker_id='w1'))
        expired.refresh_from_db()
        self.assertEqual((expired.body_text, expired.body_html), ('', ''))
        OutgoingEmail.objects.all().delete()

        failing = self.request_reset()
        OutgoingEmail.objects.filter(pk=failing.pk).update(attempts=failing.max_attempts - 1)
        failing.refresh_from_db()
        self.assertTrue(failing.mark_processing(worker_id='w1'))
        self.assertTrue(failing.mark_failed_attempt('SMTP down', worker_id='w1'))
        failing.refresh_from_db()
        self.assertEqual(failing.status, OutgoingEmail.Status.FAILED)
        self.assertEqual((failing.body_text, failing.body_html), ('', ''))

    def test_cleared_reset_mail_is_not_retried_empty(self):
        outgoing = self.request_reset()
        self.assertTrue(outgoing.mark_processing(worker_id='w1'))
        self.assertTrue(outgoing.mark_expired(worker_id='w1'))
        outgoing.refresh_from_db()
        self.assertFalse(outgoing.reset_for_retry())
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.EXPIRED)

    def test_temporary_failure_keeps_reset_content_for_retry(self):
        outgoing = self.request_reset()
        body = outgoing.body_text
        self.assertTrue(outgoing.mark_processing(worker_id='w1'))
        self.assertTrue(outgoing.mark_failed_attempt('SMTP kurz weg', worker_id='w1'))
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.PENDING)
        self.assertEqual(outgoing.body_text, body)

    def test_regular_mail_content_kept_and_visible(self):
        outgoing = self.plain()
        self.assertTrue(outgoing.mark_processing(worker_id='w1'))
        self.assertTrue(outgoing.mark_sent(worker_id='w1'))
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.body_text, 'Normaler Inhalt')
        self.client.force_login(self.support)
        response = self.client.get(reverse('admin:emails_outgoingemail_change', args=[outgoing.pk]))
        self.assertContains(response, 'Normaler Inhalt')

    def test_stale_recovery_final_failure_clears_reset_content(self):
        outgoing = self.request_reset()
        OutgoingEmail.objects.filter(pk=outgoing.pk).update(attempts=outgoing.max_attempts - 1)
        outgoing.refresh_from_db()
        self.assertTrue(outgoing.mark_processing(worker_id='w1', lease_seconds=-1))
        outgoing.refresh_from_db()
        self.assertTrue(outgoing.mark_stale_recovered(timeout_seconds=1))
        outgoing.refresh_from_db()
        self.assertEqual(outgoing.status, OutgoingEmail.Status.FAILED)
        self.assertEqual((outgoing.body_text, outgoing.body_html), ('', ''))

    def test_migration_clears_finished_reset_mails_only(self):
        from importlib import import_module
        from django.apps import apps
        finished = self.request_reset()
        OutgoingEmail.objects.filter(pk=finished.pk).update(status=OutgoingEmail.Status.SENT)
        pending = OutgoingEmail.objects.create(template_key='password_reset', recipient_email='x@example.org',
                                               subject='Reset', body_text='Link', body_html='<a>Link</a>')
        regular = self.plain(status=OutgoingEmail.Status.SENT)
        import_module('emails.migrations.0010_clear_sensitive_outbox_content').clear_sensitive_content(apps, None)
        finished.refresh_from_db(); pending.refresh_from_db(); regular.refresh_from_db()
        self.assertEqual((finished.body_text, finished.body_html), ('', ''))
        self.assertEqual(pending.body_text, 'Link')
        self.assertEqual(regular.body_text, 'Normaler Inhalt')
