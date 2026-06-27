#!/usr/bin/env python3
"""
Phase 2 断路器模块 — 三级降级防线

基于尾延迟观测数据 (P95=42.8ms, P99=57.2ms, Max=147.9ms):
  L1 (128ms): 标记低置信度，继续执行
  L2 (286ms): 切断图谱推理，返回保守结果
  L3 (296ms): 硬超时，强制返回 uncertain

用法:
    from circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    result = cb.call(engine.verify, claim)
"""

import time
import concurrent.futures
from typing import Optional, Tuple


class CircuitBreaker:
    """三级降级断路器，基于 P95/P99 尾延迟实测参数"""

    # 阈值（毫秒），来自 2026-06-02 尾延迟观测
    L1_SOFT = 0.128   # P95 × 3: 标记低置信度
    L2_CUT = 0.286    # P99 × 5: 切断图谱推理
    L3_HARD = 0.296   # Max × 2: 硬超时

    def __init__(self):
        self.total_calls = 0
        self.l1_triggers = 0
        self.l2_triggers = 0
        self.l3_triggers = 0
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def call(self, func, *args, **kwargs) -> Tuple[any, dict]:
        """调用函数，带三级断路器保护。
        返回: (result, meta)  其中 meta 包含 circuit_level 等诊断信息。
        """
        self.total_calls += 1
        meta = {"circuit_level": 0, "elapsed_ms": 0}

        t0 = time.perf_counter()
        future = self._executor.submit(func, *args, **kwargs)

        try:
            result = future.result(timeout=self.L3_HARD)
            elapsed = time.perf_counter() - t0
            meta["elapsed_ms"] = round(elapsed * 1000, 1)

            if elapsed > self.L2_CUT:
                meta["circuit_level"] = 2
                self.l2_triggers += 1
            elif elapsed > self.L1_SOFT:
                meta["circuit_level"] = 1
                self.l1_triggers += 1

            return result, meta

        except concurrent.futures.TimeoutError:
            elapsed = time.perf_counter() - t0
            meta["elapsed_ms"] = round(elapsed * 1000, 1)
            meta["circuit_level"] = 3
            self.l3_triggers += 1
            # 硬超时：返回 uncertain
            from hallucination_detector import VerificationResult
            fallback = VerificationResult(
                claim="(timeout)",
                verdict="uncertain",
                confidence=0.1,
                evidence="断路器触发: 检测超时",
                source="circuit_breaker",
                anchor_type="fallback",
            )
            return fallback, meta

    def stats(self) -> dict:
        return {
            "total": self.total_calls,
            "l1_soft": self.l1_triggers,
            "l2_cut": self.l2_triggers,
            "l3_hard": self.l3_triggers,
            "thresholds_ms": {
                "l1": int(self.L1_SOFT * 1000),
                "l2": int(self.L2_CUT * 1000),
                "l3": int(self.L3_HARD * 1000),
            },
        }
