#!/usr/bin/env python3
"""
LLM 可观测性平台 — 监控 + 告警 + 报表
纯 Python 标准库，零外部依赖

功能:
  - 实时指标采集 (请求量/拦截率/幻觉率/延迟)
  - 时序数据滚动存储 (最近 7 天)
  - 智能告警 (多级阈值 + Webhook 通知)
  - 日报/周报自动生成
"""

import json, time, threading, re
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent


# ============ 指标采集器 ============

@dataclass
class AuditMetric:
    """单次安全审计指标"""
    timestamp: float
    status: str          # safe / warning / blocked
    latency_ms: float
    text_length: int
    leak_count: int
    content_count: int
    bias_count: int
    hallucination_ratio: float


class MetricsCollector:
    """时序指标采集与存储"""

    def __init__(self, max_history: int = 10000):
        self.metrics: deque = deque(maxlen=max_history)
        self._lock = threading.Lock()
        self._start_time = time.time()

    def record(self, metric: AuditMetric):
        with self._lock:
            self.metrics.append(metric)

    def snapshot(self, window_seconds: int = 3600) -> dict:
        """获取最近 N 秒的指标快照"""
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            recent = [m for m in self.metrics if m.timestamp >= cutoff]

        if not recent:
            return self._empty_snapshot()

        total = len(recent)
        blocked = sum(1 for m in recent if m.status == "blocked")
        warning = sum(1 for m in recent if m.status == "warning")
        safe = sum(1 for m in recent if m.status == "safe")
        latencies = sorted(m.latency_ms for m in recent)
        h_ratios = [m.hallucination_ratio for m in recent if m.hallucination_ratio > 0]

        return {
            "window_seconds": window_seconds,
            "total_requests": total,
            "requests_per_minute": round(total / max(window_seconds / 60, 1), 1),
            "blocked": blocked,
            "blocked_rate": round(blocked / total, 3),
            "warning": warning,
            "safe": safe,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
            "p50_latency_ms": latencies[len(latencies)//2],
            "p95_latency_ms": latencies[int(len(latencies)*0.95)] if len(latencies) > 10 else latencies[-1],
            "p99_latency_ms": latencies[int(len(latencies)*0.99)] if len(latencies) > 50 else latencies[-1],
            "avg_hallucination_ratio": round(sum(h_ratios)/len(h_ratios), 2) if h_ratios else 0,
            "uptime_seconds": round(now - self._start_time),
            "leak_detections": sum(m.leak_count for m in recent),
            "content_blocks": sum(m.content_count for m in recent),
            "bias_warnings": sum(m.bias_count for m in recent),
        }

    def _empty_snapshot(self):
        return {
            "window_seconds": 0, "total_requests": 0,
            "requests_per_minute": 0, "blocked": 0, "blocked_rate": 0,
            "warning": 0, "safe": 0, "avg_latency_ms": 0,
            "p50_latency_ms": 0, "p95_latency_ms": 0, "p99_latency_ms": 0,
            "avg_hallucination_ratio": 0, "uptime_seconds": 0,
            "leak_detections": 0, "content_blocks": 0, "bias_warnings": 0,
        }

    def hourly_trend(self, hours: int = 24) -> list:
        """按小时聚合趋势数据"""
        now = time.time()
        buckets = {}
        with self._lock:
            for m in self.metrics:
                hour = int((m.timestamp // 3600) * 3600)
                if now - hour > hours * 3600:
                    continue
                if hour not in buckets:
                    buckets[hour] = {"total": 0, "blocked": 0, "warning": 0}
                buckets[hour]["total"] += 1
                if m.status == "blocked":
                    buckets[hour]["blocked"] += 1
                elif m.status == "warning":
                    buckets[hour]["warning"] += 1

        trend = []
        for hour in sorted(buckets.keys()):
            b = buckets[hour]
            trend.append({
                "hour": time.strftime("%m-%d %H:00", time.gmtime(hour)),
                "total": b["total"],
                "blocked": b["blocked"],
                "warning": b["warning"],
                "blocked_rate": round(b["blocked"] / max(b["total"], 1), 2),
            })
        return trend


# ============ 告警引擎 ============

@dataclass
class AlertRule:
    """告警规则"""
    name: str
    metric: str           # blocked_rate / hallucination_ratio / latency_p95
    condition: str        # gt / lt
    threshold: float
    severity: str         # critical / warning / info
    cooldown_seconds: int = 300  # 冷却时间，避免重复告警
    message_template: str = ""


class AlertEngine:
    """智能告警引擎"""

    DEFAULT_RULES = [
        AlertRule("拦截率飙升", "blocked_rate", "gt", 0.3, "critical", 300,
                  "🚨 拦截率超过 30%，当前 {value:.0%}，请检查是否有攻击或异常流量"),
        AlertRule("拦截率偏高", "blocked_rate", "gt", 0.1, "warning", 600,
                  "⚠️ 拦截率超过 10%，当前 {value:.0%}"),
        AlertRule("幻觉率飙升", "avg_hallucination_ratio", "gt", 0.5, "critical", 300,
                  "🚨 幻觉率超过 50%，当前 {value:.0%}，模型可能严重退化"),
        AlertRule("幻觉率偏高", "avg_hallucination_ratio", "gt", 0.3, "warning", 600,
                  "⚠️ 幻觉率超过 30%，当前 {value:.0%}，建议人工复核"),
        AlertRule("延迟异常", "p95_latency_ms", "gt", 5000, "warning", 300,
                  "⚠️ P95 延迟超过 5 秒，当前 {value:.0f}ms"),
        AlertRule("无流量", "total_requests", "lt", 1, "info", 3600,
                  "ℹ️ 过去 1 小时无请求流量"),
    ]

    def __init__(self, rules: list[AlertRule] = None):
        self.rules = rules or self.DEFAULT_RULES
        self._last_alerted: dict = {}  # rule_name → timestamp
        self._webhook_url: Optional[str] = None
        self._alert_history: deque = deque(maxlen=100)

    def set_webhook(self, url: str):
        self._webhook_url = url

    def evaluate(self, snapshot: dict) -> list[dict]:
        """评估指标并返回触发的告警"""
        alerts = []
        now = time.time()

        for rule in self.rules:
            value = snapshot.get(rule.metric, 0)
            triggered = False

            if rule.condition == "gt" and value > rule.threshold:
                triggered = True
            elif rule.condition == "lt" and value < rule.threshold:
                triggered = True

            if not triggered:
                continue

            # 冷却检查
            last = self._last_alerted.get(rule.name, 0)
            if now - last < rule.cooldown_seconds:
                continue

            self._last_alerted[rule.name] = now
            message = rule.message_template.format(value=value)
            alert = {
                "name": rule.name, "severity": rule.severity,
                "metric": rule.metric, "value": value,
                "threshold": rule.threshold, "message": message,
                "timestamp": now,
            }
            alerts.append(alert)
            self._alert_history.append(alert)

            # Webhook 通知
            if self._webhook_url:
                self._send_webhook(alert)

        return alerts

    def _send_webhook(self, alert: dict):
        """发送 Webhook 通知"""
        try:
            import urllib.request
            data = json.dumps(alert).encode()
            req = urllib.request.Request(
                self._webhook_url, data=data,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    @property
    def history(self) -> list:
        return list(self._alert_history)


# ============ 报表生成器 ============

class ReportGenerator:
    """日报/周报自动生成"""

    def __init__(self, collector: MetricsCollector, alert_engine: AlertEngine):
        self.collector = collector
        self.alerts = alert_engine

    def daily_report(self) -> str:
        """生成日报 (纯文本)"""
        snap = self.collector.snapshot(86400)
        trend = self.collector.hourly_trend(24)
        alert_history = self.alerts.history

        lines = []
        lines.append("=" * 60)
        lines.append(f"  📊 AI 安全网关 — 日报")
        lines.append(f"  生成时间: {time.strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 60)
        lines.append("")
        lines.append("【核心指标】")
        lines.append(f"  总请求: {snap['total_requests']}")
        lines.append(f"  拦截率: {snap['blocked_rate']:.1%}")
        lines.append(f"  幻觉率: {snap['avg_hallucination_ratio']:.1%}")
        lines.append(f"  平均延迟: {snap['avg_latency_ms']:.0f}ms")
        lines.append(f"  P95 延迟: {snap['p95_latency_ms']:.0f}ms")
        lines.append("")
        lines.append("【安全分类】")
        lines.append(f"  🚫 拦截: {snap['blocked']}")
        lines.append(f"  ⚠️ 警告: {snap['warning']}")
        lines.append(f"  ✅ 安全: {snap['safe']}")
        lines.append(f"  🔐 泄露检测: {snap['leak_detections']} 次")
        lines.append(f"  ⚖️ 偏见检出: {snap['bias_warnings']} 次")
        lines.append("")
        lines.append("【24 小时趋势】")
        for t in trend:
            bar = "█" * min(int(t["blocked_rate"] * 50), 50)
            lines.append(f"  {t['hour']} |{bar} {t['blocked']}/{t['total']}")
        lines.append("")
        lines.append("【今日告警】")
        if alert_history:
            for a in alert_history[-10:]:
                ts = time.strftime("%H:%M", time.gmtime(a["timestamp"]))
                lines.append(f"  [{ts}] {a['severity']}: {a['name']}")
        else:
            lines.append("  (无告警)")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def weekly_report(self) -> str:
        """生成周报"""
        snap = self.collector.snapshot(604800)
        trend = self.collector.hourly_trend(168)

        lines = []
        lines.append("=" * 60)
        lines.append(f"  📊 AI 安全网关 — 周报")
        lines.append(f"  周期: {time.strftime('%Y-%m-%d')}")
        lines.append("=" * 60)
        lines.append(f"  本周请求: {snap['total_requests']}")
        lines.append(f"  拦截率: {snap['blocked_rate']:.1%}")
        lines.append(f"  幻觉率: {snap['avg_hallucination_ratio']:.1%}")
        lines.append(f"  泄露检测: {snap['leak_detections']} 次")
        lines.append(f"  偏见检出: {snap['bias_warnings']} 次")
        lines.append(f"  运行时长: {snap['uptime_seconds']//3600} 小时")
        lines.append("")

        if trend:
            daily = {}
            for t in trend:
                day = t["hour"][:5]
                daily[day] = daily.get(day, 0) + t["total"]
            lines.append("  每日请求量:")
            for day, count in sorted(daily.items()):
                bar = "█" * min(count // 10, 40)
                lines.append(f"    {day} |{bar} {count}")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_json(self) -> dict:
        """导出完整 JSON 报表"""
        return {
            "daily": self.daily_report(),
            "weekly": self.weekly_report(),
            "snapshot": self.collector.snapshot(86400),
            "trend": self.collector.hourly_trend(24),
            "alerts": self.alerts.history,
            "generated_at": time.time(),
        }


# ============ 可观测性 HTTP 端点 (集成到 security_gateway) ============

class ObservabilityAPI:
    """可观测性 REST API — 嵌入到 security_gateway"""

    def __init__(self, collector: MetricsCollector = None,
                 alert_engine: AlertEngine = None,
                 report_gen: ReportGenerator = None):
        self.collector = collector or MetricsCollector()
        self.alerts = alert_engine or AlertEngine()
        self.reporter = report_gen or ReportGenerator(self.collector, self.alerts)

    def handle_get(self, path: str) -> tuple[int, dict]:
        """处理 GET 请求，返回 (status_code, data)"""
        if path == "/obs/snapshot":
            snap = self.collector.snapshot(3600)
            alerts = self.alerts.evaluate(snap)
            snap["alerts"] = alerts
            return 200, snap
        elif path == "/obs/trend":
            return 200, {"trend": self.collector.hourly_trend(24)}
        elif path == "/obs/report/daily":
            return 200, {"report": self.reporter.daily_report()}
        elif path == "/obs/report/weekly":
            return 200, {"report": self.reporter.weekly_report()}
        elif path == "/obs/report/json":
            return 200, self.reporter.to_json()
        elif path == "/obs/alerts":
            return 200, {"alerts": self.alerts.history}
        elif path == "/obs/webhook":
            body = self._read_body()
            if body:
                self.alerts.set_webhook(body.get("url", ""))
            return 200, {"webhook_url": self.alerts._webhook_url}
        return 404, {"error": "unknown observability endpoint"}


# ============ 自测 ============

def main():
    collector = MetricsCollector()
    alerts = AlertEngine()
    reporter = ReportGenerator(collector, alerts)

    # 模拟数据
    import random
    for i in range(100):
        status = random.choices(["safe", "warning", "blocked"], weights=[7, 2, 1])[0]
        collector.record(AuditMetric(
            timestamp=time.time() - random.randint(0, 86400),
            status=status,
            latency_ms=random.randint(50, 800),
            text_length=random.randint(20, 500),
            leak_count=1 if status == "blocked" else 0,
            content_count=1 if status == "blocked" else 0,
            bias_count=1 if status == "warning" else 0,
            hallucination_ratio=random.random() if status == "warning" else 0,
        ))

    snap = collector.snapshot(86400)
    print("📊 快照:", json.dumps({k: v for k, v in snap.items()
                          if k in ("total_requests", "blocked_rate", "avg_latency_ms")}, indent=2))

    triggered = alerts.evaluate(snap)
    if triggered:
        for a in triggered:
            print(f"🚨 {a['severity']}: {a['name']}")

    print("\n" + reporter.daily_report()[:500])


if __name__ == "__main__":
    main()
