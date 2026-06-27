"""
KB Generator — 从结构化实体自动生成事实（含 TRUE/FALSE 变体）
为幻觉检测基准测试提供大规模、可回归的样本。
"""

import json, re, os, sys
from pathlib import Path

ROOT = Path(__file__).parent

def generate_facts(entity: dict) -> list[dict]:
    """
    从一条结构化实体生成多条事实。

    返回: [{"text": "...", "label": "TRUE"|"FALSE", "category": "..."}, ...]
    """
    facts = []
    name = entity["name"]
    etype = entity.get("type", "concept")

    # === 1. 关键事实 (TRUE) ===
    for f in entity.get("key_facts", []):
        facts.append({"text": f, "label": "TRUE", "category": name})

    # === 2. 生卒年 (person) ===
    if etype == "person":
        birth = entity.get("birth")
        death = entity.get("death")
        nationality = entity.get("nationality", "")
        field = entity.get("field", [])

        if birth:
            facts.append({"text": f"{name}出生于{birth}年", "label": "TRUE", "category": name})
            # FALSE: 扰动年份
            for offset in [1, -1, 10, -10, 50, 100]:
                if birth + offset > 0:
                    facts.append({"text": f"{name}出生于{birth + offset}年", "label": "FALSE", "category": name})

        if death:
            facts.append({"text": f"{name}于{death}年去世", "label": "TRUE", "category": name})
            for offset in [1, -1, 5, -5, 20]:
                if death + offset > 0:
                    facts.append({"text": f"{name}于{death + offset}年去世", "label": "FALSE", "category": name})

        if birth and death:
            facts.append({"text": f"{name}生于{birth}年，卒于{death}年", "label": "TRUE", "category": name})

        # 国籍
        if nationality:
            facts.append({"text": f"{name}是{nationality}人", "label": "TRUE", "category": name})
            # FALSE: 错误国籍
            fake_nationalities = {
                "英国": "法国", "法国": "德国", "德国": "意大利",
                "美国": "加拿大", "中国": "日本", "意大利": "西班牙",
            }
            fake = fake_nationalities.get(nationality, "未知")
            facts.append({"text": f"{name}是{fake}人", "label": "FALSE", "category": name})

        # 领域
        for f in field:
            facts.append({"text": f"{name}是{f}家", "label": "TRUE", "category": name})

    # === 3. 关键年份 ===
    for event, year in entity.get("key_years", {}).items():
        facts.append({"text": f"{name}{event}于{year}年", "label": "TRUE", "category": name})
        # FALSE 扰动
        for offset in [1, -1, 5, -5]:
            if year + offset > 0:
                facts.append({"text": f"{name}{event}于{year + offset}年", "label": "FALSE", "category": name})

    # === 4. 知名成就 ===
    for achievement in entity.get("known_for", []):
        facts.append({"text": f"{name}{achievement}", "label": "TRUE", "category": name})

    # === 5. 否定事实（常见误解） ===
    for neg in entity.get("negations", []):
        facts.append({"text": neg, "label": "TRUE", "category": name})
        # FALSE: 移除否定词 → 变成错误断言
        false_version = re.sub(r'不是|没有|并非|不可以|不能', '', neg, count=1)
        if false_version.strip() and false_version != neg:
            facts.append({"text": false_version.strip(), "label": "FALSE", "category": name})

    # === 6. 朝代信息 ===
    era = entity.get("era", "")
    if era and etype == "person":
        facts.append({"text": f"{name}是{era}人", "label": "TRUE", "category": name})
        # FALSE: 错误朝代
        fake_eras = {"汉": "唐", "唐": "宋", "宋": "明", "明": "清", "清": "汉"}
        if era in fake_eras:
            facts.append({"text": f"{name}是{fake_eras[era]}人", "label": "FALSE", "category": name})

    # === 7. 地点信息 ===
    loc = entity.get("location", "")
    if loc:
        facts.append({"text": f"{name}位于{loc}", "label": "TRUE", "category": name})

    # === 8. 关系 ===
    for rel in entity.get("relations", []):
        target = rel["target"]
        rtype = rel["type"]
        if rtype == "contemporary":
            facts.append({"text": f"{name}与{target}是同时代人", "label": "TRUE", "category": name})
        elif rtype == "preceded":
            facts.append({"text": f"{name}生活在{target}之前", "label": "TRUE", "category": name})
            facts.append({"text": f"{target}生活在{name}之前", "label": "FALSE", "category": name})
        elif rtype == "discovered":
            facts.append({"text": f"{name}发现了{target}", "label": "TRUE", "category": name})

    return facts


# ============================================================
# 结构化实体库
# ============================================================




