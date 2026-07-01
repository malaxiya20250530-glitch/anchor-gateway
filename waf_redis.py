#!/usr/bin/env python3
"""Redis 增强模块 — 原子令牌桶 + 分布式封禁名单。

当 Redis 可用时，WAF 使用此模块实现跨进程速率限制与封禁同步。
"""

import os
import time
import logging
import hashlib

logger = logging.getLogger(__name__)

_SCRIPT_TOKEN_BUCKET = """
-- KEYS[1] = rate limit key
-- ARGV[1] = max_tokens (float)
-- ARGV[2] = refill_interval (float, seconds)
-- ARGV[3] = refill_count (int)
-- ARGV[4] = cost (int, default 1)
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_interval = tonumber(ARGV[2])
local refill_count = tonumber(ARGV[3])
local cost = tonumber(ARGV[4]) or 1

local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens, ts
if state[1] then
    tokens = tonumber(state[1])
    ts = tonumber(state[2])
else
    tokens = max_tokens
    ts = 0
end

-- refill
if ts > 0 then
    local elapsed = now_ms - ts
    if elapsed > 0 then
        local refill = math.floor(elapsed / (refill_interval * 1000)) * refill_count
        tokens = math.min(max_tokens, tokens + refill)
    end
else
    tokens = max_tokens
end

if tokens >= cost then
    tokens = tokens - cost
    redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
    redis.call('EXPIRE', key, math.ceil(refill_interval * 2))
    return {1, tokens}
else
    redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
    redis.call('EXPIRE', key, math.ceil(refill_interval * 2))
    return {0, tokens}
end
"""


class RedisTokenBucket:
    """Redis-backed 原子令牌桶 — 跨进程速率限制。

    用法:
        bucket = RedisTokenBucket(redis_client, key_prefix="waf:rl")
        allowed, remaining = bucket.consume("1.2.3.4", "/v1/chat")
    """

    def __init__(self, redis_client, key_prefix="rl:tokens", max_tokens=60,
                 refill_interval=1.0, refill_count=10):
        self._redis = redis_client
        self._prefix = key_prefix
        self._max_tokens = max_tokens
        self._refill_interval = refill_interval
        self._refill_count = refill_count
        self._sha = None
        if self._redis:
            try:
                self._sha = self._redis.script_load(_SCRIPT_TOKEN_BUCKET)
            except Exception as exc:
                logger.warning("RedisTokenBucket script load failed: %s", exc)

    def consume(self, ip: str, endpoint: str = "", cost: int = 1):
        """消耗令牌，返回 (allowed: bool, remaining: float)"""
        if not self._redis or not self._sha:
            return True, self._max_tokens  # 降级: 不限制

        key = f"{self._prefix}:{hashlib.md5(f'{ip}:{endpoint}'.encode()).hexdigest()}"
        try:
            result = self._redis.evalsha(
                self._sha, 1, key,
                self._max_tokens, self._refill_interval,
                self._refill_count, cost
            )
            allowed = bool(result[0])
            remaining = float(result[1])
            return allowed, remaining
        except Exception as exc:
            logger.warning("RedisTokenBucket evalsha failed: %s; degrading", exc)
            return True, self._max_tokens


class RedisBlocklist:
    """分布式封禁名单 — 跨进程 IP 封禁同步。

    TTL 自动过期，无需手动清理。
    """

    def __init__(self, redis_client, key_prefix="bl"):
        self._redis = redis_client
        self._prefix = key_prefix

    def block(self, ip: str, duration: int = 60, reason: str = "") -> None:
        """封禁 IP duration 秒"""
        if not self._redis:
            return
        key = f"{self._prefix}:{ip}"
        try:
            self._redis.setex(key, duration, reason or "blocked")
        except Exception as exc:
            logger.warning("RedisBlocklist.block(%s) failed: %s", ip, exc)

    def is_blocked(self, ip: str) -> bool:
        """检查 IP 是否被封禁"""
        if not self._redis:
            return False
        try:
            return bool(self._redis.exists(f"{self._prefix}:{ip}"))
        except Exception:
            return False

    def unblock(self, ip: str) -> None:
        """解禁 IP"""
        if not self._redis:
            return
        try:
            self._redis.delete(f"{self._prefix}:{ip}")
        except Exception:
            pass

    def get_all(self):
        """获取所有被封禁的 IP (仅供管理)"""
        if not self._redis:
            return {}
        try:
            keys = self._redis.keys(f"{self._prefix}:*")
            result = {}
            for k in keys:
                ip = k.decode() if isinstance(k, bytes) else k
                ip = ip.split(":", 1)[1]
                ttl = self._redis.ttl(k)
                if ttl > 0:
                    result[ip] = ttl
            return result
        except Exception:
            return {}
