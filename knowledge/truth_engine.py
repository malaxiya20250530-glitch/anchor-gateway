#!/usr/bin/env python3
"""
Truth Engine — 真相评估引擎
=============================
从"是否存储"升级到"是否为真"

三层评估：
  L1: 证据追踪 — 事实来自哪里？可信度如何？
  L2: 冲突检测 — 是否有相反断言？
  L3: 真相判定 — 综合证据+冲突给出评估

用法:
  engine = TruthEngine(fact_store)
  result = engine.evaluate("朱元璋发明了火锅")
  # → TruthEvaluation(verdict, confidence, evidence, conflicts, reasoning)
"""
import re, hashlib, time, sqlite3
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path


# ── 实体/属性/值 提取器 ──────────────────────────

@dataclass
class EntityTriple:
    """从事实文本中提取的 (实体, 属性, 值) 三元组"""
    entity: str = ""
    property: str = ""
    value: str = ""
    negation: bool = False  # 是否包含否定词


def extract_triple(fact: str) -> EntityTriple:
    """从中文事实文本提取实体-属性-值"""
    t = EntityTriple()

    # 检测否定
    neg_words = ["不是", "没有", "并非", "不可以", "不能", "不", "未", "无"]
    for nw in neg_words:
        if nw in fact:
            t.negation = True
            break

    # 模式 "X的Y是Z" / "X的Y为Z"
    m = re.match(r"(.+?)的(.+?)[是为](.+)", fact)
    if m:
        t.entity = m.group(1).strip()
        t.property = m.group(2).strip()
        t.value = m.group(3).strip()
        return t

    # 模式 "X是Y" / "X为Y"
    m = re.match(r"(.+?)[是为](.+)", fact)
    if m:
        t.entity = m.group(1).strip()
        t.property = "类型"
        t.value = m.group(2).strip()
        return t

    # 模式 "X位于Y" / "X属于Y"
    m = re.match(r"(.+?)(位于|属于|等于|约等于)(.+)", fact)
    if m:
        t.entity = m.group(1).strip()
        t.property = m.group(2).strip()
        t.value = m.group(3).strip()
        return t

    # 模式 "XY年" / 数值
    m = re.search(r"(.+?)(\d{3,4})年", fact)
    if m:
        t.entity = m.group(1).strip()
        t.property = "年份"
        t.value = m.group(2)
        return t

    m = re.search(r"(.+?)(\d[\d,]*)", fact)
    if m:
        t.entity = m.group(1).strip()
        t.property = "数值"
        t.value = m.group(2)
        return t

    # 兜底
    t.entity = fact[:30]
    t.property = "陈述"
    t.value = fact[30:60] if len(fact) > 30 else fact
    return t


# ── 证据表 ────────────────────────────────────────

class EvidenceTracker:
    """证据追踪：每个事实的来源、时间、可信度"""

    def __init__(self, meta_db: str):
        self._conn = sqlite3.connect(meta_db)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_hash INTEGER NOT NULL,
                source_label TEXT,
                source_url TEXT,
                evidence_type TEXT DEFAULT 'generated',
                confidence REAL DEFAULT 0.5,
                retrieved_at TEXT,
                verified_by TEXT,
                notes TEXT
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_hash ON evidence(fact_hash)")
        self._conn.commit()

    def add(self, fact_hash: int, source: str, confidence: float = 0.5,
            evidence_type: str = "generated", source_url: str = ""):
        self._conn.execute(
            """INSERT OR IGNORE INTO evidence(fact_hash, source_label, source_url, evidence_type, confidence, retrieved_at)
               VALUES(?,?,?,?,?,datetime('now'))""",
            (fact_hash, source, source_url, evidence_type, confidence)
        )
        self._conn.commit()

    def get(self, fact_hash: int) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT source_label, confidence, evidence_type, retrieved_at FROM evidence WHERE fact_hash=?",
            (fact_hash,)
        ).fetchall()
        return [{"source": r[0], "confidence": r[1], "type": r[2], "date": r[3]} for r in rows]

    def close(self):
        self._conn.close()


