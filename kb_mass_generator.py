#!/usr/bin/env python3
"""
大规模 KB 生成器 — 导入 kb_mega_tables + 激进 FALSE 变体
目标: 10万+ 事实

生成策略:
  每条 TRUE 事实 → 3~5 条 FALSE 变体
  FALSE 手法: 数值扰动、属性混搭、否定翻转、地点替换

用法:
  python3 kb_mass_generator.py                    # 全量
  python3 kb_mass_generator.py --target 100000    # 达到10万即停
"""
import json, re, time, sys, random
from pathlib import Path

ROOT = Path(__file__).parent

# 导入数据表
sys.path.insert(0, str(ROOT))
from kb_mega_tables import (
    ELEMENTS, ALL_COUNTRIES, CHINESE_PEOPLE, WORLD_PEOPLE,
    WORLD_CITIES, SCIENCE_CONCEPTS, ANIMALS_PLANTS,
    US_STATES, CN_PROVINCES, WORLD_LANGUAGES, PROGRAMMING_LANGUAGES,
    ASTRONOMY, WORLD_UNIVERSITIES, MORE_SPECIES, LANDMARKS, OLYMPIC_SPORTS,
)

# 如果有原文件中的元数据表，兼容导入
try:
    from kb_mega_tables import DYNASTIES, HISTORICAL_FIGURES, WORLD_EVENTS, DISCOVERIES, GEOGRAPHY, MATH_CS
except ImportError:
    DYNASTIES = HISTORICAL_FIGURES = WORLD_EVENTS = DISCOVERIES = GEOGRAPHY = MATH_CS = []


def make_false_number(value, max_offset=50):
    """生成数值扰动 FALSE 版本"""
    offsets = []
    if isinstance(value, int):
        offsets = [1, -1, 10, -10, 50, -50, 100]
    elif isinstance(value, float):
        offsets = [0.1, -0.1, 1.0, -1.0, 5.0]
    for off in offsets:
        new_val = value + off
        if isinstance(value, int):
            new_val = int(new_val)
        else:
            new_val = round(new_val, 1)
        if new_val != value and new_val > 0:
            yield new_val


def gen_element_facts():
    """化学元素 → TRUE/FALSE 事实"""
    results = []
    all_names = [e[0] for e in ELEMENTS]
    all_symbols = [e[2] for e in ELEMENTS]

    for name, num, sym, category in ELEMENTS:
        key = f"元素_{sym}"
        f_true = [
            f"{name}的原子序数是{num}",
            f"{name}的元素符号是{sym}",
            f"{name}属于{category}",
        ]
        f_false = []

        # 数值扰动
        for n in make_false_number(num):
            f_false.append(f"{name}的原子序数是{n}")
        # 符号错误
        wrong_sym = random.choice([s for s in all_symbols if s != sym])
        f_false.append(f"{name}的元素符号是{wrong_sym}")
        # 分类错误
        wrong_cat = random.choice(["碱金属", "卤素", "稀有气体", "非金属", "过渡金属"])
        if wrong_cat != category:
            f_false.append(f"{name}属于{wrong_cat}")
        # 名称-序数混搭
        wrong_name = random.choice([n for n in all_names if n != name])
        f_false.append(f"{wrong_name}的原子序数是{num}")
        # 否定
        f_false.append(f"{name}的原子序数不是{num}")

        results.append((key, f_true, f_false))
    return results


