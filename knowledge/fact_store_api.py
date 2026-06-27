#!/usr/bin/env python3
"""
FactStore — 统一知识库 API
============================
屏蔽底层存储差异，上层只需调用统一接口。

存储分层:
  L0: kb_core.json     ~12 万  Bootstrap 种子库 (高质量)
  L1: fact_store.db    ~1067 万 Production 事实仓库

API:
  lookup(fact)        → (found, source, confidence)
  search(query)       → [matching facts]
  verify(claim)       → (verdict, evidence, confidence)
  get_source(fact)    → source label
  get_confidence(fact)→ confidence score
  stats()             → 统计信息
"""
import sys, sqlite3, json, re, time
from pathlib import Path

# 独立运行时路径修正
try:
    from knowledge.hash_utils import stable_hash as hash_fact
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from knowledge.hash_utils import stable_hash as hash_fact

from typing import Optional, List, Tuple, Dict, Any

class FactStore:
    """统一知识库 — JSON 种子 + SQLite 仓库"""

    def __init__(self, knowledge_dir: str = None):
        if knowledge_dir is None:
            knowledge_dir = str(Path(__file__).parent)
        self.dir = Path(knowledge_dir)
        self._conn: Optional[sqlite3.Connection] = None
        self._seed: Dict[str, Any] = {}
        self._seed_hashes: set = set()
        self._seed_ready = False
        self._init()

    def _init(self):
        """初始化连接并加载种子库"""
        # SQLite
        db_path = self.dir / "fact_store.db"
        if db_path.exists():
            self._conn = sqlite3.connect(str(db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA query_only=ON")
        else:
            self._conn = None

        # JSON 种子库
        seed_path = self.dir / "kb_core.json"
        if seed_path.exists():
            t0 = time.time()
            with open(seed_path) as f:
                self._seed = json.load(f)
            # 预计算哈希
            for v in self._seed.values():
                for f in v.get("facts", []):
                    self._seed_hashes.add(hash_fact(f))
            self._seed_ready = True
            kb_keys = len([k for k in self._seed if not k.startswith("_")])
            elapsed = (time.time() - t0) * 1000
            print(f"  📄 Seed KB: {kb_keys} 键, {len(self._seed_hashes):,} 事实 ({elapsed:.0f}ms)")

        if self._conn:
            db_count = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            print(f"  📦 Fact DB: {db_count:,} 事实")
        else:
            print(f"  ⚠️  Fact DB 未找到")

    # ── 核心 API ─────────────────────────────────

    def lookup(self, fact: str) -> Tuple[bool, str, float]:
        """
        精确查询一条事实是否存在。
        返回: (found, source, confidence)
        """
        fact = fact.strip()
        f_hash = hash_fact(fact)

        # L1: SQLite 仓库（最快）
        if self._conn:
            row = self._conn.execute(
                "SELECT source, confidence FROM facts WHERE hash = ?", (f_hash,)
            ).fetchone()
            if row:
                return (True, row[0], row[1] or 0.5)

        # L0: JSON 种子库
        if self._seed_ready and f_hash in self._seed_hashes:
            return (True, "kb_core", 0.9)

        return (False, "", 0.0)

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        模糊搜索相关事实。
        """
        results = []
        q = query.strip().lower()

        # L0: JSON 种子库（遍历键名 + 事实文本）
        if self._seed_ready:
            for key, entry in self._seed.items():
                if key.startswith("_"):
                    continue
                key_lower = key.lower().replace("_", " ")
                if q in key_lower or key_lower in q:
                    for f in entry.get("facts", [])[:5]:
                        results.append({
                            "fact": f, "source": entry.get("source", "kb_core"),
                            "confidence": 0.9, "key": key
                        })
                else:
                    for f in entry.get("facts", []):
                        if q in f.lower():
                            results.append({
                                "fact": f, "source": entry.get("source", "kb_core"),
                                "confidence": 0.9, "key": key
                            })
                            break
                if len(results) >= limit:
                    break

        # L1: SQLite（如果需要更多）
        if self._conn and len(results) < limit:
            remaining = limit - len(results)
            rows = self._conn.execute(
                "SELECT fact, source, confidence FROM facts WHERE fact LIKE ? LIMIT ?",
                (f"%{q}%", remaining)
            ).fetchall()
            for fact, src, conf in rows:
                results.append({
                    "fact": fact, "source": src,
                    "confidence": conf or 0.5, "key": None
                })

        return results[:limit]

    def verify(self, claim: str) -> Dict[str, Any]:
        """
        验证一个断言是否被知识库支持。
        返回: {verdict, evidence, confidence, source}
        """
        claim = claim.strip()

        # 1. 精确匹配
        found, source, conf = self.lookup(claim)
        if found:
            return {
                "verdict": "supported",
                "evidence": [claim],
                "confidence": conf,
                "source": source,
                "method": "exact_match"
            }

        # 2. 搜索相关事实
        related = self.search(claim, limit=5)
        if related:
            # 简单启发式：如果找到相关事实且置信度高，认为"可能支持"
            avg_conf = sum(r["confidence"] for r in related) / len(related)
            sources = list(set(r["source"] for r in related))
            return {
                "verdict": "partially_supported" if avg_conf > 0.6 else "uncertain",
                "evidence": [r["fact"] for r in related[:3]],
                "confidence": avg_conf,
                "source": ", ".join(sources),
                "method": "fuzzy_search"
            }

        return {
            "verdict": "not_found",
            "evidence": [],
            "confidence": 0.0,
            "source": "",
            "method": "none"
        }

    def get_source(self, fact: str) -> str:
        """获取事实的来源标签"""
        found, source, _ = self.lookup(fact)
        return source if found else ""

    def get_confidence(self, fact: str) -> float:
        """获取事实的可信度"""
        found, _, conf = self.lookup(fact)
        return conf if found else 0.0

    def stats(self) -> Dict[str, Any]:
        """统计信息"""
        seed_count = len(self._seed_hashes) if self._seed_ready else 0
        db_count = 0
        source_dist = {}

        if self._conn:
            db_count = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            rows = self._conn.execute(
                "SELECT source, COUNT(*) FROM facts GROUP BY source"
            ).fetchall()
            source_dist = {r[0]: r[1] for r in rows}

        return {
            "seed_facts": seed_count,
            "db_facts": db_count,
            "total_facts": seed_count + db_count,
            "source_distribution": source_dist,
        }

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── CLI 测试 ──────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import argparse
    parser = argparse.ArgumentParser(description="FactStore 统一 API")
    parser.add_argument("--lookup", type=str, help="精确查询")
    parser.add_argument("--search", type=str, help="模糊搜索")
    parser.add_argument("--verify", type=str, help="验证断言")
    parser.add_argument("--stats", action="store_true", help="显示统计")
    parser.add_argument("--source", type=str, help="查询来源")
    args = parser.parse_args()

    with FactStore() as store:
        if args.lookup:
            found, src, conf = store.lookup(args.lookup)
            print(f"{'✅' if found else '❌'} 来源={src} 置信度={conf:.2f}")

        if args.search:
            results = store.search(args.search)
            for r in results:
                print(f"  [{r['source']}] {r['fact'][:100]} (置信度 {r['confidence']:.2f})")

        if args.verify:
            result = store.verify(args.verify)
            print(f"判定: {result['verdict']}")
            print(f"置信度: {result['confidence']:.2f}")
            print(f"来源: {result['source']}")
            for e in result.get('evidence', []):
                print(f"  📎 {e[:120]}")

        if args.source:
            src = store.get_source(args.source)
            print(f"来源: {src or '未找到'}")

        if args.stats:
            import pprint
            pprint.pprint(store.stats())
