#!/usr/bin/env python3
"""
实体库自动扩充器 — 从 Wikipedia 分类中提取结构化实体
自动生成 entities_mega.json 条目 + 变体事实

用法:
  python3 kb_entity_expander.py --limit 50  # 每分类 50 个实体
  python3 kb_entity_expander.py --limit 500 --merge  # 大量扩充+合并
"""
import json, re, time, sys, urllib.request, urllib.parse, urllib.error
import random
from pathlib import Path

# 安全：输入净化 + KB 投毒检测
from prompt_injection_defense import sanitize_input, KBPoisonGuard

ROOT = Path(__file__).parent
API = "https://zh.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "Anchor-KB/1.0 (contact: hubeiligang420@gmail.com)"}
DELAY = 2.0
MAX_RETRIES = 5

# 实体类型 → Wikipedia 分类
ENTITY_CATEGORIES = {
    "person": [
        "中国皇帝", "中国科学家", "中国作家", "中国画家",
        "物理学家", "化学家", "数学家", "天文学家",
        "生物学家", "计算机科学家", "经济学家", "哲学家",
        "心理学家", "发明家", "诺贝尔奖获得者",
        "中国诗人", "中国军事家", "中国政治人物",
    ],
    "concept": [
        "物理学概念", "化学概念", "生物学概念", "数学概念",
        "经济学概念", "哲学概念", "心理学概念",
    ],
    "location": [
        "中国城市", "中国省份", "中国河流", "中国湖泊",
        "中国山脉", "亚洲国家", "欧洲国家",
    ],
    "event": [
        "中国战争", "中国历史事件", "世界历史事件",
    ],
    "organization": [
        "中国大学", "中国公司", "国际组织",
    ],
}

# 国籍映射（从分类名推断）
NATIONALITY_MAP = {
    "中国皇帝": "中国", "中国科学家": "中国", "中国作家": "中国",
    "中国画家": "中国", "中国诗人": "中国", "中国军事家": "中国",
    "中国政治人物": "中国",
}


