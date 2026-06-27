#!/usr/bin/env python3
"""
异步背压控制 — 环形缓冲区 + 队列降级（纯标准库）

保证编译通道（LLM）不受觉察通道消费慢的影响：
  - 环形缓冲区暂存待观察段
  - 队列堆积 > 阈值 → 自动降级（跳过Web验证，仅本地检查）
  - 队列溢出 → 丢包 + 标记 [Confidence: Low (Downgraded)]
"""

import time
import threading
from collections import deque
from enum import Enum
from typing import Optional, Callable
from logger import log


class CheckLevel(Enum):
    FULL = "full"           # 全量：KG + 向量 + Web
    LOCAL = "local"         # 降级：仅 KG + 向量
    PATTERN = "pattern"     # 最低：仅模式匹配
    SKIP = "skip"           # 丢弃


class RingBuffer:
    """无锁环形缓冲区（单生产者单消费者安全）"""

    def __init__(self, capacity: int = 64):
        self._buf = [None] * capacity
        self._capacity = capacity
        self._head = 0   # 写入位置
        self._tail = 0   # 读取位置
        self._size = 0
        self._lock = threading.Lock()

    def push(self, item) -> bool:
        """入队，满则返回 False"""
        with self._lock:
            if self._size >= self._capacity:
                return False
            self._buf[self._head] = item
            self._head = (self._head + 1) % self._capacity
            self._size += 1
            return True

    def pop(self):
        """出队，空则返回 None"""
        with self._lock:
            if self._size == 0:
                return None
            item = self._buf[self._tail]
            self._buf[self._tail] = None
            self._tail = (self._tail + 1) % self._capacity
            self._size -= 1
            return item

    @property
    def usage(self) -> float:
        """0~1 队列占用率"""
        with self._lock:
            return self._size / self._capacity

    @property
    def size(self) -> int:
        with self._lock:
            return self._size


class BackpressureController:
    """
    背压控制器 — 根据队列堆积自动调整检查级别

    水位线:
      usage < 0.3  → FULL   (全量检查)
      usage < 0.6  → LOCAL  (本地检查，跳过Web)
      usage < 0.9  → PATTERN (仅模式匹配)
      usage >= 0.9 → SKIP   (丢弃)
    """

    def __init__(self, buffer_capacity: int = 64,
                 downgrade_thresholds: tuple = (0.3, 0.6, 0.9)):
        self.buffer = RingBuffer(buffer_capacity)
        self.thresholds = downgrade_thresholds
        self._drops = 0
        self._downgrades = {"FULL→LOCAL": 0, "LOCAL→PATTERN": 0, "PATTERN→SKIP": 0}
        self._lock = threading.Lock()

    def decide_level(self) -> CheckLevel:
        """根据当前队列水位决定检查级别"""
        usage = self.buffer.usage
        t = self.thresholds

        if usage < t[0]:
            return CheckLevel.FULL
        elif usage < t[1]:
            return CheckLevel.LOCAL
        elif usage < t[2]:
            return CheckLevel.PATTERN
        else:
            return CheckLevel.SKIP

    def submit(self, segment: str) -> tuple[bool, CheckLevel]:
        """
        提交一个语义段到缓冲区

        返回: (accepted: bool, check_level: CheckLevel)
        """
        level = self.decide_level()

        if level == CheckLevel.SKIP:
            with self._lock:
                self._drops += 1
                self._downgrades["PATTERN→SKIP"] += 1
            return False, level

        accepted = self.buffer.push(segment)
        if not accepted:
            with self._lock:
                self._drops += 1
            return False, CheckLevel.SKIP

        return True, level

    def consume(self) -> Optional[tuple[str, CheckLevel]]:
        """消费一个段（由觉察通道调用）"""
        segment = self.buffer.pop()
        if segment is None:
            return None
        level = self.decide_level()
        return segment, level

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "buffer_size": self.buffer.size,
                "buffer_capacity": self.buffer._capacity,
                "buffer_usage": round(self.buffer.usage, 3),
                "current_level": self.decide_level().value,
                "total_drops": self._drops,
                "downgrades": dict(self._downgrades),
            }


# ── 集成到觉察通道 ────────────────────────────────

class BackpressureAwareChannel:
    """
    带背压控制的觉察通道包装器

    在原有觉察通道外包裹一层：
      - 编译通道输出 → submit 到环形缓冲
      - 觉察工作线程 → consume → 运行检查器
      - 水位过高 → 自动降级
    """

    def __init__(self, check_fn: Callable, capacity: int = 64):
        self.controller = BackpressureController(capacity)
        self._check_fn = check_fn      # 实际检查函数
        self._results: list[dict] = []
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        """启动觉察工作线程"""
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def stop(self):
        """停止工作线程"""
        self._running = False
        if self._worker:
            self._worker.join(timeout=2.0)

    def observe(self, segment: str) -> dict:
        """
        非阻塞提交：不等待检查完成，立即返回

        返回: {accepted, level, queue_position}
        """
        accepted, level = self.controller.submit(segment)
        return {
            "accepted": accepted,
            "level": level.value,
            "queue_usage": round(self.controller.buffer.usage, 2),
        }

    def _worker_loop(self):
        """觉察工作线程：从缓冲区消费并运行检查"""
        while self._running:
            item = self.controller.consume()
            if item is None:
                time.sleep(0.01)  # 空转等待
                continue

            segment, level = item
            try:
                result = self._check_fn(segment, level)
                with self._lock:
                    self._results.append({
                        "segment": segment[:80],
                        "level": level.value,
                        "result": result,
                        "time": time.time(),
                    })
            except Exception as e:
                log.warning("检查器执行失败: %s", e)

    def get_results(self, clear: bool = True) -> list[dict]:
        """获取累积的检查结果"""
        with self._lock:
            results = list(self._results)
            if clear:
                self._results.clear()
            return results


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=== 背压控制器 演示 ===\n")

    bp = BackpressureController(buffer_capacity=8)

    # 模拟高速生成 → 觉察通道消费慢
    print("模拟: LLM 以 50 tok/s 生成, 觉察以 5 seg/s 消费")
    print()

    for i in range(12):
        accepted, level = bp.submit(f"段{i}: 这是第{i}个语义段的内容")
        print(f"  提交段{i}: {'✅ 接受' if accepted else '❌ 丢弃'} "
              f"级别={level.value} 队列={bp.buffer.usage:.0%}")

    print(f"\n统计: {bp.stats}")
