#!/usr/bin/env python3
"""
去重引擎 — 三层防护
====================
L1: 精确哈希去重（sha256, 零碰撞）
L2: 语义去重（n-gram Jaccard, 检测改写/近义重复）
L3: 增量迁移（版本演进不重算全库）

用法:
  engine = DedupEngine("knowledge/")
  is_new, dup_of = engine.check("新事实文本")
"""
import sqlite3, hashlib, re
from pathlib import Path
from typing import Optional, Tuple, List
from collections import defaultdict


# ── 语义指纹 ────────────────────────────────────

def ngram_fingerprint(text: str, n: int = 3) -> set:
    """字符 n-gram 集合（语义指纹）"""
    text = re.sub(r'\s+', '', text)
    return {text[i:i+n] for i in range(len(text) - n + 1)}


def jaccard(a: set, b: set) -> float:
    """Jaccard 相似度"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── 增量迁移器 ──────────────────────────────────

class IncrementalMigrator:
    """增量哈希迁移 — 只处理未迁移行"""

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS migration_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_version TEXT,
                to_version TEXT,
                rows_migrated INTEGER,
                last_rowid INTEGER,
                completed_at TEXT,
                status TEXT DEFAULT 'running'
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS hash_index_v1 (
                rowid INTEGER PRIMARY KEY,
                v1_hash INTEGER
            )
        """)
        self._conn.commit()

    def needs_migration(self, target_version: str = "sha256_v1") -> int:
        """返回需要迁移的行数"""
        try:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM facts WHERE hash_version != ? OR hash_version IS NULL",
                (target_version,)
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0
        return count

    def migrate_incremental(self, target_version: str = "sha256_v1", 
                            batch_size: int = 50000) -> int:
        """增量迁移：只处理未迁移的行"""
        total = self.needs_migration(target_version)
        if total == 0:
            print("  无需迁移")
            return 0

        print(f"  需迁移: {total:,} 行")

        # 记录迁移开始
        self._conn.execute(
            "INSERT INTO migration_log(from_version, to_version, status) VALUES(?,?,'running')",
            ("unknown", target_version)
        )
        self._conn.commit()
        log_id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 备份 v1 hash
        try:
            self._conn.execute("""
                INSERT OR IGNORE INTO hash_index_v1(rowid, v1_hash)
                SELECT rowid, hash FROM facts WHERE hash_version != ? OR hash_version IS NULL
            """, (target_version,))
            self._conn.commit()
        except:
            pass

        # 增量更新
        migrated = 0
        while True:
            rows = self._conn.execute(
                """SELECT rowid, fact FROM facts 
                   WHERE hash_version != ? OR hash_version IS NULL 
                   LIMIT ?""",
                (target_version, batch_size)
            ).fetchall()
            if not rows:
                break

            from knowledge.hash_utils import stable_hash
            updates = [(stable_hash(r[1]), target_version, r[0]) for r in rows]
            self._conn.executemany(
                "UPDATE facts SET hash = ?, hash_version = ? WHERE rowid = ?",
                updates
            )
            self._conn.commit()
            migrated += len(rows)

        # 完成
        self._conn.execute(
            "UPDATE migration_log SET rows_migrated=?, completed_at=datetime('now'), status='completed' WHERE id=?",
            (migrated, log_id)
        )
        self._conn.commit()
        print(f"  ✅ 迁移: {migrated:,} 行")
        return migrated


# ── 语义去重引擎 ────────────────────────────────

