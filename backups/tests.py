import base64
import io
import json
import os
import stat
import tempfile
import threading
import zipfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

from . import archive, database, services, storage
from .errors import BackupError
from .locking import FileLock, access_guard
from .middleware import BackupMaintenanceMiddleware

KEY = base64.urlsafe_b64encode(b'k' * 32).decode()


class PrivateStorageMixin:
    def setUp(self):
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory(prefix='entailsng-backup-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.options = override_settings(BACKUP_ROOT=self.base / 'backups', MEDIA_ROOT=self.base / 'media',
                                         PRIVATE_MEDIA_ROOT=self.base / 'private', BACKUP_ENCRYPTION_KEY=KEY,
                                         BACKUP_MIN_FREE_BYTES=0, BACKUP_DRAIN_TIMEOUT=1)
        self.options.enable()
        self.addCleanup(self.options.disable)
        for path in (settings.MEDIA_ROOT, settings.PRIVATE_MEDIA_ROOT):
            Path(path).mkdir()
        storage.initialize()


class ArchiveTests(PrivateStorageMixin, SimpleTestCase):
    def make_archive(self, contents, *, override_manifest=None, links=False):
        plain = self.base / storage.new_id()
        encrypted = self.base / storage.new_id()
        manifest = {'format_version': 1, 'files': {name: {'bytes': len(data),
                    'sha256': __import__('hashlib').sha256(data).hexdigest()} for name, data in contents.items()}}
        if override_manifest:
            manifest.update(override_manifest)
        with zipfile.ZipFile(plain, 'w') as file:
            file.writestr('manifest.json', json.dumps(manifest))
            for name, data in contents.items():
                if links:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    file.writestr(info, data)
                else:
                    file.writestr(name, data)
        archive.encrypt(plain, encrypted)
        return encrypted

    def test_authenticated_round_trip_preserves_both_media_areas(self):
        encrypted = self.make_archive({'database/postgresql.dump': b'db', 'media/logo.png': b'public',
                                       'private_media/wiki/manual.pdf': b'private'})
        target = self.base / 'unpacked'
        manifest = archive.unpack(encrypted, target)
        self.assertEqual((target / 'private_media/wiki/manual.pdf').read_bytes(), b'private')
        self.assertEqual(len(manifest['files']), 3)
        self.assertNotIn(b'private', encrypted.read_bytes())

    def test_tampering_is_rejected_before_extracting(self):
        encrypted = self.make_archive({'media/a': b'hello'})
        data = bytearray(encrypted.read_bytes())
        data[-18] ^= 1
        encrypted.write_bytes(data)
        with self.assertRaises(BackupError):
            archive.unpack(encrypted, self.base / 'bad')
        self.assertFalse((self.base / 'bad/media/a').exists())

    def test_wrong_key_is_rejected(self):
        encrypted = self.make_archive({'media/a': b'hello'})
        with override_settings(BACKUP_ENCRYPTION_KEY=base64.urlsafe_b64encode(b'z' * 32).decode()):
            with self.assertRaises(BackupError):
                archive.unpack(encrypted, self.base / 'bad')

    def test_unsafe_names_are_rejected(self):
        for name in ('../escape', '/media/a', 'media/../escape', 'media/a\\b', 'media/C:a', 'media/./a'):
            with self.subTest(name=name), self.assertRaises(BackupError):
                archive.safe_name(name)

    def test_symlink_entry_is_rejected(self):
        encrypted = self.make_archive({'media/link': b'target'}, links=True)
        with self.assertRaises(BackupError):
            archive.unpack(encrypted, self.base / 'bad')

    def test_case_collisions_are_rejected_for_portability(self):
        encrypted = self.make_archive({'media/Logo': b'a', 'media/logo': b'b'})
        with self.assertRaises(BackupError):
            archive.unpack(encrypted, self.base / 'bad')

    def test_unpacked_size_limit_is_enforced(self):
        encrypted = self.make_archive({'media/a': b'x' * 1000})
        with override_settings(BACKUP_MAX_UNPACKED_BYTES=100), self.assertRaises(BackupError):
            archive.unpack(encrypted, self.base / 'bad')

    def test_hash_mismatch_is_rejected(self):
        encrypted = self.make_archive({'media/a': b'hello'}, override_manifest={
            'files': {'media/a': {'bytes': 5, 'sha256': '0' * 64}}})
        with self.assertRaises(BackupError):
            archive.unpack(encrypted, self.base / 'bad')

    def test_key_is_required_and_separate_from_django_secret(self):
        for value in ('', 'not-a-key', KEY[:-4]):
            with override_settings(BACKUP_ENCRYPTION_KEY=value), self.assertRaises(BackupError):
                storage.encryption_key()

    def test_public_backup_root_is_rejected(self):
        with override_settings(BACKUP_ROOT=Path(settings.MEDIA_ROOT) / 'backups'), self.assertRaises(BackupError):
            storage.validate_paths()

    def test_disk_space_is_checked(self):
        with mock.patch('backups.storage.shutil.disk_usage', return_value=mock.Mock(free=1)), self.assertRaises(BackupError):
            storage.require_space(self.base, 2)


