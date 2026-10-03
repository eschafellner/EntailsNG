import contextlib
import logging
import os
import secrets
import shutil
from pathlib import Path

from django.conf import settings
from django.core.cache import caches
from django.db import connections
from django.db.migrations.executor import MigrationExecutor

from . import archive, database, storage
from .errors import BackupError
from .locking import FileLock, maintenance_active

logger = logging.getLogger(__name__)
ACTIVE = ('pending', 'running', 'interrupted', 'recovery_required')


def worker_available():
    try:
        with FileLock('worker.lock'):
            return False
    except BackupError as exc:
        return exc.key == 'backup_err_busy'


def enqueue(kind, *, actor='', description='', record_id=None, require_worker=False):
    storage.encryption_key()
    storage.initialize()
    with FileLock('control.lock'):
        if maintenance_active():
            raise BackupError('backup_err_maintenance')
        if any(job['state'] in ACTIVE for job in storage.list_records('jobs')):
            raise BackupError('backup_err_busy')
        if require_worker and not worker_available():
            raise BackupError('backup_worker_missing')
        if kind not in ('create', 'prepare', 'restore'):
            raise ValueError(kind)
        if record_id:
            record = storage.load('records', record_id)
            if kind == 'restore' and record.get('state') != 'prepared':
                raise BackupError('backup_err_not_found')
        job = {'id': storage.new_id(), 'kind': kind, 'actor': actor[:150],
               'description': description[:200], 'record_id': record_id,
               'created_at': storage.timestamp(), 'state': 'pending', 'stage': 'validate',
               'token': secrets.token_hex(32)}
        from configuration.translations import get_translation
        from .texts import TEXTS
        job['texts'] = {key: get_translation(key) for key in TEXTS}
        storage.save('jobs', job)
        if kind == 'restore':
            # Consume the prepared state: a second POST after completion must require a fresh preview.
            record['state'] = 'completed'
            storage.save('records', record)
        return job


def upload_backup(upload, *, actor='', require_worker=False):
    storage.encryption_key()
    storage.initialize()
    if upload.size > settings.BACKUP_MAX_UPLOAD_BYTES:
        raise BackupError('backup_err_limits')
    storage.require_space(storage.root(), upload.size * 2)
    value = storage.new_id()
    path = storage.artifact_path(value)
    try:
        with path.open('xb') as stream:
            os.chmod(path, 0o600)
            total = 0
            for chunk in upload.chunks():
                total += len(chunk)
                if total > settings.BACKUP_MAX_UPLOAD_BYTES:
                    raise BackupError('backup_err_limits')
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        record = {'id': value, 'created_at': storage.timestamp(), 'description': '',
                  'state': 'uploaded', 'bytes': total, 'uploaded': True}
        storage.save('records', record)
        return enqueue('prepare', actor=actor, record_id=value, require_worker=require_worker)
    except BaseException:
        path.unlink(missing_ok=True)
        storage.record_path('records', value).unlink(missing_ok=True)
        raise


def delete_backup(value):
    with FileLock('control.lock'):
        record = storage.load('records', value)
        if any(job['state'] in ACTIVE for job in storage.list_records('jobs')):
            raise BackupError('backup_err_busy')
        storage.artifact_path(value).unlink(missing_ok=True)
        storage.record_path('records', value).unlink()


def resume_mail():
    with FileLock('control.lock'):
        if maintenance_active():
            raise BackupError('backup_err_maintenance')
        (storage.root() / 'mail-paused.json').unlink(missing_ok=True)


def update_job(job, **changes):
    job.update(changes, updated_at=storage.timestamp())
    storage.save('jobs', job)


