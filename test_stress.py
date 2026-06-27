"""
stress_test 结构验证（不发送网络请求）
运行: python3 test_stress.py
"""

import sys
import stress_test


def test_test_cases_nonempty():
    assert len(stress_test.TEST_CASES) >= 8, "应有至少 8 个测试用例"

def test_analyze_texts_nonempty():
    assert len(stress_test.ANALYZE_TEXTS) >= 5, "应有至少 5 个分析文本"

def test_stress_tester_init():
    t = stress_test.StressTester("http://localhost:8800", 10, 2)
    assert t.num_requests == 10
    assert t.concurrency == 2
    assert t.base_url == "http://localhost:8800"
    assert t.latencies == []
    assert t.errors == []


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_test_cases_nonempty,
        test_analyze_texts_nonempty,
        test_stress_tester_init,
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
