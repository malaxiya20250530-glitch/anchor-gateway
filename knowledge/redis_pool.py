#!/usr/bin/env python3
"""Redis 连接池 — 三重自动降级:

1. REDIS_NODES → redis-py TCP (外部 Redis)
2. UPSTASH_URL + UPSTASH_TOKEN → upstash-redis HTTP (Serverless Redis)
3. 空配置 → fakeredis (纯 Python 内存版)

upstash_redis 的 API 与 redis-py 略有差异, 自动适配。
"""

import os
import logging

logger = logging.getLogger(__name__)

_REDIS_NODES = (os.environ.get("REDIS_NODES") or "").strip()
_UPSTASH_URL = (os.environ.get("UPSTASH_URL") or "").strip()
_UPSTASH_TOKEN = (os.environ.get("UPSTASH_TOKEN") or "").strip()
_REDIS_TIMEOUT = int(os.environ.get("REDIS_TIMEOUT", "5"))


class _UpstashCompat:
    """upstash_redis → redis-py API 兼容适配层"""

    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        return getattr(self._client, name)

    def xadd(self, name, fields, id="*", maxlen=None, approximate=True):
        """适配 redis-py 的 xadd(name, fields, id='*', maxlen=None)"""
        return self._client.xadd(
            key=name, id=id, data=fields,
            maxlen=maxlen, approximate_trim=approximate,
        )


class RedisPool:
    """轻量 Redis 连接池 — 外部 Redis > Upstash HTTP > fakeredis。"""

    def __init__(self):
        self._client = None
        self._connected = False
        self._fake = False
        self._init_client()

    def _init_client(self):
        # 1. 外部 TCP Redis
        if _REDIS_NODES:
            for node in _REDIS_NODES.split(","):
                node = node.strip()
                if not node:
                    continue
                try:
                    import redis
                    from redis.connection import ConnectionPool
                    pool = ConnectionPool.from_url(
                        node, max_connections=16,
                        socket_timeout=_REDIS_TIMEOUT,
                        socket_connect_timeout=_REDIS_TIMEOUT,
                        decode_responses=True,
                    )
                    client = redis.Redis(connection_pool=pool)
                    client.ping()
                    self._client = client
                    self._connected = True
                    logger.info("RedisPool → external Redis: %s", node)
                    return
                except ImportError:
                    break
                except Exception as exc:
                    logger.warning("RedisPool external %s: %s", node, exc)

        # 2. Upstash HTTP Redis
        if _UPSTASH_URL and _UPSTASH_TOKEN:
            try:
                from upstash_redis import Redis as UpstashRedis
                raw = UpstashRedis(url=_UPSTASH_URL, token=_UPSTASH_TOKEN)
                raw.ping()
                self._client = _UpstashCompat(raw)
                self._connected = True
                logger.info("RedisPool → Upstash HTTP: %s", _UPSTASH_URL)
                return
            except ImportError:
                logger.warning("upstash-redis not installed")
            except Exception as exc:
                logger.warning("RedisPool Upstash failed: %s", exc)

        # 3. fakeredis 保底
        try:
            import fakeredis
            self._client = fakeredis.FakeRedis(decode_responses=True)
            self._connected = True
            self._fake = True
            logger.info("RedisPool → fakeredis (in-memory)")
        except ImportError:
            logger.warning("fakeredis not installed; Redis disabled")
            self._connected = False

    @property
    def client(self):
        return self._client if self._connected else None

    @property
    def connected(self):
        return self._connected

    @property
    def is_fake(self):
        return self._fake

    def close(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._connected = False
            self._fake = False


_default_pool = None


def get_redis():
    """获取全局 Redis 连接"""
    global _default_pool
    if _default_pool is None:
        _default_pool = RedisPool()
    return _default_pool.client


def fact_key(uid: str) -> str:
    return f"fact:{uid}"


def ratelimit_key(ip: str, endpoint: str) -> str:
    return f"rl:{ip}:{endpoint}"
