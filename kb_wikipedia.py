#!/usr/bin/env python3
"""
Wikipedia 批量事实抽取 — 从分类页面提取结构化知识
带指数退避重试，避免 429 限流

用法:
  python3 kb_wikipedia.py --limit 200 --merge   # 全量抓取+合并
  python3 kb_wikipedia.py --limit 10 --merge     # 小批量测试
  python3 kb_wikipedia.py --categories "物理学,化学" --limit 50 --merge
"""

import json, re, time, sys, urllib.request, urllib.parse, urllib.error
import random
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent
API = "https://zh.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "Anchor-KB/1.0 (contact: hubeiligang420@gmail.com)"}
DELAY = 1.5          # 请求间隔（秒），保守值
BATCH_DELAY = 3.0    # 批次间隔
CAT_DELAY = 5.0      # 分类切换间隔
MAX_RETRIES = 5

# 高价值分类（中文维基已验证存在）
CATEGORIES = [
    "中国历史", "中国地理", "中国人物", "世界历史",
    "物理学", "化学", "生物学", "天文学", "数学",
    "计算机科学", "人工智能", "编程语言",
    "经济学", "哲学", "心理学", "医学",
    "发明", "诺贝尔奖获得者", "奥运会",
]


def api_call(params: dict, timeout: int = 15, retries: int = MAX_RETRIES) -> dict:
    """Wikipedia API 调用，带指数退避重试"""
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
                print(f"  ⚠️ 429 限流，等待 {wait:.1f}s (尝试 {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            return {"error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return {"error": str(e)[:80]}
    return {"error": "rate limited after retries"}


def get_category_pages(category: str, limit: int = 500) -> list:
    """获取分类下的页面标题列表"""
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
            print(f"    API 错误: {data['error']}")
            break
        members = data.get("query", {}).get("categorymembers", [])
        if not members:
            break
        for m in members:
            titles.append(m["title"])
        if "continue" in data:
            cmcontinue = data["continue"]["cmcontinue"]
        else:
            break
        time.sleep(DELAY)
    return titles[:limit]


def get_page_extracts(titles: list) -> dict:
    """批量获取页面摘要（每批最多 50 个）"""
    results = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i+50]
        params = {
            "action": "query", "prop": "extracts|info",
            "exintro": 1, "explaintext": 1, "exlimit": 50,
            "inprop": "url",
            "titles": "|".join(batch),
        }
        data = api_call(params)
        if "error" in data:
            print(f"    extract API 错误: {data['error']}")
            continue
        for page in data.get("query", {}).get("pages", {}).values():
            title = page.get("title", "")
            extract = page.get("extract", "")
            if extract and len(extract) > 50:
                results[title] = extract
        time.sleep(BATCH_DELAY)
    return results


def extract_facts_from_text(title: str, text: str) -> list:
    """从摘要文本提取事实句子"""
    facts = []
    text = text[:800]  # 前 800 字符
    sentences = re.split(r'[。！？\n；]', text)

    for s in sentences:
        s = s.strip()
        if not s or len(s) < 10:
            continue
        # 清理引用标记 [1] [2] 等
        s = re.sub(r'\[\d+\]', '', s)
        s = re.sub(r'（[^）]*）', '', s)
        s = re.sub(r'\([^)]*\)', '', s)
        if len(s) >= 10:
            facts.append(s)

    return facts[:8]


def build_kb(categories: list, page_limit: int = 100, total_limit: int = 50000) -> dict:
    """从分类页面构建知识库"""
    kb = defaultdict(lambda: {"facts": [], "source": "wikipedia"})
    total = 0

    for idx, cat in enumerate(categories):
        if total >= total_limit:
            break

        # 预检查分类是否存在
        check_params = {
            "action": "query", "list": "categorymembers",
            "cmtitle": f"Category:{cat}", "cmlimit": 1, "cmtype": "page"
        }
        check = api_call(check_params, retries=2)
        if "error" in check:
            print(f"\n📂 {cat} ❌ 跳过: {check['error']}")
            time.sleep(DELAY)
            continue

        members = check.get("query", {}).get("categorymembers", [])
        if not members:
            print(f"\n📂 {cat} ❌ 空分类，跳过")
            time.sleep(DELAY)
            continue

        print(f"\n📂 [{idx+1}/{len(categories)}] {cat} (已验证存在)...")
        pages = get_category_pages(cat, limit=page_limit)
        print(f"  📄 获取 {len(pages)}/{page_limit} 页")

        if not pages:
            time.sleep(CAT_DELAY)
            continue

        time.sleep(DELAY)

        extracts = get_page_extracts(pages)
        print(f"  📝 获取 {len(extracts)} 个摘要")

        for title, text in extracts.items():
            facts = extract_facts_from_text(title, text)
            if not facts:
                continue
            key = re.sub(r'[^\w\u4e00-\u9fff]', '_', title)[:80]
            # 去重
            existing = kb[key]["facts"]
            for f in facts:
                if f not in existing:
                    existing.append(f)
            total += len(facts)

        print(f"  📊 累计: {len(kb)} 键, {total} 事实 | 目标 {total_limit}")
        time.sleep(CAT_DELAY)

    return dict(kb)


def save_and_merge(kb: dict):
    """保存并合并到核心 KB"""
    path = ROOT / "kb_wikipedia.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    kb_size = path.stat().st_size // 1024
    print(f"\n💾 已保存: {path} ({kb_size}KB)")

    # 合并到 kb_core.json
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
            added += len(entry.get("facts", []))
        else:
            existing = set(core[key].get("facts", []))
            for f in entry.get("facts", []):
                if f not in existing:
                    core[key].setdefault("facts", []).append(f)
                    added += 1

    with open(core_path, "w") as f:
        json.dump(core, f, ensure_ascii=False, indent=2)
    print(f"📥 合并: +{added} 事实, kb_core.json 总计 {len(core)} 键")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wikipedia KB 批量导入")
    parser.add_argument("--limit", type=int, default=100, help="每分类页面数 (默认 100)")
    parser.add_argument("--total", type=int, default=50000, help="总事实上限 (默认 50000)")
    parser.add_argument("--merge", action="store_true", help="合并到 kb_core.json")
    parser.add_argument("--categories", type=str, default="all", help="逗号分隔分类，或 'all'")
    args = parser.parse_args()

    if args.categories != "all":
        cats = [c.strip() for c in args.categories.split(",")]
    else:
        cats = CATEGORIES

    print("=" * 60)
    print("  Wikipedia → Anchor KB 批量导入")
    print(f"  分类数: {len(cats)}, 每类 {args.limit} 页")
    print(f"  ⏱️  间隔 {DELAY}s, 重试 {MAX_RETRIES} 次")
    print("=" * 60)

    kb = build_kb(cats, page_limit=args.limit, total_limit=args.total)

    total_facts = sum(len(v.get("facts", [])) for v in kb.values())
    print(f"\n✅ 采集: {len(kb)} 键, {total_facts} 事实")

    if args.merge:
        save_and_merge(kb)
    else:
        path = ROOT / "kb_wikipedia.json"
        with open(path, "w") as f:
            json.dump(kb, f, ensure_ascii=False, indent=2)
        print(f"💾 已保存: {path}")


if __name__ == "__main__":
    main()
