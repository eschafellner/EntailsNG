#!/usr/bin/env python3
"""Fresh-database acceptance run; requires explicit ENTAILS_SETUP_SMOKE=1."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from io import StringIO

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    if os.environ.get('ENTAILS_SETUP_SMOKE') != '1' or not os.environ.get('DB_NAME', '').startswith('entails_smoke_'):
        raise SystemExit('Nur auf ausdrücklich ausgewählter Wegwerf-DB entails_smoke_* erlaubt.')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    os.environ['DEMO_MODE'] = 'True'
    os.environ['SECRET_KEY'] = secrets.token_urlsafe(50)
    os.environ['FIELD_ENCRYPTION_KEY'] = secrets.token_urlsafe(50)
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection
    from django.test import Client, override_settings
    from django.urls import reverse
    if connection.introspection.table_names():
        raise SystemExit('Setup-Smoke benötigt eine vollständig leere Datenbank; keine Daten geändert.')
    with tempfile.TemporaryDirectory(prefix='entails-setup-smoke-') as scratch:
        with override_settings(STATIC_ROOT=Path(scratch) / 'static', BACKUP_ROOT=Path(scratch) / 'backups',
                               EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_ASYNC_QUEUE=False):
            output = StringIO()
            # Prove the existing irreversible migration runs once on a fresh schema.
            from django.db.migrations.executor import MigrationExecutor
            executor = MigrationExecutor(connection)
            targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != 'tournaments']
            executor.migrate(targets + [('tournaments', '0016_draw_preview')])
            from tournaments.models import Team
            probe = get_user_model().objects.create_user('migration_probe', 'migration_probe@example.invalid', None)
            team = Team.objects.create(name='Migration probe', captain=probe, invite_code='OLDPROBE')
            call_command('migrate', interactive=False, stdout=output)
            team.refresh_from_db()
            rotated = team.invite_code
            assert rotated != 'OLDPROBE' and len(rotated) == 32
            call_command('migrate', interactive=False, stdout=output)
            team.refresh_from_db()
            assert team.invite_code == rotated, 'Repeated migrate rotated team code again'
            team.delete()
            probe.delete()
            from configuration.models import DemoDataset, NavigationItem, SystemTranslation
            from emails.models import EmailTemplate, GeneralEmailSettings, OutgoingEmail
            from events.models import Event
            models = (NavigationItem, SystemTranslation, EmailTemplate, GeneralEmailSettings)

            def snapshot():
                return {m._meta.label: list(m.objects.order_by('pk').values()) for m in models}

            for command in ('seed_translations', 'seed_features', 'seed_email_templates'):
                call_command(command, stdout=output)
            before = snapshot()
            for command in ('seed_translations', 'seed_features', 'seed_email_templates'):
                call_command(command, stdout=output)
            assert snapshot() == before, 'System-Seeds verändern bestehende Werte'
            call_command('seed_demo_data', stdout=output)
            marker = list(DemoDataset.objects.values())
            users = list(get_user_model().objects.values())
            events = list(Event.objects.values())
            call_command('seed_demo_data', stdout=output)
            assert list(DemoDataset.objects.values()) == marker
            assert list(get_user_model().objects.values()) == users
            assert list(Event.objects.values()) == events
            assert not OutgoingEmail.objects.exists()
            assert not get_user_model().objects.filter(is_superuser=True).exists()
            os.environ['DJANGO_SUPERUSER_PASSWORD'] = secrets.token_urlsafe(32)
            try:
                call_command('createsuperuser', interactive=False, username='smoke_admin',
                             email='smoke_admin@example.invalid', stdout=output)
            finally:
                os.environ.pop('DJANGO_SUPERUSER_PASSWORD', None)
            call_command('collectstatic', interactive=False, verbosity=0, stdout=output)
            call_command('check_runtime', health_host='127.0.0.1', require_redis=True, stdout=output)
            call_command('makemigrations', check_changes=True, dry_run=True, stdout=output)
            client = Client(HTTP_HOST='localhost')
            for path in ('/', '/login/', '/api/health/', '/info/', '/news/'):
                assert client.get(path, secure=True).status_code == 200, path
            client.force_login(get_user_model().objects.get(username='smoke_admin'))
            paths = ('/admin/', '/media-designer/', '/knowledge/', '/checkin/scanner/',
                     reverse('tournament_detail', kwargs={'slug': 'demo-cup'}))
            for path in paths:
                assert client.get(path, secure=True).status_code == 200, path
    print(json.dumps({'setup': 'passed', 'python': sys.version.split()[0], 'django': django.get_version(),
                      'postgresql': connection.pg_version, 'pages': 10, 'demo_guests': 4,
                      'seed_repeat': 'unchanged', 'demo_repeat': 'unchanged', 'team_code_migration': 'rotates once', 'real_smtp': False}))


if __name__ == '__main__':
    main()
