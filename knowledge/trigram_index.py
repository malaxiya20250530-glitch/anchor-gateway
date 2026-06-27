#!/usr/bin/env python3
"""
Trigram 倒排索引 — 大规模语义去重
=================================
用 SQLite 建立 trigram → fact_hash 倒排表，
O(1) 查找相似事实，替代随机采样。

原理:
  每个事实拆为 trigram 集合 → 倒排索引
  查询时取候选事实 → 计算 Jaccard → 阈值判定

用法:
  idx = TrigramIndex("knowledge/")
  idx.build(sample=100000)        # 建索引（10万条采样）
  similar = idx.search("新事实")   # 语义搜索
"""
import sqlite3, re, time
from pathlib import Path
from typing import List, Tuple, Set
from collections import Counter


def trigrams(text: str) -> Set[str]:
    """提取字符 3-gram"""
    text = re.sub(r'\s+', '', text)
    if len(text) < 3:
        return {text}
    return {text[i:i+3] for i in range(len(text) - 2)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class TrigramIndex:
    """Trigram 倒排索引 — SQLite 实现"""

    def __init__(self, knowledge_dir: str):
        self.dir = Path(knowledge_dir)
        idx_path = str(self.dir / "trigram_index.db")
        self._conn = sqlite3.connect(idx_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=OFF")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS trigrams (
                trigram TEXT NOT NULL,
                fact_hash INTEGER NOT NULL,
                PRIMARY KEY (trigram, fact_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_trigram ON trigrams(trigram);
            
            CREATE TABLE IF NOT EXISTS fact_cache (
                fact_hash INTEGER PRIMARY KEY,
                fact_text TEXT,
                trigram_count INTEGER
            );
        """)
        self._conn.commit()

    def build(self, sample: int = 0):
        """
        建倒排索引。
        sample=0: 全量 | sample>0: 采样
        """
        from knowledge.hash_utils import stable_hash

        db_path = str(self.dir / "fact_store.db")
        fdb = sqlite3.connect(db_path)

        if sample > 0:
            rows = fdb.execute(
                "SELECT fact FROM facts ORDER BY RANDOM() LIMIT ?", (sample,)
            ).fetchall()
        else:
            rows = fdb.execute("SELECT fact FROM facts").fetchall()

        fdb.close()

        print(f"🔧 建 trigram 索引 ({len(rows):,} 条)...")
        t0 = time.time()
        batch = []
        for fact_text, in rows:
            h = stable_hash(fact_text)
            tgs = trigrams(fact_text)
            for tg in tgs:
                batch.append((tg, h))
            # 缓存事实文本
            batch.append(("__FACT__", h))  # 标记，下面处理

            if len(batch) >= 50000:
                # 过滤出 trigram 条目
                tg_batch = [(t, h) for t, h in batch if t != "__FACT__"]
                self._conn.executemany(
                    "INSERT OR IGNORE INTO trigrams(trigram, fact_hash) VALUES(?,?)",
                    tg_batch
                )
                self._conn.commit()
                batch = []

        # 最后一批
        if batch:
            tg_batch = [(t, h) for t, h in batch if t != "__FACT__"]
            self._conn.executemany(
                "INSERT OR IGNORE INTO trigrams(trigram, fact_hash) VALUES(?,?)",
                tg_batch
            )
            self._conn.commit()

        elapsed = time.time() - t0
        cnt = self._conn.execute("SELECT COUNT(*) FROM trigrams").fetchone()[0]
        print(f"  ✅ {cnt:,} trigram 条目 ({elapsed:.0f}s)")

    def search(self, query: str, top_k: int = 10, threshold: float = 0.5) -> List[Tuple[str, float]]:
        """
        语义搜索最相似的事实。
        返回: [(fact_text, similarity), ...]
        """
        q_tgs = trigrams(query)
        if not q_tgs:
            return []

        # 查倒排索引，找候选
        placeholders = ','.join(['?'] * len(q_tgs))
        rows = self._conn.execute(
            f"SELECT fact_hash, COUNT(*) as cnt FROM trigrams WHERE trigram IN ({placeholders}) GROUP BY fact_hash ORDER BY cnt DESC LIMIT ?",
            (*q_tgs, top_k * 3)
        ).fetchall()

        if not rows:
            return []

        # 获取候选事实文本
        db_path = str(self.dir / "fact_store.db")
        fdb = sqlite3.connect(db_path)
        candidates = []
        for h, _ in rows:
            row = fdb.execute("SELECT fact FROM facts WHERE hash = ?", (h,)).fetchone()
            if row:
                candidates.append(row[0])
        fdb.close()

        # 计算 Jaccard
        results = []
        for fact in candidates:
            sim = jaccard(q_tgs, trigrams(fact))
            if sim >= threshold:
                results.append((fact, sim))

        results.sort(key=lambda x: -x[1])
        return results[:top_k]

    def stats(self) -> dict:
        cnt = self._conn.execute("SELECT COUNT(*) FROM trigrams").fetchone()[0]
        distinct = self._conn.execute("SELECT COUNT(DISTINCT trigram) FROM trigrams").fetchone()[0]
        return {"total_entries": cnt, "distinct_trigrams": distinct}


# ── CLI ──────────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys, json
    sys.path.insert(0, str(Path(__file__).parent.parent))

    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=int, default=0, help="建索引（采样数, 0=全量）")
    parser.add_argument("--search", type=str, help="语义搜索")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    idx = TrigramIndex(str(Path(__file__).parent))

    if args.build >= 0:
        idx.build(sample=args.build)

    if args.stats:
        print(json.dumps(idx.stats(), indent=2))

    if args.search:
        results = idx.search(args.search, top_k=5)
        for fact, sim in results:
            print(f"  [{sim:.2f}] {fact[:100]}")
        if not results:
            print("  未找到相似事实")
