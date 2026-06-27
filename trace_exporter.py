#!/usr/bin/env python3
"""
Trace 导出器 — Langfuse / OpenTelemetry 兼容格式

将觉察通道的标记结果导出为标准 Trace 格式，
无缝融入企业 LLMOps 监控流水线 (Langfuse / Phoenix / Arize)

导出格式:
  - Langfuse JSON (可 curl 直接上报)
  - OpenTelemetry Span (JSON 序列化)
  - 本地 JSONL 日志
"""

import json
import time
import uuid
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict


# ── 数据模型 ──────────────────────────────────────

@dataclass
class TraceSpan:
    """单个 Trace Span"""
    trace_id: str
    span_id: str
    name: str
    start_time: float
    end_time: float = 0.0
    attributes: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    status: str = "ok"

    def add_event(self, name: str, attributes: dict = None):
        self.events.append({
            "name": name,
            "time": time.time(),
            "attributes": attributes or {},
        })

    def finish(self):
        self.end_time = time.time()


class TraceExporter:
    """
    Trace 导出器 — 多格式输出

    用法:
      exporter = TraceExporter()
      exporter.start_trace("chat_completion", session_id="abc")
      exporter.add_observation("hallucination_detected", {...})
      exporter.finish_trace()
      exporter.export_langfuse("http://langfuse:3000/api/public/ingestion")
    """

    def __init__(self, service_name: str = "awareness-gateway"):
        self.service_name = service_name
        self._current_trace: Optional[TraceSpan] = None
        self._traces: list[TraceSpan] = []
        self._log_path = Path(__file__).parent / "traces.jsonl"

    def start_trace(self, name: str, **attrs):
        """开始一个 Trace"""
        trace_id = uuid.uuid4().hex[:16]
        span_id = uuid.uuid4().hex[:8]
        self._current_trace = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            name=name,
            start_time=time.time(),
            attributes={"service": self.service_name, **attrs},
        )

    def add_observation(self, event_name: str, attributes: dict):
        """添加觉察观察事件"""
        if self._current_trace:
            self._current_trace.add_event(event_name, attributes)

    def add_hallucination_check(self, claim: str, verdict: str,
                                confidence: float, evidence: str,
                                checker: str = ""):
        """便捷方法：添加幻觉检测事件"""
        self.add_observation("fact_check", {
            "claim": claim[:200],
            "verdict": verdict,
            "confidence": round(confidence, 3),
            "evidence": evidence[:200],
            "checker": checker,
        })

    def finish_trace(self, status: str = "ok"):
        """结束当前 Trace 并归档"""
        if self._current_trace:
            self._current_trace.finish()
            self._current_trace.status = status
            self._traces.append(self._current_trace)
            self._current_trace = None

    def export_langfuse(self, endpoint: str = "",
                        public_key: str = "", secret_key: str = "") -> str:
        """
        导出为 Langfuse 兼容 JSON 格式

        可 curl 直接上报:
          curl -X POST {endpoint} -H "Authorization: ..." -d @payload.json
        """
        observations = []
        for trace in self._traces:
            for event in trace.events:
                observations.append({
                    "id": uuid.uuid4().hex[:16],
                    "traceId": trace.trace_id,
                    "name": event["name"],
                    "startTime": event["time"],
                    "metadata": event.get("attributes", {}),
                    "level": "WARNING" if "contradicted" in str(event) else "DEFAULT",
                })

        payload = {
            "batch": observations,
            "metadata": {
                "source": self.service_name,
                "sdk": "awareness-gateway-python",
                "version": "2.2",
            },
        }

        # 如果提供了 endpoint，尝试上报
        if endpoint:
            try:
                from urllib.request import Request, urlopen
                data = json.dumps(payload, ensure_ascii=False).encode()
                headers = {"Content-Type": "application/json"}
                if public_key and secret_key:
                    import base64
                    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
                    headers["Authorization"] = f"Basic {auth}"
                req = Request(endpoint, data=data, headers=headers, method="POST")
                with urlopen(req, timeout=10) as resp:
                    return f"上报成功: {resp.status}"
            except Exception as e:
                return f"上报失败: {e}"

        return json.dumps(payload, ensure_ascii=False, indent=2)

    def export_opentelemetry(self) -> str:
        """导出为 OpenTelemetry Span JSON"""
        spans = []
        for trace in self._traces:
            span = {
                "traceId": trace.trace_id,
                "spanId": trace.span_id,
                "name": trace.name,
                "kind": "INTERNAL",
                "startTimeUnixNano": str(int(trace.start_time * 1e9)),
                "endTimeUnixNano": str(int(trace.end_time * 1e9)),
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in trace.attributes.items()
                ],
                "events": [
                    {
                        "name": e["name"],
                        "timeUnixNano": str(int(e["time"] * 1e9)),
                        "attributes": [
                            {"key": k, "value": {"stringValue": str(v)}}
                            for k, v in e.get("attributes", {}).items()
                        ],
                    }
                    for e in trace.events
                ],
                "status": {"code": 1 if trace.status == "ok" else 2},
            }
            spans.append(span)
        return json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]},
                          ensure_ascii=False, indent=2)

    def export_jsonl(self, path: str = None) -> str:
        """导出为本地 JSONL 日志"""
        path = path or str(self._log_path)
        with open(path, "a") as f:
            for trace in self._traces:
                entry = {
                    "trace_id": trace.trace_id,
                    "name": trace.name,
                    "start": trace.start_time,
                    "duration_ms": round((trace.end_time - trace.start_time) * 1000, 1),
                    "events": trace.events,
                    "attributes": trace.attributes,
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path

    @property
    def trace_count(self) -> int:
        return len(self._traces)

    def clear(self):
        self._traces.clear()


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=== Trace 导出器 演示 ===\n")

    exporter = TraceExporter()

    # 模拟一次对话
    exporter.start_trace(
        "chat_completion",
        session_id="demo-001",
        model="llama3.2:1b",
        user_question="火锅是谁发明的？"
    )

    # 模拟觉察发现
    exporter.add_hallucination_check(
        claim="朱元璋发明了火锅",
        verdict="contradicted",
        confidence=0.88,
        evidence="火锅远早于明代就已存在",
        checker="_check_graph_contradiction",
    )
    exporter.add_observation("alignment_check", {
        "type": "pleasing",
        "severity": 0.2,
    })

    exporter.finish_trace(status="flagged")

    # 导出演示
    langfuse_json = exporter.export_langfuse()
    print("Langfuse 格式 (前200字符):")
    print(langfuse_json[:200])
    print()

    otel_json = exporter.export_opentelemetry()
    print("OpenTelemetry 格式 (前200字符):")
    print(otel_json[:200])
    print()

    jsonl_path = exporter.export_jsonl()
    print(f"JSONL 日志: {jsonl_path}")
    print(f"Trace 数量: {exporter.trace_count}")