@contextlib.contextmanager
def maintenance(job):
    from .texts import TEXTS
    marker = storage.root() / 'maintenance.json'
    storage.atomic_json(marker, {'job_id': job['id'], 'message': job.get('texts', TEXTS)['backup_maintenance']})
    locked = False
    try:
        try:
            lock = FileLock('access.lock', timeout=settings.BACKUP_DRAIN_TIMEOUT)
            lock.__enter__()
            locked = True
        except BackupError:
            raise BackupError('backup_err_timeout') from None
        connections.close_all()
        yield
    finally:
        # On process death the marker survives; recovery is explicit, never a TTL unlock.
        journal = storage.read_json(storage.root() / 'work' / job['id'] / 'journal.json', {})
        if journal.get('phase') == 'applying':
            update_job(job, state='recovery_required', error='backup_err_operation')
        if job.get('state') != 'recovery_required':
            marker.unlink(missing_ok=True)
        if locked:
            lock.__exit__(None, None, None)


def assert_current_migrations():
    connection = connections['default']
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise BackupError('backup_err_compatible')


def capture(snapshot, db):
    snapshot.mkdir(mode=0o700, parents=True, exist_ok=False)
    major = db.preflight()
    assert_current_migrations()
    inspection = db.capture(snapshot)
    archive.copy_media(snapshot)
    for name in inspection['references']:
        if not snapshot.joinpath(*archive.safe_name(name).parts).is_file():
            raise BackupError('backup_err_references')
    return {'format_version': archive.FORMAT_VERSION, 'created_at': storage.timestamp(),
            'database_engine': db.engine, 'database_major': major, 'database_file': db.filename,
            'software_fingerprint': database.software_fingerprint(), 'migrations': inspection['migrations']}


def publish(snapshot, manifest, *, description='', protected=False, value=None):
    value = value or storage.new_id()
    path = storage.artifact_path(value)
    temporary = path.with_suffix('.partial')
    try:
        manifest = archive.pack(snapshot, manifest, temporary)
        os.replace(temporary, path)
        summary = {key: data for key, data in manifest.items() if key != 'files'}
        summary['file_count'] = len(manifest['files'])
        record = {'id': value, 'created_at': manifest['created_at'], 'description': description[:200],
                  'state': 'completed', 'manifest': summary, 'bytes': path.stat().st_size,
                  'protected': protected, 'sha256': archive.digest_file(path)}
        storage.save('records', record)
        return record
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def validate_manifest(manifest, snapshot, db):
    if (manifest.get('database_engine') != db.engine or manifest.get('database_file') != db.filename or
            manifest.get('database_major') != db.preflight(restore=True) or
            manifest.get('software_fingerprint') != database.software_fingerprint()):
        raise BackupError('backup_err_compatible')
    assert_current_migrations()
    current = db.verify_live(verify_secrets=False)
    if manifest.get('migrations') != current['migrations']:
        raise BackupError('backup_err_compatible')
    if not snapshot.joinpath(*archive.safe_name(db.filename).parts).is_file():
        raise BackupError('backup_err_archive')


def validate_stage(manifest, snapshot, db, stage):
    inspection = db.inspect(stage['candidate'])
    if inspection['migrations'] != manifest.get('migrations'):
        raise BackupError('backup_err_compatible')
    for name in inspection['references']:
        if not snapshot.joinpath(*archive.safe_name(name).parts).is_file():
            raise BackupError('backup_err_references')


def replace_media(snapshot):
    """Preserve Docker mount roots; synchronize their contents while requests are blocked."""
    for prefix, directory in (('media', settings.MEDIA_ROOT), ('private_media', settings.PRIVATE_MEDIA_ROOT)):
        target = Path(directory)
        source = snapshot / prefix
        target.mkdir(parents=True, exist_ok=True)
        files = list(source.rglob('*'))
        total = sum(path.stat().st_size for path in files if path.is_file())
        storage.require_space(target, total)
        for existing in target.iterdir():
            if existing.is_symlink() or (hasattr(existing, 'is_junction') and existing.is_junction()):
                raise BackupError('backup_err_paths')
            # Verify every recursive deletion stays inside the explicitly configured media root.
            if existing.resolve().parent != target.resolve():
                raise BackupError('backup_err_paths')
            if existing.is_dir():
                shutil.rmtree(existing)
            else:
                existing.unlink()
        shutil.copytree(source, target, dirs_exist_ok=True)
        os.chmod(target, 0o755 if prefix == 'media' else 0o700)
        for path in target.rglob('*'):
            os.chmod(path, (0o755 if prefix == 'media' else 0o700) if path.is_dir()
                     else (0o644 if prefix == 'media' else 0o600))
            if path.is_file():
                with path.open('r+b') as stream:
                    os.fsync(stream.fileno())


