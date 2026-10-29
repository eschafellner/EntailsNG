import os
import signal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import OperationalError
from django.test import SimpleTestCase

MODULE = 'emails.management.commands.process_email_queue'


class EmailWorkerLoopTests(SimpleTestCase):
    """F-022: Der Daemon übersteht Fehler einzelner Durchläufe und endet geordnet bei SIGTERM."""

    def test_survives_database_error_and_stops_on_sigterm(self):
        calls = []

        def run(limit):
            calls.append(limit)
            if len(calls) == 1:
                raise OperationalError('server closed the connection unexpectedly')
            if len(calls) == 3:
                os.kill(os.getpid(), signal.SIGTERM)
            return (1, 0)

        previous = signal.getsignal(signal.SIGTERM)
        out = StringIO()
        with patch(f'{MODULE}.process_email_queue', side_effect=run), \
                patch(f'{MODULE}.close_old_connections') as close, \
                self.assertLogs(MODULE, level='ERROR') as logs:
            call_command('process_email_queue', '--daemon', '--interval', '0', stdout=out)
        self.assertEqual(len(calls), 3)
        self.assertGreaterEqual(close.call_count, 3)
        self.assertIn('Queue-Durchlauf fehlgeschlagen', '\n'.join(logs.output))
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)
