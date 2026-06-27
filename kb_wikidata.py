#!/usr/bin/env python3
"""
Wikidata 批量导入 — 从 Wikidata SPARQL 端点拉取结构化事实
零 API Key，自动转 KNOWLEDGE_BASE 格式，增量合并到 kb_core.json

用法:
  python3 kb_wikidata.py                    # 全量抓取 (~50000 条)
  python3 kb_wikidata.py --limit 1000       # 测试模式
  python3 kb_wikidata.py --merge            # 合并到核心 KB
"""

import json, time, sys, urllib.request, urllib.parse, urllib.error
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent
ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "Anchor-KB-Builder/1.0 (https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth)",
    "Accept": "application/json",
}
BATCH_SIZE = 500
DELAY = 1.0  # Wikidata 礼貌间隔


# ═══════════════════════════════════════════════════════════
# SPARQL 查询模板
# ═══════════════════════════════════════════════════════════

QUERIES = {
    "历史人物": """
        SELECT ?name ?birth ?death ?nationality ?description WHERE {{
          ?person wdt:P31 wd:Q5.
          ?person rdfs:label ?name.
          OPTIONAL {{ ?person wdt:P569 ?birth. }}
          OPTIONAL {{ ?person wdt:P570 ?death. }}
          OPTIONAL {{ ?person wdt:P27 ?country. ?country rdfs:label ?nationality. FILTER(LANG(?nationality)="zh") }}
          OPTIONAL {{ ?person schema:description ?description. FILTER(LANG(?description)="zh") }}
          FILTER(LANG(?name)="zh" && STRLEN(?name) < 20)
          FILTER(NOT EXISTS {{ ?person wdt:P31 wd:Q4167410. }})
        }}
        ORDER BY DESC(?birth)
        LIMIT {limit}
    """,

    "国家首都": """
        SELECT ?country ?capital ?population ?area WHERE {{
          ?country wdt:P31 wd:Q3624078.
          ?country rdfs:label ?country_label. FILTER(LANG(?country_label)="zh")
          OPTIONAL {{ ?country wdt:P36 ?cap. ?cap rdfs:label ?capital. FILTER(LANG(?capital)="zh") }}
          OPTIONAL {{ ?country wdt:P1082 ?population. }}
          OPTIONAL {{ ?country wdt:P2046 ?area. }}
          BIND(?country_label AS ?name)
        }}
        LIMIT {limit}
    """,

    "科学发现": """
        SELECT ?concept ?discoverer ?year ?description WHERE {{
          ?discovery wdt:P31 wd:Q12033737.
          ?discovery rdfs:label ?concept. FILTER(LANG(?concept)="zh")
          OPTIONAL {{ ?discovery wdt:P61 ?person. ?person rdfs:label ?discoverer. FILTER(LANG(?discoverer)="zh") }}
          OPTIONAL {{ ?discovery wdt:P575 ?year. }}
          OPTIONAL {{ ?discovery schema:description ?description. FILTER(LANG(?description)="zh") }}
        }}
        LIMIT {limit}
    """,

    "公司企业": """
        SELECT ?name ?founder ?founded ?industry WHERE {{
          ?company wdt:P31/wdt:P279* wd:Q4830453.
          ?company rdfs:label ?name. FILTER(LANG(?name)="zh" && STRLEN(?name) < 30)
          OPTIONAL {{ ?company wdt:P112 ?f. ?f rdfs:label ?founder. FILTER(LANG(?founder)="zh") }}
          OPTIONAL {{ ?company wdt:P571 ?founded. }}
          OPTIONAL {{ ?company wdt:P452 ?ind. ?ind rdfs:label ?industry. FILTER(LANG(?industry)="zh") }}
        }}
        LIMIT {limit}
    """,

    "编程语言": """
        SELECT ?name ?creator ?year ?paradigm WHERE {{
          ?lang wdt:P31/wdt:P279* wd:Q9143.
          ?lang rdfs:label ?name. FILTER(LANG(?name)="en" && STRLEN(?name) < 25)
          OPTIONAL {{ ?lang wdt:P178 ?c. ?c rdfs:label ?creator. FILTER(LANG(?creator)="zh") }}
          OPTIONAL {{ ?lang wdt:P571 ?year. }}
          OPTIONAL {{ ?lang wdt:P3966 ?paradigm. }}
        }}
        LIMIT {limit}
    """,

    "发明创造": """
        SELECT ?invention ?inventor ?year ?description WHERE {{
          ?item wdt:P31 wd:Q1428155.
          ?item rdfs:label ?invention. FILTER(LANG(?invention)="zh" && STRLEN(?invention) < 20)
          OPTIONAL {{ ?item wdt:P61 ?person. ?person rdfs:label ?inventor. FILTER(LANG(?inventor)="zh") }}
          OPTIONAL {{ ?item wdt:P575 ?year. }}
          OPTIONAL {{ ?item schema:description ?description. FILTER(LANG(?description)="zh") }}
        }}
        LIMIT {limit}
    """,
}


def sparql_query(query: str, timeout: int = 30) -> list:
    """执行 SPARQL 查询，返回结果列表"""
    url = ENDPOINT + "?" + urllib.parse.urlencode({"format": "json", "query": query})
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data.get("results", {}).get("bindings", [])
    except Exception as e:
        print(f"  查询失败: {e}")
        return []