def refresh_runtime():
    connections.close_all()
    for cache in caches.all():
        cache.clear()  # Fail closed: stale cache must never be released after a restore.
    storage.atomic_json(storage.root() / 'generation.json', {'generation': storage.new_id()})


def prune():
    records = [record for record in storage.list_records() if not record.get('protected') and not record.get('uploaded')]
    for record in records[settings.BACKUP_KEEP_COUNT:]:
        storage.artifact_path(record['id']).unlink(missing_ok=True)
        storage.record_path('records', record['id']).unlink(missing_ok=True)


def create_job(job, work, db):
    update_job(job, stage='snapshot')
    with maintenance(job):
        manifest = capture(work / 'snapshot', db)
    update_job(job, stage='package')
    record = publish(work / 'snapshot', manifest, description=job['description'])
    update_job(job, result_id=record['id'])
    prune()


def prepare_job(job, work, db):
    update_job(job, stage='prepare')
    record = storage.load('records', job['record_id'])
    snapshot = work / 'incoming'
    manifest = archive.unpack(storage.artifact_path(record['id']), snapshot)
    validate_manifest(manifest, snapshot, db)
    stage = db.stage(snapshot, job)
    try:
        validate_stage(manifest, snapshot, db, stage)
    finally:
        db.discard(stage)
    record.update(state='prepared', created_at=manifest['created_at'], manifest={key: data for key, data in manifest.items() if key != 'files'},
                  sha256=archive.digest_file(storage.artifact_path(record['id'])))
    record['manifest']['file_count'] = len(manifest['files'])
    storage.save('records', record)
    update_job(job, result_id=record['id'])


def restore_job(job, work, db):
    update_job(job, stage='prepare')
    record = storage.load('records', job['record_id'])
    path = storage.artifact_path(record['id'])
    if archive.digest_file(path) != record.get('sha256'):
        raise BackupError('backup_err_archive')
    snapshot = work / 'incoming'
    manifest = archive.unpack(path, snapshot)
    validate_manifest(manifest, snapshot, db)
    stage = db.stage(snapshot, job)
    journal_path = work / 'journal.json'
    try:
        validate_stage(manifest, snapshot, db, stage)
        with maintenance(job):
            for prefix, directory in (('media', settings.MEDIA_ROOT), ('private_media', settings.PRIVATE_MEDIA_ROOT)):
                required = sum(path.stat().st_size for path in (snapshot / prefix).rglob('*') if path.is_file())
                storage.require_space(directory, required * 2)
            update_job(job, stage='safety')
            safety = work / 'safety'
            safety_manifest = capture(safety, db)
            safety_record = publish(safety, safety_manifest, description=job.get('texts', {}).get('backup_stage_safety', ''), protected=True)
            update_job(job, safety_id=safety_record['id'])
            journal = {'job_id': job['id'], 'stage': stage, 'phase': 'prepared',
                       'mail_was_paused': (storage.root() / 'mail-paused.json').exists()}
            storage.atomic_json(journal_path, journal)
            try:
                storage.atomic_json(storage.root() / 'mail-paused.json', {'job_id': job['id']})
                update_job(job, stage='apply')
                journal['phase'] = 'applying'
                storage.atomic_json(journal_path, journal)
                connections.close_all()  # Migration inspection during the safety snapshot opens a connection.
                db.apply(stage)
                replace_media(snapshot)
                update_job(job, stage='verify')
                live = db.verify_live()
                if live['migrations'] != manifest['migrations']:
                    raise BackupError('backup_err_compatible')
                for name in live['references']:
                    prefix, relative = name.split('/', 1)
                    directory = settings.MEDIA_ROOT if prefix == 'media' else settings.PRIVATE_MEDIA_ROOT
                    if not (Path(directory) / relative).is_file():
                        raise BackupError('backup_err_references')
                refresh_runtime()
                journal['phase'] = 'committed'
                storage.atomic_json(journal_path, journal)
            except Exception:
                logger.exception('Restore failed; rolling back job %s', job['id'])
                update_job(job, stage='rollback')
                try:
                    rollback(job, work, db, journal)
                except Exception:
                    logger.exception('Rollback requires operator recovery for job %s', job['id'])
                    update_job(job, state='recovery_required', error='backup_err_operation')
                raise
    finally:
        journal = storage.read_json(journal_path, {})
        if journal.get('phase') == 'committed':
            # Cleanup cannot undo a successfully committed restore.
            try:
                db.finish(stage)
            except Exception:
                logger.exception('Previous database cleanup failed for job %s', job['id'])
        elif job['state'] != 'recovery_required':
            db.discard(stage)


