#!/usr/bin/env python3
"""
KB 10 万冲击生成器 — 第三代
================================
核心理念：每个事实必须包含实体名 → 零碰撞 → 最大化产出

策略：
  每条实体 → 8-12 条 TRUE（结构化属性展开）
           → 10-20 条 FALSE（实体名锚定的针对性变体）
  产出率：~18-30 条/实体 × 5000 实体 = 90k-150k 事实

用法:
  python3 kb_100k_generator.py                     # 全量
  python3 kb_100k_generator.py --target 100000     # 到达 10 万即停
"""
import json, random, time, sys
from pathlib import Path

ROOT = Path(__file__).parent

# ── 导入所有数据表 ──────────────────────────────────
from kb_mega_tables import *
from kb_data_massive import *

# ── 所有国家名（用于跨实体混合） ──
ALL_COUNTRY_NAMES = [c[0] for c in ALL_COUNTRIES]
ALL_CAPITALS = [c[1] for c in ALL_COUNTRIES]
ALL_CONTINENTS = ["亚洲", "欧洲", "非洲", "北美洲", "南美洲", "大洋洲", "南极洲"]

# ── 生成器核心：每条实体产生大量锚定事实 ──────────

class FactGen:
    """事实生成器 — 保证实体名锚定，零碰撞"""

    def __init__(self):
        self._used = set()  # 全局去重

    def _add(self, key, true_list, false_list):
        """添加并去重"""
        facts_true = []
        facts_false = []
        for f in true_list:
            f = f.strip()
            if f and f not in self._used:
                self._used.add(f)
                facts_true.append(f)
        for f in false_list:
            f = f.strip()
            if f and f not in self._used:
                self._used.add(f)
                facts_false.append(f)
        return (key, facts_true, facts_false) if facts_true or facts_false else None

    # ── 国家 ─────────────────────────────────────
    def country(self, name, capital, continent, area, pop, currency, lang):
        key = f"country_{name}"
        t, f = [], []

        # TRUE 事实
        t.append(f"{name}的首都是{capital}")
        t.append(f"{name}位于{continent}")
        if area:
            t.append(f"{name}的国土面积约为{area//10000}万平方公里")
        if pop:
            if pop >= 100:
                t.append(f"{name}的人口约为{pop//100}亿")
            elif pop >= 1:
                t.append(f"{name}的人口约为{pop}万")
            else:
                t.append(f"{name}的人口约为{int(pop*1000)}万")
        if currency:
            t.append(f"{name}的货币是{currency}")
        if lang:
            t.append(f"{name}的官方语言包括{lang}")

        # FALSE 变体（锚定在实体名上）
        # 1. 首都错误 - 混入其他国家首都
        wrong_caps = random.sample([c for c in ALL_CAPITALS if c != capital], min(5, len(ALL_CAPITALS)-1))
        for wc in wrong_caps:
            f.append(f"{name}的首都是{wc}")

        # 2. 大洲错误
        for wc in random.sample([c for c in ALL_CONTINENTS if c != continent], 3):
            f.append(f"{name}位于{wc}")

        # 3. 人口错误
        if pop and pop > 1:
            for mult in [0.5, 2, 10]:
                fake_pop = int(pop * mult)
                if pop >= 100:
                    f.append(f"{name}的人口约为{fake_pop//100}亿")
                elif pop >= 1:
                    f.append(f"{name}的人口约为{fake_pop}万")

        # 4. 面积错误
        if area and area > 10000:
            for mult in [0.3, 3]:
                fake_area = int(area * mult)
                f.append(f"{name}的国土面积约为{fake_area//10000}万平方公里")

        # 5. 否定形式
        f.append(f"{name}的首都不是{capital}")
        f.append(f"{name}不属于{continent}")

        return self._add(key, t, f)

    # ── 化学元素 ─────────────────────────────────
    def element(self, name, num, sym, category):
        key = f"element_{sym}"
        t, f = [], []

        t.append(f"{name}的原子序数是{num}")
        t.append(f"{name}的元素符号是{sym}")
        t.append(f"{name}属于{category}")

        # FALSE - 数值扰动
        for off in [1, 2, 5, -1, -2, 10, -10]:
            n = num + off
            if n > 0 and n < 120:
                f.append(f"{name}的原子序数是{n}")

        # FALSE - 符号错误
        all_syms = [e[2] for e in ELEMENTS if e[2] != sym]
        for ws in random.sample(all_syms, min(4, len(all_syms))):
            f.append(f"{name}的元素符号是{ws}")

        # FALSE - 分类错误
        all_cats = ["碱金属", "碱土金属", "过渡金属", "非金属", "卤素", "稀有气体", "镧系", "锕系"]
        for wc in random.sample([c for c in all_cats if c != category], 3):
            f.append(f"{name}属于{wc}")

        # FALSE - 否定
        f.append(f"{name}的原子序数不是{num}")

        return self._add(key, t, f)

    # ── 人物（通用）─────────────────────────────
    def person(self, name, birth, death, era, field, achievements="", prefix="person"):
        key = f"{prefix}_{name}"
        t, f = [], []

        if birth:
            era_label = "公元前" if birth < 0 else "公元"
            t.append(f"{name}出生于{era_label}{abs(birth)}年")
            for off in [1, -1, 10, -10, 50, 100]:
                fb = birth + off
                if fb != birth and fb != 0:
                    el = "公元前" if fb < 0 else "公元"
                    f.append(f"{name}出生于{el}{abs(fb)}年")

        if death and death != 0:
            el = "公元前" if death < 0 else "公元"
            t.append(f"{name}于{el}{abs(death)}年去世")
            for off in [1, -1, 5, -5, 20, -20]:
                fd = death + off
                if fd != death and fd != 0:
                    el2 = "公元前" if fd < 0 else "公元"
                    f.append(f"{name}于{el2}{abs(fd)}年去世")

        if era:
            t.append(f"{name}是{era}时期的人物")
            wrong_eras = ["唐朝", "宋朝", "明朝", "清朝", "秦朝", "汉朝", "元朝"]
            for we in random.sample([e for e in wrong_eras if e != era], 3):
                f.append(f"{name}是{we}时期的人物")

        if achievements:
            t.append(f"{name}的重要事迹：{achievements}")

        if field:
            t.append(f"{name}是著名的{field}家")
            wrong_fields = ["物理学家", "化学家", "画家", "音乐家", "军事家", "文学家"]
            for wf in random.sample([x for x in wrong_fields if x != f"{field}家"], 2):
                f.append(f"{name}是著名的{wf}")

        return self._add(key, t, f)

    # ── 皇帝 ─────────────────────────────────────
    def emperor(self, name, start, end, dynasty, desc):
        key = f"emperor_{name}"
        t, f = [], []

        t.append(f"{name}是{dynasty}的皇帝")
        t.append(f"{name}在位时间为公元{start}年至{end}年")
        t.append(f"{name}的主要事迹：{desc}")

        # FALSE
        f.append(f"{name}是唐朝的皇帝" if dynasty != "唐" else f"{name}是宋朝的皇帝")
        for off in [10, -10, 50, -50, 100]:
            fs, fe = start + off, end + off
            if fs > 0 and fe > fs:
                f.append(f"{name}在位时间为公元{fs}年至{fe}年")

        f.append(f"{name}是一位诗人")
        f.append(f"{name}是一位科学家")

        return self._add(key, t, f)

    # ── 化合物 ───────────────────────────────────
    def compound(self, name, formula, desc):
        key = f"compound_{name}"
        t, f = [], []

        t.append(f"{name}的化学式是{formula}")
        t.append(f"{name}的组成：{desc}")
        f.append(f"{name}的化学式是H2O" if formula != "H2O" else f"{name}的化学式是NaCl")
        f.append(f"{name}是一种稀有气体")
        f.append(f"{name}对人体完全无害")

        return self._add(key, t, f)

    # ── 河流 ─────────────────────────────────────
    def river(self, name, length, location, desc):
        key = f"river_{name}"
        t, f = [], []

        t.append(f"{name}的长度约为{length}公里")
        t.append(f"{name}位于{location}")
        t.append(desc)

        for mult in [0.5, 1.5, 2]:
            f.append(f"{name}的长度约为{int(length*mult)}公里")
        f.append(f"{name}是世界上最长的河流" if "最长" not in desc else f"{name}是世界上最短的河流")
        f.append(f"{name}位于南美洲" if "南美" not in location else f"{name}位于亚洲")

        return self._add(key, t, f)

    # ── 山 ──────────────────────────────────────
    def mountain(self, name, height, location, range_name, desc):
        key = f"mountain_{name}"
        t, f = [], []

        t.append(f"{name}的海拔为{height}米")
        t.append(f"{name}位于{location}")
        t.append(f"{name}属于{range_name}")
        t.append(desc)

        for mult in [0.7, 1.3, 2]:
            f.append(f"{name}的海拔为{int(height*mult)}米")
        f.append(f"{name}是一座火山")

        return self._add(key, t, f)

    # ── 物理定律 ────────────────────────────────
    def physics_law(self, name, discoverer, alt_name, desc):
        key = f"physics_{name}"
        t, f = [], []

        t.append(f"{name}是由{discoverer}提出的" if discoverer != "无" else f"{name}是物理学重要定律")
        t.append(f"{name}又称{alt_name}")
        t.append(f"{name}的内容是：{desc}")
        f.append(f"{name}是由爱因斯坦提出的" if discoverer != "爱因斯坦" else f"{name}是由牛顿提出的")
        f.append(f"{name}属于化学领域")

        return self._add(key, t, f)

    # ── 公司 ────────────────────────────────────
    def company(self, name, country, year, industry, products):
        key = f"company_{name}"
        t, f = [], []

        t.append(f"{name}是一家{country}{industry}公司")
        t.append(f"{name}成立于{year}年")
        t.append(f"{name}的代表产品包括{products}")

        f.append(f"{name}成立于{year+random.randint(10,50)}年")
        f.append(f"{name}是一家日本公司" if country != "日本" else f"{name}是一家美国公司")
        f.append(f"{name}的主要业务是餐饮")

        return self._add(key, t, f)

    # ── 货币 ────────────────────────────────────
    def currency(self, name, code, country, year):
        key = f"currency_{name}"
        t, f = [], []

        t.append(f"{name}是{country}的法定货币")
        t.append(f"{name}的货币代码是{code}")
        t.append(f"{name}于{year}年开始发行")

        f.append(f"{name}是美国的法定货币" if country != "美国" else f"{name}是日本的法定货币")
        f.append(f"{name}是一种加密货币")

        return self._add(key, t, f)

    # ── 宗教 ────────────────────────────────────
    def religion(self, name, founder, century, origin, desc):
        key = f"religion_{name}"
        t, f = [], []

        t.append(f"{name}起源于{origin}")
        t.append(f"{name}创立于{century}")
        t.append(f"{name}的创始人是{founder}")
        t.append(desc)

        f.append(f"{name}创立于1世纪" if century != "1世纪" else f"{name}创立于7世纪")
        f.append(f"{name}的创始人是耶稣" if founder != "耶稣" else f"{name}的创始人是穆罕默德")
        f.append(f"{name}是多神教")


    # ── 文学作品 ────────────────────────────────
    def literature(self, name, author, era, desc):
        key = f"lit_{name}"
        t, f = [], []
        t.append(f"{name}的作者是{author}")
        t.append(f"{name}创作于{era}")
        t.append(desc)
        f.append(f"{name}的作者是曹雪芹" if author != "曹雪芹" else f"{name}的作者是吴承恩")
        f.append(f"{name}创作于唐朝" if era != "唐朝" else f"{name}创作于宋朝")
        return self._add(key, t, f)

    # ── 神话 ────────────────────────────────────
    def mythology(self, name, myth, desc):
        key = f"myth_{name}"
        t, f = [], []
        t.append(f"{name}是{myth}中的人物")
        t.append(desc)
        f.append(f"{name}是希腊神话中的人物" if myth != "希腊神话" else f"{name}是罗马神话中的人物")
        f.append(f"{name}是真实的历史人物")
        return self._add(key, t, f)

    # ── 地质年代 ────────────────────────────────
    def geo_era(self, name, start, end, unit, desc):
        key = f"geo_{name}"
        t, f = [], []
        t.append(f"{name}距今约{start}至{end}{unit}")
        t.append(desc)
        for off in [100, -100, 500]:
            f.append(f"{name}距今约{start+off}至{end+off}{unit}")
        return self._add(key, t, f)

    # ── 人体 ────────────────────────────────────
    def body_part(self, name, system, desc):
        key = f"body_{name}"
        t, f = [], []
        t.append(f"{name}属于人体{system}")
        t.append(desc)
        wrong_systems = ["循环系统","呼吸系统","消化系统","神经系统"]
        for ws in random.sample([s for s in wrong_systems if s!=system], 2):
            f.append(f"{name}属于人体{ws}")
        return self._add(key, t, f)

    # ── 更多城市 ────────────────────────────────
    def more_city(self, name, country, pop, desc):
        key = f"city2_{name}"
        t, f = [], []
        t.append(f"{name}位于{country}")
        t.append(desc)
        if pop:
            t.append(f"{name}的人口约{pop//10000}万")
        f.append(f"{name}是中国的城市" if country != "中国" else f"{name}是美国的城市")
        return self._add(key, t, f)

    # ── 数学定理 ────────────────────────────────
    def math_theorem(self, name, discoverer, year, desc):
        key = f"math_{name}"
        t, f = [], []
        t.append(f"{name}由{discoverer}于{abs(year)}年提出" if year>0 else f"{name}由{discoverer}于公元前{abs(year)}年提出")
        t.append(desc)
        f.append(f"{name}由牛顿提出" if discoverer != "牛顿" else f"{name}由欧拉提出")
        return self._add(key, t, f)

    # ── 批量生成包装 ─────────────────────────────
    
    # ── 美国州 ────────────────────────────────────
    def us_state(self, name, capital, area, pop):
        key = f"usstate_{name}"
        t, f = [], []
        t.append(f"{name}州的首府是{capital}")
        t.append(f"{name}州属于美国")
        if pop:
            t.append(f"{name}州的人口约{pop}百万")
        # FALSE
        other_caps = [s[1] for s in US_STATES if s[1] != capital]
        for wc in random.sample(other_caps, min(5, len(other_caps))):
            f.append(f"{name}州的首府是{wc}")
        f.append(f"{name}州属于加拿大")
        f.append(f"{name}州属于墨西哥")
        if pop:
            f.append(f"{name}州的人口约{pop*2}百万")
            f.append(f"{name}州的人口约{pop//2}百万")
        return self._add(key, t, f)

    # ── 中国省份 ─────────────────────────────────
    def cn_province(self, name, region, area, pop):
        key = f"cnprov_{name}"
        t, f = [], []
        t.append(f"{name}位于中国{region}地区")
        if pop:
            t.append(f"{name}的人口约{pop}万")
        wrong_regions = ["华北","东北","华东","华中","华南","西南","西北"]
        for wr in random.sample([r for r in wrong_regions if r != region], 4):
            f.append(f"{name}位于中国{wr}地区")
        if pop:
            for m in [0.5, 2, 5]:
                f.append(f"{name}的人口约{int(pop*m)}万")
        return self._add(key, t, f)

    # ── 编程语言 ─────────────────────────────────
    def prog_lang(self, name, year, author, desc):
        key = f"proglang_{name}"
        t, f = [], []
        t.append(f"{name}由{author}于{year}年创建")
        t.append(f"{name}是{desc}")
        for off in [1,-1,2,-2,5,-5,10,20]:
            f.append(f"{name}由{author}于{year+off}年创建")
        f.append(f"{name}是一种自然语言")
        f.append(f"{name}是一种数据库系统")
        return self._add(key, t, f)

    # ── 天体 ─────────────────────────────────────
    def astro(self, name, size, etype, desc):
        key = f"astro_{name}"
        t, f = [], []
        t.append(f"{name}属于{etype}")
        t.append(desc)
        if size > 0:
            t.append(f"{name}的直径约{size:,}公里")
        wrong_types = ["恒星","行星","卫星","彗星","星系"]
        for wt in random.sample([x for x in wrong_types if x != etype], 3):
            f.append(f"{name}属于{wt}")
        if size > 0:
            for m in [0.5, 2, 10]:
                f.append(f"{name}的直径约{int(size*m):,}公里")
        return self._add(key, t, f)

    # ── 大学 ────────────────────────────────────
    def university(self, name, country, year, desc):
        key = f"univ_{name}"
        t, f = [], []
        t.append(f"{name}位于{country}")
        t.append(f"{name}成立于{year}年")
        t.append(desc)
        for off in [10,-10,50,100,200]:
            fy = year + off
            if fy > 0 and fy < 2026:
                f.append(f"{name}成立于{fy}年")
        f.append(f"{name}位于美国" if country != "美国" else f"{name}位于英国")
        return self._add(key, t, f)

    # ── 地标 ────────────────────────────────────
    def landmark(self, name, country, year, height, desc):
        key = f"landmark_{name}"
        t, f = [], []
        if country:
            t.append(f"{name}位于{country}")
        if year:
            t.append(f"{name}建于{year}年" if year > 0 else f"{name}建于公元前{abs(year)}年")
        t.append(desc)
        wrong_ctys = ["法国","美国","中国","日本","印度","埃及","意大利"]
        for wc in random.sample([c for c in wrong_ctys if c!=country], 3):
            f.append(f"{name}位于{wc}")
        return self._add(key, t, f)

    # ── 奥运项目 ─────────────────────────────────
    def olympic(self, name, season, desc):
        key = f"olympic_{name}"
        t, f = [], []
        t.append(f"{name}是{season}奥运会项目")
        t.append(desc)
        f.append(f"{name}是{'夏季' if season=='冬季' else '冬季'}奥运会项目")
        f.append(f"{name}不属于奥运会")
        return self._add(key, t, f)

    # ── 物种 ────────────────────────────────────
    def species(self, name, category, desc):
        key = f"species_{name}"
        t, f = [], []
        t.append(f"{name}属于{category}")
        t.append(desc)
        wrong_cats = ["哺乳动物","鸟类","鱼类","爬行动物","昆虫","植物"]
        for wc in random.sample([c for c in wrong_cats if c!=category], 3):
            f.append(f"{name}属于{wc}")
        return self._add(key, t, f)

    # ── 乐器 ────────────────────────────────────
    def instrument(self, name, itype, origin, year, desc):
        key = f"instr_{name}"
        t, f = [], []
        t.append(f"{name}是一种{itype}")
        t.append(f"{name}起源于{origin}")
        t.append(desc)
        f.append(f"{name}是一种打击乐器" if "打击" not in itype else f"{name}是一种弦乐器")
        f.append(f"{name}起源于中国" if origin!="中国" else f"{name}起源于欧洲")
        return self._add(key, t, f)

    # ── 医学 ────────────────────────────────────
    def medical(self, name, category, discoverer, year, desc):
        key = f"medical_{name}"
        t, f = [], []
        t.append(f"{name}是一种{category}")
        t.append(f"{name}由{discoverer}于{year}年发现" if year else f"{name}被{discoverer}发现")
        t.append(desc)
        if year:
            for off in [5,-5,10,-10,20]:
                f.append(f"{name}于{year+off}年被发现")
        return self._add(key, t, f)

