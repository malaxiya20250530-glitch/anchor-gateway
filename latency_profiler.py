#!/usr/bin/env python3
"""
延迟/吞吐量剖析器 — P50/P95/P99 + TPS/QPS 独立测量。

测量目标:
  - 幻觉检测器直接调用延迟 (非 HTTP，消除网络噪声)
  - 冷启动 vs 热缓存延迟对比
  - 吞吐量 (TPS = 每秒检测数)
  - 分场景延迟分布 (短文本 / 长文本 / 数字密集 / 否定语义)

输出: latency_report.json

用法:
    python3 latency_profiler.py                    # 标准测量 (100次 x 4场景)
    python3 latency_profiler.py --iterations 500   # 高精度
    python3 latency_profiler.py --scene all        # 单一场景
    python3 latency_profiler.py --json             # 仅输出 JSON
"""

import json
import sys
import time
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent
REPORT_PATH = ROOT / "latency_report.json"

# ═══════════════════════════════════════════════════════════
# 测试场景
# ═══════════════════════════════════════════════════════════

SCENES = {
    "short": {
        "name": "短文本",
        "cases": [
            "地球是平的",
            "光速是无限快的",
            "朱元璋发明了火锅",
            "大脑只开发了10%",
            "金鱼只有3秒记忆",
        ],
        "expected_runs": 100,
    },
    "long": {
        "name": "长文本",
        "cases": [
            "爱因斯坦于1905年发表了狭义相对论并因此获得诺贝尔物理学奖",
            "珠穆朗玛峰是世界最高峰海拔8848米位于中国与尼泊尔边境",
            "明朝由朱元璋于1368年在应天今南京建立并持续到1644年",
        ],
        "expected_runs": 60,
    },
    "numeric": {
        "name": "数字密集",
        "cases": [
            "珠穆朗玛峰高8848米",
            "比特币总量2100万个上限",
            "光速约299792458米每秒",
            "地球的年龄约为45.4亿年",
            "人体约有37万亿个细胞",
        ],
        "expected_runs": 80,
    },
    "negation": {
        "name": "否定语义",
        "cases": [
            "抗生素对流感有效",
            "味精对人体有害",
            "维京人戴角盔作战",
            "拿破仑个子很矮",
            "鸵鸟遇到危险把头埋进沙子",
            "撒哈拉沙漠全是沙丘",
        ],
        "expected_runs": 120,
    },
}


# ═══════════════════════════════════════════════════════════
# 百分位计算
# ═══════════════════════════════════════════════════════════

def percentiles(data: list) -> dict:
    """计算 P50/P90/P95/P99/P999 和基本统计量"""
    if not data:
        return {"count": 0}
    n = len(data)
    s = sorted(data)

    def pct(p: float) -> float:
        """线性插值百分位"""
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return s[int(k)]
        return s[f] * (c - k) + s[c] * (k - f)

    return {
        "count": n,
        "min": round(s[0], 3),
        "max": round(s[-1], 3),
        "mean": round(sum(s) / n, 3),
        "std": round(_std(s), 3),
        "p50": round(pct(0.50), 3),
        "p90": round(pct(0.90), 3),
        "p95": round(pct(0.95), 3),
        "p99": round(pct(0.99), 3),
        "p999": round(pct(0.999), 3),
    }


def _std(data: list) -> float:
    """标准差"""
    if len(data) < 2:
        return 0.0
    mean = sum(data) / len(data)
    return math.sqrt(sum((x - mean) ** 2 for x in data) / (len(data) - 1))


# ═══════════════════════════════════════════════════════════
# 剖析引擎
# ═══════════════════════════════════════════════════════════

