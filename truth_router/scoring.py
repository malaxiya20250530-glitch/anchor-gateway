#!/usr/bin/env python3
"""评分模块 — 简单加权可信度评分，不做复杂模型

公式:
    truth_score = retrieval_score * 0.4 + citation_score * 0.3 + consistency_score * 0.3

子分数计算:
    retrieval_score: 检索结果数量/质量（命中实体数 / 期望数）
    citation_score: 事实来源可信度均值
    consistency_score: 多条事实的判决一致性
"""
import sys, json


def _retrieval_score(retrieval_result: dict) -> float:
    """检索质量分：基于实体命中数和事实条数"""
    entities = retrieval_result.get("entities", [])
    facts = retrieval_result.get("facts", [])
    source = retrieval_result.get("source", "none")

    # 来源权重
    source_weight = {"entity_map": 1.0, "fts": 0.6, "none": 0.0}

    # 实体命中分
    entity_score = min(len(entities) / 3.0, 1.0) if entities else 0.0

    # 事实数量分
    fact_score = min(len(facts) / 5.0, 1.0) if facts else 0.0

    # 综合
    base = (entity_score * 0.5 + fact_score * 0.5)
    return round(base * source_weight.get(source, 0.5), 4)


def _citation_score(retrieval_result: dict) -> float:
    """引用可信度分：检索事实的平均置信度"""
    facts = retrieval_result.get("facts", [])
    if not facts:
        return 0.0

    confidences = [f.get("confidence", 0.5) for f in facts]
    return round(sum(confidences) / len(confidences), 4)


def _consistency_score(fact_check_result: dict) -> float:
    """一致性分：多条事实校验结果的判决一致程度"""
    checks = fact_check_result.get("checks", [])
    if not checks:
        return 0.5  # 无数据时中性

    verdicts = [c["verdict"] for c in checks]

    # 全部一致 → 高分
    unique = set(verdicts)
    if len(unique) == 1:
        return 0.9
    elif len(unique) == len(verdicts):
        return 0.3  # 全部不一致
    else:
        # 多数一致
        from collections import Counter
        majority = max(Counter(verdicts).values())
        return round(0.3 + 0.6 * (majority / len(verdicts)), 4)


def compute_truth_score(retrieval_result: dict, fact_check_result: dict) -> dict:
    """计算综合可信度分数

    参数:
        retrieval_result: retrieval.retrieve() 的返回值
        fact_check_result: fact_check.check_claim() 的返回值
    返回:
        {
            "truth_score": float,   # 综合可信度 0.0~1.0
            "retrieval": float,     # 检索分
            "citation": float,      # 引用分
            "consistency": float,   # 一致性分
            "verdict": str,         # 最终判决
        }
    """
    retrieval = _retrieval_score(retrieval_result)
    citation = _citation_score(retrieval_result)
    consistency = _consistency_score(fact_check_result)

    truth_score = round(
        retrieval * 0.4 + citation * 0.3 + consistency * 0.3, 4
    )

    # 基于分数映射判决
    if truth_score >= 0.75:
        verdict = "verified"
    elif truth_score >= 0.4:
        verdict = "uncertain"
    else:
        verdict = "contradicted"

    return {
        "truth_score": truth_score,
        "retrieval": retrieval,
        "citation": citation,
        "consistency": consistency,
        "verdict": verdict,
    }


def main() -> None:
    """测试模式：使用模拟数据"""
    mock_retrieval = {
        "entities": ["朱元璋", "火锅"],
        "facts": [
            {"fact": "火锅起源于重庆", "source": "饮食文化", "confidence": 0.85},
            {"fact": "朱元璋是明朝开国皇帝", "source": "历史", "confidence": 0.95},
        ],
        "source": "entity_map",
    }
    mock_fact_check = {
        "checks": [
            {"verdict": "contradicted", "confidence": 0.88},
            {"verdict": "verified", "confidence": 0.92},
        ]
    }

    score = compute_truth_score(mock_retrieval, mock_fact_check)
    print(json.dumps(score, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
