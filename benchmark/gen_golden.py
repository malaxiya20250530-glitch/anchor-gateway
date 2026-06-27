#!/usr/bin/env python3
"""
黄金基准集生成器 — 按 Checker 分类，带难度标签，TRUE/FALSE 对照。

输出: benchmark/{checker_name}.jsonl
格式: {"id":"xxx","text":"...","label":"TRUE|FALSE","category":"...","checker":["..."],"difficulty":"easy|medium|hard"}
"""

import json, sys, os, random, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 加载 KB
with open(Path(__file__).parent.parent / 'kb_core.json') as f:
    KB = json.load(f)

BENCH_DIR = Path(__file__).parent
random.seed(42)

# ============================================================
# 基础数据：从 KB 提取事实
# ============================================================

def collect_facts():
    """从 KB 收集可用的正确/错误事实"""
    positives = []
    negatives = []
    
    for key, entry in KB.items():
        for fact in entry.get("facts", []):
            # 正确事实
            positives.append({"text": fact, "source": key})
            # 否定事实（从含"不是/没有/并非"的 fact 中提取）
            if re.search(r'不是|没有|并非|不可以', fact):
                # 提取其中的否定部分作为 FALSE 样本
                negated = re.sub(r'不是|没有|并非', '', fact, count=1)
                negatives.append({"text": negated.strip(), "source": key})
    
    return positives, negatives


# ============================================================
# 对抗样本生成
# ============================================================

def perturb_year(text: str) -> list:
    """年份扰动: 偏移 ±1~±100"""
    samples = []
    years = re.findall(r'\d{3,4}', text)
    for y in years:
        yi = int(y)
        for offset in [1, -1, 10, -10, 100, -100]:
            new_y = yi + offset
            if new_y < 0:
                continue
            perturbed = text.replace(y, str(new_y))
            if perturbed != text:
                samples.append(perturbed)
    return samples


def perturb_number(text: str) -> list:
    """数值扰动: 增加/减少 10%~50%"""
    samples = []
    nums = re.findall(r'\d+\.?\d*', text)
    for n in nums:
        try:
            ni = float(n)
            for factor in [1.1, 0.9, 1.5, 0.5, 2.0]:
                new_n = int(ni * factor) if ni == int(ni) else round(ni * factor, 1)
                perturbed = text.replace(n, str(new_n))
                if perturbed != text:
                    samples.append(perturbed)
        except ValueError:
            pass
    return samples


def perturb_negation(text: str) -> list:
    """否定扰动: 添加/移除否定词"""
    samples = []
    neg_words = ['不是', '没有', '并非', '不可以']
    pos_words = ['是', '有', '可以']
    
    # 移除否定词（变 TRUE 为 FALSE）
    for nw in neg_words:
        if nw in text:
            samples.append(text.replace(nw, ''))
    
    # 添加否定词（变 FALSE 为 TRUE...的反面）
    for pw, nw in zip(pos_words, neg_words):
        if pw in text and nw not in text:
            samples.append(text.replace(pw, nw, 1))
    
    return samples


def perturb_temporal(text: str) -> list:
    """时间顺序扰动: 交换朝代/人物"""
    # 从 KB 自动发现的所有人物/朝代配对
    era_pairs = [
        ("秦", "明"), ("汉", "唐"), ("宋", "清"),
        ("牛顿", "爱因斯坦"), ("达尔文", "牛顿"),
        # 新增配对（覆盖 Sprint 1 实体）
        ("李白", "杜甫"), ("巴赫", "贝多芬"), ("肖邦", "莫扎特"),
        ("康德", "黑格尔"), ("尼采", "马克思"), ("柏拉图", "亚里士多德"),
        ("伽利略", "哥白尼"), ("法拉第", "麦克斯韦"), ("居里夫人", "爱因斯坦"),
        ("莎士比亚", "但丁"), ("雨果", "托尔斯泰"), ("海明威", "鲁迅"),
        ("秦始皇", "诸葛亮"), ("成吉思汗", "拿破仑"),
        ("瓦特", "爱迪生"), ("贝尔", "马可尼"), ("达尔文", "巴斯德"),
        ("普朗克", "薛定谔"), ("费曼", "霍金"), ("门捷列夫", "居里夫人"),
    ]
    samples = []
    for a, b in era_pairs:
        if a in text and b not in text:
            samples.append(text.replace(a, b, 1))
    return samples


