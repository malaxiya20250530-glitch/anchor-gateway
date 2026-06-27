#!/usr/bin/env python3
"""分布式追踪 — OpenTelemetry 兼容的 Trace/Span 模型。

兼容导出: Jaeger / Tempo / Zipkin / OTLP (OpenTelemetry Protocol)

用法:
    from distributed_tracing import Tracer

    tracer = Tracer(service_name="awareness-gateway")

    with tracer.span("chat_completion") as span:
        span.set_attribute("model", "deepseek-chat")
        span.set_attribute("tokens", 3150)

        with tracer.span("waf_check"):
            pass  # WAF 检查

        with tracer.span("llm_call"):
            pass  # LLM 调用

    # 导出
    print(tracer.export_otlp_json())

Span 层级示例:
    chat_completion (1000ms)
    ├── waf_check (2ms)
    ├── hallucination_check (45ms)
    ├── llm_call (900ms)
    │   ├── upstream_request (880ms)
    │   └── response_parse (20ms)
    └── audit_log (5ms)
"""

import json
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from typing import Optional

from security_logger import get_security_logger


# ═══════════════════════════════════════════════════════════
# Span
# ═══════════════════════════════════════════════════════════

class Span:
    """追踪 Span — OTel 兼容的数据模型"""

    def __init__(self, name: str, trace_id: str, parent_id: str = "",
                 service_name: str = ""):
        self.name = name
        self.trace_id = trace_id
        self.span_id = uuid.uuid4().hex[:16]
        self.parent_id = parent_id
        self.service_name = service_name
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.attributes: dict[str, str] = {}
        self.events: list[dict] = []
        self.status: str = "OK"
        self._children: list[Span] = []

    def set_attribute(self, key: str, value):
        self.attributes[key] = str(value)

    def add_event(self, name: str, attributes: dict = None):
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def set_error(self, message: str):
        self.status = "ERROR"
        self.add_event("exception", {"message": message})

    def finish(self):
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return (time.time() - self.start_time) * 1000

    def to_dict(self) -> dict:
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_id or "",
            "name": self.name,
            "serviceName": self.service_name,
            "startTime": self.start_time,
            "endTime": self.end_time or time.time(),
            "durationMs": round(self.duration_ms, 3),
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
            "children": [c.to_dict() for c in self._children],
        }


# ═══════════════════════════════════════════════════════════
# Tracer
# ═══════════════════════════════════════════════════════════

class Tracer:
    """分布式追踪器 — 线程安全的 Span 管理"""

    def __init__(self, service_name: str = "awareness-gateway",
                 sample_rate: float = 0.1):
        self.service_name = service_name
        self.sample_rate = sample_rate
        self._local = threading.local()
        self._completed: list[Span] = []
        self._lock = threading.Lock()
        self._slog = get_security_logger()

    @contextmanager
    def span(self, name: str, attributes: dict = None):
        """创建 Span 上下文管理器。

        with tracer.span("llm_call", {"model": "deepseek"}) as span:
            result = call_llm()
            span.set_attribute("tokens", result.tokens)
        """
        span = self._start_span(name)
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        try:
            yield span
            span.status = "OK"
        except Exception as e:
            span.set_error(str(e))
            raise
        finally:
            span.finish()
            self._end_span(span)

    def start(self, name: str) -> Span:
        return self._start_span(name)

    def _start_span(self, name: str) -> Span:
        trace_id = getattr(self._local, 'trace_id', None) or uuid.uuid4().hex[:32]
        parent_id = getattr(self._local, 'current_span_id', None) or ""

        span = Span(name=name, trace_id=trace_id, parent_id=parent_id,
                    service_name=self.service_name)

        # 维护 Span 栈
        stack = getattr(self._local, 'span_stack', [])
        if stack:
            stack[-1]._children.append(span)
        else:
            self._local.trace_id = trace_id

        stack.append(span)
        self._local.span_stack = stack
        self._local.current_span_id = span.span_id

        return span

    def _end_span(self, span: Span):
        stack = getattr(self._local, 'span_stack', [])
        if stack and stack[-1].span_id == span.span_id:
            stack.pop()

        if stack:
            self._local.current_span_id = stack[-1].span_id
        else:
            self._local.current_span_id = None
            # 根 Span 结束 → 完整 trace 完成
            self._store_trace(span)

    def _store_trace(self, root_span: Span):
        """存储完整 trace（采样）"""
        if self.sample_rate < 1.0:
            import random
            if random.random() > self.sample_rate:
                return
        with self._lock:
            self._completed.append(root_span)
            if len(self._completed) > 1000:
                self._completed = self._completed[-500:]

    # ── 导出 ────────────────────────────────────

    def export_otlp_json(self) -> str:
        """导出为 OTLP JSON 格式（Jaeger/Tempo 兼容）"""
        with self._lock:
            traces = [s.to_dict() for s in self._completed]
        return json.dumps({
            "resourceSpans": [{
                "resource": {
                    "attributes": [{"key": "service.name",
                                    "value": {"stringValue": self.service_name}}]
                },
                "scopeSpans": [{
                    "spans": traces,
                }],
            }]
        }, ensure_ascii=False, default=str)

    def export_zipkin_json(self) -> str:
        """导出为 Zipkin JSON 格式"""
        zipkin_spans = []

        def _flatten(span: Span, parent_id: str = ""):
            zs = {
                "traceId": span.trace_id,
                "id": span.span_id,
                "parentId": parent_id or None,
                "name": span.name,
                "timestamp": int(span.start_time * 1_000_000),
                "duration": int(span.duration_ms * 1_000),
                "localEndpoint": {"serviceName": span.service_name},
                "tags": span.attributes,
                "annotations": [{
                    "timestamp": int(e["timestamp"] * 1_000_000),
                    "value": e["name"],
                } for e in span.events],
            }
            zipkin_spans.append(zs)
            for child in span._children:
                _flatten(child, span.span_id)

        with self._lock:
            for span in self._completed:
                _flatten(span)

        return json.dumps(zipkin_spans, ensure_ascii=False, default=str)

    def export_summary(self) -> dict:
        """导出摘要 — 最近的 trace 统计"""
        with self._lock:
            if not self._completed:
                return {"count": 0}
            recent = self._completed[-100:]
            durations = [s.duration_ms for s in recent]
            errors = sum(1 for s in recent if s.status == "ERROR")
            return {
                "count": len(self._completed),
                "recent_100": {
                    "avg_ms": round(sum(durations) / len(durations), 2),
                    "p50_ms": round(sorted(durations)[len(durations)//2], 2),
                    "p99_ms": round(sorted(durations)[int(len(durations)*0.99)], 2),
                    "max_ms": round(max(durations), 2),
                    "error_rate": round(errors / len(recent), 4),
                },
                "services": list(set(s.service_name for s in recent)),
            }

    def clear(self):
        with self._lock:
            self._completed.clear()


# 模块级单例
tracer = Tracer()
