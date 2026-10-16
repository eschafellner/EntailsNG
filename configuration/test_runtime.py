from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from configuration.runtime import check_runtime


@override_settings(DEBUG=True, BACKUP_ENCRYPTION_KEY='')
class RuntimeChecksTests(TestCase):
    def test_healthy_development_check_does_not_write_application_data(self):
        with CaptureQueriesContext(connection) as queries:
            result = check_runtime(health_host='127.0.0.1:8000')
        self.assertTrue(all(item['ok'] for item in result.values()))
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for q in queries))

    @override_settings(ALLOWED_HOSTS=['lan.example.invalid'])
    def test_domain_only_hosts_reject_internal_healthcheck(self):
        result = check_runtime(health_host='127.0.0.1:8000')
        self.assertFalse(result['health_host']['ok'])

    def test_production_refuses_locmem_instead_of_claiming_redis_was_tested(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command('check_runtime', stdout=StringIO())
        self.assertFalse(check_runtime(require_redis=True)['cache']['ok'])

    def test_unavailable_database_is_reported_without_connection_secrets(self):
        with patch('configuration.runtime.connection.cursor', side_effect=RuntimeError('postgres://secret:password@internal')):
            result = check_runtime()
        self.assertFalse(result['database']['ok'])
        self.assertFalse(result['migrations']['ok'])
        self.assertNotIn('secret', str(result))
        self.assertNotIn('password', str(result))

    def test_pending_migration_fails(self):
        executor = SimpleNamespace(loader=SimpleNamespace(graph=SimpleNamespace(leaf_nodes=lambda: [])),
                                   migration_plan=lambda _: ['pending'])
        with patch('configuration.runtime.MigrationExecutor', return_value=executor):
            self.assertFalse(check_runtime()['migrations']['ok'])

    def test_cache_failure_is_sanitized(self):
        from django.core.cache import cache
        with patch.object(type(cache._connections['default']), 'set', side_effect=RuntimeError('redis://secret')):
            result = check_runtime()
        self.assertFalse(result['cache']['ok'])
        self.assertNotIn('secret', str(result))

    @override_settings(BACKUP_ENCRYPTION_KEY='invalid')
    def test_enabled_backup_requires_valid_key_and_matching_tools(self):
        self.assertFalse(check_runtime()['backup_tools']['ok'])

    def test_json_has_machine_readable_results(self):
        import json
        output = StringIO()
        call_command('check_runtime', as_json=True, health_host='127.0.0.1', stdout=output)
        result = json.loads(output.getvalue())
        self.assertTrue(result['database']['ok'])

