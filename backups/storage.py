"""Private, database-independent job and artifact storage."""
import base64
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from .errors import BackupError

ID = re.compile(r'^[0-9a-f]{32}$')


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def encryption_key():
    try:
        value = settings.BACKUP_ENCRYPTION_KEY
        key = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        if len(key) != 32:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise BackupError('backup_err_key') from None


def root():
    return Path(settings.BACKUP_ROOT).resolve()


def validate_paths():
    paths = [root(), Path(settings.MEDIA_ROOT).resolve(), Path(settings.PRIVATE_MEDIA_ROOT).resolve()]
    public = [Path(settings.STATIC_ROOT).resolve(), *(Path(p).resolve() for p in settings.STATICFILES_DIRS)]
    for index, path in enumerate(paths):
        if any(path == other or path.is_relative_to(other) or other.is_relative_to(path)
               for other in paths[index + 1:]):
            raise BackupError('backup_err_paths')
    if any(root() == p or root().is_relative_to(p) for p in public):
        raise BackupError('backup_err_paths')


def initialize():
    validate_paths()
    root().mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('records', 'jobs', 'artifacts', 'work'):
        (root() / name).mkdir(mode=0o700, exist_ok=True)


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise BackupError('backup_err_not_found')
    return value


def record_path(kind, value):
    if kind not in ('records', 'jobs'):
        raise ValueError(kind)
    return root() / kind / (identifier(value) + '.json')


def artifact_path(value):
    return root() / 'artifacts' / (identifier(value) + '.entailsbackup')


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 2
        while True:
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # Windows can briefly deny replacement while a progress reader has the file open.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None):
    try:
        with Path(path).open(encoding='utf-8') as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default


def load(kind, value):
    data = read_json(record_path(kind, value))
    if data is None:
        raise BackupError('backup_err_not_found')
    return data


def save(kind, data):
    atomic_json(record_path(kind, data['id']), data)


def list_records(kind='records'):
    return sorted((read_json(p) for p in (root() / kind).glob('*.json')),
                  key=lambda item: item['created_at'], reverse=True)


def new_id():
    return uuid.uuid4().hex


def require_space(path, amount):
    path = Path(path)
    while not path.exists():
        path = path.parent
    if shutil.disk_usage(path).free < amount + settings.BACKUP_MIN_FREE_BYTES:
        raise BackupError('backup_err_space')


def remove_work(value):
    path = root() / 'work' / identifier(value)
    # Never remove an inferred path outside the designated private work directory.
    if path.is_symlink() or path.resolve().parent != (root() / 'work').resolve():
        raise BackupError('backup_err_paths')
    if path.exists():
        shutil.rmtree(path)
