"""Regression checks for review PROJECT-02/03/04 without live Docker services."""
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock

from django.contrib import admin
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


class AdminActionPermissionTests(SimpleTestCase):
    def test_read_only_staff_cannot_select_any_mutating_action(self):
        request = Mock(method='POST', GET={})
        request.user.has_perm.side_effect = lambda p: '.view_' in p
        for model_admin in admin.site._registry.values():
            with self.subTest(model=model_admin.model._meta.label):
                self.assertLessEqual(set(model_admin.get_actions(request)), {'export_as_csv'})


class CertificateBootstrapTests(SimpleTestCase):
    def run_bootstrap(self, *, lineage=False, fail=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text('DOMAIN_NAME=lan.example.org\nCERTBOT_EMAIL=ops@example.org\n')
            cert = root / 'data/certbot/conf/live/lan.example.org'
            cert.mkdir(parents=True)
            (cert / 'fullchain.pem').write_text('fallback')
            (cert / 'privkey.pem').write_text('fallback')
            if lineage:
                renewal = root / 'data/certbot/conf/renewal'
                renewal.mkdir()
                (renewal / 'lan.example.org.conf').touch()
            log = root / 'docker.log'
            docker = root / 'docker'
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$REVIEW_DOCKER_LOG"\n'
                              + ('case "$*" in *certonly*) exit 1;; esac\n' if fail else ''))
            docker.chmod(0o755)
            result = subprocess.run(['bash', str(ROOT / 'nginx/init-letsencrypt.sh')], cwd=root,
                                    env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}',
                                         'REVIEW_DOCKER_LOG': str(log)}, capture_output=True)
            return result.returncode, log.read_text()

    def test_existing_fallback_is_reissued_and_renewal_service_started(self):
        code, log = self.run_bootstrap()
        self.assertEqual(code, 0)
        self.assertIn('certonly', log)
        self.assertIn('--profile vps up -d', log)
        self.assertIn('nginx -s reload', log)

    def test_existing_certbot_lineage_is_preserved(self):
        code, log = self.run_bootstrap(lineage=True)
        self.assertEqual(code, 0)
        self.assertNotIn('--entrypoint rm', log)
        self.assertIn('certonly', log)

    def test_failed_issuance_does_not_report_success_or_reload(self):
        code, log = self.run_bootstrap(fail=True)
        self.assertNotEqual(code, 0)
        self.assertNotIn('nginx -s reload', log)
        self.assertNotIn('--profile vps up -d', log)