def gen_country_facts():
    """国家 → TRUE/FALSE 事实"""
    results = []
    all_caps = [(c[0], c[1]) for c in ALL_COUNTRIES]

    for name, capital, continent, area, pop, currency, lang in ALL_COUNTRIES:
        key = f"国家_{name}"
        f_true = [
            f"{name}的首都是{capital}",
            f"{name}位于{continent}",
        ]
        f_false = []

        if area:
            area_str = f"{area//10000}万" if area > 100000 else f"{area//1000}千"
            f_true.append(f"{name}的面积约为{area_str}平方公里")
            for off in [1, -1, 2]:
                fake = area + off * area // 10
                if fake > 0:
                    fake_str = f"{fake//10000}万" if fake > 100000 else f"{fake//1000}千"
                    f_false.append(f"{name}的面积约为{fake_str}平方公里")

        if pop:
            pop_str = f"{pop//10 if pop < 100 else pop//100}亿" if pop >= 100 else f"{pop}千" if pop < 1 else f"{pop}万"
            f_true.append(f"{name}的人口约为{pop//10000 if pop >= 10 else pop//1000}万" if pop >= 1 else f"{name}的人口约为{int(pop*10000)}人")
            if pop >= 10:
                f_false.append(f"{name}的人口约为{pop//10000 + random.randint(1,20)}万")
            elif pop >= 1:
                f_false.append(f"{name}的人口约为{(pop + random.randint(2,10)) * 1000}万")

        # 首都错误
        others = [(n, c) for n, c in all_caps if n != name]
        if others:
            wrong = random.sample(others, min(4, len(others)))
            for wn, wc in wrong:
                f_false.append(f"{name}的首都是{wc}")
                f_false.append(f"{wn}的首都是{capital}")

        # 洲际错误
        all_continents = ["亚洲", "欧洲", "非洲", "北美洲", "南美洲", "大洋洲", "南极洲"]
        wrong_cont = random.choice([c for c in all_continents if c != continent])
        f_false.append(f"{name}位于{wrong_cont}")

        results.append((key, f_true, f_false))
    return results


def gen_person_facts(people_list, prefix="人物"):
    """人物 → TRUE/FALSE 事实"""
    results = []
    all_names = [p[0] for p in people_list]

    for name, birth, death, era, field, achievements in people_list:
        key = f"{prefix}_{name}"
        f_true = []
        f_false = []

        if birth:
            era_label = "公元前" if birth < 0 else "公元"
            f_true.append(f"{name}出生于{era_label}{abs(birth)}年")
            for n in [1, -1, 10, -10, 50, 100]:
                fb = birth + n
                if fb != birth and fb != 0:
                    el = "公元前" if fb < 0 else "公元"
                    f_false.append(f"{name}出生于{el}{abs(fb)}年")

        if death and death != 0:
            el = "公元前" if death < 0 else "公元"
            f_true.append(f"{name}于{el}{abs(death)}年去世")
            for n in [1, -1, 5, -5, 20]:
                fd = death + n
                if fd != death and fd != 0:
                    el2 = "公元前" if fd < 0 else "公元"
                    f_false.append(f"{name}于{el2}{abs(fd)}年去世")

        if era:
            f_true.append(f"{name}是{era}时期人物")
            wrong_eras = ["唐朝", "宋朝", "明朝", "清朝", "古希腊", "古罗马"]
            wrong_era = random.choice([e for e in wrong_eras if e != era])
            f_false.append(f"{name}是{wrong_era}时期人物")

        if field:
            f_true.append(f"{name}是{field}家")
            wrong_fields = ["物理学家", "化学家", "画家", "音乐家", "军事家"]
            wrong_f = random.choice([f for f in wrong_fields if f != field])
            f_false.append(f"{name}是{wrong_f}")

        # 成就混搭
        if all_names:
            other = random.choice([n for n in all_names if n != name])
            f_false.append(f"{other}是{field}家")

        # 从成就文本提取关键句
        if achievements:
            ach_list = [a.strip() for a in achievements.replace("，", ",").split(",") if a.strip()]
            for a in ach_list[:2]:
                f_true.append(f"{name}{a}")

        results.append((key, f_true, f_false))
    return results


