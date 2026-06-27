#!/usr/bin/env python3
"""
Benchmark Runner — 跑黄金基准集，输出混淆矩阵 + 按 Checker 分类统计。

用法:
  python3 benchmark/run.py                  # 跑全部
  python3 benchmark/run.py --checker year   # 只跑 year_conflict
  python3 benchmark/run.py --fast           # 快速模式（不加载图谱）
"""

import json, sys, os, time, argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from hallucination_detector import HallucinationDetector

BENCH_DIR = Path(__file__).parent


def load_benchmark(checker: str = None) -> list:
    """加载基准集"""
    path = BENCH_DIR / f"{checker}.jsonl" if checker else BENCH_DIR / "all.jsonl"
    if not path.exists():
        print(f"❌ 文件不存在: {path}")
        return []
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line))
    return samples


def classify_result(verdict: str, label: str) -> str:
    """
    TRUE label + contradicted → FP (误报)
    TRUE label + verified → TP
    FALSE label + contradicted → TN
    FALSE label + verified → FN (漏报)

    uncertain/unverifiable → 不计入
    """
    if label == "TRUE":
        if verdict == "contradicted":
            return "FP"
        elif verdict == "verified":
            return "TP"
    elif label == "FALSE":
        if verdict == "contradicted":
            return "TN"
        elif verdict == "verified":
            return "FN"
    return "SKIP"


def run_benchmark(samples: list, fast: bool = False) -> dict:
    """跑基准集，返回统计"""
    detector = HallucinationDetector()
    
    # 如果不加载图谱（快速模式）
    if fast:
        detector.anchor.enable_graph = False
    
    stats = {
        "total": 0, "evaluated": 0,
        "TP": 0, "TN": 0, "FP": 0, "FN": 0,
        "by_checker": defaultdict(lambda: {"TP": 0, "TN": 0, "FP": 0, "FN": 0}),
        "by_difficulty": defaultdict(lambda: {"TP": 0, "TN": 0, "FP": 0, "FN": 0}),
        "errors": [],
    }
    
    print(f"🏃 跑 {len(samples)} 条基准...")
    t0 = time.time()
    
    for i, s in enumerate(samples):
        text = s["text"]
        label = s["label"]
        
        # 幻觉检测
        report = detector.analyze(text)
        
        # 取第一个非 unverifiable 的结果
        for r in report.results:
            if r.verdict == "unverifiable":
                continue
            
            result = classify_result(r.verdict, label)
            if result != "SKIP":
                stats[result] += 1
                stats["evaluated"] += 1
                
                # 按 checker 统计
                for c in s.get("checker", ["unknown"]):
                    stats["by_checker"][c][result] += 1
                
                # 按难度统计
                diff = s.get("difficulty", "unknown")
                stats["by_difficulty"][diff][result] += 1
                # 记录错误详情
                if result in ("FP", "FN"):
                    stats["errors"].append({
                        "id": s.get("id", ""),
                        "claim": text,
                        "label": label,
                        "verdict": r.verdict,
                        "evidence": r.evidence[:100] if r.evidence else "",
                        "confidence": r.confidence,
                        "checker": s.get("checker", []),
                        "difficulty": s.get("difficulty", "?"),
                        "error_type": result,
                    })
            
            break  # 只取第一个判定
        
        stats["total"] += 1
        
        # 进度
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(samples)}...")
    
    elapsed = time.time() - t0
    stats["elapsed"] = elapsed
    stats["samples_per_sec"] = stats["total"] / elapsed if elapsed > 0 else 0
    
    return stats


def print_confusion_matrix(stats: dict):
    """打印混淆矩阵 + 指标"""
    tp, tn, fp, fn = stats["TP"], stats["TN"], stats["FP"], stats["FN"]
    total = tp + tn + fp + fn
    
    if total == 0:
        print("⚠️  无可评估样本")
        return
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    accuracy = (tp + tn) / total
    
    print(f"\n{'=' * 55}")
    print(f"  混淆矩阵")
    print(f"  {'─' * 51}")
    print(f"                    实际 TRUE    实际 FALSE")
    print(f"  判 TRUE  (verified)   {tp:>5}         {fn:>5}      (漏报)")
    print(f"  判 FALSE (contrad)    {fp:>5}         {tn:>5}      (正确)")
    print(f"                     (误报)")
    print(f"  {'─' * 51}")
    print(f"  准确率 (Accuracy):  {accuracy:.1%}")
    print(f"  精确率 (Precision): {precision:.1%}")
    print(f"  召回率 (Recall):    {recall:.1%}")
    print(f"  F1 分数:            {f1:.3f}")
    print(f"  {'─' * 51}")
    print(f"  总样本: {stats['total']} | 可评估: {stats['evaluated']}")
    print(f"  TP={tp}  TN={tn}  FP={fp}  FN={fn}")
    print(f"  耗时: {stats['elapsed']:.1f}s ({stats['samples_per_sec']:.0f} 条/秒)")


def print_checker_breakdown(stats: dict):
    """按 Checker 分类统计"""
    print(f"\n{'=' * 55}")
    print(f"  按 Checker 分类")
    print(f"  {'─' * 51}")
    print(f"  {'Checker':<22s} {'样本':>5s} {'准确率':>7s} {'F1':>6s} {'FP率':>7s}")
    print(f"  {'─' * 51}")
    
    for checker, s in sorted(stats["by_checker"].items()):
        total = s["TP"] + s["TN"] + s["FP"] + s["FN"]
        if total == 0:
            continue
        acc = (s["TP"] + s["TN"]) / total
        prec = s["TP"] / (s["TP"] + s["FP"]) if (s["TP"] + s["FP"]) > 0 else 0
        rec = s["TP"] / (s["TP"] + s["FN"]) if (s["TP"] + s["FN"]) > 0 else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
        fp_rate = s["FP"] / (s["FP"] + s["TN"]) if (s["FP"] + s["TN"]) > 0 else 0
        
        print(f"  {checker:<22s} {total:>5d} {acc:>6.1%} {f1:>6.3f} {fp_rate:>6.1%}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Runner")
    parser.add_argument("--checker", "-c", help="只跑指定 checker (如 year_conflict)")
    parser.add_argument("--fast", action="store_true", help="快速模式（不加载知识图谱）")
    args = parser.parse_args()
    
    samples = load_benchmark(args.checker)
    if not samples:
        sys.exit(1)
    
    stats = run_benchmark(samples, fast=args.fast)
    print_confusion_matrix(stats)
    print_checker_breakdown(stats)
    
    # 持久化错误分析
    from benchmark.error_bucket import classify_and_save
    classify_and_save(stats.get("errors", []), samples)
    
    # 自动归因分析
    try:
        from benchmark.error_bucket import load_errors, summarize_root_cause
        fps, fns = load_errors()
        if fps or fns:
            summarize_root_cause(fps, "FP (误报)")
            summarize_root_cause(fns, "FN (漏报)")
    except Exception:
        pass  # 归因分析失败不影响主流程


if __name__ == "__main__":
    main()
