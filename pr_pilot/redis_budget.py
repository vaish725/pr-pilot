from typing import Optional
import logging

logger = logging.getLogger(__name__)


def check_and_decrement_budget(redis_conn, key: str, amount: int, daily_budget: int, ttl: int = 86400) -> Optional[int]:
    """Atomically ensure the budget key exists and decrement by amount.

    Returns the remaining budget (int) after decrement, or -1 if insufficient, or None on failure.
    This uses a small Lua script to initialize the key (with expire) and perform check-and-decrement.
    """
    lua = r"""
    local key = KEYS[1]
    local amount = tonumber(ARGV[1])
    local daily = tonumber(ARGV[2])
    local ttl = tonumber(ARGV[3])
    local cur = redis.call('GET', key)
    if not cur then
      redis.call('SET', key, daily, 'EX', ttl)
      cur = daily
    end
    cur = tonumber(cur)
    if cur < amount then
      return -1
    end
    redis.call('DECRBY', key, amount)
    return tonumber(redis.call('GET', key))
    """
    try:
        # redis-py eval takes script, numkeys, key, args...
        res = redis_conn.eval(lua, 1, key, amount, daily_budget, ttl)
        # redis returns bytes/str/int depending on client; force int
        try:
            return int(res)
        except Exception:
            return None
    except Exception:
        logger.exception('Redis budget check_and_decrement failed')
        return None
