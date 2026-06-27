#!/usr/bin/env python3
"""
Query Orchestrator — 统一查询路由器
=====================================
三层事实架构的调度中心:

  L1 Entity Resolver  → kb_core.json    "你在问什么?"
  L2 Fact Retriever   → fact_store.db    "世界上有哪些事实?"
  L3 Trust Scorer     → metadata.db      "哪些事实值得相信?"

标准流程:
  User Query
    → Entity Resolver (语义入口)
    → Fact Retriever  (事实检索)
    → Trust Scorer    (信念评估)
    → Ranked Answer   (排序输出)

设计原则:
  Entity ≠ Fact  — 理解问题 ≠ 找事实
  Fact ≠ Truth   — 事实 ≠ 真相
"""
import time, json, sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class ResolvedEntity:
    """解析后的实体"""
    name: str
    entity_id: str          # 在 kb_core.json 中的键名
    match_type: str         # "exact" | "synonym" | "substring"
    facts: List[str] = field(default_factory=list)


@dataclass
class RetrievedFact:
    """检索到的事实"""
    fact_id: int            # fact_store.db 中的 hash
    statement: str          # 事实文本
    source: str             # 来源
    entity: str             # 关联实体
    confidence: float = 0.5 # 初始置信度


@dataclass
class ScoredFact:
    """评分后的事实"""
    fact: RetrievedFact
    belief: float           # 信念分数 0.0~1.0
    verdict: str            # "verified" | "contradicted" | "uncertain"
    breakdown: Dict = field(default_factory=dict)


@dataclass
class QueryResult:
    """查询结果"""
    query: str
    entities: List[ResolvedEntity]
    scored_facts: List[ScoredFact]
    elapsed_ms: float
    summary: str = ""

    @property
    def top_fact(self) -> Optional[ScoredFact]:
        return self.scored_facts[0] if self.scored_facts else None

    @property
    def belief_range(self) -> Tuple[float, float]:
        if not self.scored_facts:
            return (0.0, 0.0)
        scores = [s.belief for s in self.scored_facts]
        return (min(scores), max(scores))


# ═══════════════════════════════════════════════════════════
# L1: Entity Resolver — 语义入口层
# ═══════════════════════════════════════════════════════════

class EntityResolver:
    """L1: 将查询文本解析为实体列表"""

    def __init__(self, kb_core_path: str = "kb_core.json"):
        self._entities: Dict = {}
        self._synonyms: Dict = {}
        if Path(kb_core_path).exists():
            with open(kb_core_path) as f:
                self._entities = json.load(f)
        # 合并硬编码 KNOWLEDGE_BASE (优先级低于 kb_core.json)
        try:
            from hallucination_detector import KNOWLEDGE_BASE
            for k, v in KNOWLEDGE_BASE.items():
                if k not in self._entities:
                    self._entities[k] = v
        except ImportError:
            pass
        self._load_synonyms()

    def _load_synonyms(self):
        """加载同义词映射"""
        try:
            from hallucination_detector import SYNONYM_MAP
            self._synonyms = SYNONYM_MAP
        except ImportError:
            pass

    def resolve(self, query: str) -> List[ResolvedEntity]:
        """解析查询文本中的实体

        策略:
          1. 精确匹配: 按长度降序遍历实体键
          2. 同义词扩展: 检查同义词映射
          3. 子串匹配: 短实体键出现在长查询中
        """
        results = []
        seen_names = set()

        # 1. 精确匹配 (最长优先, 过滤元实体)
        for key in sorted(self._entities.keys(), key=len, reverse=True):
            if key in query and key not in seen_names:
                facts = self._entities[key].get("facts", [])
                # 跳过元实体: 仅有1-2条事实且键名≤2字的语义标签
                if len(facts) <= 2 and len(key) <= 2:
                    continue
                results.append(ResolvedEntity(
                    name=key, entity_id=key,
                    match_type="exact",
                    facts=facts,
                ))
                seen_names.add(key)

        # 2. 同义词扩展
        for syn, target in self._synonyms.items():
            if syn in query and target not in seen_names:
                if target in self._entities:
                    results.append(ResolvedEntity(
                        name=syn, entity_id=target,
                        match_type="synonym",
                        facts=self._entities[target].get("facts", []),
                    ))
                    seen_names.add(target)

        return results[:5]  # 最多5个实体


# ═══════════════════════════════════════════════════════════
# L2: Fact Retriever — 事实存储层
# ═══════════════════════════════════════════════════════════

