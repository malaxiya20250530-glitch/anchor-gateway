#!/usr/bin/env python3
"""
Error Bucket — 自动归因分析 FP/FN，输出根因热力图与优化建议。

用法:
    python3 benchmark/error_bucket.py [--detail]

读取 benchmark/error_analysis.jsonl，输出:
    1. FP/FN 根因分布表
    2. 按 Checker × RootCause 热力图
    3. 最高 ROI 优化建议
"""

import json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
ERROR_FILE = Path(__file__).parent / "error_analysis.jsonl"


def load_errors():
    """加载错误记录"""
    fps, fns = [], []
    if not ERROR_FILE.exists():
        print("⚠️  error_analysis.jsonl 不存在，请先运行 benchmark/run.py")
        return fps, fns

    with open(ERROR_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "FP":
                fps.append(rec)
            elif rec.get("type") == "FN":
                fns.append(rec)
    return fps, fns


def summarize_root_cause(records, label):
    """汇总根因分布"""
    rc = Counter()
    for r in records:
        rc[r.get("root_cause", "unknown")] += 1
    print(f"\n{'='*60}")
    print(f"  {label} 根因分布 ({len(records)} 个)")
    print(f"{'='*60}")
    for cause, count in rc.most_common():
        pct = count / max(len(records), 1) * 100
        bar = "█" * int(pct / 2)
        print(f"  {cause:<30s} {count:>4d}  ({pct:5.1f}%)  {bar}")
    return rc


def checker_root_cause_heatmap(records, label):
    """按 Checker × RootCause 交叉统计"""
    matrix = defaultdict(lambda: Counter())
    for r in records:
        checker = r.get("checker", "unknown")
        if isinstance(checker, list):
            checker = "+".join(checker[:2])  # 取前2个
        rc = r.get("root_cause", "unknown")
        matrix[checker][rc] += 1

    print(f"\n{'='*60}")
    print(f"  {label} Checker × RootCause 热力图")
    print(f"{'='*60}")

    # 收集所有 root_cause
    all_rc = set()
    for rc_counter in matrix.values():
        all_rc.update(rc_counter.keys())
    all_rc = sorted(all_rc, key=lambda x: sum(matrix[c][x] for c in matrix), reverse=True)

    # 表头
    header = f"  {'Checker':<30s}"
    for rc in all_rc[:8]:
        header += f" {rc[:12]:>12s}"
    print(header)
    print(f"  {'-'*30}{'-'*13*min(8, len(all_rc))}")

    for checker in sorted(matrix.keys(), key=lambda c: sum(matrix[c].values()), reverse=True):
        total = sum(matrix[checker].values())
        if total < 3:
            continue
        row = f"  {checker:<30s}"
        for rc in all_rc[:8]:
            row += f" {matrix[checker][rc]:>12d}"
        print(row)


def roi_recommendations(fps, fns):
    """基于可回收错误数的优化建议"""
    print(f"\n{'='*60}")
    print(f"  📊 优化 ROI 分析")
    print(f"{'='*60}")

    # 按 root_cause 统计可回收错误
    rc_fp = Counter()
    rc_fn = Counter()
    rc_examples = defaultdict(list)

    for r in fps:
        rc = r.get("root_cause", "unknown")
        rc_fp[rc] += 1
        if len(rc_examples[rc]) < 2:
            rc_examples[rc].append(r.get("text", "")[:60])

    for r in fns:
        rc = r.get("root_cause", "unknown")
        rc_fn[rc] += 1

    recommendations = []

    # kb_no_cover (FN) → 扩 KB
    if "kb_no_cover" in rc_fn:
        recommendations.append({
            "priority": 1,
            "action": "扩充 KB 覆盖",
            "target": f"FN -{rc_fn['kb_no_cover']}",
            "effort": "低（KB Generator 已就绪）",
            "detail": f"{rc_fn['kb_no_cover']} 个 FN 源于知识缺失，每增加 100 条 KB 事实可回收约 15-20 个 FN",
        })

    # kb_overmatch (FP) → 实体置信度阈值
    if "kb_overmatch" in rc_fp:
        recommendations.append({
            "priority": 2,
            "action": "提高 KB 匹配精度",
            "target": f"FP -{rc_fp['kb_overmatch']}",
            "effort": "中（调整 _semantic_match_kb 阈值 + entity_confidence）",
            "detail": f"{rc_fp['kb_overmatch']} 个 FP 源于 KB 过度匹配，降低相似度阈值或增加实体类型校验可回收",
        })

    # entity_mismatch (FP) → 实体消歧
    if "entity_mismatch" in rc_fp:
        recommendations.append({
            "priority": 3,
            "action": "实体消歧",
            "target": f"FP -{rc_fp['entity_mismatch']}",
            "effort": "中（entity_confidence 已实装）",
            "detail": f"{rc_fp['entity_mismatch']} 个 FP 源于实体绑定错误，增强 _infer_entity_type 的上下文窗口",
        })

    # year 相关
    year_fp = rc_fp.get("year_entity_mismatch", 0) + rc_fp.get("year_conflict_fp", 0)
    year_fn = rc_fn.get("year_miss", 0)
    if year_fp or year_fn:
        recommendations.append({
            "priority": 4,
            "action": "YearChecker 专项修复",
            "target": f"FP -{year_fp}, FN -{year_fn}",
            "effort": "高（需 Error Bucket 细分年份表达类型）",
            "detail": f"年份相关错误：{year_fp} FP + {year_fn} FN。需将 year_conflict 按 '朝代/范围/引用/实体配错' 细分后再修复",
        })

    recommendations.sort(key=lambda x: x["priority"])

    for rec in recommendations:
        print(f"\n  P{rec['priority']} | {rec['action']}")
        print(f"     目标: {rec['target']}")
        print(f"     投入: {rec['effort']}")
        print(f"     {rec['detail']}")

    return recommendations


def main():
    detail = "--detail" in sys.argv

    fps, fns = load_errors()
    if not fps and not fns:
        return

    print(f"\n🔍 Error Bucket 分析")
    print(f"  FP: {len(fps)} | FN: {len(fns)} | 总计: {len(fps)+len(fns)}")

    summarize_root_cause(fps, "FP (误报)")
    summarize_root_cause(fns, "FN (漏报)")

    if detail:
        checker_root_cause_heatmap(fps, "FP")
        checker_root_cause_heatmap(fns, "FN")

    roi_recommendations(fps, fns)

    # 输出原始数据用于 CI
    summary = {
        "fp_count": len(fps),
        "fn_count": len(fns),
        "fp_root_causes": dict(Counter(r.get("root_cause","?") for r in fps)),
        "fn_root_causes": dict(Counter(r.get("root_cause","?") for r in fns)),
    }
    out_path = Path(__file__).parent / "error_summary.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n📄 摘要已保存: {out_path}")


