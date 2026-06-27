#!/usr/bin/env python3
"""
行业知识库加载器 — 将医疗/法律等垂直领域知识注入检测器

用法:
    from kb_loader import load_industry_kb
    load_industry_kb()  # 自动合并到 KNOWLEDGE_BASE
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent

INDUSTRY_KB_FILES = {
    "medical": ROOT / "kb_medical.json",
    "legal": ROOT / "kb_legal.json",
}


def load_industry_kb(domains: list = None, target: dict = None):
    """
    将行业知识库合并到主知识库

    参数:
        domains: 要加载的领域列表，默认全部 ['medical', 'legal']
        target:  目标字典，默认为 hallucination_detector.KNOWLEDGE_BASE
    返回:
        (loaded_count, total_entries) 元组
    """
    if target is None:
        from hallucination_detector import KNOWLEDGE_BASE
        target = KNOWLEDGE_BASE

    if domains is None:
        domains = list(INDUSTRY_KB_FILES.keys())

    loaded = 0
    total = 0
    for domain in domains:
        path = INDUSTRY_KB_FILES.get(domain)
        if not path or not path.exists():
            continue
        with open(path) as f:
            kb = json.load(f)
        for key, entry in kb.items():
            if key.startswith("_"):
                continue
            total += 1
            if key not in target:
                target[key] = entry
                loaded += 1

    return loaded, total


def list_domains() -> dict:
    """列出所有可用行业知识库及条目数"""
    result = {}
    for domain, path in INDUSTRY_KB_FILES.items():
        if path.exists():
            with open(path) as f:
                kb = json.load(f)
            result[domain] = {
                "path": str(path),
                "entries": sum(1 for k in kb if not k.startswith("_")),
                "meta": kb.get("_meta", {}),
            }
    return result


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for dom, info in list_domains().items():
            print(f"  {dom}: {info['entries']} 条 | {info['meta'].get('domain','')}")
        return

    loaded, total = load_industry_kb()
    print(f"✅ 行业知识库已加载: {loaded} 条新事实 (共 {total} 条)")


if __name__ == "__main__":
    main()