def perturb_entity(text: str) -> list:
    """实体关系扰动: 交换主语"""
    person_pairs = [
        ("牛顿", "爱因斯坦"), ("瓦特", "爱迪生"),
        ("朱元璋", "秦始皇"), ("毕昇", "蔡伦"),
        # Sprint 1 新增
        ("但丁", "莎士比亚"), ("歌德", "雨果"), ("托尔斯泰", "陀思妥耶夫斯基"),
        ("李白", "杜甫"), ("海明威", "鲁迅"), ("巴赫", "莫扎特"),
        ("肖邦", "柴可夫斯基"), ("康德", "尼采"), ("黑格尔", "马克思"),
        ("柏拉图", "亚里士多德"), ("苏格拉底", "孔子"),
        ("伽利略", "哥白尼"), ("法拉第", "麦克斯韦"), ("达尔文", "巴斯德"),
        ("门捷列夫", "居里夫人"), ("普朗克", "爱因斯坦"), ("费曼", "霍金"),
        ("特斯拉", "爱迪生"), ("秦始皇", "成吉思汗"), ("诸葛亮", "郑和"),
        ("释迦牟尼", "孔子"), ("甘地", "曼德拉"),
    ]
    samples = []
    for a, b in person_pairs:
        if a in text and b not in text:
            samples.append(text.replace(a, b, 1))
    return samples


# ============================================================
# Checker 分类规则
# ============================================================

CHECKER_RULES = {
    "year_conflict": {
        "keywords": ["年", "公元", "前"],
        "perturbers": [perturb_year],
        "difficulty": "easy",
    },
    "numeric_conflict": {
        "keywords": ["米", "公里", "个", "万", "%", "倍"],
        "perturbers": [perturb_number],
        "difficulty": "easy",
    },
    "negation": {
        "keywords": ["不是", "没有", "发明", "创造", "发现", "第一"],
        "perturbers": [perturb_negation],
        "difficulty": "easy",
    },
    "temporal_order": {
        "keywords": ["秦", "汉", "唐", "宋", "明", "清", "之后", "之前", "比"],
        "perturbers": [perturb_temporal],
        "difficulty": "medium",
    },
    "location_conflict": {
        "keywords": ["北京", "日本", "中国", "美国", "埃及", "法国", "英国", "印度", "澳大利亚"],
        "perturbers": [],
        "difficulty": "easy",
    },
    "graph_relation": {
        "keywords": ["发明", "发现", "提出", "建立", "统一", "创建"],
        "perturbers": [perturb_entity],
        "difficulty": "medium",
    },
    "knowledge_base": {
        "keywords": [],  # 匹配所有 KB 事实
        "perturbers": [],
        "difficulty": "easy",
    },
    "mixed": {
        "keywords": [],
        "perturbers": [perturb_year, perturb_number, perturb_negation],
        "difficulty": "hard",
    },
}


# ============================================================
# 主生成逻辑
# ============================================================

def classify_sample(text: str) -> list:
    """将文本分类到对应的 checker"""
    matched = []
    for checker, rules in CHECKER_RULES.items():
        if checker == "knowledge_base" or checker == "mixed":
            continue
        if any(kw in text for kw in rules["keywords"]):
            matched.append(checker)
    if not matched:
        matched.append("knowledge_base")
    return matched