def gen_concept_facts():
    """科学概念 → TRUE/FALSE"""
    results = []
    all_fields = set(c[1] for c in SCIENCE_CONCEPTS)

    for name, field, desc in SCIENCE_CONCEPTS:
        key = f"概念_{name}"
        f_true = [desc]
        f_false = [
            f"{name}与{random.choice(list(all_fields - {field}))}有关",
            f"{name}是由牛顿提出的",
        ]
        results.append((key, f_true, f_false))
    return results


def gen_city_facts():
    """城市 → TRUE/FALSE"""
    results = []
    all_cities = [c[0] for c in WORLD_CITIES]

    for name, country, pop, desc in WORLD_CITIES:
        key = f"城市_{name}"
        f_true = [
            f"{name}位于{country}",
            desc,
        ]
        f_false = []

        if pop:
            pop_str = f"{pop//10000}万"
            f_true.append(f"{name}的人口约{pop_str}")
            f_false.append(f"{name}的人口约{pop//10000 + random.randint(5,30)}万")

        # 国家混搭
        wrong_country = random.choice([c[0] for c in ALL_COUNTRIES if c[0] != country])
        f_false.append(f"{name}位于{wrong_country}")

        # 城市-国家混搭
        other_city = random.choice([c for c in all_cities if c != name])
        f_false.append(f"{other_city}位于{country}")

        results.append((key, f_true, f_false))
    return results


def gen_animal_facts():
    """动植物 → TRUE/FALSE"""
    results = []
    for name, category, desc in ANIMALS_PLANTS:
        key = f"生物_{name}"
        f_true = [
            f"{name}属于{category}",
            desc,
        ]
        f_false = [
            f"{name}属于{random.choice(['爬行动物', '两栖动物', '鱼类'])}",
        ]
        results.append((key, f_true, f_false))
    return results


def merge_to_kb(all_facts: list, target: int = 0):
    """合并到 kb_core.json，达到目标即停"""
    core_path = ROOT / "kb_core.json"
    if core_path.exists():
        with open(core_path) as f:
            core = json.load(f)
    else:
        core = {}

    added = 0
    for key, f_true, f_false in all_facts:
        if key not in core:
            core[key] = {"facts": [], "source": "mass_generator"}

        existing = set(core[key].get("facts", []))
        for f in f_true:
            f_clean = f.strip()
            if f_clean and f_clean not in existing:
                core[key].setdefault("facts", []).append(f_clean)
                existing.add(f_clean)
                added += 1
                if target and added >= target:
                    break
        if target and added >= target:
            break

        for f in f_false:
            f_clean = f.strip()
            if f_clean and f_clean not in existing:
                core[key].setdefault("facts", []).append(f_clean)
                existing.add(f_clean)
                added += 1
                if target and added >= target:
                    break
        if target and added >= target:
            break

    with open(core_path, "w", encoding="utf-8") as f:
        json.dump(core, f, ensure_ascii=False, indent=2)

    kb_keys = [k for k in core if not k.startswith("_")]
    total_facts = sum(len(v.get("facts", [])) for v in core.values())
    print(f"\n📊 kb_core.json: {len(kb_keys)} 键, {total_facts} 事实 (+{added})")
    return added



def gen_state_facts():
    results = []
    for name, capital, area, pop in US_STATES:
        key = f"美州_{name}"
        f_true = [f"{name}州的首府是{capital}"]
        f_false = []
        others = [(s[0], s[1]) for s in US_STATES if s[1] != capital]
        if others:
            wrong = random.sample(others, min(3, len(others)))
            for _, wc in wrong:
                f_false.append(f"{name}州的首府是{wc}")
        f_false.append(f"{name}州的首府不是{capital}")
        f_false.append(f"{name}是加拿大的一个省")
        results.append((key, f_true, f_false))
    return results


