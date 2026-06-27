"""
feedback_dashboard 单元测试
覆盖: build_card (HTML 卡片生成)
运行: python3 test_feedback_dashboard.py
"""

import sys
from feedback_dashboard import build_card


def test_build_card_contradicted():
    rec = {
        "id": 1,
        "claim": "朱元璋发明了火锅",
        "fact": "火锅源于商周时期",
        "verdict": "contradicted",
        "confidence": 0.88,
        "evidence": "考古证据",
        "source": "知识库",
        "created_at": 1717000000,
    }
    html = build_card(rec)
    assert "🔴 矛盾" in html
    assert "朱元璋发明了火锅" in html
    assert "火锅源于商周时期" in html
    assert "88%" in html or "0.88" in html

def test_build_card_verified():
    rec = {
        "id": 2,
        "claim": "Python 由 Guido 于 1991 年发布",
        "fact": "Python 由 Guido van Rossum 于 1991 年发布",
        "verdict": "verified",
        "confidence": 0.95,
        "evidence": "python.org",
        "source": "官方文档",
        "created_at": 1717000000,
    }
    html = build_card(rec)
    assert "🟢 验证" in html
    assert "Python 由 Guido" in html

def test_build_card_uncertain():
    rec = {
        "id": 3,
        "claim": "量子计算机会取代经典计算机",
        "fact": "目前尚无定论",
        "verdict": "uncertain",
        "confidence": 0.4,
        "evidence": "",
        "source": "",
        "created_at": 1717000000,
    }
    html = build_card(rec)
    assert "🟡 不确定" in html

def test_build_card_has_actions():
    rec = {
        "id": 4,
        "claim": "测试声明",
        "fact": "测试事实",
        "verdict": "contradicted",
        "confidence": 0.5,
        "evidence": "",
        "source": "测试",
        "created_at": 1717000000,
    }
    html = build_card(rec)
    assert "✅ 确认无误" in html
    assert "❌ 驳回" in html
    assert "🔧 重新匹配" in html

def test_build_card_xss_safe():
    rec = {
        "id": 5,
        "claim": "<script>alert('xss')</script>",
        "fact": "<img src=x onerror=alert(1)>",
        "verdict": "contradicted",
        "confidence": 0.9,
        "evidence": "",
        "source": "",
        "created_at": 1717000000,
    }
    html = build_card(rec)
    assert "<script>" not in html, "应转义 <script>"
    assert "&lt;script&gt;" in html


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_build_card_contradicted,
        test_build_card_verified,
        test_build_card_uncertain,
        test_build_card_has_actions,
        test_build_card_xss_safe,
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
