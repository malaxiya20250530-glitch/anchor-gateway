#!/usr/bin/env python3
"""企业级压测框架 — 可配置 QPS / 持续时间 / P95-P99 统计。

纯 Python 标准库，零外部依赖。
可压测 HTTP 端点或本地模块。

用法:
    python3 enterprise_stress.py --qps 100 --duration 60
    python3 enterprise_stress.py --qps 500 --duration 3600 --ramp 30
    python3 enterprise_stress.py --qps 1000 --duration 86400 --output report.json

输出:
    report.json  — 完整统计数据
    stdout       — 实时进度条 + 间隔统计
"""

import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

# 尝试导入本地指标
try:
    from metrics_exporter import MetricsRegistry
    _METRICS = MetricsRegistry()
except ImportError:
    _METRICS = None


# ═══════════════════════════════════════════════════════════
# 核心压测引擎
# ═══════════════════════════════════════════════════════════

class LoadTestResult:
    """单次请求结果"""
    def __init__(self, ts: float, latency: float, status: int,
                 tokens: int = 0, error: str = ""):
        self.ts = ts
        self.latency = latency
        self.status = status
        self.tokens = tokens
        self.error = error


class StressEngine:
    """并发压测引擎"""

    def __init__(self, target_url: str = "", target_func=None,
                 payload: str = "", headers: dict = None,
                 qps: int = 100, duration_sec: int = 60,
                 ramp_sec: int = 0, concurrency: int = 50):
        self.url = target_url
        self.func = target_func  # 本地函数模式
        self.payload = payload.encode() if payload else b'{"messages":[{"role":"user","content":"hi"}]}'
        self.headers = headers or {"Content-Type": "application/json"}
        self.qps = qps
        self.duration = duration_sec
        self.ramp = ramp_sec
        self.max_workers = concurrency

        self.results: list[LoadTestResult] = []
        self._lock = threading.Lock()
        self._running = True
        self._start_time = 0.0

    def run(self) -> dict:
        """执行压测，返回统计报告"""
        print(f"\n{'='*60}")
        print(f"  压测开始: {self.url or '本地函数'}")
        print(f"  目标 QPS: {self.qps}  |  持续: {self.duration}s  |  爬坡: {self.ramp}s")
        print(f"  并发: {self.max_workers}  |  时间: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}\n")

        self._start_time = time.time()
        deadline = self._start_time + self.duration + self.ramp

        # 按时间槽调度请求
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            slot = 0
            interval = 1.0 / max(self.qps, 1)

            while time.time() < deadline and self._running:
                now = time.time()
                elapsed = now - self._start_time

                # 爬坡: 前 ramp_sec 秒线性增加到目标 QPS
                current_qps = self.qps
                if elapsed < self.ramp:
                    current_qps = max(1, int(self.qps * elapsed / self.ramp))
                    interval = 1.0 / current_qps

                # 超出 duration 后停止发送新请求（等待已有请求完成）
                if elapsed > self.duration + self.ramp:
                    break

                # 发送请求
                futures.append(executor.submit(self._do_request, slot))
                slot += 1

                # 等待到下一个时间槽
                target_time = self._start_time + slot * interval
                sleep_time = target_time - time.time()
                if sleep_time > 0:
                    time.sleep(min(sleep_time, 0.1))

                # 实时进度
                if slot % max(1, self.qps * 5) == 0:
                    self._print_progress(elapsed)

            # 等待所有请求完成
            for f in as_completed(futures):
                pass

        return self._generate_report()

    def _do_request(self, slot: int):
        start = time.time()
        try:
            if self.func:
                # 本地函数模式
                result = self.func(self.payload.decode())
                latency = time.time() - start
                status = 200
                tokens = len(self.payload)
            else:
                # HTTP 模式
                req = urllib.request.Request(self.url, data=self.payload,
                                             headers=self.headers, method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    latency = time.time() - start
                    status = resp.status
                    tokens = len(resp.read())

            with self._lock:
                self.results.append(LoadTestResult(start, latency, status, tokens))

        except urllib.error.HTTPError as e:
            with self._lock:
                self.results.append(LoadTestResult(start, time.time() - start,
                                                   e.code, 0, str(e)))
        except Exception as e:
            with self._lock:
                self.results.append(LoadTestResult(start, time.time() - start,
                                                   0, 0, str(e)[:100]))

    def _print_progress(self, elapsed: float):
        with self._lock:
            total = len(self.results)
            errors = sum(1 for r in self.results if r.status >= 400 or r.error)
            if total > 0:
                latencies = [r.latency for r in self.results[-100:]]
                avg_lat = sum(latencies) / len(latencies) * 1000
                actual_qps = total / max(elapsed, 0.1)
                print(f"  [{elapsed:6.0f}s] 请求:{total:6d}  QPS:{actual_qps:6.1f}  "
                      f"延迟:{avg_lat:6.1f}ms  错误:{errors:4d}")

    def _generate_report(self) -> dict:
        total = len(self.results)
        if total == 0:
            return {"error": "无请求数据"}

        latencies = sorted([r.latency * 1000 for r in self.results])
        errors = [r for r in self.results if r.status >= 400 or r.error]
        successes = total - len(errors)
        elapsed = self.results[-1].ts - self.results[0].ts if total > 1 else 0

        def percentile(data, p):
            if not data:
                return 0
            idx = int(len(data) * p / 100)
            return data[min(idx, len(data)-1)]

        report = {
            "test_config": {
                "target": self.url or "local",
                "target_qps": self.qps,
                "duration_sec": self.duration,
                "ramp_sec": self.ramp,
                "concurrency": self.max_workers,
            },
            "results": {
                "total_requests": total,
                "successful": successes,
                "failed": len(errors),
                "error_rate": round(len(errors) / max(total, 1), 4),
                "actual_qps": round(total / max(elapsed, 0.1), 2),
                "total_duration_sec": round(elapsed, 2),
            },
            "latency_ms": {
                "min": round(latencies[0], 2),
                "max": round(latencies[-1], 2),
                "avg": round(sum(latencies) / total, 2),
                "p50": round(percentile(latencies, 50), 2),
                "p75": round(percentile(latencies, 75), 2),
                "p90": round(percentile(latencies, 90), 2),
                "p95": round(percentile(latencies, 95), 2),
                "p99": round(percentile(latencies, 99), 2),
                "p999": round(percentile(latencies, 99.9), 2),
            },
            "status_codes": {},
            "top_errors": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 状态码分布
        for r in self.results:
            code = str(r.status)
            report["status_codes"][code] = report["status_codes"].get(code, 0) + 1

        # Top 错误
        error_counts = {}
        for r in errors:
            msg = r.error[:80] if r.error else f"HTTP {r.status}"
            error_counts[msg] = error_counts.get(msg, 0) + 1
        report["top_errors"] = sorted(
            [{"error": k, "count": v} for k, v in error_counts.items()],
            key=lambda x: x["count"], reverse=True
        )[:10]

        # 打印报告
        self._print_report(report)
        return report

    def _print_report(self, r: dict):
        res = r["results"]
        lat = r["latency_ms"]
        print(f"\n{'='*60}")
        print(f"  压测报告")
        print(f"{'='*60}")
        print(f"  总请求: {res['total_requests']}  |  成功: {res['successful']}  |  "
              f"失败: {res['failed']}  |  错误率: {res['error_rate']*100:.2f}%")
        print(f"  实际QPS: {res['actual_qps']}  |  总耗时: {res['total_duration_sec']}s")
        print(f"  {'─'*56}")
        print(f"  延迟 (ms):  avg={lat['avg']}  p50={lat['p50']}  "
              f"p95={lat['p95']}  p99={lat['p99']}")
        print(f"  延迟 (ms):  min={lat['min']}  max={lat['max']}  "
              f"p75={lat['p75']}  p90={lat['p90']}  p999={lat['p999']}")
        if r["status_codes"]:
            codes = ", ".join(f"{k}:{v}" for k, v in sorted(r["status_codes"].items()))
            print(f"  状态码: {codes}")
        print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════
# 本地函数压测模式（无需启动服务）
# ═══════════════════════════════════════════════════════════

def local_hallucination_test(payload: str) -> dict:
    """本地幻觉检测压测（不依赖网络）"""
    from hallucination_detector import HallucinationDetector
    detector = HallucinationDetector()
    report = detector.analyze(payload)
    return {"verdicts": len(report.results), "score": report.overall_score}


def local_waf_test(payload: str) -> dict:
    """本地 WAF 压测"""
    from waf import WAF
    waf = WAF()
    result = waf.scan(payload, ip="127.0.0.1", endpoint="/test")
    return {"blocked": result.blocked, "reason": result.reason}


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="企业级压测框架")
    parser.add_argument("--url", default="", help="目标 URL")
    parser.add_argument("--qps", type=int, default=100, help="目标 QPS")
    parser.add_argument("--duration", type=int, default=60, help="持续时间(秒)")
    parser.add_argument("--ramp", type=int, default=0, help="爬坡时间(秒)")
    parser.add_argument("--concurrency", type=int, default=50, help="最大并发")
    parser.add_argument("--payload", default="", help="请求体")
    parser.add_argument("--output", default="", help="输出 JSON 文件")
    parser.add_argument("--local", choices=["hallucination", "waf"],
                        help="本地模块压测模式")
    parser.add_argument("--multi-stage", action="store_true",
                        help="多阶段压测: 100→500→1000 QPS")
    args = parser.parse_args()

    if args.multi_stage:
        stages = [
            (100, 120, 10, "预热"),
            (500, 300, 30, "中等负载"),
            (1000, 300, 30, "高负载"),
        ]
        all_reports = []
        for qps, dur, ramp, label in stages:
            print(f"\n{'#'*60}")
            print(f"  阶段: {label} ({qps} QPS, {dur}s)")
            print(f"{'#'*60}")
            engine = StressEngine(
                target_url=args.url or "http://localhost:8800/v1/chat/completions",
                qps=qps, duration_sec=dur, ramp_sec=ramp,
                concurrency=args.concurrency, payload=args.payload
            )
            report = engine.run()
            report["stage"] = label
            all_reports.append(report)
            time.sleep(5)  # 阶段间冷却

        if args.output:
            with open(args.output, "w") as f:
                json.dump(all_reports, f, indent=2, ensure_ascii=False)
            print(f"报告已保存: {args.output}")
        return

    func = None
    if args.local == "hallucination":
        func = local_hallucination_test
        test_payloads = [
            "朱元璋发明了火锅",
            "Python是1989年发布的",
            "爱因斯坦发明了原子弹",
            "地球是平的",
            "光速是无限快的",
        ]
        import random
        args.payload = random.choice(test_payloads)
    elif args.local == "waf":
        func = local_waf_test
        args.payload = "' OR 1=1 --"

    engine = StressEngine(
        target_url=args.url,
        target_func=func,
        qps=args.qps, duration_sec=args.duration,
        ramp_sec=args.ramp, concurrency=args.concurrency,
        payload=args.payload
    )
    report = engine.run()

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"报告已保存: {args.output}")


if __name__ == "__main__":
    main()