class FactRetriever:
    """L2: 从事实底座检索事实"""

    def __init__(self, fact_db_path: str = "knowledge/fact_store.db"):
        self.db_path = fact_db_path

    def retrieve(self, entities: List[ResolvedEntity],
                 top_k: int = 10, query: str = "") -> List[RetrievedFact]:
        """为给定实体检索相关事实

        主路径: kb_core.json 实体键内的 facts 列表 (快速)
        补充路径: fact_store.db entity_fact_map
        相关性过滤: 仅保留与查询语义重叠的事实
        """
        facts = []
        seen = set()

        entity_names = {e.name for e in entities}
        for entity in entities:
            for f_text in entity.facts:
                f_hash = hash(f_text) & 0x7FFFFFFFFFFFFFFF
                if f_hash not in seen and self._is_relevant(
                    query, f_text, entity_names):
                    seen.add(f_hash)
                    facts.append(RetrievedFact(
                        fact_id=f_hash,
                        statement=f_text,
                        source=self._get_source(entity.entity_id),
                        entity=entity.name,
                    ))

            if not entity.facts:
                facts.extend(self._retrieve_from_db(entity, seen, top_k))

        return facts[:top_k]

    @staticmethod
    def _is_relevant(query: str, fact: str, entity_names: set = None,
                     min_topic_hits: int = 1) -> bool:
        """实体感知相关性过滤

        策略:
          1. 从查询中移除实体名，得到主题关键词
          2. 事实必须包含至少一个主题关键词
          例如 "朱元璋发明了火锅", entities={"朱元璋","火锅"}
          → 主题词=["发明","了"] → 事实需含 "发明" 或 "了"
          → "朱元璋没有发明火锅" ✅ (含 "发明")
          → "朱元璋建立明朝于1368年" ❌

        回退: 如果 query 在 entity_names 去重后为空，保留所有事实
        """
        if not query:
            return True
        # 去除实体名
        topic = query
        # 仅移除多字实体名（≥2字）避免吃掉主题动词
        if entity_names:
            multi_char = sorted(
                [n for n in entity_names if len(n) >= 2],
                key=len, reverse=True
            )
            for name in multi_char:
                topic = topic.replace(name, " ")
        # 多粒度切分: 单个词 + 所有2-gram子串
        raw_words = [w for w in topic.split() if len(w) >= 1 and not w.isspace()]
        topic_words = set(raw_words)
        for w in raw_words:
            for i in range(len(w) - 1):
                topic_words.add(w[i:i+2])
        if not topic_words:
            return True  # 纯实体查询，保留所有
        # 检查事实是否包含主题词
        return any(w in fact for w in topic_words)

    def _retrieve_from_db(self, entity: ResolvedEntity,
                          seen: set, limit: int) -> List[RetrievedFact]:
        """从 SQLite entity_fact_map 表补充检索"""
        facts = []
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute(
                "SELECT fact_hash FROM entity_fact_map WHERE entity_name=? LIMIT ?",
                (entity.name, limit)
            )
            for (f_hash,) in cur.fetchall():
                if f_hash in seen:
                    continue
                seen.add(f_hash)
                cur2 = conn.execute(
                    "SELECT fact FROM facts_0 WHERE hash=?", (f_hash,)
                )
                row = cur2.fetchone()
                if row:
                    facts.append(RetrievedFact(
                        fact_id=f_hash, statement=row[0],
                        source="fact_store", entity=entity.name,
                    ))
            conn.close()
        except sqlite3.OperationalError:
            pass
        return facts

    def _get_source(self, entity_id: str) -> str:
        try:
            with open("kb_core.json") as f:
                kb = json.load(f)
            return kb.get(entity_id, {}).get("source", "kb_core")
        except (FileNotFoundError, json.JSONDecodeError):
            return "kb_core"


# ═══════════════════════════════════════════════════════════
# L3: Trust Scorer — 信念评估层
# ═══════════════════════════════════════════════════════════

