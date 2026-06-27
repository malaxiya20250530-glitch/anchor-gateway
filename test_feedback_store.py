"""
feedback_store 单元测试
覆盖：CRUD、查询、统计、分页
运行: python3 test_feedback_store.py
"""

import sys
import os
import tempfile
import atexit

# ---- 测试夹具 ----

def setup_module():
    """用临时数据库替换真实 DB_PATH"""
    import feedback_store as fs
    global _orig_db_path, _tmpdir
    _orig_db_path = fs.DB_PATH
    _tmpdir = tempfile.mkdtemp(prefix="test_feedback_")
    fs.DB_PATH = _tmpdir + "/test_feedback.db"
    fs.init_db()

def teardown_module():
    """恢复原始 DB_PATH 并清理"""
    import feedback_store as fs
    import shutil
    fs.DB_PATH = _orig_db_path
    shutil.rmtree(_tmpdir, ignore_errors=True)

# ---- 测试用例 ----

def test_init_db_creates_tables():
    import feedback_store as fs
    conn = fs._connect()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'"
    ).fetchall()
    assert len(tables) == 1, "feedback 表应存在"
    conn.close()

def test_insert_and_find():
    import feedback_store as fs
    fs.init_db()
    # 清空
    conn = fs._connect()
    conn.execute("DELETE FROM feedback")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='feedback'")
    conn.commit()
    conn.close()

    rec = fs.FeedbackRecord(
        claim="地球是平的",
        fact="地球是球体",
        verdict="contradicted",
        confidence=0.9,
        evidence="NASA",
        source="kb",
    )
    rid = fs.insert_record(rec)
    assert rid == 1, f"应有 id=1，实际 {rid}"

    found = fs.find_similar("地球是平的", "地球是球体")
    assert found is not None, "应能查到记录"
    assert found["verdict"] == "contradicted"
    assert found["confidence"] == 0.9

def test_find_applied_correction():
    import feedback_store as fs
    conn = fs._connect()
    conn.execute("DELETE FROM feedback")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='feedback'")
    conn.commit()
    conn.close()

    rec = fs.FeedbackRecord(
        claim="Python是1991年发布的",
        fact="Python于1991年发布",
        verdict="verified",
        confidence=0.95,
        evidence="python.org",
        source="kb",
    )
    rid = fs.insert_record(rec)
    fs.apply_correction(rid, "正确")

    found = fs.find_applied_correction("Python是1991年发布的", "Python于1991年发布")
    assert found is not None, "应查到已应用记录"
    assert found["applied"] == 1
    assert found["user_correction"] == "正确"

def test_find_similar_returns_none_for_missing():
    import feedback_store as fs
    result = fs.find_similar("不存在的声明", "不存在的事实")
    assert result is None, "不存在的记录应返回 None"

def test_apply_correction():
    import feedback_store as fs
    conn = fs._connect()
    conn.execute("DELETE FROM feedback")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='feedback'")
    conn.commit()
    conn.close()

    rec = fs.FeedbackRecord(
        claim="测试声明",
        fact="测试事实",
        verdict="uncertain",
        confidence=0.5,
        evidence="",
        source="test",
    )
    rid = fs.insert_record(rec)
    fs.apply_correction(rid, "用户纠正")

    conn = fs._connect()
    row = conn.execute("SELECT * FROM feedback WHERE id = ?", (rid,)).fetchone()
    conn.close()
    assert row["applied"] == 1
    assert row["user_correction"] == "用户纠正"

def test_set_rematch_and_find_rematch():
    import feedback_store as fs
    conn = fs._connect()
    conn.execute("DELETE FROM feedback")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='feedback'")
    conn.commit()
    conn.close()

    rec = fs.FeedbackRecord(
        claim="朱元璋发明了火锅",
        fact="火锅源于商周",
        verdict="contradicted",
        confidence=0.8,
        evidence="",
        source="kb",
    )
    rid = fs.insert_record(rec)
    fs.set_rematch(rid, "火锅起源")

    rematch = fs.find_rematch("朱元璋发明了火锅")
    assert rematch == "火锅起源", f"应返回 rematch_key，实际 {rematch}"

def test_reject_record():
    import feedback_store as fs
    conn = fs._connect()
    conn.execute("DELETE FROM feedback")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='feedback'")
    conn.commit()
    conn.close()

    rec = fs.FeedbackRecord(
        claim="待驳回",
        fact="事实",
        verdict="uncertain",
        confidence=0.3,
        evidence="",
        source="test",
    )
    rid = fs.insert_record(rec)
    fs.reject_record(rid)

    conn = fs._connect()
    row = conn.execute("SELECT applied FROM feedback WHERE id = ?", (rid,)).fetchone()
    conn.close()
    assert row["applied"] == -1, "驳回后 applied 应为 -1"

def test_get_pending_pagination():
    import feedback_store as fs
    conn = fs._connect()
    conn.execute("DELETE FROM feedback")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='feedback'")
    conn.commit()
    conn.close()

    # 插入 25 条待复核记录
    for i in range(25):
        rec = fs.FeedbackRecord(
            claim=f"声明{i}",
            fact=f"事实{i}",
            verdict="uncertain",
            confidence=0.5,
            evidence="",
            source="test",
        )
        fs.insert_record(rec)

    page1 = fs.get_pending(page=1, per_page=10)
    assert len(page1) == 10, f"第1页应有10条，实际 {len(page1)}"

    page3 = fs.get_pending(page=3, per_page=10)
    assert len(page3) == 5, f"第3页应有5条，实际 {len(page3)}"

def test_get_pending_count():
    import feedback_store as fs
    conn = fs._connect()
    conn.execute("DELETE FROM feedback")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='feedback'")
    conn.commit()
    conn.close()

    for i in range(3):
        rec = fs.FeedbackRecord(
            claim=f"待审{i}",
            fact=f"事实{i}",
            verdict="uncertain",
            confidence=0.5,
            evidence="",
            source="test",
        )
        fs.insert_record(rec)

    # 驳回一条
    fs.reject_record(1)
    assert fs.get_pending_count() == 2, "应有 2 条待复核"

def test_get_stats():
    import feedback_store as fs
    conn = fs._connect()
    conn.execute("DELETE FROM feedback")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='feedback'")
    conn.commit()
    conn.close()

    # 插入 3 条
    for i in range(3):
        fs.insert_record(fs.FeedbackRecord(
            claim=f"统计{i}", fact=f"事实{i}",
            verdict="uncertain", confidence=0.5,
            evidence="", source="test",
        ))
    fs.apply_correction(1, "确认")
    fs.reject_record(2)

    stats = fs.get_stats()
    assert stats["total"] == 3
    assert stats["pending"] == 1
    assert stats["applied"] == 1
    assert stats["rejected"] == 1

# ---- 主入口 ----

if __name__ == "__main__":
    setup_module()
    passed = 0
    failed = 0
    tests = [
        test_init_db_creates_tables,
        test_insert_and_find,
        test_find_applied_correction,
        test_find_similar_returns_none_for_missing,
        test_apply_correction,
        test_set_rematch_and_find_rematch,
        test_reject_record,
        test_get_pending_pagination,
        test_get_pending_count,
        test_get_stats,
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
