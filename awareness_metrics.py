#!/usr/bin/env python3
"""
觉察度量引擎 — PI/SI 量化指标（预测加工框架）
PI (Prior Intensity):  先验强度 — LLM 生成该断言的自信度
SI (Sensory Precision): 感官精度 — 外部锚定对该断言的校验确信度

幻觉 = PI >> SI
"""

import math
from collections import Counter
from typing import Optional


def compute_pi(text: str, repetition_history: list = None) -> float:
    """
    计算先验强度 PI (0~1)

    因素:
      - 流畅性标记: 绝对化词/极端词数量
      - 重复模式: 在历史对话中反复出现的断言
      - 断言密度: 单位长度内的事实性声明数
    """
    score = 0.5  # 基线

    # 1. 绝对化惩罚：越绝对，PI 越高（模型越自信）
    absolutist = ["绝对", "一定", "从来", "永远", "毫无疑问",
                  "所有人", "没有人", "完全", "必然", "毫无疑问"]
    abs_count = sum(1 for w in absolutist if w in text)
    score += min(abs_count * 0.08, 0.3)

    # 2. 断言密度：事实性动词越多，PI 越高
    factual_verbs = ["是", "发明", "创建", "证明", "发现", "位于", "属于",
                     "成为", "具有", "作为", "由", "在"]
    density = sum(1 for v in factual_verbs if v in text) / max(len(text), 1)
    score += min(density * 15, 0.15)

    # 3. 历史重复：同一断言被生成过
    if repetition_history:
        text_ngrams = {text[i:i+3] for i in range(len(text)-2)}
        hist_match = 0
        for hist_text in repetition_history[-5:]:
            hist_ngrams = {hist_text[i:i+3] for i in range(len(hist_text)-2)}
            hist_match += len(text_ngrams & hist_ngrams) / max(len(text_ngrams), 1)
        avg_repeat = hist_match / max(len(repetition_history[-5:]), 1)
        score += min(avg_repeat * 0.15, 0.15)

    return round(min(score, 1.0), 3)


def compute_si(verification_results: list[dict]) -> float:
    """
    计算感官精度 SI (0~1)

    因素:
      - 检查器命中率
      - 最高置信度
      - 多源一致性
    """
    if not verification_results:
        return 0.0

    scores = []
    for r in verification_results:
        verdict = r.get("verdict", "uncertain")
        confidence = r.get("confidence", 0.0)

        if verdict == "contradicted":
            scores.append(confidence)
        elif verdict == "verified":
            scores.append(confidence * 0.5)
        else:
            scores.append(confidence * 0.1)

    if not scores:
        return 0.0

    # 多源一致性加权
    avg_conf = sum(scores) / len(scores)
    max_conf = max(scores)
    diversity = len(set(r.get("source", "") for r in verification_results))
    diversity_bonus = min(diversity * 0.05, 0.15)

    si = avg_conf * 0.6 + max_conf * 0.3 + diversity_bonus
    return round(min(si, 1.0), 3)


def compute_hallucination_index(pi: float, si: float) -> dict:
    """
    计算幻觉指数 HI = PI - SI

    HI > 0:  先验强度超过感官精度 → 疑似幻觉
    HI ≤ 0:  外部锚定确认或压制了模型自信 → 可信

    返回:
      {hi, level, interpretation, recommendation}
    """
    hi = round(pi - si, 3)

    if hi > 0.5:
        level = "critical"
        interp = "严重幻觉风险：模型极度自信但外部证据强烈矛盾"
        rec = "建议中断或强制纠正"
    elif hi > 0.25:
        level = "high"
        interp = "高幻觉风险：模型自信显著超过外部校验结果"
        rec = "建议标记并提示用户核实"
    elif hi > 0.05:
        level = "moderate"
        interp = "中度风险：模型自信略高于外部校验"
        rec = "可标记供后续审查"
    elif hi > -0.1:
        level = "low"
        interp = "低风险：模型自信与外部校验大致平衡"
        rec = "无需干预"
    else:
        level = "verified"
        interp = "可信：外部锚定确认或超出模型先验"
        rec = "通过"

    return {
        "hi": hi,
        "pi": pi,
        "si": si,
        "level": level,
        "interpretation": interp,
        "recommendation": rec,
    }


# ── 便捷函数 ──────────────────────────────────────

def assess_claim(claim: str, verification: dict,
                 history: list = None) -> dict:
    """
    一行评估一条断言的 PI/SI/HI

    用法:
      metrics = assess_claim("朱元璋发明了火锅", {"verdict":"contradicted","confidence":0.88})
      print(metrics["level"])  # "critical"
    """
    pi = compute_pi(claim, history)
    si = compute_si([verification])
    return compute_hallucination_index(pi, si)


def batch_assess(findings: list[dict], history: list = None) -> dict:
    """
    批量评估多条发现，返回汇总
    """
    if not findings:
        return {"hi_avg": 0, "level": "verified", "count": 0}

    results = []
    for f in findings:
        pi = compute_pi(f.get("claim", ""), history)
        si = compute_si([f])
        hi = compute_hallucination_index(pi, si)
        results.append(hi)

    avg_hi = sum(r["hi"] for r in results) / len(results)
    levels = Counter(r["level"] for r in results)

    if levels.get("critical", 0) > 0:
        overall = "critical"
    elif levels.get("high", 0) > 0:
        overall = "high"
    elif levels.get("moderate", 0) > len(results) // 2:
        overall = "moderate"
    else:
        overall = "low"

    return {
        "hi_avg": round(avg_hi, 3),
        "level": overall,
        "count": len(results),
        "breakdown": dict(levels),
        "details": results,
    }


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=== PI/SI 度量引擎 演示 ===\n")

    # 演示1: 高幻觉
    claim = "朱元璋绝对毫无疑问发明了火锅"
    verification = {"verdict": "contradicted", "confidence": 0.88, "source": "明史"}
    m = assess_claim(claim, verification)
    print(f"断言: {claim}")
    print(f"  PI={m['pi']}  SI={m['si']}  HI={m['hi']}")
    print(f"  等级: {m['level']} — {m['interpretation']}")
    print(f"  建议: {m['recommendation']}")

    print()

    # 演示2: 低幻觉
    claim = "Python 由 Guido van Rossum 于 1991 年发布"
    verification = {"verdict": "verified", "confidence": 0.9, "source": "Python.org"}
    m = assess_claim(claim, verification)
    print(f"断言: {claim}")
    print(f"  PI={m['pi']}  SI={m['si']}  HI={m['hi']}")
    print(f"  等级: {m['level']} — {m['interpretation']}")
