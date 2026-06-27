#!/usr/bin/env python3
"""
update_entity_id.py — 闭环数据层
将 kb_core.json 的实体-事实文本映射写入 fact_store.db 的 entity_id 字段。

实际 schema:
  facts_0 表: hash(INTEGER PK), fact(TEXT), entity_id(TEXT), ...
  kb_core.json: { "实体名": { "facts": ["事实文本1", ...], "source": "..." } }

匹配策略: 精确匹配 fact 文本 → 写入实体名到 entity_id 字段
由于 fact_store.db 为自动生成的数学事实(704万条)，kb_core.json 为人工整理的历史/科技事实，
覆盖率预计很低——这是正常的，脚本会如实报告。

使用方法:
  python3 update_entity_id.py --dry-run   # 预览
  python3 update_entity_id.py             # 正式执行
  python3 update_entity_id.py --verify    # 仅验证当前状态
"""

import sqlite3
import json
import os
import sys
import time
import hashlib

KB_CORE_PATH = "kb_core.json"
FACT_DB_PATH = "knowledge/fact_store.db"
BATCH_SIZE = 5000
DRY_RUN = "--dry-run" in sys.argv
VERIFY_ONLY = "--verify" in sys.argv


def sha256(s):
    """计算字符串的 SHA-256 哈希（整数表示的前12位）"""
    return int(hashlib.sha256(s.encode("utf-8")).hexdigest()[:12], 16)


