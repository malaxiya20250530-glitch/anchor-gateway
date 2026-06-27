#!/usr/bin/env python3
"""
test_graph_checker.py — GraphContradictionChecker 集成测试
需要 AnchorEngine(enable_graph=True) 提供图谱推理上下文。

使用方法:
  python3 test_graph_checker.py
"""

import sys
import hallucination_detector as hd

# 清除知识图谱缓存（确保使用最新修复后的图谱数据）
import knowledge_graph as kg
kg.clear_cache()

TEST_CASES = [
    ("朱元璋发明了火锅",             "contradicted",  "时间冲突: 朱元璋(1328-1398) vs 战国火锅"),
    ("秦始皇发明了造纸术",           "contradicted",  "发明人冲突: 造纸术由蔡伦改进"),
    ("毕昇发明了活字印刷术",         "verified",      "正确归属: 毕昇确实是活字印刷术发明者"),
    ("爱迪生发明了电话",             "contradicted",  "发明人冲突: 贝尔发明电话"),
    ("李白是宋朝诗人",               "contradicted",  "时代错误"),
    ("关于朱元璋发明火锅的传说",     "unverifiable",  "叙事标记'传说'→不做验证"),
    ("秦始皇和长生不老药的故事",     "unverifiable",  "叙事标记'故事'→不做验证"),
    ("蔡伦改进了造纸术",             "verified",      "正确事实"),
    ("爱因斯坦提出了相对论",         "verified",      "正确事实(提出≠发明，不含发明人物冲突)"),
    ("牛顿发明了相对论",             "contradicted",  "发明人冲突: 爱因斯坦提出相对论"),
    ("朱元璋是火锅发明者",           "contradicted",  "显式否定: KB明确说朱元璋没有发明火锅"),
]


def run_tests():
    print("🧠 GraphContradictionChecker 集成测试 (修复后)")
    print("=" * 60)

    engine = hd.AnchorEngine(enable_graph=True)
    reasoner = engine._get_graph_reasoner()
    print(f"  推理器: {'✅ 已加载' if reasoner else '⚠️ 未加载'}")
    print(f"  测试数: {len(TEST_CASES)}")
    print()

    passed = 0
    failed = 0

    for i, (claim_text, expected, desc) in enumerate(TEST_CASES, 1):
        claim = hd.FactualClaim(
            text=claim_text,
            entities=[],
            is_verifiable=True,
            confidence=0.5
        )

        try:
            result = engine.verify(claim)
            actual = result.verdict

            if actual == expected:
                passed += 1
                status = "✅"
            else:
                failed += 1
                status = "❌"

            evidence = getattr(result, 'evidence', '')[:60]
            print(f"  {status} {claim_text:<30s} → {actual:<14s} "
                  f"({result.confidence:.2f}) | {desc}")
            if status == "❌":
                print(f"       期望={expected} 实际={actual} | {evidence}")

        except Exception as e:
            failed += 1
            print(f"  ❌ {claim_text:<30s} → 异常: {e}")

    print(f"\n{'='*60}")
    print(f"  结果: {passed}/{len(TEST_CASES)} 通过")
    if failed:
        print(f"  失败: {failed} 条")
    else:
        print(f"  🎉 全部通过！")
    print(f"{'='*60}")

    # 演示推理器
    if reasoner:
        print(f"\n🔍 GraphReasoner 推理演示:")
        for c in ["朱元璋发明了火锅", "毕昇发明了活字印刷术", "秦始皇发明了造纸术"]:
            r = reasoner.infer_contradiction(c)
            if r:
                print(f"  '{c}' → {r['verdict']} ({r.get('evidence','')[:70]})")
            else:
                print(f"  '{c}' → 无推理结论（✅ 正确放行）")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
