#!/usr/bin/env python3
"""
⑤⑥ 自动知识库更新 + 在线学习

⑤ 从已验证的用户纠错自动生成 KB 条目
⑥ 增量更新 Logistic Regression 共识模型权重
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Optional

from feedback_collector import FeedbackCollector
from ml_consensus import LogisticConsensus


class AutoKBUpdater:
    """
    自动知识库更新器

    流程:
      用户提交 correction → 验证（多人同意/管理员审核）
      → 自动追加到 KNOWLEDGE_BASE → 重建图谱
    """

    def __init__(self, min_agreement: int = 2):
        """
        min_agreement: 同一纠错被不同用户提交多少次后才自动采纳
        """
        self.min_agreement = min_agreement
        self.feedback = FeedbackCollector()
        self._pending_path = Path(__file__).parent / "kb_pending.json"
        self._applied_path = Path(__file__).parent / "kb_applied.json"

    def collect_corrections(self) -> list[dict]:
        """收集待审核的纠错建议"""
        corrections = self.feedback.get_corrections(limit=100)
        # 按 claim 聚合
        grouped = {}
        for c in corrections:
            claim = c["claim"]
            if claim not in grouped:
                grouped[claim] = {"claim": claim, "count": 0, "corrections": []}
            grouped[claim]["count"] += 1
            grouped[claim]["corrections"].append(c["correction"])

        # 筛选达到最小同意数的
        approved = [g for g in grouped.values() if g["count"] >= self.min_agreement]
        return approved

    def apply_correction(self, claim: str, correction: str, source: str = "user_feedback"):
        """应用一条纠错到 KNOWLEDGE_BASE"""
        from hallucination_detector import KNOWLEDGE_BASE

        # 生成键名（取 claim 前4字）
        key = claim[:4].strip("，。的了一是")

        if key in KNOWLEDGE_BASE:
            # 追加 fact
            if correction not in KNOWLEDGE_BASE[key].get("facts", []):
                KNOWLEDGE_BASE[key]["facts"].append(correction)
        else:
            KNOWLEDGE_BASE[key] = {
                "facts": [correction],
                "source": source,
            }

        # 记录已应用
        self._record_applied(claim, correction, key)
        return key

    def _record_applied(self, claim: str, correction: str, key: str):
        applied = []
        if self._applied_path.exists():
            applied = json.loads(self._applied_path.read_text())
        applied.append({
            "claim": claim,
            "correction": correction,
            "key": key,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        self._applied_path.write_text(json.dumps(applied, ensure_ascii=False, indent=2))

    def auto_update(self) -> dict:
        """自动执行一轮更新"""
        approved = self.collect_corrections()
        applied = []
        for item in approved:
            best = max(set(item["corrections"]), key=item["corrections"].count)
            key = self.apply_correction(item["claim"], best)
            applied.append({"claim": item["claim"], "key": key, "count": item["count"]})

        # 清除图谱缓存
        try:
            import knowledge_graph
            knowledge_graph._graph_instance = None
            knowledge_graph._reasoner_instance = None
        except ImportError:
            pass

        return {"applied": len(applied), "details": applied}


class OnlineLearner:
    """
    ⑥ 在线学习引擎

    每收到一条用户反馈 → 增量更新共识模型
    使用随机梯度下降 (SGD) 单样本更新
    """

    def __init__(self, model_path: str = "consensus_model.json"):
        self.model = LogisticConsensus()
        self.model_path = model_path
        self._loaded = self.model.load(model_path)
        self._update_count = 0

    def learn_from_feedback(self, checker_results: dict,
                            user_agreed: bool) -> float:
        """
        单样本在线学习

        checker_results: 检查器的特征向量
        user_agreed: True=用户同意检测, False=不同意
        返回更新后的 loss
        """
        label = 1 if user_agreed else 0
        result = self.model.train(
            [{"features": checker_results, "label": label}],
            learning_rate=0.01,  # 小学习率防止震荡
            epochs=1,
        )
        self._update_count += 1

        # 每 10 次更新保存一次模型
        if self._update_count % 10 == 0:
            self.model.save(self.model_path)

        return result["final_loss"]

    def learn_batch(self, feedback_batch: list[dict]):
        """批量在线学习"""
        samples = []
        for fb in feedback_batch:
            label = 1 if fb.get("user_verdict") == "agree" else 0
            samples.append({
                "features": fb.get("checker_results", {}),
                "label": label,
            })
        if samples:
            self.model.train(samples, learning_rate=0.02, epochs=5)
            self.model.save(self.model_path)

    @property
    def update_count(self) -> int:
        return self._update_count

    @property
    def is_trained(self) -> bool:
        return self.model.is_trained or self._loaded


# ── 飞轮集成 ──────────────────────────────────────

class DataFlywheel:
    """
    完整数据飞轮：反馈 → 学习 → 更新

    用法:
      flywheel = DataFlywheel()
      flywheel.on_feedback(claim, checker_results, user_agreed, correction)
    """

    def __init__(self):
        self.learner = OnlineLearner()
        self.updater = AutoKBUpdater(min_agreement=2)

    def on_feedback(self, claim: str, checker_results: dict,
                    user_agreed: bool, correction: str = "") -> dict:
        """
        处理一条用户反馈，驱动整个飞轮

        返回: {model_updated, kb_updated, loss}
        """
        result = {"model_updated": False, "kb_updated": False}

        # ① 记录反馈
        verdict = "agree" if user_agreed else "disagree"
        self.updater.feedback.submit(
            claim=claim,
            detected_verdict="contradicted",
            user_verdict=verdict,
            correction=correction,
        )

        # ⑥ 在线学习
        loss = self.learner.learn_from_feedback(checker_results, user_agreed)
        result["model_updated"] = True
        result["loss"] = round(loss, 4)
        result["updates"] = self.learner.update_count

        # ⑤ 如果提供了纠错且有多人同意，自动更新 KB
        if correction and not user_agreed:
            approved = self.updater.collect_corrections()
            for item in approved:
                if item["claim"] == claim:
                    self.updater.apply_correction(claim, correction)
                    result["kb_updated"] = True
                    break

        return result


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=== 数据飞轮 演示 ===\n")

    flywheel = DataFlywheel()

    # 模拟 5 条用户反馈
    for i in range(5):
        agreed = (i < 3)  # 前3条同意，后2条不同意
        r = flywheel.on_feedback(
            claim=f"测试断言{i}",
            checker_results={"_check_negation": {"verdict": "contradicted", "confidence": 0.8 + i*0.02}},
            user_agreed=agreed,
            correction="正确答案是XXX" if not agreed else "",
        )
        print(f"  反馈{i+1}: model={'✅' if r['model_updated'] else '❌'} "
              f"loss={r.get('loss',0):.4f} updates={r.get('updates',0)}")

    print(f"\n在线学习: {flywheel.learner.update_count} 次更新")
    print(f"模型已训练: {flywheel.learner.is_trained}")

    # 自动KB
    results = flywheel.updater.auto_update()
    print(f"自动KB更新: {results['applied']} 条")
