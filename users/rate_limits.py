"""Reserve a request before performing side effects, with a fixed expiry window."""
import logging
from django.core.cache import cache
from django.core.cache.backends.redis import RedisCache

logger = logging.getLogger(__name__)

_INCREMENT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


def reserve_rate_limit(key, *, limit, timeout):
    try:
        if isinstance(cache._connections[cache._alias], RedisCache):
            backend = cache._connections[cache._alias]
            redis_key = backend.make_and_validate_key(key)
            client = backend._cache.get_client(redis_key, write=True)
            count = client.eval(_INCREMENT, 1, redis_key, timeout)
            return count <= limit
        # LocMemCache's add/incr are atomic under its lock. Retry only on expiry;
        # never replace a concurrent counter with a read-modify-write set().
        for _ in range(3):
            if cache.add(key, 1, timeout=timeout):
                return True
            try:
                return cache.incr(key) <= limit
            except ValueError:
                continue
        return False
    except Exception:
        logger.exception('Rate limit reservation failed')
        return False
