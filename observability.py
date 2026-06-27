#!/usr/bin/env python3
"""
可观测性模块 — 请求级指标、历史聚合、FP/FN追踪

用法:
  from observability import Observability
  obs = Observability()
  obs.record_request(verdict, latency_ms, vote_details, kb_used)
  obs.snapshot()          # 实时快照
  obs.hourly_report()     # 小时级聚合
"""

import json, time, os
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class Observability:
    """企业级可观测性收集器"""

    def __init__(self, log_path: str = None):
        self.start_time = time.time()
        self.log_path = Path(log_path or str(Path(__file__).parent / 'metrics' / 'metrics_log.jsonl'))

        # 实时计数器
        self.total_requests = 0
        self.total_latency_ms = 0.0
        self.kb_hits = 0
        self.errors = 0
        self.verdict_counts = {"contradicted": 0, "verified": 0, "uncertain": 0, "unverifiable": 0}
        self.checker_hits = defaultdict(int)

        # 滑动窗口（最近1000条）
        self.recent_requests = deque(maxlen=1000)

        # 小时级聚合
        self.hourly_buckets = defaultdict(lambda: {
            "count": 0, "latency_ms": 0.0, "kb_hits": 0,
            "verdicts": defaultdict(int)
        })

        # FP/FN 追踪（从 /benchmark 端点填充）
        self.fp_count = 0  # 误报：系统判矛盾但实际正确
        self.fn_count = 0  # 漏报：系统判正确但实际矛盾
        self.benchmark_total = 0
        self.last_benchmark_time = None

        self.last_request_time = None

        # 创建日志目录
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record_request(self, verdict: str, latency_ms: float,
                       vote_details: dict, kb_used: bool, text: str = ""):
        """记录单次请求"""
        self.total_requests += 1
        self.total_latency_ms += latency_ms
        self.verdict_counts[verdict] = self.verdict_counts.get(verdict, 0) + 1
        if kb_used:
            self.kb_hits += 1
        for vote in vote_details.get("votes", []):
            self.checker_hits[vote["checker"]] += 1
        self.last_request_time = datetime.now().isoformat()

        # 滑动窗口
        record = {
            "ts": datetime.now().isoformat(),
            "verdict": verdict,
            "latency_ms": round(latency_ms, 1),
            "kb_used": kb_used,
            "text_preview": text[:80] if text else "",
        }
        self.recent_requests.append(record)

        # 小时级聚合
        hour_key = datetime.now().strftime("%Y-%m-%dT%H")
        bucket = self.hourly_buckets[hour_key]
        bucket["count"] += 1
        bucket["latency_ms"] += latency_ms
        if kb_used:
            bucket["kb_hits"] += 1
        bucket["verdicts"][verdict] += 1

        # 持久化（每10条写一次减少IO）
        if self.total_requests % 10 == 0:
            self._flush()

    def record_error(self):
        self.errors += 1

    def record_benchmark(self, verified_miss: int, total_miss: int, total: int):
        """记录基准测试结果"""
        self.fp_count = verified_miss  # verified误判数（最危险的漏报）
        self.fn_count = total_miss     # 总漏报数
        self.benchmark_total = total
        self.last_benchmark_time = datetime.now().isoformat()

    # ── 快照 ──

    def snapshot(self) -> dict:
        """实时指标快照"""
        uptime = time.time() - self.start_time
        total = max(self.total_requests, 1)
        recent = list(self.recent_requests)[-50:]  # 最近50条

        # 最近延迟P50/P95/P99
        latencies = sorted(r["latency_ms"] for r in recent)
        p50 = latencies[len(latencies)//2] if latencies else 0
        p95 = latencies[int(len(latencies)*0.95)] if len(latencies) >= 20 else (latencies[-1] if latencies else 0)
        p99 = latencies[int(len(latencies)*0.99)] if len(latencies) >= 100 else (latencies[-1] if latencies else 0)

        return {
            "uptime_seconds": round(uptime, 1),
            "total_requests": self.total_requests,
            "avg_latency_ms": round(self.total_latency_ms / total, 1),
            "latency_p50_ms": p50,
            "latency_p95_ms": p95,
            "latency_p99_ms": p99,
            "kb_hit_rate": round(self.kb_hits / total, 3),
            "verdict_distribution": dict(self.verdict_counts),
            "checker_usage": dict(sorted(
                self.checker_hits.items(), key=lambda x: -x[1])[:10]),
            "errors": self.errors,
            "last_request": self.last_request_time,
        }

    def dashboard(self) -> dict:
        """Dashboard 汇总"""
        snap = self.snapshot()
        hourly = self._hourly_summary()

        # 漏报率 (对抗基准)
        fn_rate = round(self.fn_count / max(self.benchmark_total, 1), 3)
        verified_rate = round(self.fp_count / max(self.benchmark_total, 1), 3)

        # 最近趋势（最近60秒 vs 前一分钟）
        now = time.time()
        recent_60s = [r for r in self.recent_requests
                      if now - time.mktime(datetime.fromisoformat(r["ts"]).timetuple()) < 60]
        rps = len(recent_60s) / 60.0 if recent_60s else 0

        return {
            "service": {
                "version": "2.0",
                "detection_rate": "88% (adversarial)",
                "checkers": self.total_requests > 0,  # 是否有流量
            },
            "realtime": snap,
            "hourly": hourly,
            "quality": {
                "adversarial_total": self.benchmark_total,
                "detection_rate": round(1 - fn_rate, 3),
                "missed_total": self.fn_count,
                "verified_miss": self.fp_count,
                "fn_rate": fn_rate,
                "verified_miss_rate": verified_rate,
                "last_benchmark": self.last_benchmark_time,
            },
            "throughput": {
                "rps_1m": round(rps, 2),
            },
            "recent_requests": [
                {"ts": r["ts"][-8:], "verdict": r["verdict"],
                 "ms": r["latency_ms"], "text": r["text_preview"][:40]}
                for r in list(self.recent_requests)[-10:]
            ],
        }

    def _hourly_summary(self) -> list:
        """小时级聚合摘要"""
        hours = []
        for hk in sorted(self.hourly_buckets.keys())[-24:]:  # 最近24小时
            b = self.hourly_buckets[hk]
            cnt = max(b["count"], 1)
            hours.append({
                "hour": hk,
                "requests": b["count"],
                "avg_latency_ms": round(b["latency_ms"] / cnt, 1),
                "kb_hit_rate": round(b["kb_hits"] / cnt, 3),
                "verdicts": dict(b["verdicts"]),
            })
        return hours

    def _flush(self):
        """持久化指标到文件"""
        try:
            snap = self.snapshot()
            snap["_type"] = "metrics_snapshot"
            snap["_ts"] = datetime.now().isoformat()
            with open(self.log_path, 'a') as f:
                f.write(json.dumps(snap, ensure_ascii=False) + '\n')
        except OSError:
            pass  # 磁盘满时静默

    # ── 历史查询 ──

    def history(self, hours: int = 1) -> list:
        """查询最近N小时的指标历史"""
        cutoff = datetime.now() - timedelta(hours=hours)
        records = []
        if self.log_path.exists():
            try:
                with open(self.log_path) as f:
                    for line in f:
                        try:
                            r = json.loads(line)
                            ts = datetime.fromisoformat(r.get("_ts", ""))
                            if ts >= cutoff:
                                records.append(r)
                        except (json.JSONDecodeError, ValueError):
                            continue
            except OSError:
                pass
        return records


# 全局单例
_instance: Optional[Observability] = None


def get_observability() -> Observability:
    global _instance
    if _instance is None:
        _instance = Observability()
    return _instance
