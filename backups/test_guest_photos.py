from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from users.models import GUEST_PHOTO_DIR, GuestPhoto
from . import archive, database, services
from .tests import PrivateStorageMixin


class GuestPhotoBackupExclusionTests(PrivateStorageMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser('backup-admin', 'admin@example.test', 'saved-password')
        self.photo_dir = Path(settings.PRIVATE_MEDIA_ROOT) / GUEST_PHOTO_DIR
        self.photo_dir.mkdir()
        (self.photo_dir / 'face.jpg').write_bytes(b'photo')
        (Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki').mkdir()
        (Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/manual.pdf').write_bytes(b'manual')
        now = timezone.now()
        GuestPhoto.objects.create(user=self.admin, image=f'{GUEST_PHOTO_DIR}/face.jpg',
                                  source=GuestPhoto.Source.SELF, captured_at=now, delete_after=now + timedelta(days=1))

    def test_excluded_names_match_the_guest_photo_model(self):
        self.assertEqual(archive.EXCLUDED_MEDIA_DIRS, (f'private_media/{GUEST_PHOTO_DIR}',))
        self.assertEqual(archive.EXCLUDED_TABLE_DATA, (GuestPhoto._meta.db_table,))

    def test_media_files_skip_guest_photos(self):
        self.assertEqual(sorted(archive.media_files()), ['private_media/wiki/manual.pdf'])

    def test_reference_check_ignores_guest_photos(self):
        references = database.inspect_database(connection, verify_secrets=False)['references']
        self.assertFalse([name for name in references if GUEST_PHOTO_DIR in name])

    def test_pg_dump_excludes_guest_photo_rows(self):
        adapter = database.adapter()
        snapshot = self.base / 'snapshot'
        def fake_dump(tool, *arguments, **kwargs):
            Path(arguments[arguments.index('--file') + 1]).write_bytes(b'')
        with mock.patch.object(database.PostgreSQLAdapter, 'run', side_effect=fake_dump) as run:
            adapter.capture(snapshot)
        arguments = run.call_args.args
        self.assertEqual(arguments[0], 'pg_dump')
        self.assertIn('--exclude-table-data', arguments)
        self.assertEqual(arguments[arguments.index('--exclude-table-data') + 1], 'users_guestphoto')

    def test_post_restore_cleanup_removes_guest_photo_rows_from_older_backups(self):
        with database.adapter().connect() as native:
            database.post_restore_cleanup(native)
        self.assertFalse(GuestPhoto.objects.exists())

    def test_replace_media_keeps_guest_photos_for_a_rollback(self):
        snapshot = self.base / 'restore'
        (snapshot / 'media').mkdir(parents=True)
        (snapshot / 'private_media/wiki').mkdir(parents=True)
        (snapshot / 'private_media/wiki/restored.pdf').write_bytes(b'restored')
        services.replace_media(snapshot)
        self.assertEqual((self.photo_dir / 'face.jpg').read_bytes(), b'photo')
        self.assertFalse((Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/manual.pdf').exists())
        self.assertTrue((Path(settings.PRIVATE_MEDIA_ROOT) / 'wiki/restored.pdf').exists())

    def test_cleanup_after_restore_never_fails_the_restore(self):
        with mock.patch('users.services.GuestPhotoService.purge', side_effect=OSError('disk')):
            services.purge_guest_photos_after_restore()
