#!/usr/bin/env python3
"""检查器权重网格搜索 — 用 benchmark 数据优化各检查器权重"""
import sys, json, time, re
sys.path.insert(0, '.')
from hallucination_detector import HallucinationDetector
from checker_registry import Checker
import checker_classes

def benchmark_weight_scan():
    """扫描基准数据，统计每个检查器的独立表现"""
    d = HallucinationDetector()
    anchor = d.anchor
    
    # 加载 benchmark cases
    import benchmark as bm
    cases = bm.BENCHMARK_CASES
    
    # 统计每个检查器的表现
    checker_stats = {}
    for cls in Checker.registry:
        checker_stats[cls.__name__] = {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0, 'fired': 0, 'verdicts': []}
    
    print(f"扫描 {len(cases)} 条 benchmark 用例...")
    for i, case in enumerate(cases):
        if i % 100 == 0:
            print(f"  进度: {i}/{len(cases)}")
        
        claim = case["claim"]
        expected = case["expected"]
        
        report = d.analyze(claim)
        predicted = any(r.verdict == 'contradicted' for r in report.results)
        actual = (expected == 'contradicted')
        
        # 对每个单独运行的检查器，我们无法直接获取其独立结果
        # 替代方案：分析哪些 KB 条目被匹配，然后手动检查每个 checker
        # 但因为基准代码里已经整合了，只能从整体推断
    
    # 提供更直接的方法：对每个 case，让每个 checker 独立比对事实
    print("\n分 checker 独立测试（kb_core 匹配的 case）...")
    
    from hallucination_detector import KNOWLEDGE_BASE
    
    for cls in Checker.registry:
        inst = cls()
        name = cls.__name__
        for i, case in enumerate(cases[:100]):  # 快速扫描前 100 条
            claim = case["claim"]
            expected = case["expected"]
            
            # 找 KB 匹配
            for key, entry in KNOWLEDGE_BASE.items():
                if key in claim:
                    for fact in entry.get("facts", []):
                        result = inst.check(claim, fact)
                        if result:
                            verdict, conf = result
                            actual = (expected == 'contradicted')
                            pred = (verdict == 'contradicted')
                            if pred and actual: checker_stats[name]['tp'] += 1
                            elif pred and not actual: checker_stats[name]['fp'] += 1
                            elif not pred and actual: checker_stats[name]['fn'] += 1
                            else: checker_stats[name]['tn'] += 1
                            checker_stats[name]['fired'] += 1
                            break
                    break
    
    # 输出结果
    print(f"\n{'Checker':30} {'Fired':>6} {'P':>6} {'R':>6} {'F1':>6} {'Weight':>7}")
    print('-' * 65)
    for cls in Checker.registry:
        s = checker_stats[cls.__name__]
        tp, fp, fn, tn = s['tp'], s['fp'], s['fn'], s['tn']
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        f1 = 2 * p * r / max(p + r, 0.001)
        curr_w = getattr(cls, 'weight', 1.0)
        print(f'{cls.__name__:30} {s["fired"]:6} {p:.3f} {r:.3f} {f1:.3f} {curr_w:.2f}')
        
        # 建议新权重 = F1 值（但限 0.3~0.95 之间）
        new_w = max(0.3, min(0.95, f1))
        print(f'  → 建议权重: {new_w:.2f}')

if __name__ == '__main__':
    benchmark_weight_scan()