def gen_province_facts():
    results = []
    all_regions = ["华北", "东北", "华东", "华中", "华南", "西南", "西北"]
    for name, region, area, pop in CN_PROVINCES:
        key = f"中省_{name}"
        f_true = [f"{name}位于中国{region}地区"]
        f_false = []
        if pop:
            f_true.append(f"{name}的人口约为{pop}万")
            f_false.append(f"{name}的人口约为{pop + random.randint(10,100)}万")
        wrong_r = random.choice([r for r in all_regions if r != region])
        f_false.append(f"{name}位于中国{wrong_r}地区")
        results.append((key, f_true, f_false))
    return results


def gen_language_facts():
    results = []
    families = ["印欧语系", "汉藏语系", "南岛语系", "闪含语系"]
    for name, family, speakers, desc in WORLD_LANGUAGES:
        key = f"语言_{name}"
        f_true = [f"{name}属于{family}", desc]
        f_false = [f"{name}属于{random.choice(families)}"]
        if speakers:
            f_true.append(f"{name}约有{speakers}亿使用者")
        results.append((key, f_true, f_false))
    return results


def gen_programming_lang_facts():
    results = []
    for name, year, author, desc in PROGRAMMING_LANGUAGES:
        key = f"编程_{name}"
        f_true = [f"{name}由{author}于{year}年创建", desc]
        f_false = [
            f"{name}是在{year + random.randint(5, 15)}年创建的",
            f"{name}是一种操作系统",
        ]
        results.append((key, f_true, f_false))
    return results


def gen_astronomy_facts():
    results = []
    for name, size, etype, desc in ASTRONOMY:
        key = f"天体_{name}"
        f_true = [f"{name}属于{etype}", desc]
        f_false = [f"{name}是一种人造卫星"]
        if size > 0:
            f_true.append(f"{name}的直径约{size:,}公里")
        results.append((key, f_true, f_false))
    return results


def gen_university_facts():
    results = []
    for name, country, year, desc in WORLD_UNIVERSITIES:
        key = f"大学_{name}"
        f_true = [f"{name}位于{country}", f"{name}成立于{year}年", desc]
        f_false = [f"{name}位于{random.choice(['美国', '英国', '日本', '德国'])}"]
        results.append((key, f_true, f_false))
    return results


def gen_landmark_facts():
    results = []
    countries = ["法国", "美国", "中国", "日本", "印度", "埃及"]
    for name, cty, year, height, desc in LANDMARKS:
        key = f"地标_{name}"
        f_true = [desc]
        if cty:
            f_true.append(f"{name}位于{cty}")
        if year and year > 0:
            f_true.append(f"{name}建成于{year}年")
        f_false = [f"{name}位于{random.choice(countries)}"]
        results.append((key, f_true, f_false))
    return results


def gen_olympic_facts():
    results = []
    for name, season, desc in OLYMPIC_SPORTS:
        key = f"奥运_{name}"
        f_true = [f"{name}是{season}奥运会项目", desc]
        f_false = [f"{name}是{'夏季' if season == '冬季' else '冬季'}奥运会项目"]
        results.append((key, f_true, f_false))
    return results


