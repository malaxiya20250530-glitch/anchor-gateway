#!/usr/bin/env python3
"""Redis 连接池 — 支持外部 Redis 和内置 fakeredis 自动降级。

当 REDIS_NODES 为空或连接失败时，自动使用 fakeredis（纯 Python 内存版）。
零外部依赖，适用于 Render 免费套餐。
"""

import os
import logging

logger = logging.getLogger(__name__)

_REDIS_NODES = (os.environ.get("REDIS_NODES") or "").strip()
_REDIS_TIMEOUT = int(os.environ.get("REDIS_TIMEOUT", "5"))


class RedisPool:
    """轻量 Redis 连接池 — 外部 Redis 优先, fakeredis 保底。"""

    def __init__(self, nodes=None, timeout=None):
        self.nodes = nodes or _REDIS_NODES
        self.timeout = timeout or _REDIS_TIMEOUT
        self._client = None
        self._connected = False
        self._fake = False
        self._init_client()

    def _init_client(self):
        # 1. 尝试外部 Redis
        if self.nodes:
            for node in self.nodes.split(","):
                node = node.strip()
                if not node:
                    continue
                try:
                    import redis
                    from redis.connection import ConnectionPool
                    pool = ConnectionPool.from_url(
                        node, max_connections=16,
                        socket_timeout=self.timeout,
                        socket_connect_timeout=self.timeout,
                        decode_responses=True,
                    )
                    client = redis.Redis(connection_pool=pool)
                    client.ping()
                    self._client = client
                    self._connected = True
                    logger.info("RedisPool connected to %s", node)
                    return
                except ImportError:
                    logger.warning("redis-py not installed")
                    break
                except Exception as exc:
                    logger.warning("RedisPool %s failed: %s", node, exc)

        # 2. 降级到 fakeredis (纯 Python 内存版)
        try:
            import fakeredis
            self._client = fakeredis.FakeRedis(decode_responses=True)
            self._connected = True
            self._fake = True
            logger.info("RedisPool using fakeredis (in-memory, no persistence)")
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


# 全局默认连接池
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