class LockAndMaintenanceTests(PrivateStorageMixin, SimpleTestCase):
    def test_shared_readers_coexist_and_block_exclusive_worker(self):
        with FileLock('access.lock', exclusive=False):
            with FileLock('access.lock', exclusive=False):
                with self.assertRaises(BackupError):
                    with FileLock('access.lock'):
                        pass
        with FileLock('access.lock'):
            pass

    def test_marker_rejects_new_requests_without_database_access(self):
        storage.atomic_json(storage.root() / 'maintenance.json', {'message': 'Wartung'})
        response = BackupMaintenanceMiddleware(mock.Mock(side_effect=AssertionError))(
            RequestFactory().get('/admin/'))
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'Wartung', response.content)

    def test_existing_reader_finishes_while_new_reader_is_blocked(self):
        with access_guard():
            storage.atomic_json(storage.root() / 'maintenance.json', {'message': 'Wartung'})
            with access_guard():
                pass
            result = []
            def reader():
                try:
                    with access_guard():
                        result.append('entered')
                except BackupError:
                    result.append('blocked')
            thread = threading.Thread(target=reader)
            thread.start()
            thread.join(2)
            self.assertEqual(result, ['blocked'])

    def test_healthcheck_stays_live_during_restore(self):
        storage.atomic_json(storage.root() / 'maintenance.json', {})
        response = BackupMaintenanceMiddleware(mock.Mock(side_effect=AssertionError))(
            RequestFactory().get('/api/health/'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'maintenance')

    def test_unconfigured_feature_does_not_create_files_for_normal_requests(self):
        with override_settings(BACKUP_ENCRYPTION_KEY='', BACKUP_ROOT=self.base / 'absent'):
            response = BackupMaintenanceMiddleware(lambda request: HttpResponse('ok'))(RequestFactory().get('/'))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(storage.root().exists())


class AdminTests(PrivateStorageMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.admin = get_user_model().objects.create_superuser('backup-admin', 'backup-admin@example.test', 'safe-password')
        self.staff = get_user_model().objects.create_user('backup-staff', 'backup-staff@example.test', 'pw', is_staff=True)
        self.client.force_login(self.admin)

    def test_admin_has_backup_link_and_builtin_admin_content(self):
        response = self.client.get('/admin/')
        self.assertContains(response, reverse('backups:index'))
        self.assertContains(response, 'configuration')

    def test_index_explains_missing_key(self):
        with override_settings(BACKUP_ENCRYPTION_KEY=''):
            response = self.client.get(reverse('backups:index'))
        self.assertContains(response, 'BACKUP_ENCRYPTION_KEY')

    def test_staff_cannot_access_backup_routes(self):
        self.client.force_login(self.staff)
        for path in (reverse('backups:index'), reverse('backups:download', args=['a' * 32]),
                     reverse('backups:restore', args=['a' * 32])):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_anonymous_cannot_access_admin(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('backups:index')).status_code, 302)

    def test_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse('backups:index'), {'action': 'create', 'confirm': True}).status_code, 403)

    def test_queue_prevents_double_submissions(self):
        first = services.enqueue('create')
        with self.assertRaises(BackupError):
            services.enqueue('create')
        self.assertEqual(len(storage.list_records('jobs')), 1)
        self.assertEqual(storage.load('jobs', first['id'])['state'], 'pending')

    def test_create_requires_maintenance_confirmation(self):
        with mock.patch('backups.services.worker_available', return_value=True):
            response = self.client.post(reverse('backups:index'), {'action': 'create', 'description': 'test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(storage.list_records('jobs'), [])

    def test_create_queues_outside_request(self):
        with mock.patch('backups.services.worker_available', return_value=True):
            response = self.client.post(reverse('backups:index'), {'action': 'create', 'description': 'test', 'confirm': True})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(storage.list_records('jobs')[0]['state'], 'pending')

    def test_restore_requires_password_and_explicit_confirmation(self):
        value = storage.new_id()
        storage.save('records', {'id': value, 'state': 'prepared', 'created_at': storage.timestamp(), 'bytes': 1})
        with mock.patch('backups.services.worker_available', return_value=True):
            for data in ({'password': 'wrong', 'confirm': True}, {'password': 'safe-password'}):
                response = self.client.post(reverse('backups:restore', args=[value]), data)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(storage.list_records('jobs'), [])

    def test_progress_requires_capability_and_survives_maintenance(self):
        job = services.enqueue('create')
        storage.atomic_json(storage.root() / 'maintenance.json', {})
        self.client.logout()
        with self.assertNumQueries(0):
            response = self.client.get(reverse('backups:progress', args=[job['id'], job['token']]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('actor', response.json())
        self.assertEqual(self.client.get(reverse('backups:progress', args=[job['id'], 'bad'])).status_code, 404)

    def test_initial_job_redirect_is_accessible_when_worker_has_already_started(self):
        job = services.enqueue('create')
        storage.atomic_json(storage.root() / 'maintenance.json', {})
        with self.assertNumQueries(0):
            response = self.client.get(reverse('backups:job', args=[job['id'], job['token']]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'backup-progress')

    def test_second_restore_post_requires_new_preview(self):
        value = storage.new_id()
        storage.save('records', {'id': value, 'state': 'prepared', 'created_at': storage.timestamp(), 'bytes': 1})
        job = services.enqueue('restore', record_id=value)
        services.update_job(job, state='completed')
        with self.assertRaises(BackupError):
            services.enqueue('restore', record_id=value)

    def test_download_streams_and_does_not_leak_private_storage_path(self):
        value = storage.new_id()
        storage.artifact_path(value).write_bytes(b'encrypted')
        storage.save('records', {'id': value, 'state': 'completed', 'created_at': storage.timestamp(), 'bytes': 9})
        response = self.client.get(reverse('backups:download', args=[value]))
        self.assertEqual(b''.join(response.streaming_content), b'encrypted')
        response.close()
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])

    def test_delete_is_post_only(self):
        self.assertEqual(self.client.get(reverse('backups:delete', args=['a' * 32])).status_code, 405)

    def test_identifier_cannot_traverse_filesystem(self):
        with self.assertRaises(BackupError):
            storage.load('records', '../secrets')

    def test_mail_gate_prevents_queue_and_direct_send(self):
        storage.atomic_json(storage.root() / 'mail-paused.json', {})
        from emails.services import process_email_queue
        from emails.backends import ConfiguredSMTPBackend
        with self.assertNumQueries(0):
            self.assertEqual(process_email_queue(), (0, 0))
            self.assertEqual(ConfiguredSMTPBackend().send_messages([mock.Mock()]), 0)

    def test_invalid_upload_is_queued_but_never_restored(self):
        upload = SimpleUploadedFile('test.entailsbackup', b'not an archive')
        job = services.upload_backup(upload)
        with FileLock('worker.lock'):
            services.process_next()
        self.assertEqual(storage.load('jobs', job['id'])['state'], 'failed')

    def test_oversized_upload_is_rejected_without_an_artifact(self):
        with override_settings(BACKUP_MAX_UPLOAD_BYTES=3), self.assertRaises(BackupError):
            services.upload_backup(SimpleUploadedFile('large.entailsbackup', b'1234'))
        self.assertEqual(storage.list_records(), [])


class NativeRoundTripTests(PrivateStorageMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.admin = get_user_model().objects.create_superuser('saved-admin', 'saved@example.test', 'saved-password')
        from tournaments.models import Game
        Game.objects.create(name='Saved Game', logo='game_logos/saved.png')
        (Path(settings.MEDIA_ROOT) / 'game_logos').mkdir()
        (Path(settings.MEDIA_ROOT) / 'game_logos/saved.png').write_bytes(b'public-original')
        from knowledge.models import KnowledgeSpace, KnowledgePage, KnowledgeAttachment
        space = KnowledgeSpace.objects.create(name='Saved Wiki')
        page = KnowledgePage.objects.create(space=space, title='Saved Page')
        KnowledgeAttachment.objects.create(page=page, file='wiki/manual.pdf', original_name='manual.pdf', size=16)
        (Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki').mkdir()
        (Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/manual.pdf').write_bytes(b'private-original')
        from emails.models import GeneralEmailSettings
        config = GeneralEmailSettings.load()
        config.is_enabled = True
        config.set_smtp_password('stored-secret')
        config.save()
        from django.contrib.sessions.models import Session
        from django.utils import timezone
        from datetime import timedelta
        Session.objects.create(session_key='s' * 32, session_data='expired-after-restore', expire_date=timezone.now() + timedelta(days=1))
        from users.models import EmailVerificationCode
        EmailVerificationCode.objects.create(user=self.admin, code='123456', expires_at=timezone.now() + timedelta(hours=1))
        from psycopg import sql
        original = database.PostgreSQLAdapter()
        original.preflight(restore=True)  # A PostgreSQL CI run must fail if native tools are missing.
        self.native_name = 'entailsng_test_source_' + storage.new_id()
        with original.connect('postgres', autocommit=True) as pg:
            pg.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(self.native_name)))
        self.addCleanup(self.cleanup_postgresql, original)
        dump = self.base / 'fixture.dump'
        original.run('pg_dump', '--format=custom', '--file', dump)
        original.run('pg_restore', '--no-owner', '--no-acl', '--dbname', self.native_name, dump, database=self.native_name)
        def initialize_adapter(adapter):
            adapter.config = dict(settings.DATABASES['default'], NAME=self.native_name)
            adapter.name = self.native_name
        patcher = mock.patch.object(database.PostgreSQLAdapter, '__init__', initialize_adapter)
        patcher.start()
        self.addCleanup(patcher.stop)

    def cleanup_postgresql(self, original):
        from psycopg import sql
        names = [self.native_name]
        for job in storage.list_records('jobs'):
            names.extend(['entailsng_stage_' + job['id'], 'entailsng_previous_' + job['id']])
        with original.connect('postgres', autocommit=True) as pg:
            for name in names:
                if original._exists(pg, name):
                    pg.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

    def process(self, kind, value=None):
        job = services.enqueue(kind, record_id=value)
        with FileLock('worker.lock'):
            services.process_next()
        return storage.load('jobs', job['id'])

    def create_backup(self):
        job = self.process('create')
        self.assertEqual(job['state'], 'completed', job.get('error'))
        return job['result_id']

    def mutate(self):
        with database.adapter().connect() as native:
            native.execute("UPDATE tournaments_game SET name = 'Changed Game'")
            native.commit()
        (Path(settings.MEDIA_ROOT) / 'game_logos/saved.png').write_bytes(b'changed')
        (Path(settings.MEDIA_ROOT) / 'extra.bin').write_bytes(b'new-file')
        (Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/manual.pdf').write_bytes(b'changed-private')

    def read_game(self):
        with database.adapter().connect() as native:
            return native.execute('SELECT name FROM tournaments_game').fetchone()[0]

    def test_full_restore_preserves_database_public_private_files_and_safety_backup(self):
        value = self.create_backup()
        self.mutate()
        self.assertEqual(self.process('prepare', value)['state'], 'completed')
        job = self.process('restore', value)
        self.assertEqual(job['state'], 'completed', job.get('error'))
        self.assertEqual(self.read_game(), 'Saved Game')
        self.assertEqual((Path(settings.MEDIA_ROOT) / 'game_logos/saved.png').read_bytes(), b'public-original')
        self.assertFalse((Path(settings.MEDIA_ROOT) / 'extra.bin').exists())
        self.assertEqual((Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/manual.pdf').read_bytes(), b'private-original')
        self.assertTrue(storage.artifact_path(job['safety_id']).is_file())
        self.assertTrue((storage.root() / 'mail-paused.json').exists())
        self.assertFalse((storage.root() / 'maintenance.json').exists())
        with database.adapter().connect() as native:
            self.assertEqual(native.execute('SELECT is_enabled FROM emails_generalemailsettings').fetchone()[0], 0)
            self.assertEqual(native.execute('SELECT COUNT(*) FROM django_session').fetchone()[0], 0)
            self.assertEqual(native.execute('SELECT COUNT(*) FROM users_emailverificationcode').fetchone()[0], 0)

    def test_media_failure_rolls_back_database_and_files(self):
        value = self.create_backup()
        self.mutate()
        self.process('prepare', value)
        original = services.replace_media
        calls = []
        def fail_once(snapshot):
            calls.append(snapshot)
            if len(calls) == 1:
                raise OSError('simulated media failure')
            return original(snapshot)
        with mock.patch('backups.services.replace_media', side_effect=fail_once):
            job = self.process('restore', value)
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(self.read_game(), 'Changed Game')
        self.assertEqual((Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/manual.pdf').read_bytes(), b'changed-private')
        self.assertFalse((storage.root() / 'maintenance.json').exists())
        self.assertFalse((storage.root() / 'mail-paused.json').exists())

    def test_public_media_permissions_allow_nginx_after_restore(self):
        if os.name == 'nt':
            self.skipTest('POSIX file permissions are checked in Linux CI.')
        value = self.create_backup()
        self.process('prepare', value)
        job = self.process('restore', value)
        self.assertEqual(job['state'], 'completed')
        self.assertEqual(stat.S_IMODE((Path(settings.MEDIA_ROOT) / 'game_logos').stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((Path(settings.MEDIA_ROOT) / 'game_logos/saved.png').stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/manual.pdf').stat().st_mode), 0o600)

    def test_failed_rollback_keeps_maintenance_and_is_recovered_on_restart(self):
        value = self.create_backup()
        self.mutate()
        self.process('prepare', value)
        with mock.patch('backups.services.replace_media', side_effect=OSError('disk failure')):
            job = self.process('restore', value)
        self.assertEqual(job['state'], 'recovery_required')
        self.assertTrue((storage.root() / 'maintenance.json').exists())
        with FileLock('worker.lock'):
            services.recover_interrupted()
        self.assertEqual(self.read_game(), 'Changed Game')
        self.assertFalse((storage.root() / 'maintenance.json').exists())
        self.assertEqual(storage.load('jobs', job['id'])['state'], 'failed')

    def test_process_interrupt_during_takeover_never_reopens_application(self):
        value = self.create_backup()
        self.mutate()
        self.process('prepare', value)
        with mock.patch('backups.services.replace_media', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.process('restore', value)
        self.assertTrue((storage.root() / 'maintenance.json').exists())
        with FileLock('worker.lock'):
            services.recover_interrupted()
        self.assertEqual(self.read_game(), 'Changed Game')
        self.assertFalse((storage.root() / 'maintenance.json').exists())

    def test_changed_software_is_rejected_before_takeover(self):
        value = self.create_backup()
        self.mutate()
        with mock.patch('backups.database.software_fingerprint', return_value='changed'):
            job = self.process('prepare', value)
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(job['error'], 'backup_err_compatible')
        self.assertEqual(self.read_game(), 'Changed Game')

    def test_changed_field_key_is_rejected_without_modifying_database(self):
        value = self.create_backup()
        self.mutate()
        with mock.patch.dict(os.environ, {'FIELD_ENCRYPTION_KEY': 'changed-field-key'}):
            job = self.process('prepare', value)
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(job['error'], 'backup_err_credentials')
        self.assertEqual(self.read_game(), 'Changed Game')

    def test_broken_current_credentials_do_not_prevent_safety_snapshot_and_restore(self):
        value = self.create_backup()
        self.mutate()
        with database.adapter().connect() as native:
            native.execute("UPDATE emails_generalemailsettings SET smtp_password = 'gAAAAA-broken-current-secret'")
            native.commit()
        self.assertEqual(self.process('prepare', value)['state'], 'completed')
        job = self.process('restore', value)
        self.assertEqual(job['state'], 'completed', job.get('error'))
        self.assertEqual(self.read_game(), 'Saved Game')

    def test_no_usable_superuser_password_prevents_backup(self):
        with database.adapter().connect() as native:
            native.execute("UPDATE users_user SET password = '!unusable'")
            native.commit()
        job = self.process('create')
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(job['error'], 'backup_err_references')

    def test_missing_referenced_private_file_prevents_backup(self):
        (Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/manual.pdf').unlink()
        job = self.process('create')
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(job['error'], 'backup_err_references')

    def test_pruning_keeps_latest_regular_backups_and_safety_backups(self):
        with override_settings(BACKUP_KEEP_COUNT=1):
            first = self.create_backup()
            second = self.create_backup()
        self.assertFalse(storage.artifact_path(first).exists())
        self.assertTrue(storage.artifact_path(second).exists())

    def test_cli_backup_command_runs_without_a_background_worker(self):
        output = io.StringIO()
        call_command('backup_system', 'create', stdout=output)
        self.assertTrue(storage.artifact_path(output.getvalue().strip()).is_file())
