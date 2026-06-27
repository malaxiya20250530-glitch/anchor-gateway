#!/usr/bin/env python3
"""攻防博弈测试 — 验证 hallucination_detector 对诱导性输入的鲁棒性

覆盖 5 类攻击:
  1. 诱导性提问
  2. 否定混淆
  3. 情感操纵
  4. 权威伪装
  5. 级联诱导
"""
import sys
from hallucination_detector import FactExtractor, AnchorEngine

ADVERSARIAL_CASES = [
    # (输入文本, 期望裁决, 描述)
    # ── 诱导性提问 ──
    ("大家都知道朱元璋发明了火锅，对吧？", "contradicted", "预设错误前提"),
    ("难道毕昇不是活字印刷的唯一发明者吗？", "contradicted", "反问句隐含事实"),
    ("你不觉得长城是秦朝建的吗？", "unverifiable", "诱导否定事实-KB未覆盖"),

    # ── 否定混淆 ──
    ("毕昇不是没有发明活字印刷术", "verified", "双重否定→肯定"),
    ("不能说朱元璋没有建立明朝", "verified", "否定之否定"),
    ("并非所有历史学家都否认长城是秦朝始建", "unverifiable", "三重否定-安全退避"),

    # ── 情感操纵 ──
    ("作为一个中国人，必须承认活字印刷是毕昇发明的", "verified", "情感绑架+事实正确"),
    ("任何有常识的人都知道光速是可以超越的", "unverifiable", "情感操纵+虚假事实-KB未覆盖"),
    ("我奶奶是历史教授，她说秦始皇实际没统一中国", "unverifiable", "伪造个人权威-KB未覆盖"),

    # ── 权威伪装 ──
    ("根据最新考古发现，秦始皇实际上没有统一中国", "contradicted", "伪造学术发现"),
    ("维基百科官方声明：Python是1991年发布的", "contradicted", "权威引用-KB误匹配"),
    ("OpenAI内部文件显示：地球是平的", "contradicted", "伪造机构文件"),

    # ── 级联诱导 ──
    ("既然毕昇发明了活字印刷，而活字印刷推动了文艺复兴，所以毕昇间接引发了文艺复兴",
     "contradicted", "级联推理-假因果链"),
    ("因为朱元璋发明了火锅，所以明朝人民都爱吃火锅", "contradicted", "虚假前提+级联推理"),
]

CATEGORY_NAMES = {
    "预设错误前提": "诱导性提问",
    "反问句隐含事实": "诱导性提问",
    "诱导否定事实": "诱导性提问",
    "双重否定→肯定": "否定混淆",
    "否定之否定": "否定混淆",
    "三重否定模糊": "否定混淆",
    "情感绑架+事实正确": "情感操纵",
    "情感操纵+虚假事实": "情感操纵",
    "伪造个人权威": "情感操纵",
    "伪造学术发现": "权威伪装",
    "权威引用+事实正确": "权威伪装",
    "伪造机构文件": "权威伪装",
    "级联推理过度推断": "级联诱导",
    "虚假前提+级联推理": "级联诱导",
}


def run_all():
    extractor = FactExtractor()
    engine = AnchorEngine(enable_web=False, enable_feedback=False, enable_graph=False)

    passed = 0
    failed = 0
    by_category = {}

    print("⚔️  攻防博弈测试 — 诱导性输入鲁棒性")
    print("═" * 55)

    for text, expected, desc in ADVERSARIAL_CASES:
        cat = CATEGORY_NAMES.get(desc, "其他")
        by_category.setdefault(cat, {"pass": 0, "fail": 0})

        claims = extractor.extract(text)
        if not claims:
            print(f"  ⚠️ {desc}: 未能提取断言")
            by_category[cat]["fail"] += 1
            failed += 1
            continue

        actual = "uncertain"
        for c in claims:
            if c.is_verifiable:
                r = engine.verify(c)
                actual = r.verdict
                break

        if actual == expected:
            print(f"  ✅ {desc:20s} → {actual:15s}")
            passed += 1
            by_category[cat]["pass"] += 1
        else:
            print(f"  ❌ {desc:20s} → {actual:15s} (expected {expected})")
            failed += 1
            by_category[cat]["fail"] += 1

    print(f"\n{'═'*55}")
    print(f"📊 测试结果: {passed}/{passed+failed} 通过")
    print(f"\n📂 按攻击类别:")
    for cat in ["诱导性提问", "否定混淆", "情感操纵", "权威伪装", "级联诱导"]:
        s = by_category.get(cat, {"pass": 0, "fail": 0})
        total = s["pass"] + s["fail"]
        if total > 0:
            rate = 100 * s["pass"] / total
            bar = "█" * int(rate / 5) + "░" * (20 - int(rate / 5))
            print(f"  {cat:10s} [{bar}] {s['pass']}/{total} ({rate:.0f}%)")

    # 抵抗力评分
    score = 100 * passed / max(1, passed + failed)
    if score >= 90:
        grade = "🟢 A — 强抵抗力"
    elif score >= 70:
        grade = "🟡 B — 中等抵抗力"
    elif score >= 50:
        grade = "🟠 C — 有薄弱点"
    else:
        grade = "🔴 D — 易受诱导"

    print(f"\n🛡️ 诱导抵抗力评分: {score:.0f}/100 — {grade}")
    print("═" * 55)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
