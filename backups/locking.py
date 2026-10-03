"""Cross-process shared locks: flock on Linux, LockFileEx on Windows."""
import contextlib
import os
import threading
import time

from django.conf import settings

from .errors import BackupError
from .storage import initialize, root

_local = threading.local()


class FileLock:
    def __init__(self, name, *, exclusive=True, timeout=0):
        self.name, self.exclusive, self.timeout = name, exclusive, timeout
        self.stream = None

    def __enter__(self):
        if not (root() / 'work').is_dir():
            initialize()
        self.stream = open(root() / self.name, 'a+b')
        deadline = time.monotonic() + self.timeout
        while True:
            if self._acquire():
                return self
            if time.monotonic() >= deadline:
                self.stream.close()
                self.stream = None
                raise BackupError('backup_err_busy')
            time.sleep(0.05)

    def _acquire(self):
        if os.name == 'nt':
            import ctypes
            import msvcrt
            from ctypes import wintypes

            class Overlapped(ctypes.Structure):
                _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                            ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                            ('hEvent', wintypes.HANDLE)]

            self.overlapped = Overlapped()
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
            kernel.LockFileEx.restype = wintypes.BOOL
            self.kernel = kernel
            self.handle = msvcrt.get_osfhandle(self.stream.fileno())
            result = kernel.LockFileEx(self.handle, 1 | (2 if self.exclusive else 0), 0, 1, 0,
                                       ctypes.byref(self.overlapped))
            if not result and ctypes.get_last_error() not in (33, 158):
                raise ctypes.WinError(ctypes.get_last_error())
            return bool(result)
        import fcntl
        try:
            fcntl.flock(self.stream, (fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def __exit__(self, *args):
        if self.stream is None:
            return
        try:
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                self.kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                     wintypes.DWORD, wintypes.DWORD,
                                                     ctypes.POINTER(type(self.overlapped))]
                self.kernel.UnlockFileEx(self.handle, 0, 1, 0, ctypes.byref(self.overlapped))
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None


def maintenance_active():
    return (root() / 'maintenance.json').exists()


@contextlib.contextmanager
def access_guard():
    """Admit readers before the maintenance marker, then let the worker drain them."""
    if getattr(_local, 'depth', 0):
        _local.depth += 1
        try:
            yield
        finally:
            _local.depth -= 1
        return
    if maintenance_active():
        raise BackupError('backup_err_maintenance')
    if not settings.BACKUP_ENCRYPTION_KEY:
        yield
        return
    with FileLock('access.lock', exclusive=False):
        if maintenance_active():
            raise BackupError('backup_err_maintenance')
        _local.depth = 1
        try:
            yield
        finally:
            _local.depth = 0


def guarded_email(function):
    from functools import wraps

    @wraps(function)
    def wrapper(*args, **kwargs):
        if (root() / 'mail-paused.json').exists():
            return (0, 0)
        try:
            with access_guard():
                from django.db import connections
                try:
                    return function(*args, **kwargs)
                finally:
                    # Persistent mail processes must not retain a replaced database connection.
                    if not connections['default'].in_atomic_block:
                        connections.close_all()
        except BackupError:
            return (0, 0)
    return wrapper
