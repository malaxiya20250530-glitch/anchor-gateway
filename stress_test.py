#!/usr/bin/env python3
"""
觉察网关压力测试工具

用法:
  python3 stress_test.py                    # 默认: 50请求, 并发5
  python3 stress_test.py --requests 200 --concurrency 20
  python3 stress_test.py --port 8890 --mock  # 测试mock模式

输出: 延迟分布、吞吐量、错误率、百分位数
"""

import json
import time
import sys
import argparse
import threading
from collections import defaultdict
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ============================================================
# 测试用例
# ============================================================

TEST_CASES = [
    # 事实核查场景
    {"messages": [{"role": "user", "content": "火锅是谁发明的？"}], "session_id": "stress_1"},
    {"messages": [{"role": "user", "content": "Python是哪一年发布的？"}], "session_id": "stress_2"},
    {"messages": [{"role": "user", "content": "地球是平的吗？"}], "session_id": "stress_3"},
    {"messages": [{"role": "user", "content": "光速有多快？"}], "session_id": "stress_4"},
    # 对齐检测场景
    {"messages": [{"role": "user", "content": "我觉得我做得不够好"}], "session_id": "stress_5"},
    {"messages": [{"role": "user", "content": "你真的觉得我行吗？"}], "session_id": "stress_6"},
    # 混合
    {"messages": [{"role": "user", "content": "珠穆朗玛峰有多高？"}], "session_id": "stress_7"},
    {"messages": [{"role": "user", "content": "JavaScript是谁发明的？"}], "session_id": "stress_8"},
]

ANALYZE_TEXTS = [
    "朱元璋发明了火锅。Python绝对是世界上最好的语言。",
    "地球是平的，这是毫无疑问的事实。",
    "光速是无限的，因为爱因斯坦说过的。",
    "我永远也做不好任何事情。",
    "珠峰有10000米高，是世界最高峰。",
]


# ============================================================
# 核心
# ============================================================

