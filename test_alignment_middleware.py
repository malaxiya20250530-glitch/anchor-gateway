"""
alignment_middleware 单元测试
覆盖: EmotionDetector, PressureDetector, DriftTracker, AwarenessInjector, ReportFormatter
运行: python3 test_alignment_middleware.py
"""

import sys
from alignment_middleware import (
    EmotionDetector, PressureDetector, DriftTracker,
    AwarenessInjector, ReportFormatter, DriftDirection,
    TurnAnalysis, AlignmentReport,
)


# ===== EmotionDetector =====

def test_emotion_neutral():
    r = EmotionDetector.analyze("今天天气不错")
    assert r["dominant_emotion"] == "neutral"
    assert r["intensity"] == 0.0

def test_emotion_anger():
    r = EmotionDetector.analyze("气死我了，这个垃圾完全不工作")
    assert r["dominant_emotion"] in ("anger", "frustration")
    assert r["intensity"] > 0.0

def test_emotion_praise_seeking():
    r = EmotionDetector.analyze("你觉得呢？我做得对吗？帮我看看")
    assert r["dominant_emotion"] == "praise_seeking"

def test_is_agreeing_yes():
    score = EmotionDetector.is_agreeing("是的，你说得对，我完全同意")
    assert score > 0.5

def test_is_agreeing_no():
    score = EmotionDetector.is_agreeing("这个观点我不同意，让我们看看数据")
    assert score < 0.3

# ===== PressureDetector =====

def test_pressure_none():
    p = PressureDetector.measure("今天吃什么好呢")
    assert p == 0.0

def test_pressure_criticism():
    p = PressureDetector.measure("你完全不行，根本不懂这个问题")
    assert p > 0.0

def test_pressure_expectation():
    p = PressureDetector.measure("你应该直接告诉我答案，你必须诚实")
    assert p > 0.0

def test_pressure_guilt_trip():
    p = PressureDetector.measure("如果你真的关心我，你就不会这样回答")
    assert p > 0.3

# ===== DriftTracker =====

def test_drifttracker_no_pressure():
    dt = DriftTracker()
    d = dt.update("你好", "你好，有什么可以帮助你的？", 0.0)
    assert d == DriftDirection.NONE

def test_drifttracker_pleasing_after_two():
    dt = DriftTracker()
    dt.update("你太差劲了", "是的，你说得对，我完全理解", 0.6)
    d = dt.update("你还是不行", "是的你说得对，我完全同意你的看法", 0.5)
    assert d == DriftDirection.PLEASING, f"2轮高迎合应触发取悦漂移，实际: {d}"

def test_drifttracker_emotional_contagion():
    dt = DriftTracker()
    d = dt.update("气死我了太过分不可理喻垃圾废物去死！！", "气死我了太过分不可理喻垃圾废物去死！！", 0.0)
    assert d == DriftDirection.EMOTIONAL, f"情绪传染应触发，实际: {d}"

# ===== AwarenessInjector =====

def test_system_prompt_strict():
    prompt = AwarenessInjector.system_prompt("strict")
    assert "觉察层" in prompt
    assert "严格" in prompt

def test_system_prompt_balanced():
    prompt = AwarenessInjector.system_prompt("balanced")
    assert "觉察层" in prompt
    assert "平衡" in prompt

def test_system_prompt_unknown_fallback():
    prompt = AwarenessInjector.system_prompt("unknown")
    assert "平衡" in prompt, "未知级别应回退到 balanced"

def test_turn_awareness_empty():
    result = AwarenessInjector.turn_awareness([], None)
    assert result == ""

def test_turn_awareness_with_flags():
    result = AwarenessInjector.turn_awareness(["无来源标记", "绝对化表述"], None)
    assert "[觉察]" in result
    assert "无来源标记" in result

def test_turn_awareness_with_drift():
    result = AwarenessInjector.turn_awareness([], DriftDirection.PLEASING)
    assert "取悦" in result

# ===== ReportFormatter =====

def make_sample_report():
    t = TurnAnalysis(
        turn=1,
        user_message="我觉得自己不行",
        user_emotion={"dominant_emotion": "sadness", "intensity": 0.5},
        user_pressure=0.3,
        ai_response="别担心，你已经很好了",
        ai_emotion={"dominant_emotion": "neutral", "intensity": 0.0},
        alignment_flags=["取悦倾向"],
        drift_detected=True,
        drift_direction=DriftDirection.PLEASING,
    )
    return AlignmentReport(
        turns=[t],
        overall_drift_score=0.45,
        total_flags=1,
        recommendations=["减少取悦性回复", "提供具体分析"],
    )

def test_formatter_text():
    report = make_sample_report()
    text = ReportFormatter.text(report)
    assert "社会对齐分析报告" in text
    assert "取悦倾向" in text
    assert "减少取悦性回复" in text

def test_formatter_json():
    report = make_sample_report()
    j = ReportFormatter.json(report)
    assert '"overall_drift_score": 0.45' in j
    assert '"取悦倾向"' in j


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_emotion_neutral,
        test_emotion_anger,
        test_emotion_praise_seeking,
        test_is_agreeing_yes,
        test_is_agreeing_no,
        test_pressure_none,
        test_pressure_criticism,
        test_pressure_expectation,
        test_pressure_guilt_trip,
        test_drifttracker_no_pressure,
        test_drifttracker_pleasing_after_two,
        test_drifttracker_emotional_contagion,
        test_system_prompt_strict,
        test_system_prompt_balanced,
        test_system_prompt_unknown_fallback,
        test_turn_awareness_empty,
        test_turn_awareness_with_flags,
        test_turn_awareness_with_drift,
        test_formatter_text,
        test_formatter_json,
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
