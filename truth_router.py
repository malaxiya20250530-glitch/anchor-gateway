#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║             Truth Router v1 — 三层事实路由架构               ║
║                                                              ║
║  🟦 L1 Entity Layer   — kb_core.json     "你在问什么?"       ║
║  🟨 L2 Fact Layer     — fact_store.db    "世界有哪些事实?"    ║
║  🟪 L3 Trust Layer    — checker chain    "哪些值得相信?"     ║
║                                                              ║
║  设计原则: Entity ≠ Fact ≠ Truth                             ║
╚══════════════════════════════════════════════════════════════╝

用法:
  python truth_router.py "朱元璋发明了火锅"
  python truth_router.py --build-index     # 构建实体映射
  python truth_router.py --stats           # 查看统计
"""
import sqlite3, json, time, re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════
# 0. SQLite Schema — 事实底座
# ═══════════════════════════════════════════════════════════

SCHEMA_SQL = """
-- 事实分片表 (hash % N → facts_N)
CREATE TABLE IF NOT EXISTS facts_0 (
    hash         INTEGER PRIMARY KEY,   -- 确定性64位哈希
    fact         TEXT    NOT NULL,       -- 事实文本
    source       TEXT    DEFAULT '',     -- 来源标签
    confidence   REAL    DEFAULT 0.5,    -- 初始置信度
    created_at   TEXT    DEFAULT (datetime('now')),
    entity_id    TEXT,                   -- 关联实体名 (L1↔L2桥接)
    active       INTEGER DEFAULT 1      -- 软删除标记
);
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts_0(entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_active ON facts_0(active) WHERE active=1;

-- 实体→事实 映射表 (L1↔L2双向索引)
CREATE TABLE IF NOT EXISTS entity_fact_map (
    entity_name  TEXT    NOT NULL,
    fact_hash    INTEGER NOT NULL,
    PRIMARY KEY (entity_name, fact_hash)
);
CREATE INDEX IF NOT EXISTS idx_efm_entity ON entity_fact_map(entity_name);
CREATE INDEX IF NOT EXISTS idx_efm_hash   ON entity_fact_map(fact_hash);

-- 物化计数器 (O(1)总数查询)
CREATE TABLE IF NOT EXISTS fact_counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

-- 信念审计日志 (L3可解释性)
CREATE TABLE IF NOT EXISTS trust_audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT    NOT NULL,
    fact_hash    INTEGER NOT NULL,
    verdict      TEXT    NOT NULL,       -- verified|contradicted|uncertain
    belief       REAL    NOT NULL,       -- 信念分数 0.0~1.0
    confidence   REAL    NOT NULL,       -- 检查器置信度
    checker_name TEXT,                   -- 命中的检查器名
    created_at   TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_query ON trust_audit(query);
"""


# ═══════════════════════════════════════════════════════════
# 1. 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class Entity:
    """解析后的实体"""
    name: str
    facts: List[str] = field(default_factory=list)
    source: str = ""

@dataclass
class Fact:
    """检索到的事实"""
    hash: int
    text: str
    source: str
    entity: str
    confidence: float = 0.5

@dataclass
class ScoredFact:
    """评分后的事实"""
    fact: Fact
    belief: float           # 0.0~1.0
    verdict: str            # verified|contradicted|uncertain
    checker: str = ""       # 命中的检查器名

@dataclass
class RouteResult:
    """路由结果"""
    query: str
    entities: List[Entity]
    scored: List[ScoredFact]
    elapsed_ms: float
    summary: str


# ═══════════════════════════════════════════════════════════
# 2. TruthRouter — 主路由引擎
# ═══════════════════════════════════════════════════════════

class TruthRouter:
    """Truth Router v1 — 三层事实路由"""

    def __init__(self, kb_path: str = "kb_core.json",
                 db_path: str = "knowledge/fact_store.db"):
        self.kb_path = Path(kb_path)
        self.db_path = Path(db_path)

        # 加载语义索引
        self._entities: Dict[str, dict] = {}
        self._load_kb()

        # 连接事实底座
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

        # 惰性加载检查器
        self._anchor = None

    # ── 初始化 ──────────────────────────

    def _load_kb(self):
        """加载语义索引: kb_core.json + 硬编码 KNOWLEDGE_BASE"""
        if self.kb_path.exists():
            with open(self.kb_path) as f:
                self._entities = json.load(f)
        # 合并硬编码 KB (低优先级)
        try:
            from hallucination_detector import KNOWLEDGE_BASE
            for k, v in KNOWLEDGE_BASE.items():
                if k not in self._entities:
                    self._entities[k] = v
        except ImportError:
            pass

    def _init_db(self):
        """初始化事实底座 schema"""
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def _get_anchor(self):
        """惰性加载 AnchorEngine"""
        if self._anchor is None:
            from hallucination_detector import AnchorEngine
            self._anchor = AnchorEngine(enable_web=False, enable_graph=True)
        return self._anchor

    # ── L1: Entity Resolver ─────────────────────

    def resolve_entities(self, query: str) -> List[Entity]:
        """L1: 从查询中解析实体

        策略:
          1. 最长匹配: 按实体键长度降序遍历
          2. 过滤元实体: ≤2字 且 ≤2条事实 → 跳过
          3. 同义词扩展: SYNONYM_MAP
        """
        results = []
        seen = set()

        for key in sorted(self._entities.keys(), key=len, reverse=True):
            if key in query and key not in seen and len(key) >= 1:
                entry = self._entities[key]
                facts = entry.get("facts", [])
                # 过滤元实体
                if len(facts) <= 2 and len(key) <= 2:
                    continue
                results.append(Entity(
                    name=key,
                    facts=facts,
                    source=entry.get("source", ""),
                ))
                seen.add(key)

        return results[:5]

    # ── L2: Fact Retriever ────────────────────

    def retrieve_facts(self, entities: List[Entity],
                       query: str, top_k: int = 10) -> List[Fact]:
        """L2: 检索与查询相关的事实

        主路径: entity.facts (O(1), 已实体键索引)
        过滤:   仅保留与查询主题词相关的事实
        """
        facts = []
        seen_hashes = set()

        # 提取主题词 (去实体名后的残余关键词)
        topic_words = self._extract_topic_words(query, {e.name for e in entities})

        for entity in entities:
            for f_text in entity.facts:
                f_hash = self._hash_text(f_text)
                if f_hash in seen_hashes:
                    continue
                if not self._matches_topic(f_text, topic_words):
                    continue
                seen_hashes.add(f_hash)
                facts.append(Fact(
                    hash=f_hash,
                    text=f_text,
                    source=entity.source or "kb_core",
                    entity=entity.name,
                ))

        return facts[:top_k]

    @staticmethod
    def _hash_text(text: str) -> int:
        """确定性 64 位哈希"""
        import hashlib
        return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16) & 0x7FFFFFFFFFFFFFFF

    @staticmethod
    def _extract_topic_words(query: str, entity_names: set) -> set:
        """从查询中提取主题词 (去实体名，多粒度切分)"""
        topic = query
        for name in sorted(entity_names, key=len, reverse=True):
            topic = topic.replace(name, " ")
        words = set(w for w in topic.split() if not w.isspace() and len(w) >= 1)
        # 扩展 2-gram 子串
        bigrams = set()
        for w in list(words):
            for i in range(len(w) - 1):
                bigrams.add(w[i:i+2])
        return words | bigrams

    @staticmethod
    def _matches_topic(fact: str, topic_words: set) -> bool:
        """检查事实是否包含主题词"""
        if not topic_words:
            return True
        return any(w in fact for w in topic_words)

    # ── L3: Trust Scorer ──────────────────────

    def score_facts(self, query: str, facts: List[Fact]) -> List[ScoredFact]:
        """L3: 信念评估 — 检查器责任链 + 加权信念函数"""
        anchor = self._get_anchor()
        results = []

        for fact in facts:
            # 核心: _compare_with_fact 责任链检查
            verdict, confidence = anchor._compare_with_fact(query, fact.text)

            # 信念函数
            if verdict == "verified":
                belief = 0.6 + confidence * 0.4
            elif verdict == "contradicted":
                belief = max(0.01, (1.0 - confidence) * 0.3)
            else:
                belief = 0.5

            # 源加权
            if fact.source in ("kb_core", "史记", "明史", "物理学", "NASA"):
                belief = min(belief + 0.03, 1.0)

            # 记录命中检查器
            votes = anchor.get_vote_details().get("votes", [])
            checker_name = votes[0].get("checker", "") if votes else ""

            results.append(ScoredFact(
                fact=fact,
                belief=round(belief, 3),
                verdict=verdict,
                checker=checker_name,
            ))

            # 审计日志
            self._audit(query, fact.hash, verdict, belief, confidence, checker_name)

        return results

    def _audit(self, query: str, fact_hash: int, verdict: str,
               belief: float, confidence: float, checker: str):
        """写入信念审计日志"""
        try:
            self._conn.execute(
                """INSERT INTO trust_audit(query, fact_hash, verdict, belief, confidence, checker_name)
                   VALUES(?,?,?,?,?,?)""",
                (query[:200], fact_hash, verdict, belief, confidence, checker)
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass

    # ── 统一查询路由 ─────────────────────────

    def route(self, query: str, top_k: int = 5) -> RouteResult:
        """执行完整路由管道: L1 → L2 → L3 → 排序"""
        t0 = time.time()

        # L1
        entities = self.resolve_entities(query)
        if not entities:
            return RouteResult(query, [], [],
                               round((time.time()-t0)*1000,1),
                               "未匹配实体")

        # L2
        facts = self.retrieve_facts(entities, query, top_k=top_k * 3)
        if not facts:
            return RouteResult(query, entities, [],
                               round((time.time()-t0)*1000,1),
                               f"{len(entities)}实体, 0事实")

        # L3
        scored = self.score_facts(query, facts)

        # L4: 排序 — verified优先，belief降序
        order = {"verified": 0, "uncertain": 1, "contradicted": 2}
        scored.sort(key=lambda s: (order.get(s.verdict, 1), -s.belief))

        top = scored[:top_k]
        elapsed = round((time.time() - t0) * 1000, 1)
        v_count = sum(1 for s in top if s.verdict == "verified")
        c_count = sum(1 for s in top if s.verdict == "contradicted")

        return RouteResult(query, entities, top, elapsed,
                          f"{len(entities)}实体→{len(facts)}事实→{len(top)}结果 "
                          f"(✅{v_count} ❌{c_count})")

    # ── 管理接口 ─────────────────────────────

    def stats(self) -> dict:
        """系统统计"""
        row = self._conn.execute(
            "SELECT value FROM fact_counters WHERE name='total'"
        ).fetchone()
        fact_count = row[0] if row else 0
        entity_count = len(self._entities)

        # 审计统计
        row2 = self._conn.execute(
            "SELECT COUNT(*), AVG(belief) FROM trust_audit"
        ).fetchone()

        return {
            "entities": entity_count,
            "facts": fact_count,
            "audit_queries": row2[0] or 0,
            "avg_belief": round(row2[1] or 0, 3),
            "db_size_mb": round(
                self.db_path.stat().st_size / 1024 / 1024, 1
            ) if self.db_path.exists() else 0,
        }

    def build_entity_index(self, sample: int = 500):
        """构建实体→事实映射 (为不在 kb_core.json 的实体)"""
        import hashlib
        total = 0
        for name in list(self._entities.keys())[:sample]:
            if len(name) < 2:
                continue
            # LIKE搜索 fact_store 中包含实体名的事实
            cur = self._conn.execute(
                "SELECT hash FROM facts_0 WHERE fact LIKE ? AND entity_id IS NULL LIMIT 50",
                (f"%{name}%",)
            )
            rows = cur.fetchall()
            for (h,) in rows:
                self._conn.execute(
                    "INSERT OR IGNORE INTO entity_fact_map(entity_name, fact_hash) VALUES(?,?)",
                    (name, h)
                )
                total += 1
        self._conn.commit()
        print(f"  ✅ 构建 {total} 条实体→事实映射")

    def close(self):
        if self._conn:
            self._conn.close()


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def _fmt_verdict(v: str) -> str:
    return {"verified": "✅", "contradicted": "❌", "uncertain": "❓"}.get(v, "  ")


if __name__ == "__main__":
    import sys
    router = TruthRouter()

    if len(sys.argv) < 2:
        print(__doc__)
        router.close()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "--stats":
        s = router.stats()
        print("Truth Router v1 统计")
        print("─" * 30)
        for k, v in s.items():
            print(f"  {k}: {v}")

    elif cmd == "--build-index":
        print("🔨 构建实体→事实映射索引...")
        router.build_entity_index()

    else:
        query = " ".join(sys.argv[1:])
        result = router.route(query)

        print(f"🔍 {result.query}")
        print("─" * 50)

        # L1
        print(f"\n🟦 L1 Entity ({len(result.entities)}):")
        for e in result.entities:
            tags = f"[{e.source}]" if e.source else ""
            print(f"  {e.name} {tags} → {len(e.facts)} facts")

        # L2+L3
        print(f"\n🟨 L2 → 🟪 L3:")
        for i, sf in enumerate(result.scored, 1):
            icon = _fmt_verdict(sf.verdict)
            checker_tag = f" ({sf.checker})" if sf.checker else ""
            print(f"  {icon} #{i} [{sf.fact.entity}] belief={sf.belief:.2f}{checker_tag}")
            print(f"     {sf.fact.text[:90]}")

        print(f"\n⏱️  {result.elapsed_ms}ms — {result.summary}")

    router.close()
