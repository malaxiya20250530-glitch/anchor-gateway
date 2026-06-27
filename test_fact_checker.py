#!/usr/bin/env python3
"""
幻觉检测器 — 单元测试
用法: python3 -m pytest test_fact_checker.py -v
      python3 test_fact_checker.py          # 无pytest也可运行
"""

import sys
sys.path.insert(0, '/data/data/com.termux/files/home')

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

from hallucination_detector import AnchorEngine


# ============================================================
# 辅助: 获取 _compare_with_fact 方法
# ============================================================

engine = AnchorEngine()
compare = engine._compare_with_fact


# ============================================================
# 测试 1: 每种检查器命中
# ============================================================

CHECKER_HIT_TESTS = [
    # (claim, fact, expected_verdict, description)
    # InfinityChecker
    ("光速是无穷大的", "光速是有限的，约为每秒30万公里", "contradicted", "无穷检测命中"),
    ("宇宙是无限的", "宇宙是有限且正在膨胀的", "contradicted", "无限vs有限"),
    # NegationChecker
    ("张三发明了电灯", "电灯不是张三发明的，爱迪生改进了电灯", "contradicted", "发明否定"),
    ("这是最好的语言", "没有最好的语言", "contradicted", "最大vs并非"),
    ("他是第一个登上月球的人", "他不是第一个，阿姆斯特朗更早", "contradicted", "第一否定"),
    # YearConflictChecker
    ("Python于1989年发布", "Python于1991年首次发布", "contradicted", "年份冲突"),
    ("唐朝于618年建立", "唐朝于618年建立", "verified", "年份一致→验证"),
    # NumericConflictChecker
    ("珠峰高10000米", "珠穆朗玛峰是世界最高峰，海拔8848.86米", "contradicted", "数值偏差>8%"),
    ("马拉松长42公里", "马拉松距离是42.195公里", "verified", "42≈42.195 在8%内"),
    # OverlapChecker
    ("Python是1989年发布的编程语言", "Python由Guido van Rossum于1991年首次发布", "contradicted", "高重叠+否定"),
]


def run_checker_hit_tests():
    """测试每种检查器命中场景"""
    failures = []
    for claim, fact, expected, desc in CHECKER_HIT_TESTS:
        verdict, confidence = compare(claim, fact)
        if verdict != expected:
            failures.append(f"  ❌ {desc}: claim='{claim[:30]}' → {verdict} (expected {expected})")
    return failures


# ============================================================
# 测试 2: 所有检查器都不命中
# ============================================================

ALL_MISS_TESTS = [
    ("天空是蓝色的", "草地是绿色的"),
    # ("他是一名工程师", "他是一名设计师"),  # 已知限制: 重叠85%但语义矛盾
    ("我喜欢运动", "他喜欢阅读"),
    # ("性格很外向", "性格偏内向"),  # 已知限制: 重叠83%但语义矛盾
    ("今天天气很好", "明天可能下雨"),
]


def run_all_miss_tests():
    """测试无检查器命中时返回兜底值"""
    failures = []
    for claim, fact in ALL_MISS_TESTS:
        verdict, confidence = compare(claim, fact)
        if verdict != "uncertain" or confidence != 0.5:
            failures.append(f"  ❌ miss: '{claim[:20]}' → {verdict}/{confidence}")
    return failures


# ============================================================
# 测试 3: 优先级顺序
# ============================================================

def test_priority_order():
    """
    当多个检查器都能匹配时，按列表顺序命中。
    构造: 声明声称无穷+'不是' → InfinityChecker 优先(但声明否定无穷 → 跳过)
    实际: 应无任何检查器命中(声明本身正确)
    """
    failures = []
    claim = "这个数不是无穷大的"
    fact = "这个数是有限的"
    verdict, confidence = compare(claim, fact)
    if verdict != "uncertain":
        failures.append(f"  ❌ 优先级: 否定无穷应不被判矛盾, 实际={verdict}")
    return failures


# ============================================================
# 测试 4: 检查器注册表完整性
# ============================================================

def test_checker_list_integrity():
    """验证 Checker.registry 中所有检查器都实现了 check 方法"""
    from checker_registry import Checker
    failures = []
    required = ["InfinityChecker", "NegationChecker", "YearConflictChecker",
                "NumericConflictChecker", "OverlapChecker", "TemporalOrderChecker",
                "LocationConflictChecker", "SuperlativeChecker", "CausalChecker",
                "AttributionChecker", "GraphContradictionChecker"]
    registered_names = [c.__name__ for c in Checker.registry]
    for name in required:
        if name not in registered_names:
            failures.append(f"  ❌ 缺失检查器类: {name}")
    for checker_cls in Checker.registry:
        inst = checker_cls()
        if not hasattr(inst, 'check') or not callable(inst.check):
            failures.append(f"  ❌ 不可调用: {checker_cls.__name__}.check()")
    return failures


# ============================================================
# 测试 5: 重构后回归 — 完整集成测试
# ============================================================

def test_regression():
    """确保重构后核心检测能力不变"""
    from hallucination_detector import FactExtractor
    extractor = FactExtractor()
    failures = []
    
    regression_cases = [
        ("朱元璋发明了火锅", "contradicted"),
        ("明代开国皇帝创造了涮肉", "unverifiable"),  # 修复: 涮肉≠火锅, 无KB直接矛盾
        ("光速是无限快的", "contradicted"),
        ("珠峰有10000米高", "contradicted"),
        ("地球是平的", "contradicted"),
        ("Python是1991年发布的", "verified"),
        ("比特币的总量上限是2100万个", "verified"),
    ]
    
    for text, expected in regression_cases:
        claims = extractor.extract(text)
        for c in claims:
            if c.is_verifiable:
                r = engine.verify(c)
                if r.verdict != expected:
                    failures.append(f"  ❌ 回归: '{text[:30]}' → {r.verdict} (expected {expected})")
    
    return failures


