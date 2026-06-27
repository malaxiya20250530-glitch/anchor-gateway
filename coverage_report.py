#!/usr/bin/env python3
"""
coverage_report.py — 检查器覆盖率统计
针对 14 个注册检查器，使用测试语料统计每个检查器的命中率/未命中率/平均置信度。

使用方法:
  python3 coverage_report.py                # 默认语料库运行
  python3 coverage_report.py --quick        # 快速模式(50条)
  python3 coverage_report.py --full         # 全量模式(测试所有事实对)
  python3 coverage_report.py --list         # 仅列出检查器
"""

import json
import os
import sys
import time
import random
import hallucination_detector  # 触发@checker装饰器注册
from checker_registry import Checker

KB_CORE_PATH = "kb_core.json"
QUICK_MODE = "--quick" in sys.argv
FULL_MODE = "--full" in sys.argv
LIST_ONLY = "--list" in sys.argv

# ── 测试语料库 ──
# 每个用例: (claim断言, fact事实, 预期结果类型)
CORPUS = [
    # === 年份矛盾 ===
    ("朱元璋出生于1368年", "朱元璋是明朝开国皇帝，生于1328年", "contradicted"),
    ("秦朝建立于公元前221年", "秦朝由秦始皇于公元前221年建立", "verified"),
    ("唐朝在907年灭亡", "唐朝于907年灭亡", "verified"),

    # === 数值矛盾 ===
    ("地球到月球的距离是38万公里", "月球距地球约38.4万公里", "verified"),
    ("太阳直径是100万公里", "太阳直径约139.2万公里", "contradicted"),
    ("月球直径是1000公里", "月球直径约3474公里", "contradicted"),

    # === 否定混淆 ===
    ("毕昇没有发明活字印刷术", "毕昇发明了活字印刷术", "verified"),
    ("毕昇不是没有发明活字印刷术", "毕昇发明了活字印刷术", "verified"),
    ("并非没有证据表明地球是圆的", "地球是球形的", "unverifiable"),

    # === 归属错误 ===
    ("爱因斯坦发明了相对论", "爱因斯坦提出了相对论", "verified"),
    ("牛顿发现了相对论", "爱因斯坦提出了相对论", "contradicted"),
    ("李白是宋朝诗人", "李白是唐朝诗人", "contradicted"),

    # === 地点矛盾 ===
    ("长城位于美国", "长城位于中国", "contradicted"),
    ("故宫在北京", "故宫位于北京", "verified"),

    # === 实体替换 ===
    ("秦始皇发明了造纸术", "蔡伦改进了造纸术", "contradicted"),
    ("明朝开国皇帝是李世民", "朱元璋是明朝开国皇帝", "contradicted"),

    # === 最高级断言 ===
    ("珠穆朗玛峰是地球上最高的山峰", "珠穆朗玛峰海拔8848米，是世界最高峰", "verified"),
    ("黄河是中国唯一的河流", "中国有长江、黄河等多条河流", "contradicted"),

    # === 因果矛盾 ===
    ("因为明朝灭亡，所以唐朝衰落", "唐朝(618-907年)早于明朝(1368-1644年)", "contradicted"),
    ("造纸术的发明推动了文化传播", "造纸术是中国古代四大发明之一", "verified"),

    # === 时间顺序 ===
    ("宋朝在唐朝之前建立", "唐朝(618-907年)早于宋朝(960-1279年)", "contradicted"),
    ("汉朝在秦朝之后", "秦朝(前221-前207年)早于汉朝(前202-220年)", "verified"),

    # === 比较矛盾 ===
    ("太阳比地球小", "太阳直径约139.2万公里，地球直径约12742公里", "contradicted"),
    ("长江比黄河长", "长江约6300公里，黄河约5464公里", "verified"),

    # === 时长矛盾 ===
    ("秦朝持续了500年", "秦朝从前221年到前207年，约15年", "contradicted"),
    ("唐朝延续了近300年", "唐朝从618年到907年，约289年", "verified"),

    # === 无限/绝对断言 ===
    ("所有皇帝都发明了火锅", "朱元璋是明朝开国皇帝", "contradicted"),
    ("一切事物都是相对的", "这是一句哲学陈述", "unverifiable"),

    # === 边界用例 ===
    ("这是一个无法验证的断言xyz123", "没有相关事实", "unverifiable"),

    # =====================================================================
    # ▼ 以下为覆盖率扩充语料：针对 4 个 0% 命中率检查器
    # =====================================================================

    # === InfinityChecker 用例（检测 "无穷/无限" vs 事实有限）===
    ("宇宙是无穷大的", "可观测宇宙直径约930亿光年，是有限的", "contradicted"),
    ("光速是无限快的", "光速约为每秒30万公里，是有限值", "contradicted"),
    ("人的寿命是无限的", "人类寿命有限，最长记录约122岁", "contradicted"),
    ("圆周率的小数位是有限的", "圆周率是无限不循环小数", "contradicted"),
    ("自然数是有限的", "自然数是无穷的", "contradicted"),

    # === CausalChecker 用例（检测因果声称 vs 事实反驳）===
    ("手机辐射导致脑癌", "手机辐射与脑癌无直接关系", "contradicted"),
    ("因为月球引力所以地球没有地震", "月球引力不会导致地球没有地震", "contradicted"),
    ("喝咖啡引起心脏病", "研究显示适量咖啡与心脏病并无直接因果关系", "contradicted"),
    ("疫苗造成了自闭症", "科学研究证实疫苗不会导致自闭症", "contradicted"),
    ("电子产品使用导致近视是唯一原因", "近视源于遗传与环境等多因素，并非仅由电子产品引起", "contradicted"),

    # === ComparativeChecker 用例（检测比较级数量声称 vs 实际数值）===
    ("珠穆朗玛峰不到8800米", "珠穆朗玛峰海拔8848.86米", "contradicted"),
    ("长江长度超过7000公里", "长江全长约6300公里", "contradicted"),
    ("光速不到每秒20万公里", "光速约每秒30万公里", "contradicted"),
    ("地球直径低于1万公里", "地球直径约12742公里", "contradicted"),
    ("太阳表面温度低于5000度", "太阳表面温度约5500°C", "contradicted"),
    ("黄河长度超过6000公里", "黄河全长约5464公里", "contradicted"),
    ("人类基因组不到2万个基因", "人类基因组约有20000-25000个基因", "contradicted"),
    ("马里亚纳海沟深度不到10000米", "马里亚纳海沟最深处约11034米", "contradicted"),

    # === GraphContradictionChecker 用例（需要 engine 上下文，此处为结构性占位）===
    # 注：此检查器需要 AnchorEngine 实例的 _get_graph_reasoner()，
    # 在纯 claim/fact 对测试中无法触发。需要集成测试覆盖。
    ("", "空断言", "unverifiable"),
]


