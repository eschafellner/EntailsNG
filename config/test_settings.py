import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class DatabaseHealthCheckSettingTests(SimpleTestCase):
    """F-005: Persistente DB-Verbindungen werden vor Wiederverwendung geprüft."""

    def test_health_checks_enabled_by_default(self):
        self.assertTrue(settings.DATABASES['default']['CONN_HEALTH_CHECKS'])

    def test_health_checks_can_be_disabled(self):
        env = {**os.environ, 'DB_CONN_HEALTH_CHECKS': 'False'}
        code = ("import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); "
                "django.setup(); from django.conf import settings; "
                "print(settings.DATABASES['default']['CONN_HEALTH_CHECKS'])")
        result = subprocess.run([sys.executable, '-c', code, 'test'], env=env, capture_output=True, text=True,
                                cwd=settings.BASE_DIR, check=True)
        self.assertEqual(result.stdout.strip().splitlines()[-1], 'False')


class ServerErrorHandlerTests(SimpleTestCase):
    """F-012: Die 500-Seite entsteht auch, wenn die Datenbank nicht erreichbar ist."""

    def test_handler_renders_without_database(self):
        from unittest.mock import patch
        from django.db import OperationalError
        from django.test import RequestFactory
        from config.urls import custom_500_handler

        request = RequestFactory().get('/kaputt/')
        request.system_error_id = 4711
        with patch('configuration.context_processors.feature_flags', side_effect=OperationalError('db down')), \
                patch('configuration.models.NavigationItem.objects') as nav:
            nav.filter.side_effect = OperationalError('db down')
            response = custom_500_handler(request)
        self.assertEqual(response.status_code, 500)
        self.assertIn('#4711', response.content.decode())

    def test_handler_falls_back_to_plain_text_if_template_fails(self):
        from unittest.mock import patch
        from django.test import RequestFactory
        from config.urls import custom_500_handler

        with patch('django.template.loader.render_to_string', side_effect=RuntimeError('template kaputt')):
            response = custom_500_handler(RequestFactory().get('/'))
        self.assertEqual(response.status_code, 500)
        self.assertIn('500', response.content.decode())


class EnvironmentDetectionTests(SimpleTestCase):
    """F-007: Testmodus nur über das Unterkommando 'test' oder ausdrücklich DJANGO_ENV=test."""

    def load(self, *argv, **env):
        code = ("import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); "
                "django.setup(); from django.conf import settings; print('IS_TESTING', settings.IS_TESTING); "
                "print('CACHE', settings.CACHES['default']['BACKEND'].rsplit('.', 1)[-1])")
        environ = {**os.environ, 'DEBUG': 'False', 'ALLOWED_HOSTS': 'example.org',
                   'REDIS_URL': 'redis://127.0.0.1:1/1', **env}
        environ.pop('DJANGO_ENV', None) if 'DJANGO_ENV' not in env else None
        return subprocess.run([sys.executable, '-c', code, *argv], env=environ, capture_output=True, text=True,
                              cwd=settings.BASE_DIR)

    def test_word_test_as_later_argument_is_not_test_mode(self):
        result = self.load('seed_features', 'test')
        self.assertIn('IS_TESTING False', result.stdout, result.stderr[-500:])
        self.assertIn('CACHE RedisCache', result.stdout)

    def test_subcommand_and_explicit_environment(self):
        self.assertIn('IS_TESTING True', self.load('test').stdout)
        explicit = self.load('pytest', DJANGO_ENV='test')
        self.assertIn('IS_TESTING True', explicit.stdout, explicit.stderr[-500:])
        self.assertIn('CACHE LocMemCache', explicit.stdout)


class ContentSecurityPolicyReportOnlyTests(SimpleTestCase):
    """F-006: Projektweite CSP zunächst als Report-Only."""

    def test_report_only_header_on_regular_pages(self):
        from django.test import RequestFactory
        from django.http import HttpResponse
        from django.middleware.csp import ContentSecurityPolicyMiddleware
        response = ContentSecurityPolicyMiddleware(lambda request: HttpResponse('ok'))(RequestFactory().get('/'))
        policy = response.headers.get('Content-Security-Policy-Report-Only', '')
        for directive in ("default-src 'self'", "script-src 'self'", "object-src 'none'", "base-uri 'self'"):
            self.assertIn(directive, policy)
        self.assertNotIn("'unsafe-inline'", policy.split('script-src', 1)[1].split(';', 1)[0])
        self.assertNotIn('Content-Security-Policy', response.headers)
        self.assertIn('django.middleware.csp.ContentSecurityPolicyMiddleware', settings.MIDDLEWARE)
