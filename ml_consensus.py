#!/usr/bin/env python3
"""
③ Logistic Regression 共识引擎 — 纯标准库实现

替代手写权重，从反馈数据中学习最优检查器权重
用 mini-batch 梯度下降训练逻辑回归模型
"""

import json
import math
import random
from pathlib import Path
from typing import Optional


class LogisticConsensus:
    """
    逻辑回归共识模型

    特征: 每个检查器的 verdict × confidence
    标签: 用户反馈 (1=同意矛盾检测, 0=不同意)

    训练后 predict() 输出 hallucination_probability (0~1)
    """

    def __init__(self, feature_names: list[str] = None):
        self.feature_names = feature_names or [
            "_check_infinity", "_check_negation", "_check_year_conflict",
            "_check_numeric_conflict", "_check_temporal_order",
            "_check_location_conflict", "_check_overlap",
            "_check_graph_contradiction",
        ]
        n = len(self.feature_names)
        self.weights = [0.0] * n
        self.bias = 0.0
        self._trained = False
        self._training_samples = 0

    def _sigmoid(self, z: float) -> float:
        """Sigmoid 激活"""
        if z > 20:
            return 1.0
        if z < -20:
            return 0.0
        return 1.0 / (1.0 + math.exp(-z))

    def _extract_features(self, checker_results: dict) -> list[float]:
        """从检查器结果提取特征向量"""
        features = []
        for name in self.feature_names:
            r = checker_results.get(name, {})
            verdict = r.get("verdict", "uncertain")
            conf = r.get("confidence", 0.0)
            if verdict == "contradicted":
                features.append(conf)
            elif verdict == "verified":
                features.append(-conf * 0.5)
            else:
                features.append(0.0)
        return features

    def predict(self, checker_results: dict) -> float:
        """预测幻觉概率 (0~1)"""
        x = self._extract_features(checker_results)
        z = self.bias
        for w, xi in zip(self.weights, x):
            z += w * xi
        return round(self._sigmoid(z), 4)

    def train(self, samples: list[dict], learning_rate: float = 0.05,
              epochs: int = 50, verbose: bool = False) -> dict:
        """
        mini-batch 梯度下降训练

        samples: [{"features": {...checker_results...}, "label": 1|0}, ...]
        label: 1=用户同意矛盾检测, 0=用户不同意

        返回: {epochs, final_loss, samples}
        """
        n = len(samples)
        if n == 0:
            return {"epochs": 0, "final_loss": 0, "samples": 0}

        # 打乱
        shuffled = samples[:]
        random.shuffle(shuffled)

        final_loss = 0.0
        for epoch in range(epochs):
            total_loss = 0.0
            for sample in shuffled:
                x = self._extract_features(sample.get("features", {}))
                y = sample.get("label", 0)

                # 前向
                z = self.bias
                for w, xi in zip(self.weights, x):
                    z += w * xi
                y_pred = self._sigmoid(z)

                # 损失 (binary cross-entropy)
                eps = 1e-10
                loss = -(y * math.log(y_pred + eps) + (1 - y) * math.log(1 - y_pred + eps))
                total_loss += loss

                # 梯度下降
                error = y_pred - y
                for i in range(len(self.weights)):
                    self.weights[i] -= learning_rate * error * x[i]
                self.bias -= learning_rate * error

            avg_loss = total_loss / n
            final_loss = avg_loss

            if verbose and epoch % 10 == 0:
                print(f"  epoch {epoch}: loss={avg_loss:.4f}")

        self._trained = True
        self._training_samples = n

        return {
            "epochs": epochs,
            "final_loss": round(final_loss, 4),
            "samples": n,
            "weights": {name: round(w, 4) for name, w in zip(self.feature_names, self.weights)},
            "bias": round(self.bias, 4),
        }

    def save(self, path: str = "consensus_model.json"):
        with open(path, "w") as f:
            json.dump({
                "feature_names": self.feature_names,
                "weights": self.weights,
                "bias": self.bias,
                "trained": self._trained,
                "training_samples": self._training_samples,
            }, f, ensure_ascii=False, indent=2)
        return path

    def load(self, path: str = "consensus_model.json") -> bool:
        p = Path(path)
        if not p.exists():
            return False
        with open(p) as f:
            data = json.load(f)
        self.feature_names = data["feature_names"]
        self.weights = data["weights"]
        self.bias = data["bias"]
        self._trained = data.get("trained", True)
        self._training_samples = data.get("training_samples", 0)
        return True

    @property
    def is_trained(self) -> bool:
        return self._trained


# ── 反馈 → 训练样本转换 ──────────────────────────

def feedback_to_samples(feedback_rows: list[dict],
                        feature_extractor=None) -> list[dict]:
    """
    将用户反馈转换为训练样本

    约定:
      - agree → label=1 (用户同意检测结果)
      - disagree → label=0 (用户不同意检测结果)
    """
    samples = []
    for row in feedback_rows:
        label = 1 if row.get("user_verdict") == "agree" else 0
        # 这里需要从存储的特征构建，演示用随机特征
        samples.append({
            "claim": row.get("claim", ""),
            "label": label,
            "features": {},
        })
    return samples


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=== Logistic Regression 共识 演示 ===\n")

    model = LogisticConsensus()

    # 模拟训练数据：10 个样本
    samples = [
        {"features": {"_check_negation": {"verdict":"contradicted","confidence":0.9}}, "label": 1},
        {"features": {"_check_negation": {"verdict":"contradicted","confidence":0.85}}, "label": 1},
        {"features": {"_check_graph_contradiction": {"verdict":"contradicted","confidence":0.8}}, "label": 1},
        {"features": {"_check_overlap": {"verdict":"contradicted","confidence":0.55}}, "label": 0},
        {"features": {"_check_year_conflict": {"verdict":"contradicted","confidence":0.9}}, "label": 1},
        {"features": {"_check_overlap": {"verdict":"contradicted","confidence":0.45}}, "label": 0},
        {"features": {}, "label": 0},
        {"features": {"_check_infinity": {"verdict":"contradicted","confidence":0.7}}, "label": 1},
        {"features": {"_check_location_conflict": {"verdict":"contradicted","confidence":0.88}}, "label": 1},
        {"features": {"_check_overlap": {"verdict":"contradicted","confidence":0.5}}, "label": 0},
    ]

    result = model.train(samples, epochs=30, verbose=True)
    print(f"\n训练完成: {result['samples']} 样本")
    print(f"权重: {result['weights']}")
    print(f"偏差: {result['bias']}")

    # 预测
    test = {"_check_negation": {"verdict": "contradicted", "confidence": 0.9},
            "_check_graph_contradiction": {"verdict": "contradicted", "confidence": 0.8}}
    prob = model.predict(test)
    print(f"\n预测: {prob:.0%} 幻觉概率")