def load_kb_corpus(kb_path, limit=200):
    """从 kb_core.json 生成额外的测试语料"""
    extra = []
    if not os.path.exists(kb_path):
        return extra
    with open(kb_path, "r", encoding="utf-8") as f:
        kb = json.load(f)

    for entity, data in kb.items():
        facts = data.get("facts", [])
        if len(facts) >= 2:
            # 正确匹配
            extra.append((facts[0], facts[0], "verified"))
            # 错误匹配(用另一个实体的第一个事实)
            # 找到一个不同的实体
            for other_entity, other_data in kb.items():
                if other_entity != entity and other_data.get("facts"):
                    extra.append((other_data["facts"][0], facts[0], "contradicted"))
                    break
        if len(extra) >= limit:
            break

    return extra


def run_coverage(corpus, checkers):
    """运行覆盖率统计"""
    results = {}
    for name, cls in checkers:
        results[name] = {
            "hits": 0,         # 返回了结果(非None)
            "misses": 0,       # 返回None(不适用)
            "errors": 0,       # 抛出异常
            "confidences": [], # 命中时的置信度列表
            "verdicts": {},    # 各种verdict的次数
        }

    start = time.time()
    for i, (claim, fact, expected) in enumerate(corpus):
        for checker_name, checker_cls in checkers:
            try:
                instance = checker_cls()
                result = instance.check(claim, fact)
                if result is not None:
                    verdict, confidence = result
                    results[checker_name]["hits"] += 1
                    results[checker_name]["confidences"].append(confidence)
                    results[checker_name]["verdicts"][verdict] = \
                        results[checker_name]["verdicts"].get(verdict, 0) + 1
                else:
                    results[checker_name]["misses"] += 1
            except Exception as e:
                results[checker_name]["errors"] += 1

    elapsed = time.time() - start
    return results, elapsed


