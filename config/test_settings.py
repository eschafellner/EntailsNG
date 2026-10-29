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
