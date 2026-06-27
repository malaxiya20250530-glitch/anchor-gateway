#!/usr/bin/env python3
"""
update_kb.py — 用户知识库管理工具
用法:
  python3 update_kb.py add "key" "事实文本" "来源"
  python3 update_kb.py remove "key" "事实文本"
  python3 update_kb.py list                      # 列出所有用户条目
  python3 update_kb.py apply 42                  # 将反馈记录#42写入KB
"""

import json
import sys
from pathlib import Path

KB_USER_PATH = Path(__file__).parent / "kb_user.json"


def load() -> dict:
    with open(KB_USER_PATH) as f:
        return json.load(f)


def save(data: dict) -> None:
    with open(KB_USER_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_fact(key: str, fact: str, source: str = "用户贡献") -> None:
    """向用户KB添加一条事实"""
    data = load()
    key = key.strip()
    fact = fact.strip()
    if key.startswith("_"):
        print(f"错误: '{key}' 是保留键")
        return
    if key not in data:
        data[key] = {"facts": [], "source": source}
    if fact not in data[key]["facts"]:
        data[key]["facts"].append(fact)
        save(data)
        print(f"✅ 已添加 [{key}] {fact[:50]}...")
    else:
        print(f"⏭️ 已存在: [{key}] {fact[:50]}...")


def remove_fact(key: str, fact: str) -> None:
    """从用户KB移除一条事实"""
    data = load()
    if key in data and fact in data[key]["facts"]:
        data[key]["facts"].remove(fact)
        if not data[key]["facts"]:
            del data[key]
        save(data)
        print(f"✅ 已移除 [{key}] {fact[:50]}...")
    else:
        print(f"⚠️ 未找到: [{key}] {fact[:50]}...")


def list_entries() -> None:
    """列出所有用户条目"""
    data = load()
    count = 0
    for key, entry in data.items():
        if key.startswith("_"):
            continue
        count += 1
        print(f"\n📁 [{key}] (来源: {entry.get('source', '?')})")
        for i, f in enumerate(entry.get("facts", []), 1):
            print(f"    {i}. {f}")
    if count == 0:
        print("📭 用户知识库为空")
    else:
        print(f"\n共 {count} 个条目")


def apply_feedback(record_id: int) -> None:
    """将反馈记录写入KB"""
    import feedback_store as fs
    pending = fs.get_pending()
    record = None
    for r in pending:
        if r["id"] == record_id:
            record = r
            break
    if not record:
        # 也查已应用记录
        import sqlite3
        conn = sqlite3.connect(str(Path(__file__).parent / "feedback.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM feedback WHERE id = ?", (record_id,)).fetchone()
        conn.close()
        if row:
            record = dict(row)
    if not record:
        print(f"⚠️ 未找到反馈记录 #{record_id}")
        return

    claim = record["claim"]
    fact = record["fact"]
    verdict = record["verdict"]

    # 从claim中提取关键词作为KB键
    from hallucination_detector import FactExtractor
    claims = FactExtractor.extract(claim)
    entities = claims[0].entities if claims else [claim[:6]]

    key = entities[0] if entities else claim[:6]
    # 取前6个字符做键（截断长实体）
    if len(key) > 10:
        key = key[:6]

    if verdict == "contradicted":
        new_fact = f"{claim}是错误的——{fact}"
    elif verdict == "verified":
        new_fact = f"{claim}是正确的——{fact}"
    else:
        new_fact = f"关于{claim}：{fact}"

    add_fact(key, new_fact, record.get("source", "反馈记录"))
    fs.apply_correction(record_id, f"已写入KB: {key}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 4:
        add_fact(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "用户贡献")
    elif cmd == "remove" and len(sys.argv) >= 4:
        remove_fact(sys.argv[2], sys.argv[3])
    elif cmd == "list":
        list_entries()
    elif cmd == "apply" and len(sys.argv) >= 3:
        apply_feedback(int(sys.argv[2]))
    else:
        print(__doc__)