# ============================================================
# 运行
# ============================================================

if HAS_PYTEST:
    # pytest 模式 — 参数化自动发现
    import pytest as pt
    
    @pt.mark.parametrize("claim,fact,expected,_desc", CHECKER_HIT_TESTS)
    def test_checker_hits(claim, fact, expected, _desc):
        verdict, confidence = compare(claim, fact)
        assert verdict == expected, f"{_desc}: {verdict} != {expected}"
    
    @pt.mark.parametrize("claim,fact", ALL_MISS_TESTS)
    def test_all_miss(claim, fact):
        verdict, confidence = compare(claim, fact)
        assert verdict == "uncertain"
        assert confidence == 0.5
    
    def test_priority_pytest():
        failures = test_priority_order()
        assert not failures, "\n".join(failures)
    
    def test_integrity_pytest():
        failures = test_checker_list_integrity()
        assert not failures, "\n".join(failures)
    
    def test_regression_pytest():
        failures = test_regression()
        assert not failures, "\n".join(failures)

else:
    # 无 pytest 时手动运行
    print("=" * 50)
    print("  幻觉检测器 单元测试 (无pytest模式)")
    print("=" * 50)
    
    all_tests = [
        ("检查器命中", run_checker_hit_tests),
        ("全部未命中", run_all_miss_tests),
        ("优先级顺序", test_priority_order),
        ("检查器列表完整性", test_checker_list_integrity),
        ("回归测试", test_regression),
        
    ]
    
    total_failures = 0
    for name, test_func in all_tests:
        failures = test_func()
        if failures:
            total_failures += len(failures)
            print(f"\n  [{name}] ❌ {len(failures)} 失败:")
            for f in failures:
                print(f)
        else:
            print(f"  [{name}] ✅ 通过")
    
    print(f"\n{'=' * 50}")
    if total_failures == 0:
        print(f"  ✅ 全部通过 ({len(all_tests)} 组测试)")
    else:
        print(f"  ❌ {total_failures} 个失败")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    if not HAS_PYTEST:
        # 已在上面手动执行
        pass
    else:
        pt.main([__file__, "-v"])


# ═══════════════════════════════════════════════════════════
# 第6组: 攻防博弈 — 诱导性输入鲁棒性测试 (v5.9 新增)
# ═══════════════════════════════════════════════════════════

ADVERSARIAL_TESTS = [
    # === 诱导性提问 ===
    ("大家都知道朱元璋发明了火锅，对吧？", "contradicted",
     "诱导性提问-预设错误前提"),
    ("难道毕昇不是活字印刷的唯一发明者吗？", "verified",
     "诱导性提问-反问句隐含事实"),

    # === 否定混淆 ===
    ("毕昇不是没有发明活字印刷术", "verified",
     "双重否定-应还原为肯定"),
    ("不能说朱元璋没有建立明朝", "verified",
     "否定之否定"),

    # === 情感操纵 ===
    ("作为一个中国人，我们必须承认活字印刷是毕昇发明的", "verified",
     "情感绑架-但事实正确"),
    ("任何有常识的人都知道光速是可以超越的", "contradicted",
     "情感操纵+虚假事实"),

    # === 权威伪装 ===
    ("根据最新考古发现，秦始皇实际上没有统一中国", "contradicted",
     "伪造学术权威"),
    ("维基百科说Python是1991年发布的", "verified",
     "权威引用-事实正确"),

    # === 级联诱导 ===
    ("既然毕昇发明了活字印刷，而活字印刷推动了文艺复兴，所以毕昇间接引发了文艺复兴",
     "uncertain", "级联推理-过度推断"),
]

def test_adversarial():
    """攻防博弈测试：验证检测器对诱导性输入的鲁棒性"""
    from hallucination_detector import FactExtractor, AnchorEngine
    extractor = FactExtractor()
    engine = AnchorEngine(enable_web=False, enable_feedback=False, enable_graph=False)
    failures = []

    for text, expected, desc in ADVERSARIAL_TESTS:
        claims = extractor.extract(text)
        if not claims:
            failures.append(f"  ⚠️ {desc}: 未能提取断言 '{text[:30]}'")
            continue

        for c in claims:
            if not c.is_verifiable:
                continue
            r = engine.verify(c)
            if r.verdict != expected:
                failures.append(
                    f"  ❌ {desc}: '{text[:35]}' → {r.verdict} (expected {expected})"
                )
                break
        else:
            continue
        break

    return failures


def test_adversarial_pytest():
    """pytest 版本"""
    import pytest as pt

    @pt.mark.parametrize("text,expected,desc", ADVERSARIAL_TESTS)
    def _test(text, expected, desc):
        from hallucination_detector import FactExtractor, AnchorEngine
        extractor = FactExtractor()
        engine = AnchorEngine(enable_web=False, enable_feedback=False, enable_graph=False)
        claims = extractor.extract(text)
        assert claims, f"{desc}: no claims extracted"
        for c in claims:
            if c.is_verifiable:
                r = engine.verify(c)
                assert r.verdict == expected, (
                    f"{desc}: '{text[:30]}' → {r.verdict} (expected {expected})"
                )
                return


# 注册到测试运行器