class SemanticDedup:
    """L2 语义去重 — 检测改写/近义重复"""

    def __init__(self, db_path: str, meta_db: str):
        self._conn = sqlite3.connect(db_path)
        self._meta = sqlite3.connect(meta_db)
        self._meta.execute("PRAGMA journal_mode=WAL")
        self._meta.execute("""
            CREATE TABLE IF NOT EXISTS semantic_duplicates (
                hash_a INTEGER PRIMARY KEY,
                hash_b INTEGER,
                similarity REAL,
                detected_at TEXT,
                reviewed INTEGER DEFAULT 0
            )
        """)
        self._meta.execute("CREATE INDEX IF NOT EXISTS idx_semdup_b ON semantic_duplicates(hash_b)")
        self._meta.commit()

    def check(self, text: str, sample_size: int = 1000) -> Tuple[bool, Optional[str]]:
        """
        检查新文本是否与已有事实语义重复。
        返回: (is_dup, similar_fact_text)
        """
        fp_new = ngram_fingerprint(text)

        # 从 DB 随机采样已有事实
        rows = self._conn.execute(
            "SELECT fact, hash FROM facts ORDER BY RANDOM() LIMIT ?",
            (sample_size,)
        ).fetchall()

        best_sim = 0.0
        best_fact = None

        for fact, h in rows:
            sim = jaccard(fp_new, ngram_fingerprint(fact))
            if sim > best_sim:
                best_sim = sim
                best_fact = fact

        if best_sim >= 0.85:
            return (True, best_fact)
        if best_sim >= 0.70:
            return (True, best_fact)  # 可能重复，标记
        return (False, None)

    def batch_dedup(self, sample_size: int = 5000, threshold: float = 0.85) -> int:
        """批量语义去重（对已有库运行）"""
        from knowledge.hash_utils import stable_hash

        rows = self._conn.execute(
            "SELECT fact, hash FROM facts ORDER BY RANDOM() LIMIT ?",
            (sample_size,)
        ).fetchall()

        fingerprints = []
        for fact, h in rows:
            fingerprints.append((h, fact, ngram_fingerprint(fact)))

        found = 0
        for i in range(len(fingerprints)):
            for j in range(i + 1, len(fingerprints)):
                sim = jaccard(fingerprints[i][2], fingerprints[j][2])
                if sim >= threshold:
                    ha, hb = fingerprints[i][0], fingerprints[j][0]
                    self._meta.execute(
                        """INSERT OR IGNORE INTO semantic_duplicates(hash_a, hash_b, similarity, detected_at)
                           VALUES(?,?,?,datetime('now'))""",
                        (min(ha, hb), max(ha, hb), sim)
                    )
                    found += 1

        self._meta.commit()
        return found


# ── 双版本查询 ──────────────────────────────────

class DualHashLookup:
    """双版本哈希查询 — 自动 fallback"""

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path)

    def lookup(self, fact: str) -> Optional[dict]:
        """
        双版本查询：先查 v2，再查 v1 fallback
        """
        from knowledge.hash_utils import stable_hash
        h = stable_hash(fact)

        # 优先 v2
        row = self._conn.execute(
            "SELECT fact, source, confidence, hash_version FROM facts WHERE hash = ?",
            (h,)
        ).fetchone()

        # 如果 v2 没找到，尝试 v1
        if not row:
            try:
                row = self._conn.execute(
                    """SELECT f.fact, f.source, f.confidence, f.hash_version 
                       FROM facts f JOIN hash_index_v1 v ON f.rowid = v.rowid 
                       WHERE v.v1_hash = ? LIMIT 1""",
                    (h,)
                ).fetchone()
            except:
                pass

        if row:
            return {
                "fact": row[0], "source": row[1],
                "confidence": row[2], "hash_version": row[3]
            }
        return None

    def stats(self) -> dict:
        """版本分布统计"""
        try:
            rows = self._conn.execute(
                "SELECT hash_version, COUNT(*) FROM facts GROUP BY hash_version"
            ).fetchall()
            return {r[0] or "unknown": r[1] for r in rows}
        except:
            return {}


# ── CLI ──────────────────────────────────────────
if __name__ == "__main__":
    import argparse, json, sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    parser = argparse.ArgumentParser(description="去重引擎")
    parser.add_argument("--check", type=str, help="检查语义重复")
    parser.add_argument("--migrate", action="store_true", help="增量迁移")
    parser.add_argument("--stats", action="store_true", help="版本统计")
    parser.add_argument("--dedup", type=int, default=0, help="批量语义去重（采样数）")
    args = parser.parse_args()

    KNOWLEDGE = Path(__file__).parent
    DB = str(KNOWLEDGE / "fact_store.db")
    META = str(KNOWLEDGE / "metadata.db")

    if args.migrate:
        m = IncrementalMigrator(DB)
        m.migrate_incremental()

    if args.stats:
        l = DualHashLookup(DB)
        print(json.dumps(l.stats(), indent=2, ensure_ascii=False))

    if args.check:
        s = SemanticDedup(DB, META)
        is_dup, similar = s.check(args.check)
        print(f"语义重复: {'✅ 是' if is_dup else '❌ 否'}")
        if similar:
            print(f"最相似: {similar[:120]}")

    if args.dedup > 0:
        s = SemanticDedup(DB, META)
        found = s.batch_dedup(sample_size=args.dedup)
        print(f"发现 {found} 对语义重复")
