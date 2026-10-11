from unittest import mock

from django.test import SimpleTestCase

from backups import services, storage
from backups.errors import BackupError
from backups.tests import PrivateStorageMixin


class CommittedRecoveryTests(PrivateStorageMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.record = {'id': storage.new_id(), 'created_at': storage.timestamp(),
                       'manifest': {'migrations': [['users', '0001']]}}
        storage.save('records', self.record)
        self.job = {'id': storage.new_id(), 'record_id': self.record['id'], 'kind': 'restore',
                    'state': 'interrupted', 'created_at': storage.timestamp()}
        storage.save('jobs', self.job)
        self.stage = {'candidate': 'candidate', 'old': 'previous'}
        self.work = storage.root() / 'work' / self.job['id']
        storage.atomic_json(self.work / 'journal.json', {'phase': 'committed', 'stage': self.stage})
        storage.atomic_json(storage.root() / 'maintenance.json', {'job_id': self.job['id']})
        self.db = mock.Mock()
        self.db.verify_live.return_value = {'migrations': self.record['manifest']['migrations'], 'references': []}

    def test_cleanup_failure_reopens_verified_site_and_is_retried_later(self):
        self.db.finish.side_effect = OSError('cleanup connection unavailable')
        with mock.patch('backups.services.database.adapter', return_value=self.db):
            services.recover_interrupted()
            job = storage.load('jobs', self.job['id'])
            self.assertEqual(job['state'], 'completed')
            self.assertTrue(job['cleanup_pending'])
            self.assertEqual(job['cleanup_stage'], self.stage)
            self.assertFalse((storage.root() / 'maintenance.json').exists())
            self.assertFalse(self.work.exists())
            self.db.verify_live.assert_called_once_with()
            self.db.finish.assert_called_once_with(self.stage)
            # Backoff survives a restart, and successful retry clears its record.
            services.recover_interrupted()
            self.assertEqual(self.db.finish.call_count, 1)
            job['cleanup_retry_at'] = 0
            storage.save('jobs', job)
            self.db.finish.side_effect = None
            self.assertFalse(services.process_next())
        self.assertFalse(storage.load('jobs', self.job['id'])['cleanup_pending'])
        self.assertEqual(self.db.finish.call_count, 2)

    def test_live_validation_failure_keeps_maintenance_and_previous_database(self):
        self.db.verify_live.side_effect = BackupError('backup_err_database')
        with mock.patch('backups.services.database.adapter', return_value=self.db):
            services.recover_interrupted()
        self.assertEqual(storage.load('jobs', self.job['id'])['state'], 'recovery_required')
        self.assertTrue((storage.root() / 'maintenance.json').exists())
        self.assertTrue(self.work.exists())
        self.db.finish.assert_not_called()

    def test_missing_live_media_keeps_maintenance(self):
        self.db.verify_live.return_value['references'] = ['media/missing.png']
        with mock.patch('backups.services.database.adapter', return_value=self.db):
            services.recover_interrupted()
        self.assertEqual(storage.load('jobs', self.job['id'])['state'], 'recovery_required')
        self.assertTrue((storage.root() / 'maintenance.json').exists())
        self.db.finish.assert_not_called()
