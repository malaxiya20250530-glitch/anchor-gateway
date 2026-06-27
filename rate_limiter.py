#!/usr/bin/env python3
"""
令牌桶速率限制器 — 纯 Python 标准库
支持并发控制 + 熔断降级
"""

import time
import threading
from collections import deque


class TokenBucket:
    """令牌桶 — 平滑限流"""

    def __init__(self, rate: float = 10.0, burst: int = 20):
        """
        rate:  每秒补充令牌数
        burst: 桶容量（允许突发）
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> bool:
        """尝试获取令牌，成功返回 True"""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class CircuitBreaker:
    """熔断器 — 连续失败 N 次后断开，冷却后半开试探"""

    def __init__(self, failure_threshold: int = 5,
                 recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_failure = 0.0
        self._state = "closed"  # closed → open → half_open → closed
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    def call(self, func, *args, **kwargs):
        """
        受熔断保护的调用
        返回 (success: bool, result, error: str)
        """
        with self._lock:
            if self._state == "open":
                if time.monotonic() - self._last_failure >= self.recovery_timeout:
                    self._state = "half_open"
                else:
                    return False, None, "circuit_open"

        try:
            result = func(*args, **kwargs)
            with self._lock:
                self._failures = 0
                if self._state == "half_open":
                    self._state = "closed"
            return True, result, ""
        except Exception as e:
            with self._lock:
                self._failures += 1
                self._last_failure = time.monotonic()
                if self._failures >= self.failure_threshold:
                    self._state = "open"
            return False, None, str(e)


class RateLimitedGate:
    """
    网关限流门 — 令牌桶 + 熔断器组合

    用法:
      gate = RateLimitedGate(rate=10, burst=20)
      if gate.allow():
          # 处理请求
          gate.report(success=True)
      else:
          return 429
    """

    def __init__(self, rate: float = 10.0, burst: int = 20,
                 failure_threshold: int = 5):
        self.bucket = TokenBucket(rate=rate, burst=burst)
        self.breaker = CircuitBreaker(failure_threshold=failure_threshold)
        self._recent_latency = deque(maxlen=100)

    def allow(self, cost: float = 1.0) -> bool:
        """请求是否允许通过"""
        if self.breaker.state == "open":
            return False
        return self.bucket.acquire(cost)

    def report(self, success: bool, latency_ms: float = 0):
        """上报请求结果"""
        self._recent_latency.append(latency_ms)
        if not success:
            # 通过熔断器记录失败
            self.breaker.call(lambda: 1 / 0)  # 故意失败以触发计数

    @property
    def stats(self) -> dict:
        latencies = list(self._recent_latency)
        latencies.sort()
        n = len(latencies)
        return {
            "tokens_available": round(self.bucket.available, 1),
            "circuit_state": self.breaker.state,
            "recent_requests": n,
            "p50_ms": round(latencies[n // 2], 1) if n else 0,
            "p95_ms": round(latencies[int(n * 0.95)], 1) if n > 1 else 0,
            "p99_ms": round(latencies[int(n * 0.99)], 1) if n > 2 else 0,
        }


# ── 演示 ────────────────────────────────────────────

if __name__ == "__main__":
    print("=== 令牌桶 + 熔断器 演示 ===\n")

    gate = RateLimitedGate(rate=5, burst=10, failure_threshold=3)

    # 模拟正常流量
    for i in range(12):
        allowed = gate.allow()
        gate.report(success=allowed, latency_ms=i * 3.5)
        print(f"  请求{i+1}: {'✅ 放行' if allowed else '⛔ 限流'}")

    print(f"\n  统计: {gate.stats()}")
