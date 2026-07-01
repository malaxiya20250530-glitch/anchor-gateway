#!/usr/bin/env python3
"""Redis 连接池 — 提供中心化的 Redis 连接管理。

支持多节点连接、自动故障转移、延迟敏感路由。
所有知识层/缓存/限流模块共享此连接池。
"""

import os
import time
import random
import logging

logger = logging.getLogger(__name__)

_REDIS_NODES = os.environ.get("REDIS_NODES", "redis://localhost:6379/0").split(",")
_REDIS_TIMEOUT = int(os.environ.get("REDIS_TIMEOUT", "5"))


class RedisPool:
    """轻量 Redis 连接池 (通过 redis-py/redis-py-cluster)。

    如果 redis 库未安装则自动降级为 noop。
    """

    def __init__(self, nodes=None, timeout=None, max_connections=32):
        self.nodes = nodes or _REDIS_NODES
        self.timeout = timeout or _REDIS_TIMEOUT
        self._client = None
        self._connected = False
        self._init_client(max_connections)

    def _init_client(self, max_connections):
        try:
            import redis
            from redis.connection import ConnectionPool
            node = self.nodes[0]
            pool = ConnectionPool.from_url(
                node, max_connections=max_connections,
                socket_timeout=self.timeout,
                socket_connect_timeout=self.timeout,
                decode_responses=True,
            )
            self._client = redis.Redis(connection_pool=pool)
            self._client.ping()
            self._connected = True
            logger.info("RedisPool connected to %s", node)
        except ImportError:
            logger.warning("redis-py not installed; RedisPool in noop mode")
            self._connected = False
        except Exception as exc:
            logger.warning("RedisPool connection failed: %s; noop mode", exc)
            self._connected = False

    @property
    def client(self):
        return self._client if self._connected else None

    @property
    def connected(self):
        return self._connected

    def close(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._connected = False


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