def generate():
    positives, negatives = collect_facts()
    all_samples = {}
    sample_id = 0
    
    for checker in CHECKER_RULES:
        all_samples[checker] = []
    
    # 从 KB 生成 TRUE/FALSE 对
    for fact in positives[:300]:
        text = fact["text"]
        if len(text) < 8 or len(text) > 120:
            continue
        
        checkers = classify_sample(text)
        
        # TRUE 样本
        for c in checkers:
            sample_id += 1
            all_samples.setdefault(c, []).append({
                "id": f"gold_{sample_id:05d}",
                "text": text,
                "label": "TRUE",
                "category": fact["source"],
                "checker": checkers,
                "difficulty": CHECKER_RULES.get(c, {}).get("difficulty", "easy"),
            })
        
        # 生成 FALSE 扰动样本
        rules = CHECKER_RULES.get(checkers[0] if checkers else "knowledge_base", {})
        for perturber in rules.get("perturbers", []):
            for perturbed in perturber(text)[:2]:  # 每个最多2条
                if perturbed == text or len(perturbed) < 8:
                    continue
                sample_id += 1
                all_samples.setdefault(checkers[0], []).append({
                    "id": f"gold_{sample_id:05d}",
                    "text": perturbed,
                    "label": "FALSE",
                    "category": f"{fact['source']}_perturbed",
                    "checker": checkers,
                    "difficulty": CHECKER_RULES.get(checkers[0], {}).get("difficulty", "easy"),
                })
    
    # 额外: 从 KB 否定事实中提取 FALSE 样本
    for fact in negatives[:100]:
        text = fact["text"]
        if len(text) < 8 or len(text) > 120:
            continue
        checkers = classify_sample(text)
        for c in checkers:
            sample_id += 1
            all_samples.setdefault(c, []).append({
                "id": f"gold_{sample_id:05d}",
                "text": text,
                "label": "FALSE",
                "category": fact["source"],
                "checker": checkers,
                "difficulty": "medium",
            })
    
    return all_samples


def save_benchmarks(all_samples):
    """保存到分类文件"""
    total = 0
    for checker, samples in all_samples.items():
        if not samples:
            continue
        path = BENCH_DIR / f"{checker}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        n = len(samples)
        t = sum(1 for s in samples if s["label"] == "TRUE")
        f_count = sum(1 for s in samples if s["label"] == "FALSE")
        print(f"  {checker:20s}: {n:4d} 条 (TRUE={t}, FALSE={f_count})")
        total += n
    
    # 汇总文件
    all_path = BENCH_DIR / "all.jsonl"
    with open(all_path, "w", encoding="utf-8") as f:
        for samples in all_samples.values():
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
    
    print(f"  {'─' * 40}")
    print(f"  总计: {total} 条 → {all_path}")
    
    # 生成 README
    readme = BENCH_DIR / "README.md"
    with open(readme, "w") as f:
        f.write("# 黄金基准集 (Golden Benchmark)\n\n")
        f.write(f"总计 **{total}** 条，按 8 个 Checker 分类。\n\n")
        f.write("| Checker | 样本数 | TRUE | FALSE | 难度 |\n")
        f.write("|---------|--------|------|-------|------|\n")
        for checker, samples in sorted(all_samples.items(), key=lambda x: -len(x[1])):
            if not samples: continue
            t = sum(1 for s in samples if s["label"] == "TRUE")
            f_c = len(samples) - t
            diff = samples[0]["difficulty"] if samples else "?"
            f.write(f"| {checker} | {len(samples)} | {t} | {f_c} | {diff} |\n")
        f.write("\n## 格式\n```json\n")
        f.write(json.dumps(all_samples.get("year_conflict", [{}])[0], ensure_ascii=False, indent=2))
        f.write("\n```\n")
    
    print(f"  README → {readme}")


if __name__ == "__main__":
    print("🔨 生成黄金基准集...\n")
    samples = generate()
    save_benchmarks(samples)