class TrustScorer:
    """L3: 信念评估 — 对事实进行可信度评分"""

    def __init__(self):
        self._anchor = None  # 惰性加载 AnchorEngine

    def _get_anchor(self):
        if self._anchor is None:
            from hallucination_detector import AnchorEngine
            self._anchor = AnchorEngine(enable_web=False, enable_graph=True)
        return self._anchor

    def score(self, query: str, facts: List[RetrievedFact]) -> List[ScoredFact]:
        """对每条事实进行信念评分

        校验方式:
          1. 检查器责任链: 将 query 与每个事实对比
          2. 图谱推理: GraphContradictionChecker
          3. 源权重: kb_core > fact_store
        """
        anchor = self._get_anchor()
        results = []

        for fact in facts:
            verdict, confidence = anchor._compare_with_fact(query, fact.statement)
            # 信念分数: verified高, contradicted低, uncertain中等
            if verdict == "verified":
                belief = 0.6 + confidence * 0.4
            elif verdict == "contradicted":
                belief = (1.0 - confidence) * 0.3
            else:
                belief = 0.5

            # 源加权
            if fact.source in ("kb_core", "史记", "明史", "物理学"):
                belief = min(belief + 0.05, 1.0)

            results.append(ScoredFact(
                fact=fact,
                belief=round(belief, 3),
                verdict=verdict,
                breakdown={
                    "raw_verdict": verdict,
                    "raw_confidence": confidence,
                    "source_bonus": fact.source in ("kb_core", "史记", "明史"),
                }
            ))

        return results


# ═══════════════════════════════════════════════════════════
# Query Orchestrator — 统一查询路由器
# ═══════════════════════════════════════════════════════════

class QueryOrchestrator:
    """统一查询路由器 — 协调 L1→L2→L3 三层管道"""

    def __init__(self):
        self.resolver = EntityResolver()
        self.retriever = FactRetriever()
        self.scorer = TrustScorer()

    def query(self, text: str, top_k: int = 5) -> QueryResult:
        """执行完整查询管道

        [1] Entity Resolver   → 解析实体
        [2] Fact Retriever    → 检索事实
        [3] Trust Scorer      → 信念评分
        [4] Rank & Output     → 排序返回
        """
        t0 = time.time()

        # L1: 解析实体
        entities = self.resolver.resolve(text)
        if not entities:
            return QueryResult(
                query=text, entities=[], scored_facts=[],
                elapsed_ms=round((time.time() - t0) * 1000, 1),
                summary="未找到匹配实体"
            )

        # L2: 检索事实
        facts = self.retriever.retrieve(entities, top_k=top_k * 2, query=text)
        if not facts:
            return QueryResult(
                query=text, entities=entities, scored_facts=[],
                elapsed_ms=round((time.time() - t0) * 1000, 1),
                summary=f"已解析 {len(entities)} 个实体，但未检索到事实"
            )

        # L3: 信念评分
        scored = self.scorer.score(text, facts)

        # L4: 排序 — verified 优先，然后按 belief 降序
        verdict_order = {"verified": 0, "uncertain": 1, "contradicted": 2}
        scored.sort(key=lambda s: (verdict_order.get(s.verdict, 1), -s.belief))

        elapsed = round((time.time() - t0) * 1000, 1)
        top = scored[:top_k]

        # 汇总
        verified = sum(1 for s in top if s.verdict == "verified")
        contradicted = sum(1 for s in top if s.verdict == "contradicted")
        summary = (f"{len(entities)} 实体 → {len(facts)} 事实 → "
                   f"{len(top)} 结果 (✅{verified} ❌{contradicted})")

        return QueryResult(
            query=text, entities=entities, scored_facts=top,
            elapsed_ms=elapsed, summary=summary,
        )


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    orch = QueryOrchestrator()

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"🔍 {query}")
        print("─" * 50)

        result = orch.query(query)

        # L1 输出
        print(f"\n🟦 L1 Entity Resolver ({len(result.entities)} 实体):")
        for e in result.entities:
            print(f"  {e.name} [{e.match_type}] → {len(e.facts)} facts")

        # L2+L3 输出
        print(f"\n🟨 L2→🟪 L3 Facts (belief排序):")
        for i, sf in enumerate(result.scored_facts, 1):
            icon = "✅" if sf.verdict == "verified" else "❌" if sf.verdict == "contradicted" else "❓"
            print(f"  {icon} #{i} [{sf.fact.entity}] belief={sf.belief:.2f} | {sf.fact.statement[:70]}")

        print(f"\n⏱️  {result.elapsed_ms}ms — {result.summary}")
    else:
        print("Query Orchestrator — 三层事实架构")
        print("用法: python query_orchestrator.py <查询文本>")
        print()
        print("示例:")
        print("  python query_orchestrator.py 朱元璋发明了火锅")
        print("  python query_orchestrator.py 光速是无限的吗")