def bindings_to_facts(results: list, category: str) -> dict:
    """将 SPARQL 结果转为 KNOWLEDGE_BASE 格式"""
    kb = defaultdict(lambda: {"facts": [], "source": "wikidata"})
    
    for row in results:
        # 提取主名称作为 key
        name_val = None
        for k in ["name", "country", "concept", "invention"]:
            if k in row:
                name_val = row[k]["value"]
                break
        if not name_val:
            continue
        
        key = name_val[:80]
        facts = []
        
        # 处理各种字段
        if "birth" in row and "death" in row:
            b = row["birth"]["value"][:4]
            d = row["death"]["value"][:4]
            facts.append(f"{name_val}生于{b}年，卒于{d}年")
        elif "birth" in row:
            facts.append(f"{name_val}出生于{row['birth']['value'][:4]}年")
        elif "death" in row:
            facts.append(f"{name_val}于{row['death']['value'][:4]}年去世")
        
        if "nationality" in row:
            facts.append(f"{name_val}是{row['nationality']['value']}人")
        
        if "population" in row:
            pop = int(row["population"]["value"])
            facts.append(f"{name_val}人口约{pop//10000}万")
        
        if "area" in row:
            area = float(row["area"]["value"])
            facts.append(f"{name_val}面积约{area:.0f}平方公里")
        
        if "capital" in row:
            facts.append(f"{name_val}首都是{row['capital']['value']}")
        
        if "year" in row:
            y = str(row["year"]["value"])[:4]
            if "discoverer" in row:
                facts.append(f"{name_val}由{row['discoverer']['value']}于{y}年发现")
            elif "inventor" in row:
                facts.append(f"{name_val}由{row['inventor']['value']}于{y}年发明")
            elif "creator" in row:
                facts.append(f"{name_val}由{row['creator']['value']}于{y}年创建")
            elif "founded" in row:
                facts.append(f"{name_val}成立于{y}年")
            else:
                facts.append(f"{name_val}始于{y}年")
        else:
            if "discoverer" in row:
                facts.append(f"{name_val}由{row['discoverer']['value']}发现")
            elif "inventor" in row:
                facts.append(f"{name_val}由{row['inventor']['value']}发明")
            elif "creator" in row:
                facts.append(f"{name_val}由{row['creator']['value']}创建")
            elif "founder" in row:
                facts.append(f"{name_val}由{row['founder']['value']}创立")
        
        if "description" in row:
            desc = row["description"]["value"][:200]
            if desc and desc != name_val:
                facts.append(desc)
        
        if "paradigm" in row:
            facts.append(f"{name_val}支持{row['paradigm']['value']}编程范式")
        
        if "industry" in row:
            facts.append(f"{name_val}属于{row['industry']['value']}行业")
        
        for f in facts:
            if f and f not in kb[key]["facts"]:
                kb[key]["facts"].append(f)
    
    return dict(kb)


def fetch_all(limit: int = 10000) -> dict:
    """拉取所有类别，返回合并后的 KB"""
    all_kb = {}
    total = 0
    
    for category, query_template in QUERIES.items():
        print(f"\n📡 {category}...")
        query = query_template.format(limit=limit)
        results = sparql_query(query)
        kb = bindings_to_facts(results, category)
        
        new_keys = 0
        new_facts = 0
        for key, entry in kb.items():
            if key not in all_kb:
                all_kb[key] = entry
                new_keys += 1
            else:
                existing = set(all_kb[key]["facts"])
                for f in entry["facts"]:
                    if f not in existing:
                        all_kb[key]["facts"].append(f)
                        new_facts += 1
        
        print(f"  获取 {len(results)} 条 → {new_keys} 新键 + {new_facts} 新事实")
        total += len(results)
        time.sleep(DELAY)
    
    total_facts = sum(len(v["facts"]) for v in all_kb.values())
    print(f"\n📊 总计: {len(all_kb)} 个键, {total_facts} 条事实")
    return all_kb


def save_kb(kb: dict, path: Path = None):
    """保存 KB 到文件"""
    if path is None:
        path = ROOT / "kb_wikidata.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    print(f"💾 已保存: {path} ({path.stat().st_size//1024}KB)")


def merge_to_core(kb: dict):
    """合并到 kb_core.json"""
    core_path = ROOT / "kb_core.json"
    if core_path.exists():
        with open(core_path) as f:
            core = json.load(f)
    else:
        core = {}
    
    added = 0
    for key, entry in kb.items():
        if key.startswith("_"):
            continue
        if key not in core:
            core[key] = entry
            added += len(entry["facts"])
        else:
            existing = set(core[key].get("facts", []))
            for f in entry.get("facts", []):
                if f not in existing:
                    core[key].setdefault("facts", []).append(f)
                    added += 1
    
    with open(core_path, "w") as f:
        json.dump(core, f, ensure_ascii=False, indent=2)
    print(f"📥 合并到 kb_core.json: +{added} 事实, 总计 {len(core)} 键")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wikidata KB 批量导入")
    parser.add_argument("--limit", type=int, default=10000, help="每类查询上限")
    parser.add_argument("--merge", action="store_true", help="合并到 kb_core.json")
    args = parser.parse_args()
    
    print("=" * 50)
    print("  Wikidata → Anchor KB 批量导入")
    print("=" * 50)
    
    kb = fetch_all(limit=args.limit)
    save_kb(kb)
    
    if args.merge:
        merge_to_core(kb)
    
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
