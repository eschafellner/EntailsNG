"""Native snapshots and staged restores; never run fixtures or model save hooks."""
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import models

from .archive import safe_name
from .errors import BackupError
from .storage import require_space

logger = logging.getLogger(__name__)


def software_fingerprint():
    base = Path(settings.BASE_DIR)
    directories = {'config', 'backups', 'templates', 'static'}
    for app in apps.get_app_configs():
        path = Path(app.path)
        if path.is_relative_to(base) and '.venv' not in path.parts:
            directories.add(path.relative_to(base).as_posix())
    files = set()
    for directory in directories:
        for path in (base / directory).rglob('*'):
            if path.is_file() and path.suffix in ('.py', '.html', '.js', '.css'):
                if not any(part.startswith('test') or part == '__pycache__' for part in path.parts):
                    files.add(path)
    files.add(base / 'requirements.txt')
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def inspect_database(connection, *, verify_secrets=True):
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT app, name FROM django_migrations ORDER BY app, name')
        migrations = [list(row) for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM users_user WHERE is_active AND is_superuser AND is_staff AND password <> '' AND password NOT LIKE '!%'")
        if not cursor.fetchone()[0]:
            raise BackupError('backup_err_references')
        references = []
        for model in apps.get_models():
            fields = [field for field in model._meta.local_fields if isinstance(field, models.FileField)]
            for field in fields:
                cursor.execute(f'SELECT {quoted(field.column)} FROM {quoted(model._meta.db_table)}')
                private = Path(field.storage.location).resolve() == Path(settings.PRIVATE_MEDIA_ROOT).resolve()
                prefix = 'private_media' if private else 'media'
                for row in cursor.fetchall():
                    if row[0]:
                        name = f'{prefix}/{row[0]}'
                        safe_name(name)
                        references.append(name)
        cursor.execute('SELECT smtp_password FROM emails_generalemailsettings')
        secrets = [row[0] for row in cursor.fetchall() if row[0]]
        from emails.crypto import decrypt_secret, SecretUnreadable
        try:
            for secret in secrets if verify_secrets else []:
                decrypt_secret(secret)
        except SecretUnreadable:
            raise BackupError('backup_err_credentials') from None
        return {'migrations': migrations, 'references': sorted(set(references))}
    finally:
        cursor.close()


def post_restore_cleanup(connection):
    cursor = connection.cursor()
    try:
        cursor.execute('DELETE FROM django_session')
        cursor.execute('DELETE FROM users_emailverificationcode')
        cursor.execute('UPDATE emails_generalemailsettings SET is_enabled = false')
        connection.commit()
    finally:
        cursor.close()


class SQLiteAdapter:
    engine = 'sqlite'
    filename = 'database/sqlite.sqlite3'

    def __init__(self):
        self.path = Path(settings.DATABASES['default']['NAME']).resolve()

    def preflight(self, restore=False):
        if not self.path.is_file() or self.path.stat().st_size == 0:
            raise BackupError('backup_err_database')
        return sqlite3.sqlite_version.split('.')[0]

    @contextmanager
    def connect(self, path=None):
        connection = sqlite3.connect(path or self.path)
        try:
            yield connection
        finally:
            connection.close()

    def capture(self, snapshot):
        destination = snapshot / self.filename
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require_space(snapshot, self.path.stat().st_size * 2)
        try:
            with self.connect() as source, self.connect(destination) as target:
                source.backup(target, pages=256)
            os.chmod(destination, 0o600)
            return self.inspect(destination, verify_secrets=False)
        except sqlite3.Error:
            logger.exception('SQLite snapshot failed')
            raise BackupError('backup_err_database') from None

    def inspect(self, path, *, verify_secrets=True):
        try:
            with self.connect(path) as connection:
                if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise BackupError('backup_err_database')
                if connection.execute('PRAGMA foreign_key_check').fetchone():
                    raise BackupError('backup_err_database')
                return inspect_database(connection, verify_secrets=verify_secrets)
        except sqlite3.Error:
            logger.exception('SQLite verification failed')
            raise BackupError('backup_err_database') from None

    def stage(self, snapshot, job):
        candidate = snapshot.parent / 'candidate.sqlite3'
        if not candidate.exists():
            shutil.copyfile(snapshot / self.filename, candidate)
        self.inspect(candidate)
        with self.connect(candidate) as connection:
            post_restore_cleanup(connection)
        return {'candidate': str(candidate)}

    def apply(self, stage):
        require_space(self.path.parent, Path(stage['candidate']).stat().st_size * 2)
        deadline = time.monotonic() + settings.BACKUP_OPERATION_TIMEOUT

        def progress(status, remaining, total):
            if time.monotonic() >= deadline:
                raise BackupError('backup_err_timeout')

        # SQLite commits the complete destination in one transaction. Keeping the file
        # permits idle handles on Windows and preserves SQLite's journal/WAL semantics.
        # Managed readers have drained; an unmanaged lock must not wait indefinitely.
        try:
            with self.connect(stage['candidate']) as source, self.connect() as target:
                source.backup(target, pages=256, progress=progress, sleep=0.05)
        except sqlite3.Error:
            logger.exception('SQLite restore failed')
            raise BackupError('backup_err_database') from None

    def rollback(self, stage, safety_snapshot):
        self.apply({'candidate': str(safety_snapshot / self.filename)})

    def finish(self, stage):
        pass

    def discard(self, stage):
        pass

    def verify_live(self, *, verify_secrets=True):
        return self.inspect(self.path, verify_secrets=verify_secrets)


class PostgreSQLAdapter:
    engine = 'postgresql'
    filename = 'database/postgresql.dump'

    def __init__(self):
        self.config = settings.DATABASES['default']
        self.name = self.config['NAME']

    def tool(self, name):
        directory = settings.BACKUP_PG_BIN_DIR
        path = Path(directory) / (name + ('.exe' if os.name == 'nt' else '')) if directory else shutil.which(name)
        if not path or not Path(path).is_file():
            raise BackupError('backup_err_tools')
        return str(path)

    @contextmanager
    def connect(self, database=None, autocommit=False):
        import psycopg
        connection = psycopg.connect(dbname=database or self.name, user=self.config['USER'],
                                     password=self.config['PASSWORD'], host=self.config.get('HOST'),
                                     port=self.config.get('PORT') or 5432, autocommit=autocommit,
                                     connect_timeout=10)
        try:
            yield connection
        finally:
            connection.close()

    def run(self, tool, *arguments, database=None):
        environment = dict(os.environ, PGDATABASE=database or self.name, PGUSER=self.config['USER'],
                           PGPASSWORD=self.config['PASSWORD'], PGHOST=self.config.get('HOST') or '',
                           PGPORT=str(self.config.get('PORT') or 5432), PGCONNECT_TIMEOUT='10')
        try:
            result = subprocess.run([self.tool(tool), '--no-password', *map(str, arguments)],
                                    env=environment, capture_output=True, timeout=settings.BACKUP_OPERATION_TIMEOUT,
                                    check=False)
            if result.returncode:
                # Do not expose connection strings, SQL or dump contents in the admin UI.
                logger.error('%s failed with exit code %s', tool, result.returncode)
                raise BackupError('backup_err_database')
        except (OSError, subprocess.TimeoutExpired):
            raise BackupError('backup_err_database') from None

    def preflight(self, restore=False):
        if self.name in ('postgres', 'template0', 'template1'):
            raise BackupError('backup_err_compatible')
        with self.connect() as connection:
            version = str(connection.info.server_version // 10000)
            if restore:
                row = connection.execute('SELECT rolsuper OR rolcreatedb FROM pg_roles WHERE rolname = current_user').fetchone()
                if not row or not row[0]:
                    raise BackupError('backup_err_tools')
        for tool in ('pg_dump', 'pg_restore'):
            result = subprocess.run([self.tool(tool), '--version'], capture_output=True, timeout=10, check=True)
            match = re.search(rb'(\d+)\.', result.stdout)
            if not match or match.group(1).decode() != version:
                raise BackupError('backup_err_tools')
        return version

    def capture(self, snapshot):
        destination = snapshot / self.filename
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as connection:
            size = connection.execute('SELECT pg_database_size(current_database())').fetchone()[0]
            inspection = inspect_database(connection, verify_secrets=False)
        require_space(snapshot, size * 2)
        self.run('pg_dump', '--format=custom', '--file', destination)
        os.chmod(destination, 0o600)
        return inspection

    def inspect(self, database, *, verify_secrets=True):
        with self.connect(database) as connection:
            return inspect_database(connection, verify_secrets=verify_secrets)

    def stage(self, snapshot, job):
        from psycopg import sql
        name = 'entailsng_stage_' + job['id']
        with self.connect('postgres', autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        stage = {'candidate': name, 'old': 'entailsng_previous_' + job['id']}
        try:
            self.run('pg_restore', '--single-transaction', '--no-owner', '--no-acl',
                     '--dbname', name, snapshot / self.filename, database=name)
            self.inspect(name)
            with self.connect(name) as connection:
                post_restore_cleanup(connection)
            return stage
        except BaseException:
            self.discard(stage)
            raise

    def _exists(self, connection, name):
        return bool(connection.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,)).fetchone())

    def _disconnect(self, connection, name):
        from psycopg import sql
        connection.execute(sql.SQL('ALTER DATABASE {} ALLOW_CONNECTIONS false').format(sql.Identifier(name)))
        connection.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s', (name,))

    def apply(self, stage):
        from psycopg import sql
        with self.connect('postgres', autocommit=True) as connection:
            self._disconnect(connection, self.name)
            self._disconnect(connection, stage['candidate'])
            connection.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(
                sql.Identifier(self.name), sql.Identifier(stage['old'])))
            connection.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(
                sql.Identifier(stage['candidate']), sql.Identifier(self.name)))
            connection.execute(sql.SQL('ALTER DATABASE {} ALLOW_CONNECTIONS true').format(sql.Identifier(self.name)))

    def rollback(self, stage, safety_snapshot):
        from psycopg import sql
        with self.connect('postgres', autocommit=True) as connection:
            if self._exists(connection, stage['old']):
                if self._exists(connection, self.name):
                    self._disconnect(connection, self.name)
                    connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(self.name)))
                connection.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(
                    sql.Identifier(stage['old']), sql.Identifier(self.name)))
            connection.execute(sql.SQL('ALTER DATABASE {} ALLOW_CONNECTIONS true').format(sql.Identifier(self.name)))
        self.discard(stage)

    def finish(self, stage):
        from psycopg import sql
        with self.connect('postgres', autocommit=True) as connection:
            if self._exists(connection, stage['old']):
                connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(stage['old'])))

    def discard(self, stage):
        from psycopg import sql
        with self.connect('postgres', autocommit=True) as connection:
            if self._exists(connection, stage['candidate']):
                connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(stage['candidate'])))

    def verify_live(self, *, verify_secrets=True):
        return self.inspect(self.name, verify_secrets=verify_secrets)


def adapter():
    engine = settings.DATABASES['default']['ENGINE']
    if engine.endswith('sqlite3'):
        return SQLiteAdapter()
    if engine.endswith('postgresql'):
        return PostgreSQLAdapter()
    raise BackupError('backup_err_database')
