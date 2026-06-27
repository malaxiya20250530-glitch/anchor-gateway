"""共识投票模块 — 替换简单责任链聚合

提供三种投票策略:
  1. majority  — 多数决：最多检查器支持的裁决
  2. weighted  — 加权投票：Σ(w × c × 裁决分值) / Σ(w)
  3. borda     — Borda计数：按置信度排名聚合

从 v5.9 多智能体共识机制和 v5.5 consensus/society.py 提取
"""
import math
from typing import List, Tuple, Dict, Optional
from enum import Enum


class VoteMode(Enum):
    MAJORITY = "majority"
    WEIGHTED = "weighted"
    BORDA = "borda"


# 裁决 → 数值映射
VERDICT_SCORE = {
    "verified": 1.0,
    "uncertain": 0.5,
    "unverifiable": -0.2,
    "contradicted": 0.0,
}

# 反向映射（用于多数决）
SCORE_TO_VERDICT = {1.0: "verified", 0.5: "uncertain", 0.0: "contradicted"}


class ConsensusVoter:
    """共识投票器 — 多策略聚合检查器结果

    输入: [(checker_name, verdict, confidence, weight), ...]
    输出: (final_verdict, final_confidence, vote_details)
    """

    def __init__(self, mode: VoteMode = VoteMode.WEIGHTED,
                 contradiction_threshold: float = 0.55,
                 min_voters: int = 2):
        """
        Args:
            mode: 投票模式
            contradiction_threshold: 加权分数低于此值视为矛盾
            min_voters: 最低投票人数（低于此值退回默认）
        """
        self.mode = mode
        self.contradiction_threshold = contradiction_threshold
        self.min_voters = min_voters

    def vote(self, results: List[Tuple[str, str, float, float, float]]
             ) -> Tuple[str, float, dict]:
        """执行共识投票

        Args:
            results: [(name, verdict, confidence, weight, weighted_score), ...]

        Returns:
            (verdict, confidence, vote_details)
        """
        if len(results) < self.min_voters:
            return ("uncertain", 0.5, {"reason": "insufficient_voters"})

        if self.mode == VoteMode.MAJORITY:
            return self._majority_vote(results)
        elif self.mode == VoteMode.BORDA:
            return self._borda_vote(results)
        else:
            return self._weighted_vote(results)

    def _majority_vote(self, results) -> Tuple[str, float, dict]:
        """多数决：各检查器一票，权重作平局打破

        每检查器投 1 票给其裁决方向：
        - verified → +1
        - contradicted → -1
        - uncertain → 0
        """
        votes = {"verified": 0.0, "uncertain": 0.0,
                 "unverifiable": 0.0, "contradicted": 0.0}
        total_weight = 0.0
        details = []

        for name, verdict, confidence, weight, ws in results:
            vote_weight = weight
            votes[verdict] += vote_weight
            total_weight += vote_weight
            details.append({
                "checker": name, "vote": verdict,
                "confidence": round(confidence, 3), "weight": round(weight, 3),
            })

        # 找票数最多的裁决
        best_verdict = max(votes, key=votes.get)
        winning_votes = votes[best_verdict]
        confidence = winning_votes / max(total_weight, 0.001)

        # 如果 unverifiable 票数占优，优先采用
        if votes.get("unverifiable", 0) > votes.get(best_verdict, 0) * 1.5:
            best_verdict = "unverifiable"
            confidence = votes["unverifiable"] / max(total_weight, 0.001)
        # 如果最高票不超过半数且存在矛盾，降级为 uncertain
        elif confidence < 0.5 and votes.get("contradicted", 0) > 0:
            best_verdict = "uncertain"
            confidence = 0.5

        return (best_verdict, min(1.0, confidence), {
            "mode": "majority",
            "votes": votes,
            "details": details,
            "total_weight": round(total_weight, 3),
        })

    def _weighted_vote(self, results) -> Tuple[str, float, dict]:
        """加权投票：最高加权分优先 + 平均分数作为置信度校准

        保留原逻辑的 max-score-first，同时计算加权平均作为校准信号
        """
        total_weighted_score = 0.0
        total_weight = 0.0
        details = []
        max_ws = -1
        max_result = None

        for name, verdict, confidence, weight, ws in results:
            score = VERDICT_SCORE.get(verdict, 0.5)
            effective_weight = weight * confidence
            total_weighted_score += effective_weight * score
            total_weight += effective_weight
            details.append({
                "checker": name, "verdict": verdict,
                "confidence": round(confidence, 3), "weight": round(weight, 3),
                "effective": round(effective_weight, 4),
            })
            if ws > max_ws:
                max_ws = ws
                max_result = (verdict, confidence, weight)

        if max_result is None:
            return ("uncertain", 0.5, {"mode": "weighted", "reason": "no_results"})

        avg_score = total_weighted_score / max(total_weight, 0.001)

        # 最高加权分裁决（与原逻辑一致）
        verdict, confidence, weight = max_result

        # 如果最高分是 contradicted 且平均值偏中性 → 降级
        if verdict == "contradicted" and avg_score > 0.4:
            verdict = "uncertain"
            confidence = 0.5
        # 如果最高分是 unverifiable → 直接采用
        elif verdict == "unverifiable":
            confidence = confidence

        return (verdict, round(min(1.0, confidence), 3), {
            "mode": "weighted",
            "avg_score": round(avg_score, 4),
            "max_weighted_score": round(max_ws, 3),
            "details": details,
            "total_weight": round(total_weight, 3),
        })

    def _borda_vote(self, results) -> Tuple[str, float, dict]:
        """Borda 计数：按置信度排序，名次越高得分越高

        每个检查器根据其置信度排名获得 Borda 分
        - 第 1 名得 n 分，第 n 名得 1 分
        - 按裁决分组求和
        """
        n = len(results)
        if n == 0:
            return ("uncertain", 0.5, {"mode": "borda", "reason": "no_results"})

        # 按 (confidence × weight) 排序
        sorted_results = sorted(results, key=lambda r: r[2] * r[3], reverse=True)

        scores = {"verified": 0.0, "uncertain": 0.0,
                  "unverifiable": 0.0, "contradicted": 0.0}
        max_possible = n * (n + 1) / 2  # Borda 总分
        details = []

        for rank, (name, verdict, confidence, weight, ws) in enumerate(sorted_results):
            borda_points = n - rank  # 第1名=n分，最后1名=1分
            scores[verdict] += borda_points
            details.append({
                "checker": name, "verdict": verdict, "rank": rank + 1,
                "confidence": round(confidence, 3), "borda": borda_points,
            })

        best = max(scores, key=scores.get)
        confidence = scores[best] / max_possible

        return (best, round(min(1.0, confidence), 3), {
            "mode": "borda",
            "scores": scores,
            "details": details,
            "max_possible": max_possible,
        })

    def compare_modes(self, results) -> Dict[str, Tuple[str, float]]:
        """调试用：同时运行三种模式，返回对比结果"""
        original_mode = self.mode
        outcomes = {}

        for mode in VoteMode:
            self.mode = mode
            verdict, conf, _ = self.vote(results)
            outcomes[mode.value] = (verdict, round(conf, 3))

        self.mode = original_mode
        return outcomes
