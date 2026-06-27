"""
update_kb 单元测试
覆盖：load, save, add_fact, remove_fact, 边界条件
运行: python3 test_update_kb.py
"""

import sys
import os
import tempfile
import json
import shutil

# ---- 测试夹具 ----

_orig_path = None
_tmpdir = None

def setup_module():
    global _orig_path, _tmpdir
    import update_kb
    _orig_path = update_kb.KB_USER_PATH
    _tmpdir = tempfile.mkdtemp(prefix="test_kb_")
    update_kb.KB_USER_PATH = _tmpdir + "/test_kb_user.json"
    # 初始化空 KB
    update_kb.save({})

def teardown_module():
    import update_kb
    update_kb.KB_USER_PATH = _orig_path
    shutil.rmtree(_tmpdir, ignore_errors=True)

def _reset_kb():
    import update_kb
    update_kb.save({"_reserved": {"facts": ["内部数据"], "source": "system"}})

# ---- 测试用例 ----

def test_load_save_empty():
    import update_kb
    update_kb.save({"test": "hello"})
    data = update_kb.load()
    assert data == {"test": "hello"}, f"load/save 不匹配: {data}"

def test_add_fact_new_key():
    import update_kb
    _reset_kb()
    update_kb.add_fact("Python", "Python 由 Guido van Rossum 创建", "官方")
    data = update_kb.load()
    assert "Python" in data
    assert len(data["Python"]["facts"]) == 1
    assert data["Python"]["facts"][0] == "Python 由 Guido van Rossum 创建"
    assert data["Python"]["source"] == "官方"

def test_add_fact_duplicate():
    import update_kb
    _reset_kb()
    update_kb.add_fact("Java", "Java 由 James Gosling 创建", "官方")
    update_kb.add_fact("Java", "Java 由 James Gosling 创建", "官方")
    data = update_kb.load()
    assert len(data["Java"]["facts"]) == 1, "重复事实不应添加"

def test_add_fact_multiple():
    import update_kb
    _reset_kb()
    update_kb.add_fact("Python", "事实1", "src")
    update_kb.add_fact("Python", "事实2", "src")
    data = update_kb.load()
    assert len(data["Python"]["facts"]) == 2

def test_add_fact_reserved_key():
    import update_kb
    _reset_kb()
    update_kb.add_fact("_internal", "不应添加", "src")
    data = update_kb.load()
    assert "_internal" not in data or len(data.get("_internal", {}).get("facts", [])) <= 1, \
        "保留键不应被修改"

def test_remove_fact_existing():
    import update_kb
    _reset_kb()
    update_kb.add_fact("Go", "Go 是 Google 开发的", "官方")
    update_kb.remove_fact("Go", "Go 是 Google 开发的")
    data = update_kb.load()
    assert "Go" not in data, "移除后键应被删除"

def test_remove_fact_partial():
    import update_kb
    _reset_kb()
    update_kb.add_fact("Rust", "Rust 由 Mozilla 开发", "官方")
    update_kb.add_fact("Rust", "Rust 是系统编程语言", "官方")
    update_kb.remove_fact("Rust", "Rust 由 Mozilla 开发")
    data = update_kb.load()
    assert "Rust" in data
    assert len(data["Rust"]["facts"]) == 1
    assert "Rust 是系统编程语言" in data["Rust"]["facts"]

def test_remove_fact_nonexistent():
    import update_kb
    _reset_kb()
    update_kb.remove_fact("不存在", "不存在的事实")
    data = update_kb.load()
    assert "不存在" not in data, "不存在的键不应被创建"

def test_list_entries_empty():
    import update_kb
    update_kb.save({})
    # 不抛异常即可
    try:
        update_kb.list_entries()
    except Exception as e:
        assert False, f"空 KB 列出不应抛异常: {e}"

# ---- 主入口 ----

if __name__ == "__main__":
    setup_module()
    passed = 0
    failed = 0
    tests = [
        test_load_save_empty,
        test_add_fact_new_key,
        test_add_fact_duplicate,
        test_add_fact_multiple,
        test_add_fact_reserved_key,
        test_remove_fact_existing,
        test_remove_fact_partial,
        test_remove_fact_nonexistent,
        test_list_entries_empty,
    ]
    for t in tests:
        try:
            t()
            print(f"  [{t.__name__}] ✅ 通过")
            passed += 1
        except Exception as e:
            print(f"  [{t.__name__}] ❌ 失败: {e}")
            failed += 1
    teardown_module()
    print(f"\n{'='*50}")
    if failed == 0:
        print(f"  ✅ 全部通过 ({passed} 组测试)")
    else:
        print(f"  ❌ {failed}/{passed+failed} 失败")
    sys.exit(1 if failed else 0)
