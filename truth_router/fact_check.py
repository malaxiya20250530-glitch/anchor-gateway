#!/usr/bin/env python3
"""事实校验模块 — 封装 hallucination_detector 检查器链，对检索结果进行真相判定"""
import sys
from pathlib import Path

# 确保项目根在 path 中
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hallucination_detector import AnchorEngine


_engine: AnchorEngine = None


def get_engine() -> AnchorEngine:
    """获取全局 AnchorEngine 单例（延迟初始化）"""
    global _engine
    if _engine is None:
        _engine = AnchorEngine(enable_web=False)
    return _engine


def check_claim(claim: str, facts: list[dict]) -> dict:
    """对声明与多个事实逐一比对

    参数:
        claim: 用户声明（如 "朱元璋发明了火锅"）
        facts: 检索结果列表，每项含 fact/source/confidence
    返回:
        {
            "claim": str,
            "verdict": str,        # "verified"|"contradicted"|"uncertain"
            "confidence": float,   # 最高置信度
            "checks": [dict, ...], # 每条事实的校验明细
            "vote_details": dict,  # 检查器投票明细
        }
    """
    engine = get_engine()
    checks = []

    for f in facts:
        verdict, conf = engine._compare_with_fact(claim, f["fact"])
        checks.append({
            "fact": f["fact"],
            "source": f.get("source", ""),
            "verdict": verdict,
            "confidence": round(conf, 4),
        })

    # 汇总判决：取最有利结果
    if checks:
        # 优先级: verified > contradicted > uncertain
        verdict_order = {"verified": 3, "contradicted": 2, "uncertain": 1}
        best = max(checks, key=lambda c: (verdict_order.get(c["verdict"], 0), c["confidence"]))
        final_verdict = best["verdict"]
        final_confidence = best["confidence"]
    else:
        final_verdict = "uncertain"
        final_confidence = 0.5

    vote_details = engine.get_vote_details()

    return {
        "claim": claim,
        "verdict": final_verdict,
        "confidence": final_confidence,
        "checks": checks,
        "vote_details": vote_details,
    }


def check_single(claim: str, fact: str) -> tuple:
    """单条声明 vs 单事实校验（薄封装）"""
    engine = get_engine()
    return engine._compare_with_fact(claim, fact)


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python3 fact_check.py <声明> <事实>")
        print("示例: python3 fact_check.py '朱元璋发明了火锅' '火锅起源于重庆'")
        sys.exit(1)

    claim = sys.argv[1]
    fact = sys.argv[2]

    result = check_claim(claim, [{"fact": fact, "source": "cli"}])
    print(f"声明: {result['claim']}")
    print(f"判决: {result['verdict']}")
    print(f"置信度: {result['confidence']}")
    if result["checks"]:
        c = result["checks"][0]
        print(f"  vs '{c['fact'][:60]}' → {c['verdict']} ({c['confidence']})")


if __name__ == "__main__":
    main()
