"""元权重学习器 — 从 v5.8 MetaEngine 提取的爬山法动态权重更新

集成到 hallucination_detector 的 Checker 权重系统：
- 追踪每个检查器的历史表现（命中率、准确率）
- 定期微调权重 → 观察整体准确率变化 → 择优保留
- 替代当前静态 F1 权重

用法:
  learner = MetaWeightLearner()
  learner.record(checker_name, verdict, is_correct)
  learner.learn_step()  # 定期调用，自动调整权重
"""
import math
import random
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class CheckerStats:
    """单个检查器的运行时统计"""
    name: str
    weight: float
    hit_count: int = 0          # 命中次数（返回了结果）
    correct_count: int = 0      # 正确次数
    false_positive: int = 0     # 误报（标为contradicted但实际正确）
    false_negative: int = 0     # 漏报（标为verified但实际错误）
    total_confidence: float = 0.0  # 累计置信度（用于计算平均）
    last_updated: float = 0.0

    @property
    def accuracy(self) -> float:
        """精准率：正确 / 命中"""
        return self.correct_count / max(1, self.hit_count)

    @property
    def avg_confidence(self) -> float:
        """平均置信度"""
        return self.total_confidence / max(1, self.hit_count)

    @property
    def f1_estimate(self) -> float:
        """运行时的 F1 近似"""
        precision = self.correct_count / max(1, self.correct_count + self.false_positive)
        recall = self.correct_count / max(1, self.correct_count + self.false_negative)
        if precision + recall < 0.001:
            return 0.0
        return 2 * precision * recall / (precision + recall)


class MetaWeightLearner:
    """元权重学习器 — 爬山法自适应调整检查器权重

    核心逻辑（从 v5.8 MetaEngine.learn_from_feedback 提取）:
      1. 记录每次检查结果
      2. 每 N 步，微调权重（±5%）
      3. 比较全局准确率 → 改善则保留，恶化则回退
    """

    def __init__(self, seed: int = 42, learn_every: int = 20,
                 perturbation_scale: float = 0.05):
        self.rng = random.Random(seed)
        self.learn_every = learn_every
        self.perturbation_scale = perturbation_scale
        self.step_count: int = 0
        self.stats: Dict[str, CheckerStats] = {}
        self._baseline_accuracy: float = 0.0
        self._last_weights: Dict[str, float] = {}
        self._accepted: int = 0
        self._rejected: int = 0

    def register_checker(self, name: str, initial_weight: float):
        """注册检查器"""
        self.stats[name] = CheckerStats(name=name, weight=initial_weight)

    def record(self, name: str, verdict: str, is_correct: bool,
               confidence: float = 0.0):
        """记录一次检查结果

        Args:
            name: 检查器名称
            verdict: 返回的裁决 (verified/contradicted/uncertain)
            is_correct: 该裁决是否正确
            confidence: 返回的置信度
        """
        if name not in self.stats:
            return
        s = self.stats[name]
        s.hit_count += 1
        s.total_confidence += confidence
        if is_correct:
            s.correct_count += 1
        elif verdict == "contradicted":
            s.false_positive += 1
        elif verdict == "verified":
            s.false_negative += 1

        self.step_count += 1

    def get_weight(self, name: str) -> float:
        """获取当前有效权重"""
        if name in self.stats:
            return self.stats[name].weight
        return 1.0

    def get_all_weights(self) -> Dict[str, float]:
        """获取全部当前权重"""
        return {name: s.weight for name, s in self.stats.items()}

    def global_accuracy(self) -> float:
        """全局准确率：所有检查器的正确数 / 总命中数"""
        total_hits = sum(s.hit_count for s in self.stats.values())
        if total_hits == 0:
            return 0.0
        total_correct = sum(s.correct_count for s in self.stats.values())
        return total_correct / total_hits

    def learn_step(self) -> dict:
        """执行一步元学习

        仅在 learn_every 步后执行，否则返回空结果
        """
        if self.step_count < self.learn_every:
            return {"action": "wait", "reason": f"need {self.learn_every} steps, have {self.step_count}"}

        baseline = self.global_accuracy()

        # 保存当前权重
        self._last_weights = self.get_all_weights()

        # 微调：选择 3 个检查器随机扰动
        candidates = [s for s in self.stats.values() if s.hit_count >= 3]
        if len(candidates) < 2:
            return {"action": "skip", "reason": "not enough data"}

        selected = self.rng.sample(candidates, min(3, len(candidates)))
        old_weights = {s.name: s.weight for s in selected}

        # 扰动权重
        for s in selected:
            delta = self.rng.uniform(-self.perturbation_scale,
                                     self.perturbation_scale)
            s.weight = max(0.2, min(1.0, s.weight + delta))

        # 模拟评估：用现有 F1 近似作为目标函数
        new_f1 = self._estimate_global_f1()

        # 决策
        improved = new_f1 > self._baseline_accuracy
        if improved:
            self._baseline_accuracy = new_f1
            self._accepted += 1
            action = "accepted"
            # 减少扰动尺度（精细调优）
            self.perturbation_scale = max(0.01, self.perturbation_scale * 0.95)
        else:
            # 回退
            for s in selected:
                s.weight = old_weights[s.name]
            self._rejected += 1
            action = "rejected"
            self.perturbation_scale = min(0.12, self.perturbation_scale * 1.05)

        self.step_count = 0  # 重置计数器

        return {
            "action": action,
            "baseline": round(baseline, 4),
            "new_f1": round(new_f1, 4),
            "perturbed": [s.name for s in selected],
            "weights": self.get_all_weights(),
            "scale": round(self.perturbation_scale, 4),
        }

    def _estimate_global_f1(self) -> float:
        """用加权 F1 估计全局表现"""
        total_weight = sum(s.weight for s in self.stats.values())
        if total_weight == 0:
            return 0.0
        weighted_f1 = sum(s.weight * s.f1_estimate
                         for s in self.stats.values()) / total_weight
        return weighted_f1

    def force_learn(self) -> dict:
        """强制执行一步学习（不等待 learn_every）"""
        saved = self.step_count
        self.step_count = self.learn_every
        result = self.learn_step()
        self.step_count = saved
        return result

    def stats_summary(self) -> dict:
        """返回学习状态摘要"""
        return {
            "total_steps": sum(s.hit_count for s in self.stats.values()),
            "global_accuracy": round(self.global_accuracy(), 4),
            "accepted": self._accepted,
            "rejected": self._rejected,
            "accept_rate": round(
                self._accepted / max(1, self._accepted + self._rejected), 3),
            "weights": self.get_all_weights(),
            "per_checker": {
                name: {
                    "weight": round(s.weight, 3),
                    "hits": s.hit_count,
                    "accuracy": round(s.accuracy, 3),
                    "f1_est": round(s.f1_estimate, 3),
                }
                for name, s in self.stats.items()
            }
        }
