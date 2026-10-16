"""Operational checks without seeds, migrations, or persistent application writes."""
import uuid

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http.request import split_domain_port, validate_host


def check_runtime(*, health_host=None, require_redis=False):
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SHOW server_version')
            version = cursor.fetchone()[0].split()[0]
        checks['database'] = {'ok': True, 'detail': f'PostgreSQL {version}'}
    except Exception:
        checks['database'] = {'ok': False, 'detail': 'Datenbank nicht erreichbar; DB_* prüfen.'}

    if checks['database']['ok']:
        try:
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
            checks['migrations'] = {'ok': not pending, 'detail': f'{len(pending)} ausstehende Migrationen.'}
        except Exception:
            checks['migrations'] = {'ok': False, 'detail': 'Migrationsstand nicht prüfbar.'}
    else:
        checks['migrations'] = {'ok': False, 'detail': 'Ohne Datenbank nicht prüfbar.'}

    cache = caches['default']
    redis = isinstance(cache, RedisCache)
    key = f'operational-check:{uuid.uuid4().hex}'
    try:
        cache.set(key, 'ready', timeout=10)
        available = cache.get(key) == 'ready'
        checks['cache'] = {'ok': available and (redis or not require_redis),
                           'detail': ('RedisCache' if redis else type(cache).__name__)
                           + (' erreichbar.' if available else ' nicht erreichbar.')
                           + (' Redis ist erforderlich.' if require_redis and not redis else '')}
    except Exception:
        checks['cache'] = {'ok': False, 'detail': 'Cache nicht erreichbar; REDIS_URL prüfen.'}
    finally:
        try:
            cache.delete(key)
        except Exception:
            checks['cache'] = {'ok': False, 'detail': 'Cacheprüfung/Aufräumen fehlgeschlagen.'}

    if health_host is not None:
        domain, _ = split_domain_port(health_host.lower())
        allowed = bool(domain and validate_host(domain, settings.ALLOWED_HOSTS))
        checks['health_host'] = {'ok': allowed, 'detail': 'Healthcheck-Host erlaubt.' if allowed
                                else 'Healthcheck-Host fehlt in ALLOWED_HOSTS.'}

    if settings.BACKUP_ENCRYPTION_KEY:
        try:
            from backups.database import PostgreSQLAdapter
            from backups.storage import encryption_key
            encryption_key()
            major = PostgreSQLAdapter().preflight()
            checks['backup_tools'] = {'ok': True, 'detail': f'Native Backup-Programme passen zu PostgreSQL {major}.'}
        except Exception:
            checks['backup_tools'] = {'ok': False, 'detail': 'Backup-Schlüssel oder passende native Programme fehlen.'}
    else:
        checks['backup_tools'] = {'ok': True, 'detail': 'Backups nicht aktiviert; native Programme nicht geprüft.'}
    return checks