def api_call(params: dict, timeout: int = 15, retries: int = MAX_RETRIES) -> dict:
    params["format"] = "json"
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(2 ** (attempt + 1) + random.uniform(0, 1), 30)
                time.sleep(wait)
                continue
            return {"error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return {"error": str(e)[:80]}
    return {"error": "rate limited"}


def get_category_pages(category: str, limit: int = 100) -> list:
    titles = []
    cmcontinue = None
    while len(titles) < limit:
        remaining = limit - len(titles)
        params = {
            "action": "query", "list": "categorymembers",
            "cmtitle": f"Category:{category}", "cmlimit": min(50, remaining),
            "cmtype": "page",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = api_call(params)
        if "error" in data:
            break
        members = data.get("query", {}).get("categorymembers", [])
        for m in members:
            titles.append(m["title"])
        if "continue" in data:
            cmcontinue = data["continue"]["cmcontinue"]
        else:
            break
        time.sleep(DELAY)
    return titles[:limit]


def get_page_info(titles: list) -> dict:
    """获取页面摘要+分类"""
    results = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i+50]
        params = {
            "action": "query", "prop": "extracts|categories",
            "exintro": 1, "explaintext": 1, "exlimit": 50,
            "cllimit": 10,
            "titles": "|".join(batch),
        }
        data = api_call(params)
        if "error" in data:
            continue
        for page in data.get("query", {}).get("pages", {}).values():
            title = page.get("title", "")
            extract = page.get("extract", "")[:1000]
            cats = [c["title"].replace("Category:", "") for c in page.get("categories", [])]
            results[title] = {"extract": extract, "categories": cats}
        time.sleep(DELAY * 2)
    return results


def parse_entity(title: str, info: dict, etype: str, category: str) -> dict:
    """从页面信息解析结构化实体"""
    entity = {
        "name": title,
        "type": etype,
        "key_facts": [],
        "key_years": {},
        "known_for": [],
        "negations": [],
        "relations": [],
    }

    text = info.get("extract", "")
    nationality = NATIONALITY_MAP.get(category, "")
    if nationality:
        entity["nationality"] = nationality

    # 提取年份
    years = re.findall(r'(?:公元)?(\d{3,4})年', text)
    years_int = sorted(set(int(y) for y in years if 500 < int(y) < 2026))

    if etype == "person" and years_int:
        entity["birth"] = years_int[0]
        if len(years_int) > 1:
            entity["death"] = years_int[-1]

    # 提取关键事实（第一句通常是定义）
    first_sent = text.split("。")[0] if "。" in text else text[:120]
    if len(first_sent) > 10:
        # 安全净化：过滤 Wikipedia 中可能的注入内容
        clean_sent = sanitize_input(first_sent.strip())
        entity["key_facts"].append(clean_sent)

    # 从分类推断领域
    field_map = {
        "物理学家": "物理学", "化学家": "化学", "数学家": "数学",
        "天文学家": "天文学", "生物学家": "生物学",
        "计算机科学家": "计算机科学", "经济学家": "经济学",
        "哲学家": "哲学", "心理学家": "心理学",
        "中国作家": "文学", "中国诗人": "文学",
    }
    if category in field_map:
        entity["field"] = [field_map[category]]

    # 已知成就（从关键词提取）
    achievement_patterns = [
        (r'发明了?([^，。；]+)', "发明"),
        (r'发现了?([^，。；]+)', "发现"),
        (r'提出了?([^，。；]+)', "提出"),
        (r'创立了?([^，。；]+)', "创立"),
    ]
    for pat, prefix in achievement_patterns:
        m = re.search(pat, text)
        if m:
            entity["known_for"].append(f"{prefix}{m.group(1)}")

    return entity


def expand_entities(limit_per_cat: int = 100) -> list:
    """从 Wikipedia 扩充实体库"""
    entities = []
    total = 0

    for etype, categories in ENTITY_CATEGORIES.items():
        if total >= limit_per_cat * 5:  # 粗略限制
            break
        for cat in categories:
            if total >= limit_per_cat * len(categories):
                break
            print(f"\n📂 [{etype}] {cat}...")
            pages = get_category_pages(cat, limit=limit_per_cat)
            print(f"  📄 {len(pages)} 页")

            if not pages:
                time.sleep(DELAY * 2)
                continue

            infos = get_page_info(pages[:limit_per_cat])
            print(f"  📝 {len(infos)} 摘要")

            for title, info in infos.items():
                entity = parse_entity(title, info, etype, cat)
                if entity["key_facts"]:
                    entities.append(entity)
                total += 1

            print(f"  ✅ 累计 {len(entities)} 实体")
            time.sleep(DELAY * 3)

    return entities


def main():
    import argparse
    parser = argparse.ArgumentParser(description="实体库自动扩充")
    parser.add_argument("--limit", type=int, default=50, help="每分类实体数")
    parser.add_argument("--merge", action="store_true", help="合并到 entities_mega.json")
    args = parser.parse_args()

    print("=" * 60)
    print("  实体库自动扩充器 — Wikipedia → entities_mega.json")
    print(f"  类型: {len(ENTITY_CATEGORIES)} 种, 分类: {sum(len(v) for v in ENTITY_CATEGORIES.values())} 个")
    print(f"  每分类 {args.limit} 实体")
    print("=" * 60)

    entities = expand_entities(limit_per_cat=args.limit)

    # 保存
    out_path = ROOT / "entities_expanded.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entities, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已保存: {out_path} ({len(entities)} 实体)")

    if args.merge:
        mega_path = ROOT / "entities_mega.json"
        if mega_path.exists():
            with open(mega_path) as f:
                existing = json.load(f)
            existing_names = {e["name"] for e in existing}
            added = 0
            skipped_poison = 0
            for entity in entities:
                if entity["name"] not in existing_names:
                    # KB 投毒检测：过滤恶意条目
                    entry = {
                        "facts": entity.get("key_facts", []),
                        "source": "wikipedia",
                    }
                    safe, reason = KBPoisonGuard.scan_entry(entity["name"], entry)
                    if not safe:
                        skipped_poison += 1
                        print(f"  🛡️ 跳过投毒条目: {entity['name']} ({reason[:40]})")
                        continue
                    existing.append(entity)
                    added += 1
            with open(mega_path, "w") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            print(f"📥 合并: +{added} 实体 (跳过 {skipped_poison} 个投毒条目), entities_mega.json 总计 {len(existing)} 实体")


if __name__ == "__main__":
    main()
