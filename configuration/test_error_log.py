from datetime import timedelta
from importlib import import_module
from io import StringIO
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve
from django.utils import timezone

from configuration.middleware import DynamicDebugMiddleware
from configuration.models import SystemErrorLog


class PublicTinyMCERoutesTests(TestCase):
    """F-004: Keine öffentlichen django-tinymce-Views, keine anonym auslösbaren 500er."""

    def test_tinymce_views_are_not_routed(self):
        client = Client(raise_request_exception=False)
        for url in ('/tinymce/flatpages_link_list/', '/tinymce/filebrowser/', '/tinymce/compressor/'):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 404)
        self.assertFalse(SystemErrorLog.objects.exists())


@override_settings(DEBUG=False)
class SystemErrorLogDeduplicationTests(TestCase):
    """F-010: Gleiche Fehler zählen hoch statt je eine neue Zeile anzulegen."""

    def capture(self, path, exc_class=RuntimeError, message='kaputt'):
        request = RequestFactory().get(path)
        request.resolver_match = resolve(path)
        try:
            raise exc_class(message)
        except Exception as exc:
            DynamicDebugMiddleware(lambda req: None).process_exception(request, exc)
        return request

    def test_repeated_error_on_same_route_is_counted(self):
        first = self.capture('/seating/api/plan/1/')
        second = self.capture('/seating/api/plan/2/', message='kaputt 2')
        self.assertEqual(SystemErrorLog.objects.count(), 1)
        log = SystemErrorLog.objects.get()
        self.assertEqual(log.occurrences, 2)
        self.assertEqual(first.system_error_id, log.pk)
        self.assertEqual(second.system_error_id, log.pk)
        self.assertGreaterEqual(log.last_seen, log.timestamp)

    def test_different_errors_get_own_entries(self):
        self.capture('/seating/api/plan/1/')
        self.capture('/seating/api/plan/1/', exc_class=ValueError)
        self.capture('/news/')
        self.assertEqual(SystemErrorLog.objects.count(), 3)

    def test_resolved_entry_is_not_reopened(self):
        self.capture('/news/')
        SystemErrorLog.objects.update(resolved=True)
        self.capture('/news/')
        self.assertEqual(SystemErrorLog.objects.count(), 2)
        self.assertEqual(SystemErrorLog.objects.get(resolved=False).occurrences, 1)


class SystemErrorLogRetentionTests(TestCase):
    """F-010: Fehlerprotokolle (inkl. IP-Adressen) werden nach der Aufbewahrungsfrist gelöscht."""

    def make_log(self, days_ago, **extra):
        log = SystemErrorLog.objects.create(
            path='/x/', exception_type='RuntimeError', error_message='x', traceback='x',
            ip_address='203.0.113.7', **extra,
        )
        SystemErrorLog.objects.filter(pk=log.pk).update(last_seen=timezone.now() - timedelta(days=days_ago))
        return log

    def test_purge_deletes_entries_older_than_retention(self):
        old = self.make_log(31)
        old_resolved = self.make_log(40, resolved=True)
        recent = self.make_log(29)
        out = StringIO()
        call_command('purge_error_logs', stdout=out)
        self.assertEqual(list(SystemErrorLog.objects.values_list('pk', flat=True)), [recent.pk])
        self.assertFalse(SystemErrorLog.objects.filter(pk__in=[old.pk, old_resolved.pk]).exists())
        self.assertIn('2', out.getvalue())

    def test_days_option_setting_and_dry_run(self):
        self.make_log(8)
        self.make_log(3)
        call_command('purge_error_logs', '--days', '7', '--dry-run', stdout=StringIO())
        self.assertEqual(SystemErrorLog.objects.count(), 2)
        with override_settings(SYSTEM_ERROR_LOG_RETENTION_DAYS=7):
            call_command('purge_error_logs', stdout=StringIO())
        self.assertEqual(SystemErrorLog.objects.count(), 1)

    def test_hourly_privacy_worker_also_purges_error_logs(self):
        self.make_log(31)
        with patch('users.management.commands.purge_guest_photos.connections'):
            call_command('purge_guest_photos', stdout=StringIO())
        self.assertFalse(SystemErrorLog.objects.exists())

    def test_migration_copies_timestamp_to_last_seen(self):
        log = self.make_log(0)
        SystemErrorLog.objects.filter(pk=log.pk).update(timestamp=timezone.now() - timedelta(days=90))
        module = import_module('configuration.migrations.0028_systemerrorlog_dedup_retention')
        module.copy_timestamp_to_last_seen(apps, None)
        log.refresh_from_db()
        self.assertEqual(log.last_seen, log.timestamp)


class ExpiredSessionCleanupTests(TestCase):
    """F-032: Der stündliche Löschfristen-Worker entfernt abgelaufene Sessions."""

    def test_expired_sessions_are_removed(self):
        from django.contrib.sessions.models import Session
        now = timezone.now()
        Session.objects.create(session_key='a' * 32, session_data='x', expire_date=now - timedelta(seconds=1))
        Session.objects.create(session_key='b' * 32, session_data='x', expire_date=now + timedelta(days=1))
        with patch('users.management.commands.purge_guest_photos.connections'):
            call_command('purge_guest_photos', stdout=StringIO())
        self.assertEqual(list(Session.objects.values_list('session_key', flat=True)), ['b' * 32])