def gen_more_species_facts():
    results = []
    cats = ["哺乳动物", "鸟类", "鱼类", "爬行动物", "昆虫"]
    for name, category, desc in MORE_SPECIES:
        key = f"物种_{name}"
        f_true = [f"{name}属于{category}", desc]
        f_false = [f"{name}属于{random.choice(cats)}"]
        results.append((key, f_true, f_false))
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=0, help="目标新增事实数")
    args = parser.parse_args()

    print("=" * 60)
    print("  大规模 KB 生成器 v2 (激进 FALSE 变体)")
    target_str = f"{args.target:,}" if args.target else "无限制"
    print(f"  目标: +{target_str}")
    print("=" * 60)

    # 先加载当前 KB
    core_path = ROOT / "kb_core.json"
    with open(core_path) as f:
        core = json.load(f)
    start_total = sum(len(v.get("facts", [])) for v in core.values())
    print(f"  当前: {start_total:,} 事实\n")

    generators = [
        ("化学元素(激进)", lambda: gen_element_facts()),
        ("国家/地区(激进)", lambda: gen_country_facts()),
        ("中国人物(激进)", lambda: gen_person_facts(CHINESE_PEOPLE, "人物中")),
        ("世界人物(激进)", lambda: gen_person_facts(WORLD_PEOPLE, "人物世")),
        ("科学概念(激进)", lambda: gen_concept_facts()),
        ("世界城市(激进)", lambda: gen_city_facts()),
        ("动植物(激进)", lambda: gen_animal_facts()),
        ("美国州", lambda: gen_state_facts()),
        ("中国省份", lambda: gen_province_facts()),
        ("世界语言", lambda: gen_language_facts()),
        ("编程语言", lambda: gen_programming_lang_facts()),
        ("天文学", lambda: gen_astronomy_facts()),
        ("世界大学", lambda: gen_university_facts()),
        ("世界地标", lambda: gen_landmark_facts()),
        ("奥运项目", lambda: gen_olympic_facts()),
        ("更多物种", lambda: gen_more_species_facts()),
    ]

    all_facts = []
    total_raw = 0
    for name, gen_func in generators:
        facts = gen_func()
        raw = sum(len(t) + len(f) for _, t, f in facts)
        all_facts.extend(facts)
        total_raw += raw
        print(f"  📦 {name}: {len(facts)} 键, {raw} 事实(原始)")

    print(f"\n  🔢 原始总计: {len(all_facts)} 键, {total_raw:,} 事实")

    actual_target = args.target if args.target > 0 else None
    added = merge_to_kb(all_facts, target=actual_target)
    print(f"  ✅ 净新增: +{added:,} 事实")

    # 再读出总事实数
    with open(core_path) as f:
        core = json.load(f)
    final_total = sum(len(v.get("facts", [])) for v in core.values())
    kb_keys = [k for k in core if not k.startswith("_")]
    print(f"  📊 总计: {len(kb_keys)} 键, {final_total:,} 事实")
    print(f"  📈 增长率: +{final_total - start_total:,} ({100*(final_total-start_total)/max(start_total,1):.0f}%)")


if __name__ == "__main__":
    main()

# ============================================================
# 新增生成器函数
# ============================================================

def gen_state_facts():
    """美国州 → TRUE/FALSE"""
    results = []
    all_names = [s[0] for s in US_STATES]
    for name, capital, area, pop in US_STATES:
        key = f"美国州_{name}"
        f_true = [
            f"{name}州的首府是{capital}",
            f"{name}州属于美国",
        ]
        f_false = []
        # 错误首府
        others = [s for s in US_STATES if s[1] != capital]
        if others:
            wrong = random.sample(others, min(3, len(others)))
            for _, wc, _, _ in wrong:
                f_false.append(f"{name}州的首府是{wc}")
        # 否定
        f_false.append(f"{name}州的首府不是{capital}")
        # 国家混淆
        f_false.append(f"{name}是加拿大的一个省")

        results.append((key, f_true, f_false))
    return results


def gen_province_facts():
    """中国省份 → TRUE/FALSE"""
    results = []
    for name, region, area, pop in CN_PROVINCES:
        key = f"中国省_{name}"
        f_true = [
            f"{name}位于中国{region}地区",
        ]
        f_false = []
        if pop:
            f_true.append(f"{name}的人口约为{pop}万")
            f_false.append(f"{name}的人口约为{pop + random.randint(10,100)}万")
        # 区域错误
        all_regions = ["华北", "东北", "华东", "华中", "华南", "西南", "西北"]
        wrong_r = random.choice([r for r in all_regions if r != region])
        f_false.append(f"{name}位于中国{wrong_r}地区")
        # 否定
        f_false.append(f"{name}不属于中国")

        results.append((key, f_true, f_false))
    return results


