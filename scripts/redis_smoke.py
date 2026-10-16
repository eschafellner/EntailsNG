#!/usr/bin/env python3
"""Prove real, cross-process Django Redis caching with only a private expiring key."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    if os.environ.get('ENTAILS_SETUP_SMOKE') != '1' or not os.environ.get('REDIS_URL'):
        raise RuntimeError('Explicit disposable Redis environment required')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.core.cache import caches
    from django.core.cache.backends.redis import RedisCache
    cache = caches['default']
    if not isinstance(cache, RedisCache):
        raise RuntimeError('RedisCache is not active')
    if len(sys.argv) == 4 and sys.argv[1] == '--read':
        if not sys.argv[2].startswith('entails-smoke:') or cache.get(sys.argv[2]) != sys.argv[3]:
            raise RuntimeError('Value not visible to second process')
        return
    key, value = 'entails-smoke:' + secrets.token_hex(16), secrets.token_hex(16)
    try:
        cache.set(key, value, timeout=30)
        assert cache.get(key) == value
        from django.conf import settings
        import redis
        with redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=3, socket_timeout=3) as client:
            assert 0 < client.ttl(cache.make_key(key)) <= 30
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--read', key, value],
                       check=True, capture_output=True, timeout=20)
    finally:
        cache.delete(key)
    print(json.dumps({'redis': 'passed', 'backend': 'RedisCache', 'cross_process': True, 'ttl': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Redis-Smoke fehlgeschlagen; REDIS_URL, Backend und Erreichbarkeit prüfen.') from None
