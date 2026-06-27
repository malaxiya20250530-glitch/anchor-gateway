"""
向量知识库单元测试（惰性加载优化版）
运行: python3 test_vector_kb.py
"""

import sys
from vector_kb import VectorKnowledgeBase, _ngrams, _cosine_similarity

# 全局共享实例，避免重复加载
_vkb = None
def _get_vkb():
    global _vkb
    if _vkb is None:
        _vkb = VectorKnowledgeBase()
    return _vkb

def test_ngrams_chinese():
    grams = _ngrams("朱元璋发明了火锅")
    assert "朱元" in grams, "应包含 2-gram"
    assert "璋发" in grams
    assert "朱元璋" in grams, "应包含 3-gram"

def test_cosine_identical():
    a = [1.0, 0.0, 0.5]
    b = [1.0, 0.0, 0.5]
    assert abs(_cosine_similarity(a, b) - 1.0) < 0.01, "相同向量相似度应为 1"

def test_cosine_orthogonal():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert abs(_cosine_similarity(a, b) - 0.0) < 0.01, "正交向量相似度应为 0"

def test_vector_kb_search_hit():
    vkb = _get_vkb()
    results = vkb.search("朱元璋发明了火锅", top_k=2, threshold=0.1)
    assert len(results) > 0, "应至少命中 1 条"
    key, fact, sim = results[0]
    assert "朱元璋" in fact or "火锅" in fact, "相关事实应包含关键词"

def test_vector_kb_search_miss():
    vkb = _get_vkb()
    results = vkb.search("xyz假词不存在abc", top_k=2, threshold=0.3)
    assert len(results) == 0, "不存在的内容不应命中"

def test_vector_kb_count():
    vkb = _get_vkb()
    assert len(vkb.texts) >= 200, f"向量库应有足够条目，当前 {len(vkb.texts)}"


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_ngrams_chinese,
        test_cosine_identical,
        test_cosine_orthogonal,
        test_vector_kb_search_hit,
        test_vector_kb_search_miss,
        test_vector_kb_count,
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
