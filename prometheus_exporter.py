#!/usr/bin/env python3
"""
④ Prometheus 指标导出器 — 纯标准库 /metrics 端点

导出格式符合 Prometheus text exposition format
可被 Prometheus → Grafana 直接抓取
"""

import time
import threading
from collections import deque, Counter
from typing import Optional


# ── 指标注册表 ──────────────────────────────────

class Metric:
    """单个 Prometheus 指标"""
    def __init__(self, name: str, help_text: str, mtype: str = "gauge"):
        self.name = name
        self.help = help_text
        self.type = mtype
        self._value = 0.0
        self._labels: dict[str, str] = {}
        self._lock = threading.Lock()

    def set(self, value: float, labels: dict = None):
        with self._lock:
            self._value = value
            if labels:
                self._labels = labels

    def inc(self, delta: float = 1.0):
        with self._lock:
            self._value += delta

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def render(self) -> str:
        """渲染为 Prometheus text 格式"""
        lines = [f"# HELP {self.name} {self.help}",
                 f"# TYPE {self.name} {self.type}"]
        with self._lock:
            if self._labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in self._labels.items())
                lines.append(f"{self.name}{{{label_str}}} {self._value}")
            else:
                lines.append(f"{self.name} {self._value}")
        return "\n".join(lines)


class CounterMetric(Metric):
    """累积计数器"""
    def __init__(self, name: str, help_text: str):
        super().__init__(name, help_text, "counter")


class HistogramMetric(Metric):
    """简单直方图（预定义桶）"""
    def __init__(self, name: str, help_text: str,
                 buckets: list[float] = None):
        super().__init__(name, help_text, "histogram")
        self.buckets = buckets or [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        self._bucket_counts = Counter()
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def observe(self, value: float):
        with self._lock:
            self._sum += value
            self._count += 1
            for b in self.buckets:
                if value <= b:
                    self._bucket_counts[b] += 1
                    break

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}",
                 f"# TYPE {self.name} histogram"]
        with self._lock:
            cum = 0
            for b in sorted(self.buckets):
                cum += self._bucket_counts.get(b, 0)
                lines.append(f'{self.name}_bucket{{le="{b}"}} {cum}')
            lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._count}')
            lines.append(f"{self.name}_sum {self._sum}")
            lines.append(f"{self.name}_count {self._count}")
        return "\n".join(lines)


# ── 觉察网关指标集 ──────────────────────────────

class AwarenessMetricsRegistry:
    """觉察网关专用 Prometheus 指标注册表"""

    def __init__(self):
        self._start_time = time.time()

        # 请求指标
        self.requests_total = CounterMetric(
            "awareness_requests_total",
            "Total number of chat completion requests")
        self.requests_inflight = Metric(
            "awareness_requests_inflight",
            "Currently in-flight requests")

        # 幻觉检测指标
        self.hallucinations_detected = CounterMetric(
            "awareness_hallucinations_detected_total",
            "Total hallucinations detected")
        self.hallucination_score = HistogramMetric(
            "awareness_hallucination_score",
            "Distribution of hallucination scores",
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])

        # 检查器指标
        self.checker_hits = CounterMetric(
            "awareness_checker_hits_total",
            "Total checker activations")
        self.checker_misses = CounterMetric(
            "awareness_checker_misses_total",
            "Total checker non-activations")

        # 延迟
        self.request_latency = HistogramMetric(
            "awareness_request_latency_seconds",
            "Request latency in seconds",
            [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0])

        # PI/SI/HI
        self.pi_value = Metric("awareness_pi", "Prior Intensity")
        self.si_value = Metric("awareness_si", "Sensory Precision")
        self.hi_value = Metric("awareness_hi", "Hallucination Index")

        # 背压
        self.backpressure_drops = CounterMetric(
            "awareness_backpressure_drops_total",
            "Total segments dropped due to backpressure")

        # 反馈
        self.feedback_total = CounterMetric(
            "awareness_feedback_total",
            "Total user feedback submissions")
        self.feedback_agreement = Metric(
            "awareness_feedback_agreement_rate",
            "User agreement rate with detections")

        # 在线学习
        self.model_training_samples = Metric(
            "awareness_model_training_samples",
            "Number of training samples for consensus model")

    def render_all(self) -> str:
        """渲染所有指标为 Prometheus text 格式"""
        metrics = [
            self.requests_total,
            self.requests_inflight,
            self.hallucinations_detected,
            self.hallucination_score,
            self.checker_hits,
            self.checker_misses,
            self.request_latency,
            self.pi_value,
            self.si_value,
            self.hi_value,
            self.backpressure_drops,
            self.feedback_total,
            self.feedback_agreement,
            self.model_training_samples,
        ]
        parts = [m.render() for m in metrics]
        uptime = time.time() - self._start_time
        parts.append(f"# HELP awareness_uptime_seconds Gateway uptime")
        parts.append(f"# TYPE awareness_uptime_seconds gauge")
        parts.append(f"awareness_uptime_seconds {uptime:.0f}")
        return "\n".join(parts) + "\n"


# ── 全局单例 ────────────────────────────────────

_registry: Optional[AwarenessMetricsRegistry] = None

def get_registry() -> AwarenessMetricsRegistry:
    global _registry
    if _registry is None:
        _registry = AwarenessMetricsRegistry()
    return _registry


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    reg = get_registry()

    # 模拟一些活动
    reg.requests_total.inc(100)
    reg.hallucinations_detected.inc(23)
    reg.hallucination_score.observe(0.15)
    reg.hallucination_score.observe(0.75)
    reg.request_latency.observe(0.5)
    reg.pi_value.set(0.72)
    reg.si_value.set(0.68)

    print(reg.render_all()[:500])
    print("...")
    print("✅ Prometheus metrics 可被 Grafana 抓取")
