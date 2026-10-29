import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase


class WorkerHeartbeatTests(TestCase):
    """F-039: Worker melden erfolgreiche Durchläufe über eine Heartbeat-Datei (Compose-Healthcheck)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'heartbeat'
        patcher = patch.dict(os.environ, {'WORKER_HEARTBEAT_FILE': str(self.path)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_guest_photo_and_clan_workers_touch_heartbeat(self):
        for command, module in (('purge_guest_photos', 'users.management.commands.purge_guest_photos'),
                                ('process_clan_seat_holds', 'seating.management.commands.process_clan_seat_holds')):
            with self.subTest(command=command):
                self.path.unlink(missing_ok=True)
                with patch(f'{module}.connections'):
                    call_command(command, stdout=StringIO())
                self.assertTrue(self.path.exists())

    def test_failed_run_does_not_touch_heartbeat(self):
        with patch('users.management.commands.purge_guest_photos.connections'), \
                patch('users.services.GuestPhotoService.purge', side_effect=RuntimeError('kaputt')), \
                self.assertRaises(RuntimeError):
            call_command('purge_guest_photos', stdout=StringIO())
        self.assertFalse(self.path.exists())


class EmailWorkerHeartbeatTests(SimpleTestCase):
    def test_email_worker_touches_heartbeat_only_after_success(self):
        import signal
        module = 'emails.management.commands.process_email_queue'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'heartbeat'
            seen = []

            def run(limit):
                seen.append(path.exists())
                if len(seen) == 1:
                    raise RuntimeError('kaputt')
                if len(seen) == 3:
                    os.kill(os.getpid(), signal.SIGTERM)
                return (0, 0)

            with patch.dict(os.environ, {'WORKER_HEARTBEAT_FILE': str(path)}), \
                    patch(f'{module}.process_email_queue', side_effect=run), \
                    patch(f'{module}.close_old_connections'), self.assertLogs(module, level='ERROR'):
                call_command('process_email_queue', '--daemon', '--interval', '0', stdout=StringIO())
            self.assertEqual(seen, [False, False, True])
            self.assertTrue(path.exists())
