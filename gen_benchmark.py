#!/usr/bin/env python3
"""
Benchmark 生成器 — 从 KNOWLEDGE_BASE 自动生成正负样本
输出: hallucination_benchmark.jsonl
"""
import json, random, re, sys
sys.path.insert(0, '.')
from hallucination_detector import KNOWLEDGE_BASE

random.seed(42)

POSITIVE_TEMPLATES = [
    "{fact}",
    "据记载，{fact}",
    "众所周知，{fact}",
    "历史事实是：{fact}",
    "{fact}，这是确定的",
]

NEGATIVE_TRANSFORMS = [
    # (描述, 变换函数)
    ("年份篡改", lambda f: re.sub(r'(\d{4})年', lambda m: str(int(m.group(1)) + random.choice([-50, 50, 100, -200])) + '年', f)),
    ("朝代置换", lambda f: f.replace("明", "清").replace("宋", "唐").replace("唐", "汉").replace("汉", "宋")),
    ("人物错配", lambda f: re.sub(r'朱元璋|毕昇|蔡伦|李白|苏轼|爱因斯坦',
                                   lambda m: random.choice(['朱元璋','毕昇','蔡伦','李白','苏轼','爱因斯坦']), f)),
    ("地点谬误", lambda f: f.replace("中国", "日本").replace("北京", "巴黎").replace("南京", "伦敦")),
    ("数值夸大", lambda f: re.sub(r'(\d+)', lambda m: str(int(m.group(1)) * random.choice([2, 3, 5, 10])), f)),
]

samples = []

# 正样本: 每个 KB 事实生成 3-5 个变体
for key, entry in KNOWLEDGE_BASE.items():
    for fact in entry.get("facts", []):
        if len(fact) < 6:
            continue
        for _ in range(random.randint(3, 5)):
            tmpl = random.choice(POSITIVE_TEMPLATES)
            text = tmpl.format(fact=fact)
            samples.append({"text": text[:200], "label": "positive", "source_key": key})

# 负样本: 每个事实生成 2-3 个篡改版本
for key, entry in KNOWLEDGE_BASE.items():
    for fact in entry.get("facts", []):
        if len(fact) < 10:
            continue
        for desc, transform in NEGATIVE_TRANSFORMS:
            if random.random() > 0.6:
                continue
            try:
                mutated = transform(fact)
                if mutated == fact or len(mutated) < 6:
                    continue
                samples.append({"text": mutated[:200], "label": "negative", "source_key": key, "mutated_by": desc})
            except (ValueError, TypeError, IndexError):
                pass

random.shuffle(samples)

# 限制总量
pos = [s for s in samples if s["label"] == "positive"][:1100]
neg = [s for s in samples if s["label"] == "negative"][:1100]
samples = pos + neg
random.shuffle(samples)

# 写入
with open("hallucination_benchmark.jsonl", "w", encoding="utf-8") as f:
    for s in samples:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

print(f"✅ Benchmark 生成完成")
print(f"   正样本: {len(pos)}")
print(f"   负样本: {len(neg)}")
print(f"   总计:   {len(samples)}")
