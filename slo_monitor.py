#!/usr/bin/env python3
"""SLO/SLA 监控 — 可用性 / 延迟 / 错误率 / 预算燃烧。

定义四项核心 SLO，提供实时监控和预算燃烧告警。

SLO 目标:
  - 可用性: 99.9% (月误差预算 ≈ 43.2 分钟不可用)
  - 延迟 P95: < 100ms (幻觉检测端到端)
  - 延迟 P99: < 300ms
  - 错误率: < 1%

用法:
    python3 slo_monitor.py                          # 显示当前 SLO 状态
    python3 slo_monitor.py --reset                  # 重置统计窗口
    python3 slo_monitor.py --import-benchmark       # 从基准报告导入指标
    python3 slo_monitor.py --burn-alert             # 检查预算燃烧告警
"""

import json
import os
import time
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════
# SLO 定义
# ═══════════════════════════════════════════════════════════

SLO_DEFINITIONS = {
    "availability": {
        "target": 0.999,       # 99.9%
        "window_days": 30,     # 滚动窗口
        "unit": "成功率",
        "description": "幻觉检测服务可用性",
    },
    "latency_p95_ms": {
        "target": 100,         # P95 < 100ms
        "window_days": 7,
        "unit": "ms",
        "description": "端到端检测延迟 P95",
    },
    "latency_p99_ms": {
        "target": 300,         # P99 < 300ms
        "window_days": 7,
        "unit": "ms",
        "description": "端到端检测延迟 P99",
    },
    "error_rate": {
        "target": 0.01,       # 1%
        "window_days": 7,
        "unit": "比例",
        "description": "检测错误率",
    },
}

# ═══════════════════════════════════════════════════════════
# SLO 状态存储
# ═══════════════════════════════════════════════════════════

SLO_STATE_FILE = Path(__file__).parent / "slo_state.json"


def _load_state() -> dict:
    """加载 SLO 持久状态"""
    if SLO_STATE_FILE.exists():
        with open(SLO_STATE_FILE) as f:
            return json.load(f)
    return {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_reset": datetime.now(timezone.utc).isoformat(),
        "slos": {k: {"current": None, "status": "unknown", "updated_at": None}
                 for k in SLO_DEFINITIONS},
        "burn_events": [],
    }


