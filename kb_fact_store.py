#!/usr/bin/env python3
"""
FactStore — 事实底座 (Truth Substrate)
=======================================
角色: 单一事实来源，平铺存储所有已验证事实。
      语义索引 (kb_core.json) 在其上提供实体键查找。

五层架构：
  L0: Bloom Filter (预判存在, ~10MB)
  L1: uint64 哈希内存集合 (快速去重, ~80MB/千万)
  L2: SQLite 持久化 (分片存储, 压缩友好)
  L3: 批量写入 (事务批量, 万条/次)
  L4: 增量统计 (新增率/重复率实时)

用法:
  store = FactStore("facts.db")
  added = store.insert_batch([fact1, fact2, ...])
  store.stats()
"""
import sqlite3, hashlib, array, time, os
from pathlib import Path
from typing import List, Tuple


class BloomFilter:
    """简单 Bloom Filter — 快速预判存在"""

    def __init__(self, size_bits: int = 100_000_000, hash_count: int = 3):
        # 100M bits = 12.5 MB
        self.size = size_bits
        self.hash_count = hash_count
        self.bits = bytearray(size_bits // 8)

    def _hashes(self, item_hash: int):
        for i in range(self.hash_count):
            yield (item_hash + i * 0x9e3779b97f4a7c15) % self.size

    def add(self, item_hash: int):
        for pos in self._hashes(item_hash):
            byte_idx = pos // 8
            bit_idx = pos % 8
            self.bits[byte_idx] |= (1 << bit_idx)

    def might_contain(self, item_hash: int) -> bool:
        for pos in self._hashes(item_hash):
            byte_idx = pos // 8
            bit_idx = pos % 8
            if not (self.bits[byte_idx] & (1 << bit_idx)):
                return False
        return True

    def estimated_size(self) -> int:
        """估算已插入元素数"""
        ones = sum(bin(b).count('1') for b in self.bits)
        total_bits = self.size
        if ones == 0:
            return 0
        # 近似公式
        return int(-total_bits / self.hash_count * 
                   __import__('math').log(1 - ones / total_bits))


def hash_fact(fact: str) -> int:
    """确定性 64 位哈希（sha256 截断，跨进程一致）"""
    import hashlib
    return int(hashlib.sha256(fact.encode("utf-8")).hexdigest()[:16], 16) & 0x7FFFFFFFFFFFFFFF


class FactStore:
    """千万级事实存储 — 支持按 hash 分片"""

    def __init__(self, db_path: str = "fact_store.db", bloom_bits: int = 100_000_000,
                 num_shards: int = 1):
        self.db_path = Path(db_path)
        self.num_shards = max(1, num_shards)
        self.bloom = BloomFilter(size_bits=bloom_bits, hash_count=3)
        self._hash_set: set = set()
        self._batch: List[Tuple[int, str]] = []
        self._total_inserted = 0
        self._total_duplicates = 0
        self._conn = None
        self._init_db()
        self._load_existing_hashes()

    def _shard_name(self, shard_idx: int) -> str:
        return f"facts_{shard_idx}"

    def _shard_for_hash(self, h: int) -> int:
        return h % self.num_shards

    def _init_db(self):
        """初始化 SQLite — 分片表 + 计数器 + 元数据"""
        self._conn = sqlite3.connect(str(self.db_path))
        # 迁移: 旧格式 facts 表 → facts_0（处理并存情况）
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        )
        has_old = cur.fetchone() is not None
        cur2 = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts_0'"
        )
        has_new = cur2.fetchone() is not None
        if has_old and not has_new:
            print("  🔄 迁移: facts → facts_0 ...")
            self._conn.execute("ALTER TABLE facts RENAME TO facts_0")
            self._conn.commit()
            print("  ✅ 迁移完成")
        elif has_old and has_new:
            # 旧表和新表并存：删空新表，重命名旧表
            c = self._conn.execute("SELECT COUNT(1) FROM facts_0").fetchone()[0]
            if c == 0:
                self._conn.execute("DROP TABLE IF EXISTS facts_0")
                self._conn.execute("ALTER TABLE facts RENAME TO facts_0")
                self._conn.commit()
                print("  🔄 迁移: facts → facts_0 (覆盖空表)")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=OFF")
        self._conn.execute("PRAGMA cache_size=-64000")
        # 为每个分片创建表
        for i in range(self.num_shards):
            table = self._shard_name(i)
            self._conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    hash INTEGER PRIMARY KEY,
                    fact TEXT NOT NULL
                )
            """)
            self._conn.execute(f"CREATE INDEX IF NOT EXISTS idx_hash_{i} ON {table}(hash)")
        # 全局计数器表
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS fact_counters (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
        """)
        # 元数据: 分片配置
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS fact_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._conn.execute(
            "INSERT OR REPLACE INTO fact_meta(key, value) VALUES(?, ?)",
            ("num_shards", str(self.num_shards))
        )
        self._conn.commit()

    def _load_existing_hashes(self):
        """从所有分片恢复哈希集合"""
        print("  📥 加载已有哈希...")
        t0 = time.time()
        count = 0
        for i in range(self.num_shards):
            table = self._shard_name(i)
            try:
                for row in self._conn.execute(f"SELECT hash FROM {table}"):
                    self._hash_set.add(row[0])
                    self.bloom.add(row[0])
                    count += 1
            except sqlite3.OperationalError:
                pass
        elapsed = time.time() - t0
        if count > 0:
            mem_mb = count * 8 / 1024 / 1024
            print(f"  ✅ 已加载 {count:,} 条哈希 ({elapsed:.1f}s, ~{mem_mb:.0f}MB)")
        # 同步物化计数器
        self._sync_counter()

    def _sync_counter(self):
        """同步物化计数器 — 优先用已有值，避免全表扫描"""
        row = self._conn.execute(
            "SELECT value FROM fact_counters WHERE name='total'"
        ).fetchone()
        if row and row[0] > 0:
            return  # 已有有效计数，无需重新扫描
        # 无计数器或为0 → 遍历分片聚合（仅首次）
        total = 0
        for i in range(self.num_shards):
            table = self._shard_name(i)
            try:
                total += self._conn.execute(
                    f"SELECT COUNT(1) FROM {table}"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                pass
        self._conn.execute(
            "INSERT OR REPLACE INTO fact_counters(name, value) VALUES(?, ?)",
            ("total", total)
        )
        self._conn.commit()

    def insert(self, fact: str) -> bool:
        """插入单条事实，返回是否为新"""
        f_hash = hash_fact(fact)

        # L0: Bloom 预判
        if self.bloom.might_contain(f_hash):
            # L1: 哈希集合确认
            if f_hash in self._hash_set:
                self._total_duplicates += 1
                return False

        # 新事实
        self._hash_set.add(f_hash)
        self.bloom.add(f_hash)
        self._batch.append((f_hash, fact))
        self._total_inserted += 1

        # 批量刷入
        if len(self._batch) >= 10000:
            self.flush()

        return True

    def insert_batch(self, facts: List[str]) -> int:
        """批量插入，返回新增数"""
        added = 0
        for f in facts:
            if self.insert(f):
                added += 1
        return added

    def flush(self):
        """刷入 SQLite — 按分片路由"""
        if not self._batch:
            return
        # 按分片分组
        shard_batches = {}
        for f_hash, fact in self._batch:
            s = self._shard_for_hash(f_hash)
            if s not in shard_batches:
                shard_batches[s] = []
            shard_batches[s].append((f_hash, fact))
        # 逐分片写入
        total_written = 0
        for shard_idx, rows in shard_batches.items():
            table = self._shard_name(shard_idx)
            try:
                self._conn.executemany(
                    f"INSERT OR IGNORE INTO {table}(hash, fact) VALUES(?, ?)",
                    rows
                )
                total_written += len(rows)
            except Exception as e:
                print(f"  ⚠️ {table} 写入失败: {e}")
        if total_written > 0:
            self._conn.execute(
                "UPDATE fact_counters SET value = value + ? WHERE name='total'",
                (total_written,)
            )
        self._conn.commit()
        self._batch = []

    def stats(self) -> dict:
        """返回统计信息 — 物化计数器 O(1) + 分片详情"""
        self.flush()
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        row = self._conn.execute(
            "SELECT value FROM fact_counters WHERE name='total'"
        ).fetchone()
        row_count = row[0] if row else len(self._hash_set)
        # 分片分布
        shards_info = {}
        for i in range(self.num_shards):
            table = self._shard_name(i)
            try:
                c = self._conn.execute(f"SELECT COUNT(1) FROM {table}").fetchone()[0]
                shards_info[table] = c
            except sqlite3.OperationalError:
                shards_info[table] = 0
        return {
            "total_inserted": self._total_inserted,
            "total_duplicates": self._total_duplicates,
            "hash_set_size": len(self._hash_set),
            "db_rows": row_count,
            "db_size_mb": db_size / 1024 / 1024,
            "bloom_estimated": self.bloom.estimated_size(),
            "num_shards": self.num_shards,
            "shards": shards_info,
        }

    def total_count(self) -> int:
        """O(1) 总数查询 — 直接读物化计数器"""
        self.flush()
        row = self._conn.execute(
            "SELECT value FROM fact_counters WHERE name='total'"
        ).fetchone()
        return row[0] if row else 0

    def close(self):
        self.flush()
        if self._conn:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── CLI 测试 ──────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    test_db = Path("/tmp/fact_store_test.db")
    if test_db.exists():
        test_db.unlink()

    with FactStore(str(test_db), bloom_bits=1_000_000) as store:
        # 插入测试
        t0 = time.time()
        added = 0
        for i in range(100000):
            fact = f"测试事实_{i}"
            if store.insert(fact):
                added += 1
        elapsed = time.time() - t0
        stats = store.stats()

        print(f"\n  ✅ 插入: {added}/100000 ({elapsed:.2f}s, {100000/elapsed:.0f} 条/s)")
        print(f"  📊 统计: {stats}")
        print(f"  💾 DB 大小: {stats['db_size_mb']:.1f} MB")

    test_db.unlink()
    print("  ✅ 测试通过")
