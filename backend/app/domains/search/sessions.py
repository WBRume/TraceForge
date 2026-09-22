"""User-isolated bounded ranking snapshots; Redis failure is explicit."""
import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4
from fastapi import HTTPException
from app.config import settings
from app.core.redis_client import get_redis_client


def signing_key():
    return settings.SEARCH_CURSOR_SECRET.encode() if settings.SEARCH_CURSOR_SECRET else hmac.new(
        settings.JWT_SECRET_KEY.encode(), b'traceforge-search-cursor-v1', hashlib.sha256).digest()


def sign(payload):
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(signing_key(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + mac


def unsign(token, purpose, user_id):
    try:
        if len(token) > 4096:
            raise ValueError()
        raw, mac = token.split(".")
        expected = hmac.new(signing_key(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if data["purpose"] != purpose or data["user"] != user_id or data["expires"] < time.time():
            raise ValueError()
        return data
    except (ValueError, KeyError, TypeError):
        raise HTTPException(410, "SEARCH_CURSOR_EXPIRED") from None


CREATE = """
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 300)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - 300)
if redis.call('ZCARD', KEYS[2]) >= 1000 then return 0 end
while redis.call('ZCARD', KEYS[1]) >= 3 do
  local old = redis.call('ZRANGE', KEYS[1], 0, 0)[1]
  redis.call('DEL', old)
  redis.call('ZREM', KEYS[1], old)
  redis.call('ZREM', KEYS[2], old)
end
redis.call('SET', KEYS[3], ARGV[2], 'EX', 120)
redis.call('ZADD', KEYS[1], now, KEYS[3])
redis.call('ZADD', KEYS[2], now, KEYS[3])
redis.call('EXPIRE', KEYS[1], 300)
redis.call('EXPIRE', KEYS[2], 300)
return 1
"""
READ = """
local value = redis.call('GET', KEYS[1])
if not value then return nil end
local remaining = tonumber(ARGV[1]) - tonumber(ARGV[2])
if remaining <= 0 then redis.call('DEL', KEYS[1]); return nil end
redis.call('EXPIRE', KEYS[1], math.min(120, remaining))
return value
"""


def key(user, session):
    return f"{settings.SEARCH_SESSION_NAMESPACE}:{user}:{session}"


async def create(user, binding, candidates, metadata):
    sid = uuid4().hex
    snapshot = dict(binding=binding, candidates=candidates, metadata=metadata, expires=int(time.time()) + 300)
    raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode()) > 524288:
        raise HTTPException(503, "SEARCH_SESSION_TOO_LARGE")
    try:
        redis = await get_redis_client()
        accepted = await redis.eval(CREATE, 3, key(user, "sessions"), key("all", "sessions"), key(user, sid), time.time(), raw)
        if not accepted:
            raise HTTPException(429, "SEARCH_SESSION_CAPACITY")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "SEARCH_SESSION_UNAVAILABLE") from None
    return sid, snapshot


async def read(user, cursor, binding):
    token = unsign(cursor, "search", user)
    try:
        redis = await get_redis_client()
        raw = await redis.eval(READ, 1, key(user, token["session"]), token["expires"], int(time.time()))
    except Exception:
        raise HTTPException(503, "SEARCH_SESSION_UNAVAILABLE") from None
    if not raw:
        raise HTTPException(410, "SEARCH_CURSOR_EXPIRED")
    data = json.loads(raw)
    if data["binding"] != binding:
        raise HTTPException(410, "SEARCH_CURSOR_EXPIRED")
    return token["session"], data, token["offset"], token["shown"]


def cursor(user, sid, snapshot, offset, shown):
    return sign(dict(purpose="search", user=user, session=sid, offset=offset, shown=shown, expires=snapshot["expires"]))


async def close(user, token):
    data = unsign(token, "search", user)
    redis = await get_redis_client()
    await redis.delete(key(user, data["session"]))
    await redis.zrem(key(user, "sessions"), key(user, data["session"]))
    await redis.zrem(key("all", "sessions"), key(user, data["session"]))
