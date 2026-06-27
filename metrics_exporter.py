#!/usr/bin/env python3
"""企业级 Prometheus 指标导出器 — Grafana 仪表盘就绪。

在现有 prometheus_exporter.py 基础上增加业务级指标聚合层。

用法:
    from metrics_exporter import MetricsRegistry

    metrics = MetricsRegistry()

    # 记录请求
    metrics.request_total.inc()
    metrics.request_latency.observe(0.234)
    metrics.tokens_consumed.inc(3150)

    # 获取 /metrics 端点输出
    print(metrics.render_all())

Grafana 仪表盘变量:
  - $rate(awareness_requests_total[5m])       → 请求速率
  - $histogram_quantile(0.99, awareness_request_latency) → P99 延迟
  - $rate(awareness_tokens_total[1h])          → Token 消耗趋势
  - $awareness_circuit_breaker_state            → 熔断器状态
"""

import json
import threading
import time
from collections import deque
from typing import Optional


# ═══════════════════════════════════════════════════════════
# 轻量指标基类（不依赖 prometheus_exporter）
# ═══════════════════════════════════════════════════════════

class _Metric:
    def __init__(self, name: str, help_text: str, mtype: str):
        self.name = name
        self.help = help_text
        self.type = mtype
        self._value = 0.0
        self._labels = {}
        self._lock = threading.Lock()

    def set(self, v): 
        with self._lock: self._value = v
    def inc(self, d=1): 
        with self._lock: self._value += d
    def val(self): 
        with self._lock: return self._value

    def render(self) -> str:
        with self._lock:
            header = f"# HELP {self.name} {self.help}\n# TYPE {self.name} {self.type}"
            if self._labels:
                lbl = ",".join(f'{k}="{v}"' for k, v in self._labels.items())
                return f"{header}\n{self.name}{{{lbl}}} {self._value}"
            return f"{header}\n{self.name} {self._value}"


class _Counter(_Metric):
    def __init__(self, name, help_text):
        super().__init__(name, help_text, "counter")


class _Gauge(_Metric):
    def __init__(self, name, help_text):
        super().__init__(name, help_text, "gauge")
    def dec(self, d=1): 
        with self._lock: self._value -= d


class _Histogram(_Metric):
    def __init__(self, name, help_text, buckets=None):
        super().__init__(name, help_text, "histogram")
        self._buckets = sorted(buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0])
        self._bucket_vals = [0] * (len(self._buckets) + 1)
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def observe(self, value: float):
        with self._lock:
            self._sum += value
            self._count += 1
            for i, b in enumerate(self._buckets):
                if value <= b:
                    self._bucket_vals[i] += 1
                    return
            self._bucket_vals[-1] += 1

    def render(self) -> str:
        with self._lock:
            lines = [f"# HELP {self.name} {self.help}",
                     f"# TYPE {self.name} histogram"]
            for i, b in enumerate(self._buckets):
                lines.append(f'{self.name}_bucket{{le="{b}"}} {self._bucket_vals[i]}')
            lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._bucket_vals[-1]}')
            lines.append(f"{self.name}_sum {self._sum}")
            lines.append(f"{self.name}_count {self._count}")
            return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 业务指标注册表
# ═══════════════════════════════════════════════════════════