def gen_language_facts():
    """语言 → TRUE/FALSE"""
    results = []
    for name, family, speakers, desc in WORLD_LANGUAGES:
        key = f"语言_{name}"
        f_true = [
            f"{name}属于{family}",
            desc,
        ]
        f_false = []
        if speakers:
            f_true.append(f"{name}约有{speakers}亿使用者")
            if speakers > 1:
                f_false.append(f"{name}约有{speakers + random.randint(1,10)}亿使用者")
        # 语系错误
        f_false.append(f"{name}属于{random.choice(['印欧语系','汉藏语系','南岛语系'])}")
        # 否定
        f_false.append(f"{name}是虚构的语言")

        results.append((key, f_true, f_false))
    return results


def gen_programming_lang_facts():
    """编程语言 → TRUE/FALSE"""
    results = []
    for name, year, author, desc in PROGRAMMING_LANGUAGES:
        key = f"编程_{name}"
        f_true = [
            f"{name}由{author}于{year}年创建",
            desc,
        ]
        f_false = [
            f"{name}由{random.choice(['Google','Microsoft','Apple'])}创建",
            f"{name}是在{year+random.randint(5,15)}年创建的",
        ]
        results.append((key, f_true, f_false))
    return results


def gen_astronomy_facts():
    """天体 → TRUE/FALSE"""
    results = []
    for name, size, etype, desc in ASTRONOMY:
        key = f"天体_{name}"
        f_true = [
            f"{name}属于{etype}",
            desc,
        ]
        f_false = []
        if size > 0:
            f_true.append(f"{name}的直径约{size:,}公里")
            if size > 100:
                f_false.append(f"{name}的直径约{size + random.randint(10000,50000):,}公里")

        wrong_types = [t for t in ["恒星", "行星", "卫星", "彗星", "星系", "矮行星"] if t != etype]
        if wrong_types:
            f_false.append(f"{name}属于{random.choice(wrong_types)}")

        results.append((key, f_true, f_false))
    return results


def gen_university_facts():
    """大学 → TRUE/FALSE"""
    results = []
    for name, country, year, desc in WORLD_UNIVERSITIES:
        key = f"大学_{name}"
        f_true = [
            f"{name}位于{country}",
            f"{name}成立于{year}年",
            desc,
        ]
        f_false = [
            f"{name}位于{random.choice(['英国','美国','日本','德国'])}",
            f"{name}成立于{year + random.randint(50,200)}年",
        ]
        results.append((key, f_true, f_false))
    return results


def gen_landmark_facts():
    """地标 → TRUE/FALSE"""
    results = []
    for name, country, year, height, desc in LANDMARKS:
        key = f"地标_{name}"
        f_true = [desc]
        if country:
            f_true.append(f"{name}位于{country}")
        if year and year > 0:
            f_true.append(f"{name}建成于{year}年")
        elif year:
            f_true.append(f"{name}建于公元前{abs(year)}年")
        f_false = [
            f"{name}位于{random.choice(['法国','美国','中国','日本'])}",
        ]
        results.append((key, f_true, f_false))
    return results


def gen_olympic_facts():
    """奥运项目 → TRUE/FALSE"""
    results = []
    for name, season, desc in OLYMPIC_SPORTS:
        key = f"奥运_{name}"
        f_true = [
            f"{name}是{season}奥运会项目",
            desc,
        ]
        f_false = [
            f"{name}是{'夏季' if season == '冬季' else '冬季'}奥运会项目",
        ]
        results.append((key, f_true, f_false))
    return results


def gen_more_species_facts():
    """更多动植物 → TRUE/FALSE"""
    results = []
    for name, category, desc in MORE_SPECIES:
        key = f"物种_{name}"
        f_true = [
            f"{name}属于{category}",
            desc,
        ]
        f_false = [
            f"{name}属于{random.choice(['哺乳动物','鸟类','鱼类'])}",
        ]
        results.append((key, f_true, f_false))
    return results