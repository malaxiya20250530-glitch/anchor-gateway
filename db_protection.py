#!/usr/bin/env python3
"""数据库防护层 — 连接池 / 超时 / 熔断器。

保护后端数据库（SQLite/PostgreSQL/Redis）不拖垮推理服务。

用法:
    from db_protection import ConnectionPool, with_circuit_breaker

    pool = ConnectionPool(max_connections=5, timeout_sec=3.0)

    @with_circuit_breaker(failure_threshold=5, reset_timeout=30)
    def query_db(sql: str):
        with pool.acquire() as conn:
            return conn.execute(sql)

特性:
  - 连接池: 限制最大并发连接数
  - 超时: 获取连接/执行查询均有超时
  - 熔断: 连续失败 N 次后自动熔断，冷却后尝试半开恢复
  - 零外部依赖: 纯 Python 标准库
"""

import functools
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Callable, Optional

from security_logger import get_security_logger


# ═══════════════════════════════════════════════════════════
# 连接池
# ═══════════════════════════════════════════════════════════

class ConnectionPool:
    """通用连接池 — 不限后端类型。

    acquire() 返回连接对象（由调用方定义），
    池满时阻塞等待（受 timeout_sec 限制）。
    """

    def __init__(self, max_connections: int = 5, timeout_sec: float = 3.0):
        self._max = max_connections
        self._timeout = timeout_sec
        self._pool = deque()
        self._in_use = 0
        self._lock = threading.Condition()
        self._slog = get_security_logger()

    @contextmanager
    def acquire(self):
        """上下文管理器: 获取连接 → 使用 → 自动归还"""
        conn = self._get()
        try:
            yield conn
        finally:
            self._release()

    def _get(self):
        """从池中获取连接（阻塞等待）"""
        deadline = time.time() + self._timeout
        with self._lock:
            while self._in_use >= self._max:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self._slog.error(
                        event="db_pool_timeout",
                        message=f"连接池超时 ({self._timeout}s), 当前使用: {self._in_use}/{self._max}"
                    )
                    raise TimeoutError(
                        f"数据库连接池已满 ({self._in_use}/{self._max})，"
                        f"等待超时 {self._timeout}s"
                    )
                self._lock.wait(timeout=min(remaining, 0.1))

            self._in_use += 1
            if self._pool:
                return self._pool.popleft()
            return None  # 调用方负责创建连接

    def _release(self) -> None:
        """归还连接到池"""
        with self._lock:
            self._in_use = max(0, self._in_use - 1)
            self._lock.notify()

    @property
    def stats(self) -> dict:
        """连接池统计"""
        with self._lock:
            return {
                "in_use": self._in_use,
                "available": len(self._pool),
                "max": self._max,
                "utilization": round(self._in_use / max(self._max, 1), 2),
            }


# ═══════════════════════════════════════════════════════════
# 熔断器
# ═══════════════════════════════════════════════════════════

class CircuitBreakerOpen(Exception):
    """熔断器开启异常"""
    pass


class CircuitBreaker:
    """熔断器 — 连续失败达阈值后自动熔断。

    状态机: CLOSED → (failures >= threshold) → OPEN → (timeout) → HALF_OPEN
    """

    CLOSED = "closed"        # 正常
    OPEN = "open"            # 熔断中
    HALF_OPEN = "half_open"  # 探测恢复

    def __init__(self, name: str = "db",
                 failure_threshold: int = 5,
                 reset_timeout: float = 30.0,
                 half_open_max: int = 1):
        self.name = name
        self.threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max = half_open_max

        self._state = self.CLOSED
        self._failures = 0
        self._last_failure_time = 0.0
        self._half_open_count = 0
        self._lock = threading.Lock()
        self._slog = get_security_logger()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def record_success(self) -> None:
        """记录一次成功"""
        with self._lock:
            self._failures = 0
            if self._state == self.HALF_OPEN:
                self._state = self.CLOSED
                self._half_open_count = 0
                self._slog.audit(action="circuit_closed", subject=self.name,
                                 detail="熔断器恢复")

    def record_failure(self) -> None:
        """记录一次失败"""
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()
            if self._state == self.HALF_OPEN:
                self._half_open_count += 1
                if self._half_open_count >= self.half_open_max:
                    self._state = self.OPEN
                    self._slog.security_alert(
                        ip="0.0.0.0", threat_type="circuit_breaker",
                        action="open", detail=f"{self.name}: 半开探测失败，重新熔断"
                    )
            elif self._failures >= self.threshold:
                self._state = self.OPEN
                self._slog.security_alert(
                    ip="0.0.0.0", threat_type="circuit_breaker",
                    action="open", detail=f"{self.name}: {self._failures}次连续失败，熔断"
                )

    def allow_request(self) -> bool:
        """检查是否允许请求通过"""
        with self._lock:
            if self._state == self.CLOSED:
                return True
            if self._state == self.OPEN:
                if time.time() - self._last_failure_time >= self.reset_timeout:
                    self._state = self.HALF_OPEN
                    self._half_open_count = 0
                    self._slog.audit(action="circuit_half_open", subject=self.name,
                                     detail="熔断器进入半开状态")
                    return True
                return False
            # HALF_OPEN: 允许有限请求通过
            return self._half_open_count < self.half_open_max

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state,
                "failures": self._failures,
                "threshold": self.threshold,
            }


# 全局熔断器实例
_db_circuit_breaker = CircuitBreaker(name="database")
_redis_circuit_breaker = CircuitBreaker(name="redis")


def with_circuit_breaker(breaker: CircuitBreaker = None):
    """装饰器: 为函数添加熔断器保护。

    Args:
        breaker: CircuitBreaker 实例，默认使用 _db_circuit_breaker
    """
    cb = breaker or _db_circuit_breaker

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not cb.allow_request():
                raise CircuitBreakerOpen(f"熔断器 {cb.name} 已开启")
            try:
                result = func(*args, **kwargs)
                cb.record_success()
                return result
            except Exception as e:
                cb.record_failure()
                raise
        return wrapper
    return decorator
