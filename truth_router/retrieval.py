#!/usr/bin/env python3
"""检索模块 — 从知识库检索与查询相关的事实"""
import json, sqlite3, re, sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
KB_CORE = ROOT / "kb_core.json"
FACT_DB = ROOT / "knowledge" / "fact_store.db"


def _load_kb_core() -> dict:
    """加载语义索引"""
    try:
        if KB_CORE.exists():
            return json.loads(KB_CORE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _extract_entities(query: str, kb_core: dict) -> list[str]:
    """从查询中提取知识库内存在的实体名

    按长度降序匹配，过滤长度<2的模糊单字实体；
    优先匹配长实体（如"朱元璋"），避免短实体（如"明"）误匹配。
    """
    found = []
    sorted_entities = sorted(kb_core.keys(), key=len, reverse=True)
    matched_spans = set()

    for entity_name in sorted_entities:
        if len(entity_name) < 2:
            continue
        if entity_name.lower() in query.lower():
            idx = query.lower().index(entity_name.lower())
            span = set(range(idx, idx + len(entity_name)))
            if span & matched_spans:
                continue
            found.append(entity_name)
            matched_spans.update(span)
    return found



def _search_kb_core(kb_core: dict, entities: list[str], limit: int = 10) -> list[dict]:
    """从 kb_core.json 语义索引直接提取事实（最快路径）

    kb_core.json 中每个实体条目包含 facts 列表和 source，
    无需查询 fact_store.db。
    """
    results = []
    seen = set()
    for entity in entities:
        entry = kb_core.get(entity, {})
        facts = entry.get("facts", [])
        source = entry.get("source", entity)
        for fact in facts:
            if fact in seen:
                continue
            seen.add(fact)
            # 从 fact_store.db 获取置信度（如有），否则用默认值
            results.append({
                "fact": fact,
                "source": source,
                "confidence": 0.85,
                "entity": entity,
            })
            if len(results) >= limit:
                return results
    return results


def _search_fact_db(keywords: list[str], limit: int = 10) -> list[dict]:
    """在 fact_store.db 中搜索匹配事实

    参数:
        keywords: 关键词列表（实体名）
        limit: 返回上限
    返回:
        [{"fact": str, "source": str, "confidence": float}, ...]
    """
    if not FACT_DB.exists():
        return []

    results = []
    try:
        conn = sqlite3.connect(str(FACT_DB))
        conn.row_factory = sqlite3.Row

        for kw in keywords:
            # 通过实体映射表查找
            rows = conn.execute(
                """SELECT f.fact, f.source, f.confidence
                   FROM facts_0 f
                   INNER JOIN entity_fact_map m ON m.fact_hash = f.hash
                   WHERE m.entity_name = ? AND f.active = 1
                   LIMIT ?""",
                (kw, limit)
            ).fetchall()
            for row in rows:
                results.append({
                    "fact": row["fact"],
                    "source": row["source"],
                    "confidence": row["confidence"],
                    "entity": kw,
                })

        conn.close()
    except Exception:
        pass

    return results


def _search_fts(query: str, limit: int = 10) -> list[dict]:
    """全文搜索回退（当实体映射无结果时）

    策略：优先 FTS bigram；FTS 无结果则降级为 SQL LIKE 搜索。
    原因：SQLite FTS5 unicode61 分词器对中文按单字索引，"火锅"作为词搜不到。
    """
    if not FACT_DB.exists():
        return []

    results = []
    try:
        conn = sqlite3.connect(str(FACT_DB))
        conn.row_factory = sqlite3.Row

        # 构建 bigram 搜索词
        words = query.split()
        if len(words) == 1 and len(words[0]) > 2:
            chars = list(words[0])
            terms_list = ["".join(chars[i:i+2]) for i in range(len(chars)-1)]
        else:
            terms_list = [t for t in words if len(t) >= 2]

        if not terms_list:
            conn.close()
            return []

        seen = set()

        # 1) 尝试 FTS
        terms = " OR ".join(f'"{t}"' for t in terms_list)
        try:
            rows = conn.execute(
                """SELECT f.fact, f.source, f.confidence
                   FROM facts_fts ft
                   JOIN facts_0 f ON f.rowid = ft.rowid
                   WHERE facts_fts MATCH ?
                   LIMIT ?""",
                (terms, limit)
            ).fetchall()
            for row in rows:
                key = row["fact"]
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "fact": row["fact"],
                        "source": row["source"],
                        "confidence": row["confidence"],
                    })
        except Exception:
            pass

        # 2) FTS 无结果 → LIKE 回退（带超时保护）
        if not results and terms_list:
            conn.execute("PRAGMA query_only = true")
            for term in terms_list[:4]:  # 最多 4 个 bigram 防爆炸
                try:
                    rows = conn.execute(
                        """SELECT fact, source, confidence
                           FROM facts_0
                           WHERE fact LIKE ? AND active = 1
                           LIMIT ?""",
                        (f"%{term}%", max(1, limit // len(terms_list)))
                    ).fetchall()
                    for row in rows:
                        key = row["fact"]
                        if key not in seen:
                            seen.add(key)
                            results.append({
                                "fact": row["fact"],
                                "source": row["source"],
                                "confidence": row["confidence"],
                            })
                except Exception:
                    pass

        conn.close()
    except Exception:
        pass

    return results[:limit]


def retrieve(query: str, max_results: int = 10) -> dict:
    """检索与查询相关的事实

    参数:
        query: 用户查询文本
        max_results: 最大返回条数
    返回:
        {
            "query": str,
            "entities": [str, ...],
            "facts": [{"fact": str, "source": str, "confidence": float}, ...],
            "source": str  # "entity_map" | "fts" | "none"
        }
    """
    kb_core = _load_kb_core()
    entities = _extract_entities(query, kb_core)

    if entities:
        # 优先从 kb_core 语义索引取事实（最快）
        facts = _search_kb_core(kb_core, entities, max_results)
        if facts:
            source = "kb_core"
        else:
            # kb_core 无结果，尝试 entity_fact_map
            facts = _search_fact_db(entities, max_results)
            if facts:
                source = "entity_map"
            else:
                # 最后回退到 LIKE 搜索
                facts = _search_fts(query, max_results)
                source = "fts" if facts else "none"
    else:
        facts = _search_fts(query, max_results)
        source = "fts" if facts else "none"
        entities = []

    return {
        "query": query,
        "entities": entities,
        "facts": facts,
        "source": source,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python3 retrieval.py <查询文本>")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    result = retrieve(query)

    print(f"查询: {result['query']}")
    print(f"实体: {result['entities'] or '(未识别)'}")
    print(f"来源: {result['source']}")
    print(f"事实 ({len(result['facts'])} 条):")
    for f in result["facts"]:
        print(f"  [{f.get('entity', f['source'])}] {f['fact'][:80]} (置信度:{f['confidence']})")


if __name__ == "__main__":
    main()