class MetricsRegistry:
    """企业级指标 — 覆盖 RED 方法论 (Rate/Error/Duration) + 业务维度"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_metrics()
        return cls._instance

    def _init_metrics(self):
        # ── RED: Rate ──
        self.request_total = _Counter(
            "awareness_requests_total",
            "API 请求总数"
        )
        self.request_by_endpoint = {}  # endpoint → Counter
        self.request_by_status = {}    # status_class → Counter

        # ── RED: Error ──
        self.http_429_total = _Counter(
            "awareness_http_429_total",
            "HTTP 429 (速率限制) 总数"
        )
        self.http_500_total = _Counter(
            "awareness_http_500_total",
            "HTTP 500 (服务器错误) 总数"
        )

        # ── RED: Duration ──
        self.request_latency = _Histogram(
            "awareness_request_latency_seconds",
            "请求延迟分布 (秒)",
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]
        )
        self.llm_latency = _Histogram(
            "awareness_llm_latency_seconds",
            "上游 LLM 延迟分布 (秒)"
        )

        # ── Token 消耗 ──
        self.tokens_in_total = _Counter(
            "awareness_tokens_in_total",
            "输入 Token 总数"
        )
        self.tokens_out_total = _Counter(
            "awareness_tokens_out_total",
            "输出 Token 总数"
        )

        # ── 安全 ──
        self.waf_blocks_total = _Counter(
            "awareness_waf_blocks_total",
            "WAF 拦截总数"
        )
        self.waf_blocks_by_type = {}  # threat_type → Counter

        # ── 熔断器 ──
        self.circuit_breaker_state = _Gauge(
            "awareness_circuit_breaker_state",
            "熔断器状态 (0=closed, 1=half_open, 2=open)"
        )
        self.circuit_breaker_trips = _Counter(
            "awareness_circuit_breaker_trips_total",
            "熔断器跳闸次数"
        )

        # ── 缓存 ──
        self.cache_hits = _Counter(
            "awareness_cache_hits_total",
            "缓存命中次数"
        )
        self.cache_misses = _Counter(
            "awareness_cache_misses_total",
            "缓存未命中次数"
        )

        # ── 连接池 ──
        self.db_pool_in_use = _Gauge(
            "awareness_db_pool_in_use",
            "数据库连接池使用数"
        )
        self.db_pool_timeouts = _Counter(
            "awareness_db_pool_timeouts_total",
            "数据库连接池超时次数"
        )

        # ── 幻觉检测 ──
        self.hallucination_detected = _Counter(
            "awareness_hallucination_detected_total",
            "检测到的幻觉断言数"
        )
        self.hallucination_verified = _Counter(
            "awareness_hallucination_verified_total",
            "验证通过的断言数"
        )

        # ── 并发 ──
        self.active_requests = _Gauge(
            "awareness_active_requests",
            "当前活跃请求数"
        )

    # ── 便捷方法 ────────────────────────────────

    def record_request(self, endpoint: str = "", status: int = 200,
                       latency: float = 0, tokens_in: int = 0, tokens_out: int = 0):
        """一次 API 调用的完整指标记录"""
        self.request_total.inc()
        self.request_latency.observe(latency)

        if endpoint:
            ep_key = f"endpoint:{endpoint}"
            if ep_key not in self.request_by_endpoint:
                self.request_by_endpoint[ep_key] = _Counter(
                    f"awareness_requests_total{{endpoint=\"{endpoint}\"}}",
                    f"请求数: {endpoint}"
                )
            self.request_by_endpoint[ep_key].inc()

        status_class = f"{status // 100}xx"
        if status_class not in self.request_by_status:
            self.request_by_status[status_class] = _Counter(
                f"awareness_requests_total{{status_class=\"{status_class}\"}}",
                f"请求数: {status_class}"
            )
        self.request_by_status[status_class].inc()

        if status == 429:
            self.http_429_total.inc()
        elif status >= 500:
            self.http_500_total.inc()

        self.tokens_in_total.inc(tokens_in)
        self.tokens_out_total.inc(tokens_out)

    def record_waf_block(self, threat_type: str = ""):
        """WAF 拦截记录"""
        self.waf_blocks_total.inc()
        if threat_type:
            if threat_type not in self.waf_blocks_by_type:
                self.waf_blocks_by_type[threat_type] = _Counter(
                    f"awareness_waf_blocks_total{{threat_type=\"{threat_type}\"}}",
                    f"WAF拦截: {threat_type}"
                )
            self.waf_blocks_by_type[threat_type].inc()

    def record_circuit_change(self, state: str):
        """熔断器状态变更 (closed/half_open/open)"""
        state_map = {"closed": 0, "half_open": 1, "open": 2}
        self.circuit_breaker_state.set(state_map.get(state, -1))
        if state == "open":
            self.circuit_breaker_trips.inc()

    def record_cache(self, hit: bool):
        """缓存命中/未命中"""
        if hit:
            self.cache_hits.inc()
        else:
            self.cache_misses.inc()

    @property
    def cache_hit_ratio(self) -> float:
        """缓存命中率"""
        hits = self.cache_hits.val()
        total = hits + self.cache_misses.val()
        return hits / max(total, 1)

    def record_hallucination(self, verdict: str):
        """幻觉检测结果"""
        if verdict == "contradicted":
            self.hallucination_detected.inc()
        elif verdict == "verified":
            self.hallucination_verified.inc()

    def render_all(self) -> str:
        """渲染所有指标为 Prometheus text 格式"""
        lines = []
        # 核心指标
        for attr in ['request_total', 'http_429_total', 'http_500_total',
                     'request_latency', 'llm_latency',
                     'tokens_in_total', 'tokens_out_total',
                     'waf_blocks_total', 'circuit_breaker_state',
                     'circuit_breaker_trips', 'cache_hits', 'cache_misses',
                     'db_pool_in_use', 'db_pool_timeouts',
                     'hallucination_detected', 'hallucination_verified',
                     'active_requests']:
            m = getattr(self, attr, None)
            if m:
                lines.append(m.render())

        # 动态计数器
        for d in [self.request_by_endpoint, self.request_by_status,
                  self.waf_blocks_by_type]:
            for m in d.values():
                lines.append(m.render())

        # 计算指标
        hit_ratio = self.cache_hit_ratio
        lines.append(f"# HELP awareness_cache_hit_ratio 缓存命中率")
        lines.append(f"# TYPE awareness_cache_hit_ratio gauge")
        lines.append(f"awareness_cache_hit_ratio {hit_ratio:.4f}")

        return "\n".join(lines) + "\n"

    def render_json(self) -> str:
        """渲染为 JSON 格式（供 API 返回）"""
        return json.dumps({
            "requests_total": self.request_total.val(),
            "http_429": self.http_429_total.val(),
            "http_500": self.http_500_total.val(),
            "active_requests": self.active_requests.val(),
            "cache_hit_ratio": round(self.cache_hit_ratio, 4),
            "waf_blocks": self.waf_blocks_total.val(),
            "circuit_breaker": self.circuit_breaker_state.val(),
            "tokens_in": self.tokens_in_total.val(),
            "tokens_out": self.tokens_out_total.val(),
            "hallucination_detected": self.hallucination_detected.val(),
            "hallucination_verified": self.hallucination_verified.val(),
        }, ensure_ascii=False)


# 模块级单例
metrics = MetricsRegistry()