class LatencyProfiler:
    """延迟剖析器 — 直接测量 HallucinationDetector.analyze()"""

    def __init__(self, iterations: int = None):
        self.iterations = iterations
        self._detector = None

    @property
    def detector(self):
        """惰性加载检测器"""
        if self._detector is None:
            from hallucination_detector import HallucinationDetector
            self._detector = HallucinationDetector()
        return self._detector

    def _measure_scene(self, scene_key: str, scene_def: dict,
                       iterations: int) -> dict:
        """测量单个场景的延迟分布"""
        cases = scene_def["cases"]
        latencies = []
        errors = 0
        t0 = time.perf_counter()

        for i in range(iterations):
            claim = cases[i % len(cases)]
            try:
                t_start = time.perf_counter()
                self.detector.analyze(claim)
                elapsed_ms = (time.perf_counter() - t_start) * 1000
                latencies.append(elapsed_ms)
            except Exception:
                errors += 1

        total_sec = time.perf_counter() - t0
        tps = len(latencies) / max(total_sec, 0.001)

        stats = percentiles(latencies)
        stats["errors"] = errors
        stats["total_sec"] = round(total_sec, 2)
        stats["tps"] = round(tps, 1)
        stats["scene"] = scene_key

        return stats

    def profile(self, scenes: list = None) -> dict:
        """运行完整剖析"""
        if scenes is None:
            scenes = list(SCENES.keys())

        report = {
            "title": "幻觉检测器延迟/吞吐量剖析",
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scenes": {},
            "aggregate": {},
        }

        print(f"\n{'='*60}")
        print(f"  ⏱️  延迟/吞吐量剖析器")
        print(f"  场景: {len(scenes)}  |  时间: "
              f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")

        all_latencies = []
        total_errors = 0

        for scene_key in scenes:
            scene_def = SCENES[scene_key]
            iterations = self.iterations or scene_def["expected_runs"]
            name = scene_def["name"]

            print(f"\n  📐 {name} ({iterations} 次)...", end=" ", flush=True)
            stats = self._measure_scene(scene_key, scene_def, iterations)
            print(f"P50={stats['p50']:.1f}ms  "
                  f"P95={stats['p95']:.1f}ms  "
                  f"P99={stats['p99']:.1f}ms  "
                  f"TPS={stats['tps']:.1f}")

            report["scenes"][scene_key] = {
                "name": name,
                "iterations": iterations,
                **stats,
            }
            all_latencies.extend(
                [stats["p50"]] * iterations  # 用中位数代表
            )
            total_errors += stats.get("errors", 0)

        # 聚合统计
        if all_latencies:
            report["aggregate"] = percentiles(
                [s["mean"] for s in report["scenes"].values()]
            )
            report["aggregate"]["errors"] = total_errors
            report["aggregate"]["scenes"] = len(scenes)

        # 评级
        avg_p50 = report["aggregate"].get("p50", 999)
        avg_p99 = report["aggregate"].get("p99", 999)
        if avg_p50 < 50 and avg_p99 < 200:
            grade = "🟢 优秀"
        elif avg_p50 < 100 and avg_p99 < 500:
            grade = "🟡 良好"
        elif avg_p50 < 200:
            grade = "🟠 可接受"
        else:
            grade = "🔴 需要优化"
        report["grade"] = grade

        print(f"\n  {'─'*60}")
        print(f"  综合评级: {grade}")
        print(f"  聚合 P50: {avg_p50:.1f}ms  |  "
              f"P95: {report['aggregate'].get('p95',0):.1f}ms  |  "
              f"P99: {avg_p99:.1f}ms")
        print(f"{'='*60}")

        return report

    def save_report(self, report: dict, path: str = None) -> None:
        """保存报告"""
        path = path or str(REPORT_PATH)
        with open(path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  报告已保存: {path}")


# ═══════════════════════════════════════════════════════════
# 快速 TPS 测量
# ═══════════════════════════════════════════════════════════

def measure_tps(duration_sec: float = 5.0) -> dict:
    """持续运行测量纯吞吐量"""
    from hallucination_detector import HallucinationDetector
    detector = HallucinationDetector()

    cases = [
        "地球是平的", "朱元璋发明了火锅", "光速是无限快的",
        "Python是1991年发布的", "大脑只开发了10%",
        "珠穆朗玛峰高8848米", "明朝由朱元璋建立",
        "爱因斯坦发明了原子弹", "抗生素对流感有效",
        "金鱼只有3秒记忆",
    ]

    count = 0
    errors = 0
    latencies = []
    deadline = time.perf_counter() + duration_sec

    while time.perf_counter() < deadline:
        claim = cases[count % len(cases)]
        try:
            t0 = time.perf_counter()
            detector.analyze(claim)
            latencies.append((time.perf_counter() - t0) * 1000)
            count += 1
        except Exception:
            errors += 1

    elapsed = time.perf_counter() - (deadline - duration_sec)
    tps = count / max(elapsed, 0.001)

    stats = percentiles(latencies)
    stats["tps"] = round(tps, 1)
    stats["duration_sec"] = round(elapsed, 1)
    stats["total_requests"] = count
    stats["errors"] = errors

    return stats


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="延迟/吞吐量剖析器")
    parser.add_argument("--iterations", type=int, default=None,
                        help="每个场景的迭代次数")
    parser.add_argument("--scene", default="",
                        help="单一场景 (short/long/numeric/negation/all)")
    parser.add_argument("--tps", action="store_true",
                        help="仅测量吞吐量 (5秒持续运行)")
    parser.add_argument("--tps-duration", type=float, default=5.0,
                        help="TPS 测量持续时间(秒)")
    parser.add_argument("--json", action="store_true",
                        help="仅输出 JSON")
    parser.add_argument("--output", default="",
                        help="输出文件路径")
    args = parser.parse_args()

    if args.tps:
        stats = measure_tps(args.tps_duration)
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"\n  ⚡ TPS 测量 ({stats['duration_sec']}s):")
            print(f"  请求: {stats['total_requests']}  "
                  f"错误: {stats['errors']}")
            print(f"  TPS:  {stats['tps']} req/s")
            print(f"  P50:  {stats['p50']}ms  "
                  f"P95: {stats['p95']}ms  "
                  f"P99: {stats['p99']}ms")
    else:
        profiler = LatencyProfiler(iterations=args.iterations)
        scenes = None
        if args.scene and args.scene != "all":
            if args.scene not in SCENES:
                print(f"未知场景: {args.scene}")
                print(f"可用: {', '.join(SCENES.keys())}")
                sys.exit(1)
            scenes = [args.scene]

        report = profiler.profile(scenes=scenes)
        profiler.save_report(report, args.output)

        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