if __name__ == "__main__":
    main()


def classify_error(rec: dict, sample: dict) -> str:
    """根据错误记录和原始样本推断根因类别"""
    verdict = rec.get("verdict", "")
    label = rec.get("label", "")
    claim = rec.get("claim", "")
    evidence = rec.get("evidence", "")
    checker = rec.get("checker", "")

    if isinstance(checker, list):
        checker_str = "+".join(checker[:2])
    else:
        checker_str = str(checker)

    if label == "TRUE" and verdict == "contradicted":  # FP
        # 检查证据是否为空或 claim 不在 KB 中
        if not evidence or evidence == claim:
            return "kb_overmatch"
        if "year" in checker_str.lower() and ("entity" in checker_str.lower() or "mismatch" in checker_str.lower()):
            return "year_entity_mismatch"
        if "year" in checker_str.lower():
            return "year_conflict_fp"
        if "negation" in checker_str.lower():
            return "negation_mismatch"
        if "entity" in checker_str.lower() or "mismatch" in checker_str.lower():
            return "entity_mismatch"
        if any(w in claim for w in ["在", "之前", "之后", "当时", "曾经"]):
            return "narrative_context"
        return "kb_overmatch"

    elif label == "FALSE" and verdict != "contradicted":  # FN
        if not evidence or evidence == claim:
            return "kb_no_cover"
        if "year" in checker_str.lower():
            return "year_miss"
        if verdict == "verified":
            return "verified_false"
        return "entity_miss"

    return "unknown"


def classify_and_save(errors: list, samples: list):
    """分类错误并保存到 error_analysis.jsonl"""
    import json
    from pathlib import Path

    out_path = Path(__file__).parent / "error_analysis.jsonl"
    sample_map = {s.get("id", ""): s for s in samples}

    with open(out_path, "w") as f:
        for rec in errors:
            sample = sample_map.get(rec.get("id", ""), {})
            rec["root_cause"] = classify_error(rec, sample)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 统计
    from collections import Counter
    fps = [r for r in errors if r.get("error_type") == "FP" or r.get("type") == "FP"]
    fns = [r for r in errors if r.get("error_type") == "FN" or r.get("type") == "FN"]
    print(f"\n  📊 错误已分类: FP={len(fps)}, FN={len(fns)} → {out_path}")
