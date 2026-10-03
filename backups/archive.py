"""Streaming authenticated encryption and bounded, explicit ZIP extraction."""
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings

from .errors import BackupError
from .storage import encryption_key, require_space

MAGIC = b'ENTAILSNG-BACKUP\x01'
BLOCK = 1024 * 1024
FORMAT_VERSION = 1


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(BLOCK):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or '\x00' in name or
            path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')) or
            str(path) != name or path.parts[0] not in ('database', 'media', 'private_media')):
        raise BackupError('backup_err_archive')
    return path


def media_files():
    result = {}
    for prefix, directory in (('media', settings.MEDIA_ROOT), ('private_media', settings.PRIVATE_MEDIA_ROOT)):
        directory = Path(directory)
        if not directory.exists():
            continue
        for path in directory.rglob('*'):
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise BackupError('backup_err_paths')
            if path.is_file():
                name = f'{prefix}/{path.relative_to(directory).as_posix()}'
                safe_name(name)
                result[name] = path
                if len(result) > settings.BACKUP_MAX_FILES:
                    raise BackupError('backup_err_limits')
    return result


def copy_media(destination):
    """Called only while the exclusive maintenance lock is held."""
    files = media_files()
    total = sum(path.stat().st_size for path in files.values())
    require_space(destination, total)
    import shutil
    for name, source in files.items():
        target = destination.joinpath(*safe_name(name).parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for prefix in ('media', 'private_media'):
        (destination / prefix).mkdir(mode=0o700, exist_ok=True)


def encrypt(source, destination):
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES256(encryption_key()), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    with Path(source).open('rb') as incoming, Path(destination).open('xb') as outgoing:
        os.chmod(destination, 0o600)
        outgoing.write(MAGIC + nonce)
        while chunk := incoming.read(BLOCK):
            outgoing.write(encryptor.update(chunk))
        outgoing.write(encryptor.finalize())
        outgoing.write(encryptor.tag)
        outgoing.flush()
        os.fsync(outgoing.fileno())


def decrypt(source, destination):
    size = Path(source).stat().st_size
    if size > settings.BACKUP_MAX_UPLOAD_BYTES:
        raise BackupError('backup_err_limits')
    if size < len(MAGIC) + 12 + 16:
        raise BackupError('backup_err_archive')
    require_space(destination.parent, size)
    try:
        with Path(source).open('rb') as incoming:
            if incoming.read(len(MAGIC)) != MAGIC:
                raise BackupError('backup_err_archive')
            nonce = incoming.read(12)
            incoming.seek(-16, os.SEEK_END)
            tag = incoming.read(16)
            incoming.seek(len(MAGIC) + 12)
            decryptor = Cipher(algorithms.AES256(encryption_key()), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(MAGIC)
            remaining = size - len(MAGIC) - 12 - 16
            with Path(destination).open('xb') as outgoing:
                os.chmod(destination, 0o600)
                while remaining:
                    chunk = incoming.read(min(BLOCK, remaining))
                    if not chunk:
                        raise BackupError('backup_err_archive')
                    remaining -= len(chunk)
                    outgoing.write(decryptor.update(chunk))
                outgoing.write(decryptor.finalize())
    except (InvalidTag, ValueError):
        Path(destination).unlink(missing_ok=True)
        raise BackupError('backup_err_archive') from None


def pack(snapshot, manifest, destination):
    files = sorted(p for p in snapshot.rglob('*') if p.is_file())
    if len(files) > settings.BACKUP_MAX_FILES:
        raise BackupError('backup_err_limits')
    manifest['files'] = {}
    total = 0
    for path in files:
        name = path.relative_to(snapshot).as_posix()
        safe_name(name)
        size = path.stat().st_size
        total += size
        manifest['files'][name] = {'bytes': size, 'sha256': digest_file(path)}
    if total > settings.BACKUP_MAX_UNPACKED_BYTES:
        raise BackupError('backup_err_limits')
    manifest['unpacked_bytes'] = total
    encoded_manifest = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
    if len(encoded_manifest) > settings.BACKUP_MAX_MANIFEST_BYTES:
        raise BackupError('backup_err_limits')
    temporary = destination.with_suffix('.zip')
    require_space(destination.parent, total * 2)
    try:
        with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            os.chmod(temporary, 0o600)
            for path in files:
                archive.write(path, path.relative_to(snapshot).as_posix())
            archive.writestr('manifest.json', encoded_manifest)
        encrypt(temporary, destination)
        if destination.stat().st_size > settings.BACKUP_MAX_UPLOAD_BYTES:
            destination.unlink()
            raise BackupError('backup_err_limits')
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def unpack(source, destination):
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    temporary = destination / '.authenticated.zip'
    try:
        decrypt(source, temporary)  # Authenticate the entire container before reading any ZIP metadata.
        with zipfile.ZipFile(temporary) as archive:
            entries = archive.infolist()
            if len(entries) > settings.BACKUP_MAX_FILES + 1:
                raise BackupError('backup_err_limits')
            names = [item.filename for item in entries]
            if len(names) != len(set(names)) or names.count('manifest.json') != 1:
                raise BackupError('backup_err_archive')
            info = archive.getinfo('manifest.json')
            if info.file_size > settings.BACKUP_MAX_MANIFEST_BYTES:
                raise BackupError('backup_err_limits')
            manifest = json.loads(archive.read(info))
            if manifest.get('format_version') != FORMAT_VERSION or not isinstance(manifest.get('files'), dict):
                raise BackupError('backup_err_archive')
            if set(names) != set(manifest['files']) | {'manifest.json'}:
                raise BackupError('backup_err_archive')
            total = sum(item.file_size for item in entries)
            if total > settings.BACKUP_MAX_UNPACKED_BYTES:
                raise BackupError('backup_err_limits')
            require_space(destination, total)
            case_names = set()
            for item in entries:
                if item.filename == 'manifest.json':
                    continue
                name = safe_name(item.filename)
                folded = item.filename.casefold()
                if folded in case_names:
                    raise BackupError('backup_err_archive')
                case_names.add(folded)
                mode = item.external_attr >> 16
                if item.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise BackupError('backup_err_archive')
                expected = manifest['files'][item.filename]
                if expected.get('bytes') != item.file_size:
                    raise BackupError('backup_err_archive')
                target = destination.joinpath(*name.parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                digest = hashlib.sha256()
                copied = 0
                with archive.open(item) as incoming, target.open('xb') as outgoing:
                    os.chmod(target, 0o600)
                    while chunk := incoming.read(BLOCK):
                        copied += len(chunk)
                        if copied > item.file_size:
                            raise BackupError('backup_err_limits')
                        digest.update(chunk)
                        outgoing.write(chunk)
                if copied != expected['bytes'] or digest.hexdigest() != expected.get('sha256'):
                    raise BackupError('backup_err_archive')
            for prefix in ('media', 'private_media'):
                (destination / prefix).mkdir(mode=0o700, exist_ok=True)
            return manifest
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
        raise BackupError('backup_err_archive') from None
    finally:
        temporary.unlink(missing_ok=True)
