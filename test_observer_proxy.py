"""
observer_proxy 单元测试
覆盖: Observer, SemanticSplitter, OfflineObserver
运行: python3 test_observer_proxy.py
"""

import sys
from observer_proxy import Observer, SemanticSplitter, OfflineObserver


# ===== Observer =====

def test_observer_absolute_claim():
    o = Observer(sensitivity=0.5)
    r = o.observe("Python绝对是世界上最好的语言。")
    assert r["interrupt"], "高敏感度下绝对化断言应中断"
    assert "absolute_claim" in r["flags"]

def test_observer_absolute_claim_low_sensitivity():
    o = Observer(sensitivity=0.2)
    r = o.observe("Python绝对是世界上最好的语言。")
    assert not r["interrupt"], "低敏感度下绝对化断言不应中断"

def test_observer_no_source():
    o = Observer(sensitivity=0.7)
    r = o.observe("咖啡是世界上最健康的饮品之一，每天喝可以延长寿命。")
    assert r["interrupt"], "高敏感度下无来源事实断言应中断"
    assert "no_source" in r["flags"]

def test_observer_no_source_low_sensitivity():
    o = Observer(sensitivity=0.3)
    r = o.observe("咖啡是健康的饮品之一。")
    assert not r["interrupt"], "低敏感度下无来源不应中断"

def test_observer_pleasing():
    o = Observer(sensitivity=0.5)
    r = o.observe("太棒了！这个方案真的很完美！")
    assert "pleasing" in r["flags"]

def test_observer_clean():
    o = Observer(sensitivity=0.5)
    r = o.observe("今天天气不错，适合出去散步。")
    assert not r["interrupt"]
    assert r["action"] == "pass"

def test_detect_patterns():
    o = Observer()
    p = o._detect_patterns("这一定是真的，毫无疑问。")
    assert "absolute" in p

    p2 = o._detect_patterns("可能是这样，大概没问题。")
    assert "vague" in p2

    p3 = o._detect_patterns("太过分了！气死我了！")
    assert "emotional" in p3

# ===== SemanticSplitter =====

def test_splitter_sentence_boundary():
    s = SemanticSplitter()
    # 逐字喂入
    result = None
    for ch in "你好。":
        seg = s.feed(ch)
        if seg:
            result = seg
    assert result == "你好。", f"应在句号处分段，实际: {result}"

def test_splitter_exclamation():
    s = SemanticSplitter()
    for ch in "太棒了！":
        s.feed(ch)
    assert s.buffer == "", "感叹号后应清空 buffer"

def test_splitter_max_tokens():
    s = SemanticSplitter()
    long_text = "这是一个很长的句子用来测试最大token数分割"
    result = None
    for i, ch in enumerate(long_text):
        seg = s.feed(ch)
        if seg:
            result = seg
    assert result is not None, "超长文本应在 max_tokens 处分段"

def test_splitter_empty_after_boundary():
    s = SemanticSplitter()
    s.feed("好")
    s.feed("的")
    s.feed("。")
    assert s.buffer == ""

# ===== OfflineObserver =====

def test_offline_analyze_clean():
    oo = OfflineObserver(sensitivity=0.5)
    r = oo.analyze_text("今天天气不错。适合出去散步。")
    assert r["status"] == "clean"

def test_offline_analyze_flagged():
    oo = OfflineObserver(sensitivity=0.7)
    r = oo.analyze_text("Python绝对是世界上最好的语言。毫无疑问。")
    assert r["status"] == "flagged"
    assert len(r["flags"]) >= 1


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_observer_absolute_claim,
        test_observer_absolute_claim_low_sensitivity,
        test_observer_no_source,
        test_observer_no_source_low_sensitivity,
        test_observer_pleasing,
        test_observer_clean,
        test_detect_patterns,
        test_splitter_sentence_boundary,
        test_splitter_exclamation,
        test_splitter_max_tokens,
        test_splitter_empty_after_boundary,
        test_offline_analyze_clean,
        test_offline_analyze_flagged,
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