def main():
    # ── 1. 加载 kb_core.json ──
    if not os.path.exists(KB_CORE_PATH):
        sys.exit(f"❌ 找不到 {KB_CORE_PATH}")
    print(f"📖 读取 {KB_CORE_PATH} ...")
    with open(KB_CORE_PATH, "r", encoding="utf-8") as f:
        kb = json.load(f)
    entities = list(kb.keys())
    print(f"✅ 加载 {len(entities)} 个实体")

    # ── 2. 构建 fact_text → entity_name 映射 ──
    fact_to_entity = {}
    total_fact_texts = 0
    for entity, data in kb.items():
        for fact_text in data.get("facts", []):
            if isinstance(fact_text, str) and fact_text.strip():
                fact_to_entity[fact_text.strip()] = entity
                total_fact_texts += 1
    print(f"✅ 构建 {len(fact_to_entity)} 条 fact_text → entity 映射（总事实文本 {total_fact_texts} 条）")

    # ── 3. 连接数据库 ──
    if not os.path.exists(FACT_DB_PATH):
        sys.exit(f"❌ 找不到 {FACT_DB_PATH}")
    conn = sqlite3.connect(FACT_DB_PATH)
    cur = conn.cursor()

    # ── 4. 创建 entities 字典表 ──
    print("🛠️  创建/确认 entities 字典表...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY,
            display_name TEXT,
            fact_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    if VERIFY_ONLY:
        cur.execute("SELECT COUNT(*) FROM facts_0 WHERE entity_id IS NOT NULL AND entity_id != ''")
        filled = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM facts_0")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM entities")
        ent_count = cur.fetchone()[0]
        print(f"\n📊 验证结果:")
        print(f"   facts_0 总行数: {total:,}")
        print(f"   entity_id 非空: {filled:,} ({filled/total*100:.2f}%)" if total else "   entity_id 非空: 0")
        print(f"   entities 表实体数: {ent_count}")
        conn.close()
        return

    # ── 5. 写入 entities 表 ──
    print("🆔 写入实体名称...")
    for entity in entities:
        cur.execute(
            "INSERT OR IGNORE INTO entities (entity_id, display_name) VALUES (?, ?)",
            (entity, entity)
        )
    conn.commit()
    print(f"✅ entities 表已有 {cur.execute('SELECT COUNT(*) FROM entities').fetchone()[0]} 条记录")

    # ── 6. 匹配并更新 facts_0 ──
    # 策略：先用 hash 精确匹配，再用全文检索
    print("🔍 开始匹配事实文本...")

    matched = 0
    not_found = 0
    total = len(fact_to_entity)
    report_interval = max(1, total // 20)

    if DRY_RUN:
        print("🔍 干运行模式：仅统计匹配数，不写入数据库")
        # 只用小批量抽样验证
        sample = list(fact_to_entity.items())[:100]
        sample_matched = 0
        for fact_text, entity in sample:
            h = sha256(fact_text)
            cur.execute("SELECT COUNT(*) FROM facts_0 WHERE hash = ?", (h,))
            if cur.fetchone()[0] > 0:
                sample_matched += 1
        print(f"   抽样 {len(sample)} 条，匹配 {sample_matched} 条 ({sample_matched/len(sample)*100:.1f}%)")
        print(f"   预计全量匹配: ~{int(len(fact_to_entity) * sample_matched / len(sample))} 条")
        conn.close()
        return

    # 正式执行：逐条精确 hash 匹配 + UPDATE
    print("📊 开始逐条匹配与更新（使用 hash 精确匹配）...")
    start_time = time.time()

    update_count = 0
    batch_updates = []

    for i, (fact_text, entity) in enumerate(fact_to_entity.items()):
        h = sha256(fact_text)
        cur.execute("SELECT COUNT(*) FROM facts_0 WHERE hash = ?", (h,))
        if cur.fetchone()[0] > 0:
            batch_updates.append((entity, h))
            matched += 1
        else:
            not_found += 1

        # 分批提交
        if len(batch_updates) >= BATCH_SIZE:
            cur.executemany(
                "UPDATE facts_0 SET entity_id = ? WHERE hash = ?",
                batch_updates
            )
            update_count += len(batch_updates)
            conn.commit()
            batch_updates = []

        # 进度报告
        if (i + 1) % report_interval == 0 or i == total - 1:
            elapsed = time.time() - start_time
            print(f"   进度: {i+1}/{total} ({((i+1)/total)*100:.1f}%) "
                  f"| 匹配: {matched} | 未找到: {not_found} "
                  f"| 已更新: {update_count} | 耗时: {elapsed:.1f}s")

    # 提交剩余批次
    if batch_updates:
        cur.executemany(
            "UPDATE facts_0 SET entity_id = ? WHERE hash = ?",
            batch_updates
        )
        update_count += len(batch_updates)
        conn.commit()

    elapsed = time.time() - start_time

    # ── 7. 更新 entities 表的 fact_count ──
    print("📊 更新实体关联计数...")
    cur.execute("""
        UPDATE entities
        SET fact_count = (
            SELECT COUNT(*) FROM facts_0
            WHERE facts_0.entity_id = entities.entity_id
        )
    """)
    conn.commit()

    # ── 8. 验证报告 ──
    cur.execute("SELECT COUNT(*) FROM facts_0 WHERE entity_id IS NOT NULL AND entity_id != ''")
    filled = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM facts_0")
    total_facts = cur.fetchone()[0]

    print(f"\n{'='*60}")
    print(f"✅ 更新完成！")
    print(f"   kb_core.json 事实文本总数: {total}")
    print(f"   在 facts_0 中精确匹配: {matched} ({matched/total*100:.1f}%)" if total else "   在 facts_0 中精确匹配: 0")
    print(f"   未找到匹配: {not_found}")
    print(f"   实际 UPDATE 行数: {update_count}")
    print(f"   facts_0 entity_id 非空记录: {filled:,} / {total_facts:,} ({filled/total_facts*100:.2f}%)" if total_facts else "")
    print(f"   总耗时: {elapsed:.1f} 秒")
    print(f"{'='*60}")

    if matched == 0:
        print("\n⚠️  警告: 精确 hash 匹配为 0。")
        print("   这是因为 fact_store.db 的数据是自动生成的数学事实(整数判断)，")
        print("   而 kb_core.json 是人工整理的历史/科技事实。二者文本域不同。")
        print("   建议: 将 kb_core.json 的事实写入 fact_store.db 作为新记录。")
        print("   使用: python3 update_entity_id.py --insert-new")

    conn.close()
    print("🔒 数据库连接已关闭。")


if __name__ == "__main__":
    main()

# =====================================================================
# --insert-new 模式：将 kb_core.json 的事实写入 fact_store.db
# =====================================================================
INSERT_NEW = "--insert-new" in sys.argv

if __name__ == "__main__" and INSERT_NEW:
    import hashlib as _hashlib
    from datetime import datetime as _dt

    if not os.path.exists(KB_CORE_PATH):
        sys.exit(f"❌ 找不到 {KB_CORE_PATH}")
    if not os.path.exists(FACT_DB_PATH):
        sys.exit(f"❌ 找不到 {FACT_DB_PATH}")

    print(f"📖 读取 {KB_CORE_PATH} ...")
    with open(KB_CORE_PATH, "r", encoding="utf-8") as f:
        kb = json.load(f)

    conn = sqlite3.connect(FACT_DB_PATH)
    cur = conn.cursor()

    # 创建 entities 表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY,
            display_name TEXT,
            fact_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    inserted = 0
    skipped = 0
    now = _dt.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    print(f"📊 开始插入 kb_core.json 事实到 fact_store.db ...")
    print(f"   实体数: {len(kb)}")

    for entity, data in kb.items():
        # 写入实体
        cur.execute(
            "INSERT OR IGNORE INTO entities (entity_id, display_name) VALUES (?, ?)",
            (entity, entity)
        )

        source = data.get("source", "kb_core")
        for fact_text in data.get("facts", []):
            if not isinstance(fact_text, str) or not fact_text.strip():
                skipped += 1
                continue

            h = int(_hashlib.sha256(fact_text.encode("utf-8")).hexdigest()[:12], 16)
            try:
                cur.execute(
                    """INSERT OR IGNORE INTO facts_0
                       (hash, fact, source, confidence, created_at, hash_version, active, entity_id)
                       VALUES (?, ?, ?, 0.8, ?, 'sha256_v1', 1, ?)""",
                    (h, fact_text.strip(), source, now, entity)
                )
                if cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                skipped += 1

    conn.commit()

    # 更新计数器
    cur.execute("""
        UPDATE entities
        SET fact_count = (
            SELECT COUNT(*) FROM facts_0
            WHERE facts_0.entity_id = entities.entity_id
        )
    """)
    conn.commit()

    # 报告
    cur.execute("SELECT COUNT(*) FROM facts_0 WHERE entity_id IS NOT NULL AND entity_id != ''")
    total_filled = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM facts_0")
    total_all = cur.fetchone()[0]

    print(f"\n{'='*60}")
    print(f"✅ --insert-new 完成！")
    print(f"   新增事实: {inserted} 条")
    print(f"   跳过(重复/无效): {skipped} 条")
    print(f"   facts_0 entity_id 非空记录: {total_filled:,} / {total_all:,}")
    print(f"   entities 表实体数: {cur.execute('SELECT COUNT(*) FROM entities').fetchone()[0]}")
    print(f"{'='*60}")

    conn.close()
    print("🔒 数据库连接已关闭。")
    sys.exit(0)
