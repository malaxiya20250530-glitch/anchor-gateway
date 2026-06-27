#!/usr/bin/env python3
"""
Wikipedia 批量标题收割 — 从分类中获取海量页面标题作为实体键
每个标题 = 一个实体 = 1-2 条事实
零碰撞（标题天然唯一）

策略：
  20+ 分类 × 200-500 页/分类 = 4000-10000 实体
  每个实体 1-3 条事实 = 4000-30000 事实
  加上 FALSE 变体 = 翻倍

用法:
  python3 kb_wiki_titles.py --limit 200   # 每分类 200 页
  python3 kb_wiki_titles.py --limit 500   # 每分类 500 页
"""
import json, time, sys, urllib.request, urllib.parse, urllib.error
import random, re
from pathlib import Path

ROOT = Path(__file__).parent
API = "https://zh.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "Anchor-KB/1.0 TitleHarvester"}
DELAY = 2.0
MAX_RETRIES = 5

# 高价值分类 + 预期页面数
TARGET_CATEGORIES = [
    "物理学", "化学", "生物学", "数学", "天文学",
    "计算机科学", "人工智能", "经济学", "哲学", "心理学",
    "中国历史", "世界历史", "中国地理", "中国人物",
    "物理学概念", "化学概念", "生物学概念",
    "编程语言", "算法", "数据结构",
    "诺贝尔奖获得者", "奥运会", "发明",
    "中国城市", "中国省份", "亚洲国家",
]


def api_call(params, timeout=15, retries=MAX_RETRIES):
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
                print(f"    ⚠️ 429, 等 {wait:.1f}s")
                time.sleep(wait)
                continue
            return {"error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            return {"error": str(e)[:80]}
    return {"error": "rate limited"}


def get_category_titles(category: str, limit: int = 500) -> list:
    """获取分类下所有页面标题"""
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


def gen_facts_from_title(title: str) -> tuple:
    """从页面标题生成事实"""
    key = f"wiki_{re.sub(r'[^\w\u4e00-\u9fff]', '_', title)[:80]}"
    t, f = [], []

    # TRUE: 标题本身是一个概念
    t.append(f"{title}是中文维基百科收录的知识条目")
    t.append(f"关于{title}的信息可以在维基百科查阅")

    # FALSE 变体
    f.append(f"{title}是虚构的概念，不存在于现实中")
    f.append(f"关于{title}的信息无法在维基百科查阅")

    return key, t, f


def merge_to_kb(results):
    """增量合并到 kb_core"""
    core_path = ROOT / "kb_core.json"
    with open(core_path) as f:
        core = json.load(f)

    added = 0
    for key, f_true, f_false in results:
        if key not in core:
            core[key] = {"facts": [], "source": "wiki_titles"}
        existing = set(core[key].get("facts", []))
        for f in f_true + f_false:
            f = f.strip()
            if f and f not in existing:
                core[key].setdefault("facts", []).append(f)
                existing.add(f)
                added += 1

    with open(core_path, "w") as f:
        json.dump(core, f, ensure_ascii=False, indent=2)

    kb_keys = [k for k in core if not k.startswith("_")]
    total = sum(len(v.get("facts", [])) for v in core.values())
    print(f"  📊 KB: {len(kb_keys):,} 键, {total:,} 事实 (+{added})")
    return added


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wikipedia 标题收割器")
    parser.add_argument("--limit", type=int, default=200, help="每分类标题数")
    parser.add_argument("--categories", type=str, default="all", help="逗号分隔分类")
    args = parser.parse_args()

    if args.categories != "all":
        cats = [c.strip() for c in args.categories.split(",")]
    else:
        cats = TARGET_CATEGORIES

    print(f"{'='*50}")
    print(f"  Wikipedia 标题收割")
    print(f"  {len(cats)} 个分类, 每类 {args.limit} 页")
    print(f"{'='*50}")

    all_results = []
    total_titles = 0

    for idx, cat in enumerate(cats):
        print(f"\n📂 [{idx+1}/{len(cats)}] {cat}...")
        titles = get_category_titles(cat, limit=args.limit)
        cat_count = len(titles)
        total_titles += cat_count
        print(f"  📄 {cat_count} 个标题")

        for title in titles:
            r = gen_facts_from_title(title)
            all_results.append(r)

        # 每 3 个分类合并一次（避免内存过大）
        if idx % 3 == 2 or idx == len(cats) - 1:
            merge_to_kb(list(all_results)); all_results.clear()

        time.sleep(DELAY * 2)

    print(f"\n✅ 收割完成: {total_titles} 个标题")