# ── 冲突检测引擎 ──────────────────────────────────

class ConflictDetector:
    """检测事实之间的矛盾"""

    def __init__(self, meta_db: str):
        self._conn = sqlite3.connect(meta_db)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash_a INTEGER NOT NULL,
                hash_b INTEGER NOT NULL,
                conflict_type TEXT,
                entity TEXT,
                property TEXT,
                detected_at TEXT,
                resolved INTEGER DEFAULT 0,
                UNIQUE(hash_a, hash_b)
            )
        """)
        self._conn.commit()

    def detect(self, new_hash: int, new_fact: str, 
               existing_facts: List[Tuple[int, str]]) -> List[Dict]:
        """
        检查新事实是否与已有事实冲突。
        existing_facts: [(hash, fact_text), ...]
        返回: [{hash_a, hash_b, conflict_type, reason}, ...]
        """
        new_triple = extract_triple(new_fact)
        conflicts = []

        for ex_hash, ex_fact in existing_facts:
            ex_triple = extract_triple(ex_fact)

            # 同实体 + 同属性 + 互斥值 = 冲突
            if (new_triple.entity and ex_triple.entity and
                new_triple.entity == ex_triple.entity and
                new_triple.property == ex_triple.property):

                # 直接否定：一个说 X是Y，另一个说 X不是Y
                if new_triple.negation != ex_triple.negation:
                    # 提取核心值比较
                    new_core = new_triple.value.replace("不是", "").replace("没有", "").strip()
                    ex_core = ex_triple.value.replace("不是", "").replace("没有", "").strip()
                    if new_core == ex_core or new_core in ex_core or ex_core in new_core:
                        conflicts.append({
                            "hash_a": new_hash, "hash_b": ex_hash,
                            "conflict_type": "direct_negation",
                            "entity": new_triple.entity,
                            "property": new_triple.property,
                            "reason": f"'{new_fact[:60]}' 与 '{ex_fact[:60]}' 直接矛盾"
                        })
                        continue

                # 数值冲突：同属性不同值
                new_num = re.findall(r'\d+', new_triple.value)
                ex_num = re.findall(r'\d+', ex_triple.value)
                if new_num and ex_num and new_num != ex_num and not new_triple.negation and not ex_triple.negation:
                    conflicts.append({
                        "hash_a": new_hash, "hash_b": ex_hash,
                        "conflict_type": "value_conflict",
                        "entity": new_triple.entity,
                        "property": new_triple.property,
                        "reason": f"'{new_triple.entity}'的'{new_triple.property}'存在冲突值: {new_triple.value} vs {ex_triple.value}"
                    })

        # 保存冲突
        for c in conflicts:
            self._conn.execute(
                """INSERT OR IGNORE INTO conflicts(hash_a, hash_b, conflict_type, entity, property, detected_at)
                   VALUES(?,?,?,?,?,datetime('now'))""",
                (c["hash_a"], c["hash_b"], c["conflict_type"], c["entity"], c["property"])
            )
        self._conn.commit()

        return conflicts

    def get_conflicts_for(self, fact_hash: int) -> List[Dict]:
        """获取某事实的所有冲突"""
        rows = self._conn.execute(
            """SELECT hash_a, hash_b, conflict_type, entity, property, detected_at
               FROM conflicts WHERE hash_a=? OR hash_b=? AND resolved=0""",
            (fact_hash, fact_hash)
        ).fetchall()
        return [{"hash_a": r[0], "hash_b": r[1], "type": r[2], 
                 "entity": r[3], "property": r[4], "detected": r[5]} for r in rows]

    def close(self):
        self._conn.close()


# ── 真相评估结果 ──────────────────────────────────

@dataclass 
class TruthEvaluation:
    """真相评估结果"""
    statement: str = ""
    verdict: str = "not_found"      # supported | contradicted | uncertain | not_found
    confidence: float = 0.0
    evidence: List[Dict] = field(default_factory=list)
    conflicts: List[Dict] = field(default_factory=list)
    reasoning: str = ""
    source: str = ""

    def to_dict(self) -> Dict:
        return {
            "statement": self.statement,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "conflicts": self.conflicts,
            "reasoning": self.reasoning,
            "source": self.source,
        }


# ── Truth Engine 主类 ─────────────────────────────

class TruthEngine:
    """真相评估引擎"""

    def __init__(self, knowledge_dir: str = None):
        if knowledge_dir is None:
            knowledge_dir = str(Path(__file__).parent)
        self.dir = Path(knowledge_dir)
        meta_path = str(self.dir / "metadata.db")
        self.evidence = EvidenceTracker(meta_path)
        self.conflicts = ConflictDetector(meta_path)

        # 连接事实仓库
        db_path = self.dir / "fact_store.db"
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA query_only=ON")

        # 加载种子库
        import json
        seed_path = self.dir / "kb_core.json"
        self._seed_facts: Dict[int, str] = {}
        if seed_path.exists():
            with open(seed_path) as f:
                seed = json.load(f)
            for v in seed.values():
                for fact in v.get("facts", []):
                    h = self._hash(fact)
                    self._seed_facts[h] = fact
        
        # 构建种子库实体索引（用于模糊搜索）
        self._seed_entity_index: Dict[str, List[Tuple[int, str]]] = {}
        for h, fact in self._seed_facts.items():
            triple = extract_triple(fact)
            if triple.entity:
                key = triple.entity.lower()
                self._seed_entity_index.setdefault(key, []).append((h, fact))

    def _hash(self, fact: str) -> int:
        return int(hashlib.sha256(fact.encode()).hexdigest()[:16], 16) & 0x7FFFFFFFFFFFFFFF

    def evaluate(self, claim: str) -> TruthEvaluation:
        """
        评估一个断言是否为真。
        综合证据 + 冲突 + 来源可信度。
        """
        claim = claim.strip()
        h = self._hash(claim)
        result = TruthEvaluation(statement=claim)

        # 1. 精确匹配（DB）
        row = self._conn.execute(
            "SELECT fact, source, confidence FROM facts WHERE hash = ?", (h,)
        ).fetchone()

        if row:
            result.verdict = "supported"
            result.confidence = row[2] or 0.5
            result.source = row[1]
            result.evidence = self.evidence.get(h)
            result.conflicts = self.conflicts.get_conflicts_for(h)

            if result.conflicts:
                result.verdict = "contradicted"
                conflict_entities = set(c["entity"] for c in result.conflicts if c["entity"])
                result.reasoning = f"该事实存在 {len(result.conflicts)} 条冲突记录（涉及: {', '.join(list(conflict_entities)[:3])}）。虽然有正面证据，但存在矛盾断言。"
            else:
                sources = list(set(e["source"] for e in result.evidence)) if result.evidence else [row[1]]
                result.reasoning = f"精确匹配，来自 {', '.join(sources)}，置信度 {result.confidence:.0%}。"

            return result

        # 2. 种子库匹配
        if h in self._seed_facts:
            result.verdict = "supported"
            result.confidence = 0.9
            result.source = "kb_core"
            result.reasoning = "种子库精确匹配，高置信度。"
            return result

        # 3. 种子库模糊搜索（按实体匹配）
        seed_supporting = []
        seed_contradicting = []
        claim_triple = extract_triple(claim)
        if claim_triple.entity:
            entity_key = claim_triple.entity.lower()
            seed_matches = self._seed_entity_index.get(entity_key, [])
            for sh, sf in seed_matches[:20]:
                st = extract_triple(sf)
                if st.property == claim_triple.property:
                    if st.negation:
                        seed_contradicting.append(sf)
                    else:
                        seed_supporting.append(sf)
            if seed_matches and not seed_supporting and not seed_contradicting:
                # 同实体不同属性，也算弱支持
                seed_supporting = [sf for _, sf in seed_matches[:5]]

        if seed_supporting and not seed_contradicting:
            result.verdict = "supported"
            result.confidence = 0.85
            result.source = "kb_core"
            result.evidence = [{"source": "kb_core_entity", "confidence": 0.85, "type": "entity_match", "date": ""}]
            result.reasoning = f"种子库实体匹配：'{claim_triple.entity}' 找到 {len(seed_supporting)} 条相关事实，无矛盾。"
            return result
        elif seed_contradicting:
            result.verdict = "contradicted"
            result.confidence = 0.2
            result.conflicts = [{"hash_a": 0, "hash_b": 0, "type": "seed_negation", "entity": claim_triple.entity, "property": claim_triple.property}]
            result.reasoning = f"种子库存在矛盾证据：{seed_contradicting[0][:80]}"
            return result

        # 4. DB 模糊搜索（寻找相关事实）
        rows = self._conn.execute(
            "SELECT fact, hash, source, confidence FROM facts WHERE fact LIKE ? LIMIT 10",
            (f"%{claim[:20]}%",)
        ).fetchall()

        if rows:
            # 检查是否有矛盾
            related_triples = []
            for r in rows:
                related_triples.append((r[0], extract_triple(r[0])))

            claim_triple = extract_triple(claim)
            supporting = []
            contradicting = []

            for fact, triple in related_triples:
                if (triple.entity == claim_triple.entity and 
                    triple.property == claim_triple.property):
                    if triple.negation:
                        contradicting.append(fact)
                    else:
                        supporting.append(fact)

            if supporting and not contradicting:
                result.verdict = "partially_supported"
                result.confidence = 0.6
                result.evidence = [{"source": "fuzzy_match", "confidence": 0.6, "type": "related", "date": ""}]
                result.reasoning = f"找到 {len(supporting)} 条相关支持事实，无矛盾。"
            elif contradicting:
                result.verdict = "contradicted"
                result.confidence = 0.3
                result.conflicts = [{"hash_a": 0, "hash_b": 0, "type": "fuzzy_negation", "entity": claim_triple.entity, "property": claim_triple.property}]
                result.reasoning = f"找到矛盾证据：{contradicting[0][:80]}"
            else:
                result.verdict = "uncertain"
                result.confidence = 0.3
                result.reasoning = f"找到 {len(rows)} 条相关事实，但无直接支持或矛盾。"
        else:
            result.verdict = "not_found"
            result.reasoning = "未找到任何相关事实。"
            result.confidence = 0.0

        return result

    def insert_with_verification(self, fact: str, source: str = "manual", 
                                  confidence: float = 0.5) -> TruthEvaluation:
        """插入事实并自动检测冲突"""
        # 先用现有数据评估
        evaluation = self.evaluate(fact)

        if evaluation.verdict in ("contradicted",):
            # 已有矛盾，记录但不覆盖
            return evaluation

        # 无冲突或未知，可以插入
        h = self._hash(fact)
        self.evidence.add(h, source, confidence, "manual")
        return evaluation

    def close(self):
        self._conn.close()
        self.evidence.close()
        self.conflicts.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── CLI 测试 ──────────────────────────────────────
if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser(description="Truth Engine")
    parser.add_argument("--evaluate", type=str, help="评估断言")
    parser.add_argument("--triple", type=str, help="提取三元组（调试）")
    args = parser.parse_args()

    with TruthEngine() as engine:
        if args.triple:
            t = extract_triple(args.triple)
            print(f"实体: {t.entity}")
            print(f"属性: {t.property}")
            print(f"值:   {t.value}")
            print(f"否定: {t.negation}")

        if args.evaluate:
            result = engine.evaluate(args.evaluate)
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
