#!/usr/bin/env python3
"""
共识引擎 — 多检查器加权投票（替代简单责任链）
每个检查器独立投票 → 权重复合 → 最终幻觉概率得分 (0~100%)
"""

from collections import Counter
from typing import Optional


# ── 检查器权重配置 ──────────────────────────────

# 基于各检查器的可靠性分配权重
# 图谱推理最可靠（结构化知识），模式匹配次之，模糊匹配再次之
CHECKER_WEIGHTS = {
    "_check_infinity":            0.85,   # 绝对化检测 → 高可靠
    "_check_negation":            0.80,   # 否定模式 → 高可靠
    "_check_year_conflict":       0.90,   # 年份冲突 → 极高可靠（数值精确）
    "_check_numeric_conflict":    0.90,   # 数值偏差 → 极高可靠
    "_check_temporal_order":      0.80,   # 时序逻辑 → 高可靠
    "_check_location_conflict":   0.85,   # 地点矛盾 → 高可靠
    "_check_overlap":             0.55,   # 字符重叠 → 中等可靠（可能误报）
    "_check_graph_contradiction": 0.75,   # 图谱推理 → 中高可靠
    "semantic_match":             0.50,   # 语义回退 → 中等可靠
    "fuzzy_match":                0.45,   # 模糊匹配 → 较低可靠
    "web_verify":                 0.60,   # 联网验证 → 中等可靠（网络不稳定）
}


class ConsensusEngine:
    """
    多检查器加权投票引擎

    流程:
      1. 所有检查器独立运行 → 收集 (verdict, confidence) 投票
      2. 按权重计算 hallucination_score (0~1)
      3. 输出最终 verdict + 投票明细

    hallucination_score = Σ(w_i × v_i) / Σ(w_i)
    其中 v_i = confidence (contradicted) / 0 (verified) / 0.5×confidence (uncertain)
    """

    def __init__(self, checker_results: list[dict] = None,
                 weights: dict = None):
        """
        checker_results: [{"checker": "_check_infinity", "verdict": "contradicted",
                           "confidence": 0.85, "evidence": "..."}, ...]
        """
        self.weights = weights or CHECKER_WEIGHTS
        self.votes: list[dict] = checker_results or []

    def add_vote(self, checker: str, verdict: str, confidence: float,
                 evidence: str = ""):
        """添加一个检查器的投票"""
        self.votes.append({
            "checker": checker,
            "verdict": verdict,
            "confidence": round(confidence, 3),
            "evidence": evidence[:200],
            "weight": self.weights.get(checker, 0.5),
        })

    def compute(self) -> dict:
        """
        计算加权共识

        返回:
          {hallucination_score, verdict, confidence, votes, breakdown}
        """
        if not self.votes:
            return {
                "hallucination_score": 0.0,
                "verdict": "unverifiable",
                "confidence": 0.0,
                "votes": [],
                "breakdown": {"contradicted": 0, "verified": 0, "uncertain": 0},
            }

        total_weight = 0.0
        weighted_sum = 0.0
        breakdown = Counter()

        for v in self.votes:
            w = v["weight"]
            total_weight += w
            breakdown[v["verdict"]] += 1

            if v["verdict"] == "contradicted":
                weighted_sum += w * v["confidence"]
            elif v["verdict"] == "verified":
                weighted_sum -= w * v["confidence"] * 0.5  # 减分
            # uncertain 不贡献

        hallucination_score = max(0.0, min(1.0,
            weighted_sum / max(total_weight, 1.0)
        ))

        # 判定最终 verdict
        contradicted_votes = breakdown.get("contradicted", 0)
        verified_votes = breakdown.get("verified", 0)
        total_votes = sum(breakdown.values())

        if hallucination_score > 0.6:
            verdict = "contradicted"
            confidence = hallucination_score
        elif hallucination_score > 0.3:
            verdict = "likely_contradicted"
            confidence = hallucination_score
        elif hallucination_score > 0.1:
            verdict = "uncertain"
            confidence = hallucination_score
        elif verified_votes > contradicted_votes:
            verdict = "verified"
            confidence = 1.0 - hallucination_score
        else:
            verdict = "unverifiable"
            confidence = 0.3

        return {
            "hallucination_score": round(hallucination_score, 3),
            "verdict": verdict,
            "confidence": round(confidence, 3),
            "total_votes": total_votes,
            "breakdown": dict(breakdown),
            "top_evidence": self._top_evidence(),
            "votes": self.votes,
        }

    def _top_evidence(self) -> list[str]:
        """提取最高置信度的矛盾证据（最多3条）"""
        contradicted = [v for v in self.votes if v["verdict"] == "contradicted"]
        contradicted.sort(key=lambda x: x["weight"] * x["confidence"], reverse=True)
        return [v["evidence"][:100] for v in contradicted[:3]]


# ── 便捷集成 ──────────────────────────────────────

def consensus_from_compare_results(compare_results: list[tuple]) -> dict:
    """
    从 _compare_with_fact 的输出构建共识

    compare_results: [(verdict_str, confidence_float), ...]
    """
    engine = ConsensusEngine()
    for verdict, confidence in compare_results:
        # 推断检查器名称
        engine.add_vote(
            checker="combined",
            verdict=verdict,
            confidence=confidence,
        )
    return engine.compute()


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=== 共识引擎 演示 ===\n")

    # 场景1: 多检查器一致认为矛盾
    engine = ConsensusEngine()
    engine.add_vote("_check_negation", "contradicted", 0.85, "否定模式匹配")
    engine.add_vote("_check_year_conflict", "contradicted", 0.90, "年份冲突: 1328 vs 战国")
    engine.add_vote("_check_graph_contradiction", "contradicted", 0.75, "图谱推理: 朱元璋≠火锅发明者")
    engine.add_vote("_check_overlap", "uncertain", 0.40, "部分重叠")

    result = engine.compute()
    print(f"场景1: 多源一致矛盾")
    print(f"  幻觉得分: {result['hallucination_score']:.0%}")
    print(f"  verdict: {result['verdict']} ({result['confidence']:.0%})")
    print(f"  投票: {result['breakdown']}")
    print(f"  证据: {result['top_evidence']}")

    print()

    # 场景2: 检查器分歧（有矛盾的，也有验证通过的）
    engine2 = ConsensusEngine()
    engine2.add_vote("_check_negation", "contradicted", 0.65, "疑似否定冲突")
    engine2.add_vote("_check_year_conflict", "verified", 0.80, "年份核对一致")
    engine2.add_vote("semantic_match", "verified", 0.70, "语义匹配确认")

    result2 = engine2.compute()
    print(f"场景2: 检查器分歧")
    print(f"  幻觉得分: {result2['hallucination_score']:.0%}")
    print(f"  verdict: {result2['verdict']} ({result2['confidence']:.0%})")
    print(f"  投票: {result2['breakdown']}")
