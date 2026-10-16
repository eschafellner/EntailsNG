import os
from pathlib import Path
import subprocess
import tempfile

from django.test import SimpleTestCase


class EntrypointInitializationTests(SimpleTestCase):
    def test_seed_failure_stops_startup_and_does_not_run_later_steps(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            log = folder / 'calls'
            python = folder / 'python'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$INIT_TEST_LOG"\n'
                              'case "$*" in *seed_features*) exit 7;; esac\n')
            python.chmod(0o755)
            result = subprocess.run(['bash', str(root / 'entrypoint.sh'), 'sh', '-c', 'echo SHOULD_NOT_START'],
                env={**os.environ, 'PATH': f'{folder}:{os.environ["PATH"]}', 'INIT_TEST_LOG': str(log),
                     'BACKUP_ROOT': str(folder), 'SKIP_ENTRYPOINT_WAIT': '1', 'SKIP_ENTRYPOINT_MIGRATION': '1',
                     'SKIP_ENTRYPOINT_INIT': '0', 'DEMO_MODE': 'False', 'LOAD_DEMO_DATA': 'False'},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 7)
            self.assertNotIn('SHOULD_NOT_START', result.stdout)
            self.assertNotIn('seed_email_templates', log.read_text())

    def test_demo_failure_propagates_without_global_deletion_or_fallback_seeds(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            log = folder / 'calls'
            python = folder / 'python'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$INIT_TEST_LOG"\n'
                              'case "$*" in *seed_demo_data*) exit 9;; esac\n')
            python.chmod(0o755)
            result = subprocess.run(['bash', str(root / 'entrypoint.sh'), 'sh', '-c', 'echo SHOULD_NOT_START'],
                env={**os.environ, 'PATH': f'{folder}:{os.environ["PATH"]}', 'INIT_TEST_LOG': str(log),
                     'BACKUP_ROOT': str(folder), 'SKIP_ENTRYPOINT_WAIT': '1', 'SKIP_ENTRYPOINT_MIGRATION': '1',
                     'SKIP_ENTRYPOINT_INIT': '0', 'DEMO_MODE': 'True'}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 9)
            self.assertNotIn('SHOULD_NOT_START', result.stdout)
            self.assertNotIn('seed_features', log.read_text())
            self.assertNotIn('loaddata', log.read_text())
