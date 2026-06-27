#!/usr/bin/env python3
"""长跑浸泡测试 — 24h 稳定性验证 + 内存趋势 + 错误率监控。

用法:
    python3 soak_test.py --duration 3600           # 1小时
    python3 soak_test.py --duration 86400 --qps 50  # 24小时
"""

import json
import os
import sys
import time
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from security_logger import get_security_logger


class SoakTest:
    """长时间浸泡测试"""

    def __init__(self, duration_sec: int = 3600, qps: int = 10,
                 check_interval: int = 60):
        self.duration = duration_sec
        self.qps = qps
        self.interval = check_interval
        self._slog = get_security_logger()
        self._running = True
        self._errors = deque(maxlen=10000)
        self._latencies = deque(maxlen=10000)
        self._memory_samples = []
        self._start_time = 0.0

    def run(self) -> dict:
        """执行浸泡测试"""
        print(f"\n{'='*60}")
        print(f"  长跑浸泡测试")
        print(f"  持续: {self.duration}s ({self.duration/3600:.1f}h)")
        print(f"  QPS: {self.qps}  |  采样间隔: {self.interval}s")
        print(f"  开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        self._start_time = time.time()
        deadline = self._start_time + self.duration

        # 后台 worker
        worker = threading.Thread(target=self._worker_loop, args=(deadline,), daemon=True)
        worker.start()

        # 监控循环
        while time.time() < deadline and self._running:
            time.sleep(self.interval)
            self._sample()

        self._running = False
        worker.join(timeout=5)

        return self._generate_report()

    def _worker_loop(self, deadline: float):
        """后台持续压测"""
        from hallucination_detector import HallucinationDetector
        detector = HallucinationDetector()
        texts = [
            "朱元璋发明了火锅", "Python是1989年发布的",
            "爱因斯坦发明了原子弹", "地球是平的",
            "光速是无限快的", "瓦特发明了蒸汽机",
            "爱迪生发明了电灯泡", "大脑只开发了10%",
        ]
        slot = 0
        interval = 1.0 / max(self.qps, 1)

        while time.time() < deadline and self._running:
            text = texts[slot % len(texts)]
            start = time.time()
            try:
                detector.analyze(text)
                self._latencies.append(time.time() - start)
            except Exception as e:
                self._errors.append(str(e)[:100])
            slot += 1
            time.sleep(max(0, interval - (time.time() - start)))

    def _sample(self):
        """采样"""
        elapsed = time.time() - self._start_time
        errors = list(self._errors)[-100:]
        lats = list(self._latencies)[-100:]
        avg_lat = sum(lats) / max(len(lats), 1) * 1000 if lats else 0

        # 内存采样
        try:
            import tracemalloc
            if not tracemalloc.is_tracing():
                tracemalloc.start()
            current, peak = tracemalloc.get_traced_memory()
            self._memory_samples.append({
                "elapsed_sec": round(elapsed, 0),
                "current_kb": round(current / 1024, 1),
            })
        except Exception:
            pass

        print(f"  [{elapsed/3600:5.1f}h] "
              f"请求: {len(self._latencies):6d}  "
              f"延迟: {avg_lat:6.1f}ms  "
              f"错误: {len(errors):4d}  "
              f"内存: {self._memory_samples[-1]['current_kb'] if self._memory_samples else '?':>8.0f}KB")

    def _generate_report(self) -> dict:
        elapsed = time.time() - self._start_time
        total = len(self._latencies)
        errors = list(self._errors)
        lats = list(self._latencies)

        if lats:
            sorted_lats = sorted(lats)
            def p(data, n):
                return data[int(len(data) * n / 100)]

        report = {
            "test_config": {
                "duration_sec": self.duration,
                "target_qps": self.qps,
                "actual_duration": round(elapsed, 0),
            },
            "results": {
                "total_requests": total,
                "total_errors": len(errors),
                "error_rate": round(len(errors) / max(total, 1), 4),
                "actual_qps": round(total / max(elapsed, 0.1), 2),
            },
            "latency_ms": {
                "avg": round(sum(lats) / max(len(lats), 1) * 1000, 2),
                "p95": round(p(sorted_lats, 95) * 1000, 2) if lats else 0,
                "p99": round(p(sorted_lats, 99) * 1000, 2) if lats else 0,
            } if lats else {},
            "memory_trend": self._memory_samples,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 内存趋势分析
        if len(self._memory_samples) >= 3:
            first = self._memory_samples[0]["current_kb"]
            last = self._memory_samples[-1]["current_kb"]
            growth_pct = round((last - first) / max(first, 1) * 100, 1)
            report["memory_analysis"] = {
                "start_kb": first,
                "end_kb": last,
                "growth_pct": growth_pct,
                "stable": abs(growth_pct) < 20,
            }

        print(f"\n{'='*60}")
        print(f"  浸泡测试报告")
        print(f"{'='*60}")
        print(f"  总请求: {total}  |  错误: {len(errors)}  |  "
              f"错误率: {report['results']['error_rate']*100:.2f}%")
        if report["latency_ms"]:
            print(f"  延迟: avg={report['latency_ms']['avg']}ms  "
                  f"p95={report['latency_ms']['p95']}ms  "
                  f"p99={report['latency_ms']['p99']}ms")
        mem = report.get("memory_analysis", {})
        if mem:
            print(f"  内存: {mem['start_kb']}KB → {mem['end_kb']}KB  "
                  f"({mem['growth_pct']:+.1f}%)  {'✅ 稳定' if mem['stable'] else '⚠️ 增长趋势'}")
        print(f"{'='*60}\n")

        return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="长跑浸泡测试")
    parser.add_argument("--duration", type=int, default=3600, help="持续时间(秒)")
    parser.add_argument("--qps", type=int, default=10, help="目标 QPS")
    parser.add_argument("--interval", type=int, default=60, help="采样间隔(秒)")
    parser.add_argument("--output", default="", help="输出 JSON 文件")
    args = parser.parse_args()

    test = SoakTest(duration_sec=args.duration, qps=args.qps,
                    check_interval=args.interval)
    report = test.run()

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"报告已保存: {args.output}")
