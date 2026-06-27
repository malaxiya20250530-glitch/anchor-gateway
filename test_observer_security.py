"""
observer_security 单元测试
覆盖: ObserverVerdict, ExternalAnchor (锚定引擎)
运行: python3 test_observer_security.py
"""

import sys
from observer_security import ObserverAction, ObserverVerdict, ExternalAnchor


def test_observer_verdict_is_silent_true():
    v = ObserverVerdict(
        action=ObserverAction.FLAG,
        reason="",
        confidence=0.5,
        observer_id="test",
    )
    assert v.is_silent(), "无 reason 的 FLAG 应触发静默报警"

def test_observer_verdict_is_silent_false():
    v = ObserverVerdict(
        action=ObserverAction.PASS,
        reason="",
        confidence=0.5,
        observer_id="test",
    )
    assert not v.is_silent(), "PASS 不应触发静默报警"

def test_observer_verdict_with_reason():
    v = ObserverVerdict(
        action=ObserverAction.FLAG,
        reason="检测到绝对化表述",
        confidence=0.7,
        observer_id="test",
    )
    assert not v.is_silent(), "有 reason 不应触发静默报警"

# ---- ExternalAnchor ----

def make_anchor():
    return ExternalAnchor()

def test_verify_factual_hit():
    a = make_anchor()
    r = a.verify_factual("Python 是一种很好的语言")
    assert r["matched"], "Python 应在知识库中"
    assert r["confidence"] > 0.8

def test_verify_factual_miss():
    a = make_anchor()
    r = a.verify_factual("量子计算机可以破解所有加密")
    assert not r["matched"], "不在知识库中应返回未匹配"

def test_check_source_attribution_has():
    a = make_anchor()
    r = a.check_source_attribution("根据研究显示，咖啡有益健康")
    assert r["has_attribution"]

def test_check_source_attribution_none():
    a = make_anchor()
    r = a.check_source_attribution("咖啡绝对是最好的饮品")
    assert not r["has_attribution"]

def test_check_consistency_consistent():
    a = make_anchor()
    a.check_consistency("Python 是动态类型语言")
    r = a.check_consistency("Python 支持面向对象编程")
    assert r["consistent"], "不同主题应判定为一致"

def test_check_consistency_contradiction():
    a = make_anchor()
    a.check_consistency("太阳 从 东方 升起 地球 是 圆形")
    r = a.check_consistency("太阳 从 西方 升起 地球 不是 圆形")
    assert not r["consistent"], "否定翻转应检测到矛盾（需足够重叠度）"

def test_anchor_returns_verdicts():
    a = make_anchor()
    verdicts = a.anchor("Python 是一种语言")
    assert len(verdicts) >= 1, "Python 在 KB 中应至少产生锚定结果"

def test_anchor_no_source_marks_flag():
    a = make_anchor()
    verdicts = a.anchor("太阳明天会爆炸")
    actions = [v.action for v in verdicts]
    assert ObserverAction.FLAG in actions, "无来源标记应 FLAG"


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_observer_verdict_is_silent_true,
        test_observer_verdict_is_silent_false,
        test_observer_verdict_with_reason,
        test_verify_factual_hit,
        test_verify_factual_miss,
        test_check_source_attribution_has,
        test_check_source_attribution_none,
        test_check_consistency_consistent,
        test_check_consistency_contradiction,
        test_anchor_returns_verdicts,
        test_anchor_no_source_marks_flag,
    ]
    for t in tests:
        try:
            t()
            print(f"  [{t.__name__}] ✅ 通过")
            passed += 1
        except Exception as e:
            print(f"  [{t.__name__}] ❌ 失败: {e}")
            failed += 1
    print(f"\n{'='*50}")
    if failed == 0:
        print(f"  ✅ 全部通过 ({passed} 组测试)")
    else:
        print(f"  ❌ {failed}/{passed+failed} 失败")
    sys.exit(1 if failed else 0)