def _save_state(state: dict) -> None:
    """持久化 SLO 状态"""
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(SLO_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 指标采集
# ═══════════════════════════════════════════════════════════

def collect_from_benchmark(benchmark_path: str = "benchmark_report.json") -> dict:
    """从基准报告采集 SLO 指标"""
    if not os.path.exists(benchmark_path):
        return {}

    with open(benchmark_path) as f:
        report = json.load(f)

    return {
        "error_rate": 1.0 - report.get("accuracy", 0),
        "latency_p95_ms": report.get("p95_latency_ms",
                                       report.get("avg_latency_ms", 0) * 2.5),
        "latency_p99_ms": report.get("p99_latency_ms",
                                       report.get("avg_latency_ms", 0) * 3.5),
        "availability": report.get("success_rate", 1.0 - (report.get("errors", 0)
                                   / max(report.get("total", 1), 1))),
    }


def collect_from_latency(path: str = "latency_report.json") -> dict:
    """从延迟剖析报告采集 P50/P95/P99 和 TPS"""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        report = json.load(f)
    agg = report.get("aggregate", {})
    if not agg:
        return {}
    return {
        "latency_p50_ms": agg.get("p50"),
        "latency_p95_ms": agg.get("p95"),
        "latency_p99_ms": agg.get("p99"),
        "tps": report.get("scenes", {}).get("short", {}).get("tps"),
        "grade": report.get("grade", ""),
    }


def collect_from_chaos(chaos_path: str = "chaos_report.json") -> dict:
    """从混沌报告采集可用性指标"""
    if not os.path.exists(chaos_path):
        return {}

    with open(chaos_path) as f:
        report = json.load(f)

    return {
        "availability": report.get("pass_rate", 1.0),
        "chaos_scenarios_passed": report.get("passed", 0),
        "chaos_scenarios_total": report.get("total", 0),
    }


def collect_from_stress(stress_path: str = "stress_report.json") -> dict:
    """从压力测试采集延迟指标"""
    if not os.path.exists(stress_path):
        return {}

    with open(stress_path) as f:
        report = json.load(f)

    latencies = report.get("latencies", [])
    if not latencies:
        return {}

    sorted_lats = sorted(latencies)
    n = len(sorted_lats)
    return {
        "latency_p95_ms": sorted_lats[int(n * 0.95)] if n > 0 else 0,
        "latency_p99_ms": sorted_lats[int(n * 0.99)] if n > 0 else 0,
        "avg_latency_ms": sum(latencies) / n if n > 0 else 0,
    }


# ═══════════════════════════════════════════════════════════
# 预算燃烧分析
# ═══════════════════════════════════════════════════════════

def burn_rate(current: float, target: float, window_days: int) -> float:
    """计算误差预算燃烧率。

    返回: 倍数 (1.0 = 正常消耗, >2.0 = 快速燃烧, >10 = 紧急)
    """
    if current is None or target is None:
        return 0.0

    error_budget = 1.0 - target
    if error_budget <= 0:
        return 0.0

    current_error = 1.0 - current if target < 1.0 else current / target - 1.0
    if current_error <= 0:
        return 0.0

    # 假设均匀消耗，按天数比例
    consumed_ratio = min(current_error / error_budget, 1.0)
    burn = consumed_ratio * (30.0 / max(window_days, 1))
    return round(burn, 1)


def burn_alert_level(burn_rate_val: float) -> str:
    """预算燃烧告警级别"""
    if burn_rate_val >= 10:
        return "🔴 CRITICAL"
    elif burn_rate_val >= 5:
        return "🟠 HIGH"
    elif burn_rate_val >= 2:
        return "🟡 WARNING"
    elif burn_rate_val >= 1:
        return "🔵 INFO"
    return "🟢 OK"


# ═══════════════════════════════════════════════════════════
# 综合评估
# ═══════════════════════════════════════════════════════════

def evaluate_slo(metrics: dict) -> dict:
    """综合 SLO 评估 — 对比实际值 vs 目标值"""
    state = _load_state()
    results = {}

    for slo_name, slo_def in SLO_DEFINITIONS.items():
        target = slo_def["target"]
        current = metrics.get(slo_name)

        if current is None:
            status = "no_data"
            compliance = None
            burn = 0.0
        else:
            if slo_name.startswith("latency"):
                # 延迟类指标: 越低越好
                compliance = current <= target
                ratio = current / max(target, 1)
                burn = burn_rate(1.0 - ratio * 0.01, target / 1000.0,
                                 slo_def["window_days"])
            elif slo_name == "error_rate":
                compliance = current <= target
                burn = burn_rate(1.0 - current, 1.0 - target,
                                 slo_def["window_days"])
            else:
                # 可用性: 越高越好
                compliance = current >= target
                burn = burn_rate(current, target, slo_def["window_days"])

            status = "compliant" if compliance else "violated"

        alert = burn_alert_level(burn)

        results[slo_name] = {
            "target": target,
            "current": current,
            "status": status,
            "compliance": compliance,
            "burn_rate": burn,
            "alert": alert,
            "description": slo_def["description"],
            "unit": slo_def["unit"],
        }

        state["slos"][slo_name] = {
            "current": current,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    _save_state(state)
    return results


# ═══════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════

def print_slo_report(results: dict) -> None:
    """打印格式化的 SLO 报告"""
    print(f"\n{'='*65}")
    print(f"  📊 SLO/SLA 状态报告")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*65}")

    fmt = "  {alert:<12} {slo:<18} {current:>8} {arrow:>3} {target:>8} {unit:<8} {burn:>6}"
    print(fmt.format(alert="告警", slo="SLO", current="当前值", arrow="",
                     target="目标", unit="单位", burn="燃烧率"))
    print(f"  {'-'*63}")

    for slo_name, r in results.items():
        arrow = "<=" if r["target"] < 1 else ">="
        current_str = f"{r['current']:.4f}" if r['current'] is not None else "N/A"
        target_str = f"{r['target']}" if r['target'] is not None else "N/A"
        burn_str = f"{r['burn_rate']}x" if r['burn_rate'] > 0 else "-"

        print(fmt.format(
            alert=r["alert"],
            slo=slo_name,
            current=current_str,
            arrow=arrow,
            target=target_str,
            unit=r["unit"],
            burn=burn_str,
        ))

    compliant = sum(1 for r in results.values() if r["status"] == "compliant")
    violated = sum(1 for r in results.values() if r["status"] == "violated")
    nodata = sum(1 for r in results.values() if r["status"] == "no_data")

    print(f"\n  合规: {compliant}  |  违规: {violated}  |  无数据: {nodata}")

    alerts = [r for r in results.values() if "🔴" in r.get("alert", "")]
    if alerts:
        print(f"\n  ⚠️  紧急告警:")
        for a in alerts:
            print(f"    - {a['description']}: 当前 {a['current']}, "
                  f"预算燃烧 {a['burn_rate']}x")


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SLO/SLA 监控")
    parser.add_argument("--reset", action="store_true", help="重置统计窗口")
    parser.add_argument("--import-benchmark", action="store_true",
                        help="从 benchmark_report.json 导入指标")
    parser.add_argument("--burn-alert", action="store_true",
                        help="仅显示预算燃烧告警")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    if args.reset:
        if SLO_STATE_FILE.exists():
            SLO_STATE_FILE.unlink()
        print("✅ SLO 状态已重置")
        exit(0)

    # 采集指标
    metrics = {}

    if args.import_benchmark:
        benchmark_metrics = collect_from_benchmark()
        if benchmark_metrics:
            metrics.update(benchmark_metrics)
            print("📥 已从 benchmark_report.json 导入指标")
        else:
            print("⚠️  benchmark_report.json 未找到")

    latency_metrics = collect_from_latency()
    if latency_metrics:
        metrics.update(latency_metrics)
    chaos_metrics = collect_from_chaos()
    if chaos_metrics:
        metrics.update(chaos_metrics)

    stress_metrics = collect_from_stress()
    if stress_metrics:
        metrics.update(stress_metrics)

    if not metrics:
        # 无外部数据时使用默认估测值
        state = _load_state()
        for slo_name, slo_data in state["slos"].items():
            if slo_data["current"] is not None:
                metrics[slo_name] = slo_data["current"]

        if not metrics:
            print("⚠️  无可用指标数据")
            print("  运行方式:")
            print("    python3 slo_monitor.py --import-benchmark")
            print("    python3 benchmark.py  (先生成基准报告)")
            exit(1)

    results = evaluate_slo(metrics)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif args.burn_alert:
        for name, r in results.items():
            if r["burn_rate"] >= 2:
                print(f"{r['alert']} {name}: 燃烧率 {r['burn_rate']}x "
                      f"(当前: {r['current']}, 目标: {r['target']})")
    else:
        print_slo_report(results)