def print_report(results, total_cases, elapsed):
    """打印覆盖率报告"""
    print(f"\n{'='*70}")
    print(f"  检查器覆盖率报告")
    print(f"{'='*70}")
    print(f"  测试用例总数: {total_cases}")
    print(f"  注册检查器数: {len(results)}")
    print(f"  执行耗时: {elapsed:.2f}秒")
    print(f"{'='*70}\n")

    # 按命中率排序
    sorted_results = sorted(
        results.items(),
        key=lambda x: x[1]["hits"] / total_cases if total_cases else 0,
        reverse=True
    )

    print(f"  {'检查器':<28s} {'命中':>5s} {'未命中':>5s} {'命中率':>7s} {'平均置信度':>10s} {'异常':>4s}")
    print(f"  {'-'*64}")

    total_hits = 0
    total_misses = 0
    total_errors = 0

    for name, stats in sorted_results:
        hits = stats["hits"]
        misses = stats["misses"]
        errors = stats["errors"]
        hit_rate = hits / total_cases * 100 if total_cases else 0
        avg_conf = sum(stats["confidences"]) / len(stats["confidences"]) if stats["confidences"] else 0

        total_hits += hits
        total_misses += misses
        total_errors += errors

        # 命中率可视化条
        bar_len = int(hit_rate / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        flag = "⚠️ " if hit_rate < 10 else "  "

        print(f"{flag}{name:<26s} {hits:>5d} {misses:>5d} {bar} {hit_rate:>5.1f}% {avg_conf:>8.3f} {errors:>4d}")

    print(f"  {'-'*64}")
    print(f"  {'合计':<28s} {total_hits:>5d} {total_misses:>5d} {'':>20s} {'':>10s} {total_errors:>4d}")

    # 每个检查器的详细裁决分布
    print(f"\n{'='*70}")
    print(f"  裁决分布（各检查器命中时的 verdict 计数）")
    print(f"{'='*70}")

    for name, stats in sorted_results:
        if stats["verdicts"]:
            verdict_str = ", ".join(f"{k}:{v}" for k, v in sorted(stats["verdicts"].items()))
            hit_rate = stats["hits"] / total_cases * 100 if total_cases else 0
            print(f"  {name:<26s} [{hit_rate:>5.1f}%] {verdict_str}")

    # 覆盖薄弱警告
    print(f"\n{'='*70}")
    print(f"  覆盖薄弱检查器（命中率 < 10%）")
    print(f"{'='*70}")
    weak_count = 0
    for name, stats in sorted_results:
        hit_rate = stats["hits"] / total_cases * 100 if total_cases else 0
        if hit_rate < 10:
            weak_count += 1
            print(f"  ⚠️  {name}: {hit_rate:.1f}% ({stats['hits']}/{total_cases})")
    if weak_count == 0:
        print(f"  ✅ 所有检查器命中率 ≥ 10%")
    else:
        print(f"\n  共 {weak_count} 个检查器覆盖率薄弱，建议补充针对性测试用例。")


def main():
    if LIST_ONLY:
        print("已注册检查器:")
        for i, cls in enumerate(Checker.registry, 1):
            print(f"  {i:>2}. {cls.__name__:<30s} 权重={cls.weight}")
        return

    # ── 构建语料库 ──
    corpus = list(CORPUS)

    if not QUICK_MODE:
        print("📖 从 kb_core.json 扩充测试语料...")
        kb_extra = load_kb_corpus(KB_CORE_PATH, limit=300 if FULL_MODE else 100)
        corpus.extend(kb_extra)
        print(f"   补充 {len(kb_extra)} 条用例")

    if QUICK_MODE:
        corpus = random.sample(corpus, min(50, len(corpus)))

    # ── 获取检查器列表 ──
    checkers = [(cls.__name__, cls) for cls in Checker.registry]

    # ── 运行覆盖率统计 ──
    print(f"\n🔍 开始统计 {len(checkers)} 个检查器的覆盖率...")
    print(f"   测试用例: {len(corpus)} 条")
    print(f"   总检查次数: {len(checkers) * len(corpus)} 次")

    results, elapsed = run_coverage(corpus, checkers)

    # ── 打印报告 ──
    print_report(results, len(corpus), elapsed)


if __name__ == "__main__":
    main()