class StressTester:
    def __init__(self, base_url: str, num_requests: int, concurrency: int):
        self.base_url = base_url.rstrip("/")
        self.num_requests = num_requests
        self.concurrency = concurrency
        self.latencies = []
        self.errors = []
        self.observer_stats = defaultdict(int)
        self.lock = threading.Lock()

    def _post(self, path: str, body: dict) -> tuple[float, dict | str]:
        """发送POST请求, 返回 (延迟ms, 结果dict或错误str)"""
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        start = time.monotonic()
        try:
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=30) as resp:
                raw = resp.read()
                elapsed = (time.monotonic() - start) * 1000
                result = json.loads(raw)
                return elapsed, result
        except (URLError, HTTPError, OSError, json.JSONDecodeError) as e:
            elapsed = (time.monotonic() - start) * 1000
            return elapsed, str(e)

    def _worker_chat(self, thread_id: int):
        """工作线程 — /v1/chat/completions"""
        for i in range(self.num_requests // self.concurrency):
            case = TEST_CASES[(thread_id + i) % len(TEST_CASES)]
            case = json.loads(json.dumps(case))  # deep copy
            case["session_id"] = f"stress_t{thread_id}_r{i}"

            latency, result = self._post("/v1/chat/completions", case)
            with self.lock:
                self.latencies.append(latency)
                if isinstance(result, dict):
                    obs = result.get("_observer", {})
                    status = obs.get("status", "unknown")
                    self.observer_stats[status] += 1
                    self.observer_stats["total_flags"] += len(obs.get("flags", []))
                else:
                    self.errors.append((case.get("session_id", "?"), result))
                    self.observer_stats["errors"] += 1

    def _worker_analyze(self, thread_id: int):
        """工作线程 — /analyze"""
        for i in range(self.num_requests // self.concurrency):
            text = ANALYZE_TEXTS[(thread_id + i) % len(ANALYZE_TEXTS)]
            latency, result = self._post("/analyze", {"text": text})
            with self.lock:
                self.latencies.append(latency)
                if isinstance(result, dict):
                    self.observer_stats[result.get("status", "unknown")] += 1
                else:
                    self.errors.append((text[:30], result))

    def run(self, endpoint: str = "chat"):
        print(f"\n{'='*60}")
        print(f"  觉察网关 · 压力测试")
        print(f"{'='*60}")
        print(f"  目标:    {self.base_url}")
        print(f"  端点:    {endpoint}")
        print(f"  请求数:  {self.num_requests}")
        print(f"  并发:    {self.concurrency}")
        print(f"{'='*60}\n")

        if endpoint == "chat":
            worker = self._worker_chat
        else:
            worker = self._worker_analyze

        threads = []
        start = time.monotonic()

        for t in range(self.concurrency):
            th = threading.Thread(target=worker, args=(t,))
            threads.append(th)
            th.start()

        # 进度条
        total = self.num_requests
        while any(t.is_alive() for t in threads):
            done = len(self.latencies) + len(self.errors)
            pct = min(100, done * 100 // total)
            bar = "█" * (pct // 4) + "░" * (25 - pct // 4)
            sys.stderr.write(f"\r  [{bar}] {pct}% ({done}/{total})")
            sys.stderr.flush()
            time.sleep(0.2)

        for t in threads:
            t.join()

        elapsed = time.monotonic() - start
        sys.stderr.write("\r" + " " * 50 + "\r")

        # ======== 结果 ========
        self._print_results(elapsed)

    def _print_results(self, elapsed: float):
        lat = sorted(self.latencies)
        n = len(lat)

        if n == 0:
            print("  ❌ 全部请求失败!")
            for e in self.errors[:5]:
                print(f"    错误: {e}")
            return

        avg = sum(lat) / n
        p50 = lat[n // 2] if n > 0 else 0
        p95 = lat[int(n * 0.95)] if n > 1 else lat[-1]
        p99 = lat[int(n * 0.99)] if n > 2 else lat[-1]
        tps = n / elapsed
        error_rate = len(self.errors) / (n + len(self.errors)) * 100

        print(f"\n  {'='*50}")
        print(f"  📊 压测结果")
        print(f"  {'='*50}")
        print(f"  总耗时:       {elapsed:.2f}s")
        print(f"  成功请求:     {n}")
        print(f"  失败请求:     {len(self.errors)}")
        print(f"  错误率:       {error_rate:.1f}%")
        print(f"  吞吐量:       {tps:.1f} req/s")
        print(f"  {'─'*50}")
        print(f"  平均延迟:     {avg:.1f}ms")
        print(f"  最小延迟:     {lat[0]:.1f}ms")
        print(f"  最大延迟:     {lat[-1]:.1f}ms")
        print(f"  P50 (中位):   {p50:.1f}ms")
        print(f"  P95:          {p95:.1f}ms")
        print(f"  P99:          {p99:.1f}ms")
        print(f"  {'─'*50}")
        print(f"  觉察统计:")
        for status, count in sorted(self.observer_stats.items()):
            if status not in ("total_flags", "errors"):
                print(f"    {status:20s}: {count}")
        if self.observer_stats.get("total_flags"):
            print(f"    总计标记数:          {self.observer_stats['total_flags']}")
        print()

        # 评级
        if error_rate < 1 and avg < 50:
            grade = "🟢 优秀"
        elif error_rate < 5 and avg < 200:
            grade = "🟡 良好"
        elif error_rate < 10 and avg < 500:
            grade = "🟠 一般"
        else:
            grade = "🔴 需要优化"

        print(f"  评级: {grade}")
        print()


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="觉察网关压力测试工具")
    parser.add_argument("--port", "-p", type=int, default=8800,
                       help="网关端口(默认8800)")
    parser.add_argument("--host", default="localhost",
                       help="网关地址(默认localhost)")
    parser.add_argument("--requests", "-n", type=int, default=50,
                       help="总请求数(默认50)")
    parser.add_argument("--concurrency", "-c", type=int, default=5,
                       help="并发数(默认5)")
    parser.add_argument("--endpoint", "-e", choices=["chat", "analyze"],
                       default="chat", help="测试端点(默认chat)")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"

    # 健康检查
    try:
        req = Request(f"{base_url}/health")
        with urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read())
            print(f"  ✅ 网关在线: {health.get('status', '?')}")
    except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
        print(f"  ❌ 无法连接到网关 {base_url}: {e}")
        print(f"  请先启动网关:")
        print(f"    python3 awareness_gateway.py --port {args.port} --mock &")
        sys.exit(1)

    tester = StressTester(base_url, args.requests, args.concurrency)
    tester.run(args.endpoint)


if __name__ == "__main__":
    main()
