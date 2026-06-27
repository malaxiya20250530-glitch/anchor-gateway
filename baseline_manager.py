#!/usr/bin/env python3
"""基准管理器 — 版本化基准追踪 / 回归检测 / 趋势对比。

功能:
  - 将每次 benchmark 结果存档到 baselines.json
  - 对比当前 vs 历史最佳
  - 检测 F1/延迟回归

用法:
    python3 baseline_manager.py --snapshot              # 从当前报告存档
    python3 baseline_manager.py --list                  # 列出历史基准
    python3 baseline_manager.py --compare               # 对比最新 vs 最佳
    python3 baseline_manager.py --trend                 # 趋势可视化
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

BASELINE_FILE = Path(__file__).parent / "baselines.json"
BENCHMARK_REPORT = Path(__file__).parent / "benchmark_report.json"

KEY_METRICS = ["f1", "precision", "recall", "accuracy", "avg_latency_ms",
               "tp", "fp", "fn", "tn", "total", "checker_count"]


# ═══════════════════════════════════════════════════════════
# 数据操作
# ═══════════════════════════════════════════════════════════

def load_baselines() -> dict:
    """加载基准历史"""
    if BASELINE_FILE.exists():
        with open(BASELINE_FILE) as f:
            return json.load(f)
    return {"version": "1.0", "snapshots": [], "best": {}}


def save_baselines(data: dict) -> None:
    """保存基准历史"""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(BASELINE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _extract_metrics(report: dict) -> dict:
    """从基准报告中提取核心指标"""
    metrics = {}
    for key in KEY_METRICS:
        if key in report:
            metrics[key] = report[key]
    # 额外字段
    metrics["kb_entries"] = report.get("kb_entries", 0)
    metrics["checkers"] = report.get("checkers", [])
    return metrics


def snapshot(source: str = "benchmark_report.json") -> dict:
    """从当前基准报告存档"""
    if not os.path.exists(source):
        print(f"❌ 未找到基准报告: {source}")
        print("  先运行: python3 benchmark.py")
        return {}

    with open(source) as f:
        report = json.load(f)

    data = load_baselines()
    metrics = _extract_metrics(report)

    snapshot_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": _get_commit_hash(),
        "source": source,
        "metrics": metrics,
    }

    data["snapshots"].append(snapshot_entry)

    # 更新最佳记录
    if not data["best"] or metrics.get("f1", 0) > data["best"].get("f1", 0):
        data["best"] = {
            "f1": metrics.get("f1", 0),
            "precision": metrics.get("precision", 0),
            "recall": metrics.get("recall", 0),
            "accuracy": metrics.get("accuracy", 0),
            "avg_latency_ms": metrics.get("avg_latency_ms", 0),
            "snapshot_index": len(data["snapshots"]) - 1,
            "timestamp": snapshot_entry["timestamp"],
        }

    save_baselines(data)

    n = len(data["snapshots"])
    print(f"✅ 基准已存档 (#{n})")
    print(f"   F1: {metrics.get('f1', 0):.3f}  "
          f"精度: {metrics.get('precision', 0):.3f}  "
          f"召回: {metrics.get('recall', 0):.3f}")
    return snapshot_entry


def compare_latest() -> dict:
    """对比最新基准 vs 历史最佳"""
    data = load_baselines()

    if not data["snapshots"]:
        print("❌ 无基准快照")
        print("  先运行: python3 baseline_manager.py --snapshot")
        return {}

    latest = data["snapshots"][-1]["metrics"]
    best = data["best"]

    comparison = {}
    print(f"\n{'='*60}")
    print(f"  基准对比: 最新 vs 历史最佳")
    print(f"{'='*60}")
    print(f"  {'指标':<20} {'最新':>8} {'最佳':>8} {'变化':>8} {'状态':>6}")
    print(f"  {'-'*50}")

    for key in ["f1", "precision", "recall", "accuracy", "avg_latency_ms"]:
        latest_val = latest.get(key, 0)
        best_val = best.get(key, 0)

        if isinstance(latest_val, (int, float)) and best_val:
            delta = latest_val - best_val
            delta_pct = round(delta / max(abs(best_val), 0.001) * 100, 1)

            # 对于延迟: 越低越好; 对于其他: 越高越好
            if key == "avg_latency_ms":
                degraded = latest_val > best_val * 1.2  # 延迟升高 > 20%
                status = "⚠️" if degraded else "✅"
            else:
                degraded = latest_val < best_val * 0.9  # 下降 > 10%
                status = "⚠️" if degraded else "✅"

            comparison[key] = {
                "latest": latest_val,
                "best": best_val,
                "delta": round(delta, 4),
                "delta_pct": delta_pct,
                "degraded": degraded,
            }

            print(f"  {key:<20} {latest_val:>8.4f} {best_val:>8.4f} "
                  f"{delta:>+8.4f} {status:>6}")
        else:
            print(f"  {key:<20} {latest_val!s:>8} {'-':>8} {'-':>8}")

    # 回归检测
    regressions = [k for k, v in comparison.items() if v.get("degraded")]
    if regressions:
        print(f"\n  ⚠️  检测到 {len(regressions)} 项回归: {', '.join(regressions)}")
    else:
        print(f"\n  ✅ 无回归检测")

    print(f"\n  快照总数: {len(data['snapshots'])}")
    return comparison


def show_trend() -> dict:
    """显示 F1 和延迟的历史趋势"""
    data = load_baselines()

    if not data["snapshots"]:
        print("❌ 无基准快照")
        return {}

    print(f"\n{'='*60}")
    print(f"  基准趋势 ({len(data['snapshots'])} 个快照)")
    print(f"{'='*60}")

    f1_values = []
    lat_values = []

    print(f"  {'#':>3} {'日期':<22} {'F1':>6} {'精度':>6} "
          f"{'召回':>6} {'延迟':>8} {'检查器':>6}")
    print(f"  {'-'*58}")

    for i, snap in enumerate(data["snapshots"]):
        m = snap["metrics"]
        ts = snap["timestamp"][:19].replace("T", " ")
        f1 = m.get("f1", 0)
        prec = m.get("precision", 0)
        rec = m.get("recall", 0)
        lat = m.get("avg_latency_ms", 0)
        chk = m.get("checker_count", 0)

        f1_values.append(f1)
        lat_values.append(lat)

        marker = " ⭐" if i == data["best"].get("snapshot_index", -1) else ""
        print(f"  {i+1:>3} {ts:<22} {f1:>6.3f} {prec:>6.3f} "
              f"{rec:>6.3f} {lat:>7.1f}ms {chk:>6}{marker}")

    # 趋势分析
    if len(f1_values) >= 2:
        f1_trend = "📈 上升" if f1_values[-1] > f1_values[0] else "📉 下降"
        lat_trend = "📉 改善" if lat_values[-1] < lat_values[0] else "📈 恶化"
        print(f"\n  F1 趋势: {f1_trend} ({f1_values[0]:.3f} → {f1_values[-1]:.3f})")
        print(f"  延迟趋势: {lat_trend} ({lat_values[0]:.1f}ms → "
              f"{lat_values[-1]:.1f}ms)")

    return {"f1_history": f1_values, "latency_history": lat_values}


def _get_commit_hash() -> str:
    """获取当前 git commit hash"""
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        return proc.stdout.strip() if proc.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="基准管理器")
    parser.add_argument("--snapshot", action="store_true", help="从当前报告存档")
    parser.add_argument("--list", action="store_true", help="列出历史基准")
    parser.add_argument("--compare", action="store_true", help="对比最新 vs 最佳")
    parser.add_argument("--trend", action="store_true", help="趋势分析")
    parser.add_argument("--source", default="benchmark_report.json",
                        help="基准报告路径")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    if args.snapshot:
        result = snapshot(args.source)
    elif args.list:
        data = load_baselines()
        for i, snap in enumerate(data["snapshots"]):
            m = snap["metrics"]
            ts = snap["timestamp"][:19].replace("T", " ")
            best = " ⭐" if i == data["best"].get("snapshot_index", -1) else ""
            print(f"  #{i+1} {ts}  F1={m.get('f1',0):.3f}  "
                  f"延迟={m.get('avg_latency_ms',0):.1f}ms{best}")
        exit(0)
    elif args.compare:
        result = compare_latest()
    elif args.trend:
        result = show_trend()
    else:
        print("请选择一个选项: --snapshot, --list, --compare, --trend")
        print("  python3 baseline_manager.py --snapshot")
        print("  python3 baseline_manager.py --trend")
        sys.exit(1)

    if args.json and result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
