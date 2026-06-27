#!/usr/bin/env python3
"""批量幻觉检测 — 一次加载，多次核查，避免重复导入开销"""
import sys, json, time

sys.path.insert(0, '.')
from hallucination_detector import FactExtractor, AnchorEngine, Reporter

engine = AnchorEngine()
extractor = FactExtractor()

tests = [
    # (声明, 预期)
    ("朱元璋发明了火锅", "应矛盾"),
    ("毕昇发明了活字印刷术", "应通过"),
    ("爱因斯坦发明了相对论", "应通过"),
    ("爱因斯坦发明了原子弹", "应矛盾"),
    ("李白是宋朝诗人", "应矛盾"),
    ("苏轼是唐代词人", "应矛盾"),
    ("蔡伦改进了造纸术", "应通过"),
    ("长城在巴黎", "应矛盾"),
    ("光速是无限快的", "应矛盾"),
    ("地球是平的", "应矛盾"),
    ("不对，火锅在汉代已有雏形，远比朱元璋的时代早", "应通过"),
    ("郑和下西洋发生在清朝", "应矛盾"),
]

t0 = time.time()
passed = 0
failed = 0

for claim, expected in tests:
    claims = extractor.extract(claim)
    if not claims:
        v = 'none'
    else:
        v = engine.verify(claims[0]).verdict
    
    ok = (expected == "应矛盾" and v == "contradicted") or \
         (expected == "应通过" and v != "contradicted")
    label = {'contradicted':'矛盾','verified':'已验证','unverifiable':'不可核查'}.get(v, v)
    status = '✅' if ok else '❌'
    if ok:
        passed += 1
    else:
        failed += 1
        print(f'{status} {claim:<40} → {label} (预期 {expected})')

elapsed = time.time() - t0
print(f'\n{"="*50}')
print(f'  结果: {passed}✅ / {failed}❌ (共 {len(tests)} 条)')
print(f'  耗时: {elapsed:.2f}s ({elapsed/len(tests)*1000:.0f}ms/条)')

if failed:
    sys.exit(1)