def rollback(job, work, db, journal):
    db.rollback(journal['stage'], work / 'safety')
    replace_media(work / 'safety')
    db.verify_live(verify_secrets=False)
    refresh_runtime()
    if not journal.get('mail_was_paused'):
        (storage.root() / 'mail-paused.json').unlink(missing_ok=True)
    journal['phase'] = 'rolled_back'
    storage.atomic_json(work / 'journal.json', journal)


def recover_interrupted():
    """Called with worker.lock held, before admitting any new jobs."""
    for job in storage.list_records('jobs'):
        if job['state'] not in ('running', 'interrupted', 'recovery_required'):
            continue
        work = storage.root() / 'work' / job['id']
        journal = storage.read_json(work / 'journal.json', {})
        if job['kind'] == 'restore' and journal.get('phase') in ('applying', 'prepared'):
            update_job(job, state='running', stage='rollback')
            try:
                with maintenance(job):
                    rollback(job, work, database.adapter(), journal)
            except Exception:
                update_job(job, state='recovery_required', error='backup_err_operation')
                logger.exception('Recovery failed for job %s', job['id'])
                # maintenance() may have removed the marker before this state was persisted.
                storage.atomic_json(storage.root() / 'maintenance.json', {'job_id': job['id'], 'message': 'Entails-NG wird gewartet.'})
                return
        elif job['kind'] == 'restore' and journal.get('phase') == 'committed':
            database.adapter().finish(journal['stage'])
            (storage.root() / 'maintenance.json').unlink(missing_ok=True)
            update_job(job, state='completed')
            storage.remove_work(job['id'])
            continue
        else:
            # Before takeover: discard deterministic staging databases left by a terminated worker.
            if job['kind'] in ('prepare', 'restore'):
                database.adapter().discard({'candidate': 'entailsng_stage_' + job['id']})
            (storage.root() / 'maintenance.json').unlink(missing_ok=True)
        update_job(job, state='failed', error='backup_interrupted')
        storage.remove_work(job['id'])


def process_next():
    if maintenance_active():
        return False
    with FileLock('control.lock'):
        pending = [job for job in storage.list_records('jobs') if job['state'] == 'pending']
        if not pending:
            return False
        job = pending[-1]
        update_job(job, state='running')
    work = storage.root() / 'work' / job['id']
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        {'create': create_job, 'prepare': prepare_job, 'restore': restore_job}[job['kind']](job, work, database.adapter())
        update_job(job, state='completed')
    except Exception as exc:
        logger.exception('Backup job %s failed', job['id'])
        if job['state'] != 'recovery_required':
            update_job(job, state='failed', error=getattr(exc, 'key', 'backup_err_operation'))
    finally:
        connections.close_all()
        if job['state'] != 'recovery_required':
            storage.remove_work(job['id'])
    return True