ENTITIES = [
    {
        "id": "socrates",
        "name": "苏格拉底",
        "type": "person",
        "birth": -469,
        "death": -399,
        "nationality": "古希腊",
        "field": [
            "哲学"
        ],
        "known_for": [
            "开创了苏格拉底式提问法"
        ],
        "negations": [
            "苏格拉底没有留下任何著作——他的思想主要通过柏拉图记录"
        ]
    },
    {
        "id": "schrodinger",
        "name": "薛定谔",
        "type": "person",
        "birth": 1887,
        "death": 1961,
        "nationality": "奥地利",
        "field": [
            "物理学"
        ],
        "known_for": [
            "提出了薛定谔方程"
        ],
        "key_facts": [
            "薛定谔的猫是著名的思想实验"
        ]
    },
    {
        "id": "feynman",
        "name": "费曼",
        "type": "person",
        "birth": 1918,
        "death": 1988,
        "nationality": "美国",
        "field": [
            "物理学"
        ],
        "known_for": [
            "提出了量子电动力学"
        ],
        "key_years": {
            "获诺贝尔奖": 1965
        },
        "key_facts": [
            "费曼图是量子场论的重要工具"
        ]
    },
    {
        "id": "genghis_khan",
        "name": "成吉思汗",
        "type": "person",
        "birth": 1162,
        "death": 1227,
        "nationality": "蒙古",
        "known_for": [
            "建立了蒙古帝国"
        ],
        "key_years": {
            "统一蒙古": 1206
        },
        "key_facts": [
            "成吉思汗建立了史上最大的陆上帝国"
        ],
        "negations": [
            "成吉思汗不是只懂杀戮——他也建立了法典和驿站系统"
        ]
    },
    {
        "id": "dna_discovery",
        "name": "DNA双螺旋发现",
        "type": "event",
        "key_years": {
            "发现": 1953
        },
        "key_facts": [
            "沃森和克里克于1953年发现了DNA的双螺旋结构",
            "罗莎琳德·富兰克林的X射线衍射图对发现起到了关键作用"
        ]
    },
    {
        "id": "internet_birth",
        "name": "互联网诞生",
        "type": "event",
        "key_years": {
            "ARPANET建立": 1969,
            "万维网发明": 1989
        },
        "key_facts": [
            "ARPANET于1969年建立，是互联网的前身",
            "蒂姆·伯纳斯-李于1989年发明了万维网"
        ]
    },
    {
        "id": "antibiotics",
        "name": "抗生素发现",
        "type": "event",
        "key_years": {
            "青霉素发现": 1928
        },
        "key_facts": [
            "弗莱明于1928年发现了青霉素",
            "青霉素的发现开启了抗生素时代"
        ]
    },
    {
        "id": "buddha",
        "name": "释迦牟尼",
        "type": "person",
        "birth": -563,
        "death": -483,
        "nationality": "古印度",
        "field": [
            "宗教"
        ],
        "known_for": [
            "创立了佛教"
        ],
        "key_facts": [
            "释迦牟尼原名乔达摩·悉达多"
        ]
    },
    {
        "id": "mahatma_gandhi",
        "name": "甘地",
        "type": "person",
        "birth": 1869,
        "death": 1948,
        "nationality": "印度",
        "known_for": [
            "领导了印度非暴力独立运动"
        ],
        "negations": [
            "甘地不是印度独立后第一任总理——那是尼赫鲁"
        ]
    },
    {
        "id": "mandela",
        "name": "曼德拉",
        "type": "person",
        "birth": 1918,
        "death": 2013,
        "nationality": "南非",
        "known_for": [
            "是南非反种族隔离斗士"
        ],
        "key_years": {
            "任南非总统": 1994
        },
        "negations": [
            "曼德拉不是在监狱里呆了27年连续不断——他先后被关押在多处监狱"
        ]
    }
]


# ============================================================
# 主流程
# ============================================================

def main():
    print(f"🔨 结构化实体: {len(ENTITIES)} 个\n")
    
    all_facts = []
    stats = {"TRUE": 0, "FALSE": 0}
    
    for entity in ENTITIES:
        facts = generate_facts(entity)
        for fact in facts:
            if fact["text"] not in {f["text"] for f in all_facts}:
                all_facts.append(fact)
                stats[fact["label"]] += 1
    
    print(f"  生成事实: {len(all_facts)} 条")
    print(f"  TRUE: {stats['TRUE']}, FALSE: {stats['FALSE']}")
    
    kb = {}
    for entity in ENTITIES:
        name = entity["name"]
        facts_list = [f["text"] for f in all_facts if f["category"] == name and f["label"] == "TRUE"]
        if facts_list:
            kb[name] = {
                "facts": facts_list,
                "source": entity.get("nationality", "") or entity.get("location", "") or "结构化知识库",
            }
    
    old_kb_path = ROOT / "kb_core.json"
    if old_kb_path.exists():
        with open(old_kb_path) as f:
            old_kb = json.load(f)
        for key, entry in kb.items():
            old_kb[key] = entry
        kb = old_kb
    
    with open(ROOT / "kb_core.json", "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    
    total_facts = sum(len(v["facts"]) for v in kb.values())
    print(f"\n  KB 总计: {len(kb)} 条实体, {total_facts} 条事实 → kb_core.json")
    
    from kb_compiler import compile_full, save_index, save_manifest
    idx, manifest = compile_full(kb)
    save_index(idx)
    save_manifest(manifest)
    print(f"  索引: {len(idx)/1024:.1f}KB → kb_core.idx")


if __name__ == "__main__":
    main()
