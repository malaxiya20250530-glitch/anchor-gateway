#!/usr/bin/env python3
"""
Entity Index Layer — 实体映射层
================================
角色: 语义路由表 — 连接语义索引(kb_core.json)与事实底座(fact_store.db)

双向映射:
  entity → [fact_hash, ...]   (实体到事实的倒排索引)
  fact_hash → [entity_tag, ...] (事实到实体的标签)

统一查询路径:
  query → entity match (kb_core.json)
       → fact retrieval (fact_store.db FTS)
       → trust scoring (trust system)
"""
import sqlite3, json, time
from pathlib import Path
from typing import List, Optional, Set


class EntityIndex:
    """实体映射层 — kb_core.json 语义索引 ↔ fact_store.db 事实底座"""

    def __init__(self, kb_core_path: str = "kb_core.json",
                 fact_db_path: str = "knowledge/fact_store.db"):
        self.kb_core_path = Path(kb_core_path)
        self.fact_db_path = Path(fact_db_path)
        self._entities: dict = {}       # entity_name → {"facts": [...], "source": "..."}
        self._entity_fact_cache: dict = {}  # entity → {fact_hash, ...}
        self._fact_entity_cache: dict = {}  # fact_hash → {entity_tag, ...}
        self._conn = None
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._load_entities()
        self._init_mapping_table()
        self._loaded = True

    def _load_entities(self):
        """加载语义索引中的实体列表"""
        if self.kb_core_path.exists():
            with open(self.kb_core_path) as f:
                self._entities = json.load(f)
        # 也加入同义词映射中的别名
        try:
            from hallucination_detector import SYNONYM_MAP
            for syn, target in SYNONYM_MAP.items():
                if target in self._entities and syn not in self._entities:
                    self._entities[syn] = self._entities[target]
        except ImportError:
            pass

    def _init_mapping_table(self):
        """初始化映射表"""
        self._conn = sqlite3.connect(str(self.fact_db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_fact_map (
                entity_name TEXT NOT NULL,
                fact_hash   INTEGER NOT NULL,
                PRIMARY KEY (entity_name, fact_hash)
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_efm_entity ON entity_fact_map(entity_name)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_efm_hash ON entity_fact_map(fact_hash)
        """)
        self._conn.commit()

    # ── 构建索引 ──────────────────────────────

    def build_index(self, entities: Optional[List[str]] = None,
                    sample_per_entity: int = 200) -> dict:
        """为指定实体构建映射（使用 FTS 高效检索）

        Args:
            entities: 要构建的实体名列表，None=全部
            sample_per_entity: 每个实体最多采样事实数
        Returns:
            {"indexed": count, "mapped": total_mappings, "elapsed": seconds}
        """
        self._ensure_loaded()
        if entities is None:
            entities = list(self._entities.keys())

        t0 = time.time()
        total_mapped = 0
        indexed = 0

        for name in entities:
            if not name or len(name) < 1:
                continue
            # 用 FTS 搜索包含实体名的事实
            hashes = self._search_entity_in_fts(name, limit=sample_per_entity)
            if hashes:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO entity_fact_map(entity_name, fact_hash) VALUES(?, ?)",
                    [(name, h) for h in hashes]
                )
                self._entity_fact_cache[name] = hashes
                total_mapped += len(hashes)
                indexed += 1

        self._conn.commit()
        elapsed = time.time() - t0
        return {"indexed": indexed, "mapped": total_mapped, "elapsed": round(elapsed, 1)}

    def _search_entity_in_fts(self, entity_name: str, limit: int = 200) -> Set[int]:
        """搜索包含实体名的事实哈希 — FTS优先，LIKE回退"""
        results = set()
        # 1. 尝试 FTS
        try:
            safe_name = entity_name.replace('"', '""')
            cur = self._conn.execute(
                "SELECT rowid FROM facts_fts WHERE facts_fts MATCH ? LIMIT ?",
                (f'"{safe_name}"', limit)
            )
            for (rowid,) in cur.fetchall():
                results.add(rowid)
            if results:
                return results
        except sqlite3.OperationalError:
            pass
        # 2. LIKE 回退（仅在需要时）
        try:
            cur = self._conn.execute(
                "SELECT hash FROM facts_0 WHERE fact LIKE ? LIMIT ?",
                (f"%{entity_name}%", limit)
            )
            for (h,) in cur.fetchall():
                results.add(h)
        except sqlite3.OperationalError:
            pass
        return results

    # ── 查询接口 ──────────────────────────────

    def get_facts_for_entity(self, entity_name: str) -> List[dict]:
        """查询: 实体 → 事实列表（kb_core.json 优先，fact_store.db 补充）"""
        self._ensure_loaded()
        facts = []

        # 主路径: kb_core.json 直接命中（O(1)）
        if entity_name in self._entities:
            for f_text in self._entities[entity_name].get("facts", []):
                facts.append({
                    "hash": hash(f_text) & 0x7FFFFFFFFFFFFFFF,
                    "fact": f_text,
                    "source": self._entities[entity_name].get("source", ""),
                })
            if facts:
                return facts

        # 补充路径: entity_fact_map 映射表
        cur = self._conn.execute(
            "SELECT fact_hash FROM entity_fact_map WHERE entity_name=?",
            (entity_name,)
        )
        hashes = [row[0] for row in cur.fetchall()]
        if hashes:
            return self._resolve_hashes_to_facts(hashes)
        return []

    def get_entities_for_fact(self, fact_hash: int) -> List[str]:
        """查询: 事实 → 实体标签列表"""
        self._ensure_loaded()
        if fact_hash in self._fact_entity_cache:
            return list(self._fact_entity_cache[fact_hash])

        cur = self._conn.execute(
            "SELECT entity_name FROM entity_fact_map WHERE fact_hash=?",
            (fact_hash,)
        )
        entities = [row[0] for row in cur.fetchall()]
        self._fact_entity_cache[fact_hash] = set(entities)
        return entities

    def _resolve_hashes_to_facts(self, hashes) -> List[dict]:
        """将事实哈希解析为完整事实文本"""
        facts = []
        for h in list(hashes)[:50]:  # 最多返回50条
            cur = self._conn.execute(
                "SELECT fact FROM facts_0 WHERE hash=?", (h,)
            )
            row = cur.fetchone()
            if row:
                facts.append({"hash": h, "fact": row[0]})
        return facts

    # ── 统一查询路径 ──────────────────────────

    def query(self, text: str, top_k: int = 5) -> List[dict]:
        """统一查询: entity match → fact filter → scoring

        Args:
            text: 查询文本
            top_k: 返回结果数
        Returns:
            [{"entity": str, "fact": str, "hash": int, "source": str}, ...]
        """
        self._ensure_loaded()
        results = []

        # 1. 实体匹配: 在 kb_core.json 实体键中搜索
        matched_entities = []
        for entity_name in sorted(self._entities.keys(), key=len, reverse=True):
            if entity_name in text and len(entity_name) >= 1:
                matched_entities.append(entity_name)
                if len(matched_entities) >= 3:
                    break

        # 2. 事实检索: 从 fact_store.db 获取匹配事实
        for entity in matched_entities:
            facts = self.get_facts_for_entity(entity)
            src = self._entities.get(entity, {}).get("source", "")
            for f in facts[:top_k]:
                results.append({
                    "entity": entity,
                    "fact": f["fact"],
                    "hash": f["hash"],
                    "source": src,
                })

        return results[:top_k]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# ── CLI ────────────────────────────────────────
if __name__ == "__main__":
    import sys
    idx = EntityIndex()

    if len(sys.argv) > 1 and sys.argv[1] == "build":
        print("🔨 构建实体映射索引...")
        result = idx.build_index()
        print(f"  ✅ 已索引 {result['indexed']} 个实体, {result['mapped']} 条映射 ({result['elapsed']}s)")
    elif len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"🔍 查询: {query}")
        results = idx.query(query)
        for r in results:
            print(f"  [{r['entity']}] {r['fact'][:80]}  ({r['source']})")
    else:
        print("用法: python entity_index.py build       # 构建索引")
        print("      python entity_index.py <query>     # 查询")

    idx.close()