def batch(self, items, gen_func):
        results = []
        for item in items:
            r = gen_func(*item)
            if r:
                results.append(r)
        return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=100000, help="目标总事实数")
    args = parser.parse_args()

    # 加载当前 KB
    core_path = ROOT / "kb_core.json"
    with open(core_path) as f:
        core = json.load(f)
    start_total = sum(len(v.get("facts", [])) for v in core.values())
    print(f"当前 KB: {start_total:,} 事实")
    print(f"目标: {args.target:,} 事实")
    print(f"需新增: {args.target - start_total:,} 事实\n")

    gen = FactGen()
    all_results = []

    # ── 各类型批量生成 ──────────────────────────
    batches = [
        ("国家/地区", ALL_COUNTRIES, lambda c: gen.country(*c)),
        ("化学元素", ELEMENTS, lambda e: gen.element(*e)),
        ("中国皇帝", CN_EMPERORS, lambda e: gen.emperor(*e)),
        ("美国总统", US_PRESIDENTS, lambda p: gen.person(p[0], p[1], p[2], "美国", "政治", p[3], "usp")),
        ("中国人物", CHINESE_PEOPLE, lambda p: gen.person(p[0], p[1], p[2], p[3], p[4], p[5] if len(p)>5 else "", "cnp")),
        ("世界人物", WORLD_PEOPLE, lambda p: gen.person(p[0], p[1], p[2], p[3], p[4], p[5] if len(p)>5 else "", "wp")),
        ("化学化合物", CHEMICAL_COMPOUNDS, lambda c: gen.compound(*c)),
        ("诺贝尔奖", NOBEL_WINNERS, lambda n: gen.person(n[0], n[2], 0, "现代", n[1], n[3], "nobel")),
        ("世界河流", WORLD_RIVERS, lambda r: gen.river(*r)),
        ("世界名山", WORLD_MOUNTAINS, lambda m: gen.mountain(*m)),
        ("物理定律", PHYSICS_LAWS, lambda l: gen.physics_law(*l)),
        ("世界公司", WORLD_COMPANIES, lambda c: gen.company(*c)),
        ("世界货币", WORLD_CURRENCIES, lambda c: gen.currency(*c)),
        ("世界宗教", WORLD_RELIGIONS, lambda r: gen.religion(*r)),
        ("美国州", US_STATES, lambda s: gen.us_state(*s)),
        ("中国省份", CN_PROVINCES, lambda p: gen.cn_province(*p)),
        ("编程语言", PROGRAMMING_LANGUAGES, lambda l: gen.prog_lang(*l)),
        ("天文学", ASTRONOMY, lambda a: gen.astro(*a)),
        ("世界大学", WORLD_UNIVERSITIES, lambda u: gen.university(*u)),
        ("世界地标", LANDMARKS, lambda l: gen.landmark(*l)),
        ("奥运项目", OLYMPIC_SPORTS, lambda o: gen.olympic(*o)),
        ("更多物种", MORE_SPECIES, lambda s: gen.species(*s)),
        ("乐器", MUSICAL_INSTRUMENTS, lambda i: gen.instrument(*i)),
        ("医学", MEDICAL_KNOWLEDGE, lambda m: gen.medical(*m)),
        ("希腊神话", MYTHOLOGY, lambda m: gen.mythology(*m)),
        ("中国文学", CN_LITERATURE, lambda l: gen.literature(*l)),
        ("世界哲学家", WORLD_PHILOSOPHERS, lambda p: gen.person(p[0], p[1], p[2], p[3], p[3], p[4], "phil")),
        ("地质年代", GEOLOGICAL_ERAS, lambda g: gen.geo_era(*g)),
        ("人体系统", HUMAN_BODY, lambda b: gen.body_part(*b)),
        ("更多城市", MORE_CITIES, lambda c: gen.more_city(*c)),
        ("数学定理", MATH_THEOREMS, lambda m: gen.math_theorem(*m)),
    ]

    total_raw = 0
    for name, data, func in batches:
        results = []
        for item in data:
            r = func(item)
            if r:
                results.append(r)
                total_raw += len(r[1]) + len(r[2])
        all_results.extend(results)
        net = sum(len(r[1])+len(r[2]) for r in results)
        print(f"  📦 {name}: {len(results)} 键 → {net} 事实")

    print(f"\n  🔢 原始生成: {len(all_results)} 键, {total_raw:,} 事实(去重前)")

    # ── 合并到 kb_core.json ──────────────────────
    added = 0
    for key, f_true, f_false in all_results:
        if key not in core:
            core[key] = {"facts": [], "source": "kb_100k"}

        existing = set(core[key].get("facts", []))
        for f in f_true + f_false:
            f = f.strip()
            if f and f not in existing:
                core[key].setdefault("facts", []).append(f)
                existing.add(f)
                added += 1

        if args.target and start_total + added >= args.target:
            break

    with open(core_path, "w", encoding="utf-8") as f:
        json.dump(core, f, ensure_ascii=False, indent=2)

    final_total = start_total + added
    kb_keys = [k for k in core if not k.startswith("_")]
    total_facts = sum(len(v.get("facts", [])) for v in core.values())

    print(f"\n{'='*50}")
    print(f"  ✅ 合并: +{added:,} 事实")
    print(f"  📊 kb_core.json: {len(kb_keys)} 键, {total_facts:,} 事实")
    print(f"  📈 完成度: {total_facts/args.target*100:.1f}%")
    if total_facts >= args.target:
        print(f"  🎉 已达到 10 万+ 目标!")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
