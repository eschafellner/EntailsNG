"""The release gate must fail closed on partial audits and vulnerable runtimes."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts import audit_dependencies, dependency_inventory


class DependencyGateTests(SimpleTestCase):
    def audit(self, report, *, exit_code=0, timeout=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / 'packages.txt'
            inventory.write_text('Django==6.0.9\npython-dotenv==1.2.4\n')
            # A stale successful report must not survive an unsuccessful request.
            (root / 'dependency-audit.json').write_text(json.dumps({'dependencies': []}))

            def run(command, **kwargs):
                if '--version' in command:
                    return subprocess.CompletedProcess(command, 0, 'pip-audit test\n', '')
                if timeout:
                    raise subprocess.TimeoutExpired(command, 300)
                if report is not None:
                    (root / 'dependency-audit.json').write_text(json.dumps(report))
                return subprocess.CompletedProcess(command, exit_code, '', '')

            arguments = ['audit_dependencies.py', '--inventory', str(inventory), '--output-dir', str(root)]
            with patch('sys.argv', arguments), patch.object(audit_dependencies.subprocess, 'run', run):
                with redirect_stdout(StringIO()), self.assertRaises(SystemExit) as raised:
                    audit_dependencies.main()
            return raised.exception.code, json.loads((root / 'audit-summary.json').read_text())

    def clean_report(self):
        return {'dependencies': [
            {'name': 'django', 'version': '6.0.9', 'vulns': []},
            {'name': 'python-dotenv', 'version': '1.2.4', 'vulns': []},
        ]}

    def test_complete_clean_audit_passes(self):
        code, summary = self.audit(self.clean_report())
        self.assertEqual(code, 0)
        self.assertTrue(summary['complete'])

    def test_missing_package_fails_even_with_zero_tool_exit(self):
        report = self.clean_report()
        report['dependencies'].pop()
        code, summary = self.audit(report)
        self.assertEqual(code, 1)
        self.assertFalse(summary['complete'])

    def test_skipped_package_fails(self):
        report = self.clean_report()
        report['dependencies'][0]['skip_reason'] = 'No audit data'
        self.assertEqual(self.audit(report)[0], 1)

    def test_package_without_vulnerability_result_fails(self):
        report = self.clean_report()
        del report['dependencies'][0]['vulns']
        self.assertEqual(self.audit(report)[0], 1)

    def test_findings_fail_and_duplicate_advisories_are_grouped(self):
        report = self.clean_report()
        report['dependencies'][0]['vulns'] = [
            {'id': 'GHSA-example', 'aliases': ['CVE-2026-example']},
            {'id': 'PYSEC-example', 'aliases': ['CVE-2026-example']},
        ]
        code, summary = self.audit(report)
        self.assertEqual(code, 1)
        self.assertEqual(len(summary['findings']), 1)
        self.assertEqual(summary['findings'][0]['ids'], ['CVE-2026-example', 'GHSA-example', 'PYSEC-example'])

    def test_collection_failure_fails_even_with_complete_report(self):
        self.assertEqual(self.audit(self.clean_report(), exit_code=1)[0], 1)

    def test_timeout_removes_stale_report_and_fails(self):
        code, summary = self.audit(None, timeout=True)
        self.assertEqual(code, 1)
        self.assertFalse(summary['passed'])
        self.assertFalse(summary['complete'])
        self.assertIn('TimeoutExpired', summary['error'])

    def test_lockfile_pin_with_hashes_is_recognised(self):
        import django
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'requirements.txt').write_text(
                f'asgiref==3.13.0 \\\n    --hash=sha256:00\ndjango=={django.get_version()} \\\n'
                '    --hash=sha256:11 \\\n    --hash=sha256:22\n    # via -r requirements.in\n')
            with patch.object(dependency_inventory, 'ROOT', root):
                packages = dependency_inventory.inventory()
            self.assertTrue(packages)

    def test_downgrading_pin_and_runtime_does_not_bypass_security_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'requirements.txt').write_text('Django==6.0.7\n')
            with patch.object(dependency_inventory, 'ROOT', root):
                with patch('django.get_version', return_value='6.0.7'), patch('django.VERSION', (6, 0, 7, 'final', 0)):
                    with self.assertRaisesRegex(RuntimeError, 'security baseline mismatch'):
                        dependency_inventory.inventory()
