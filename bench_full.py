import json, time, sys
sys.path.insert(0, '.')
from hallucination_detector import HallucinationDetector

with open('benchmark/all.jsonl') as f:
    samples = [json.loads(l) for l in f.readlines()]

print(f'全量基准: {len(samples)} 条', flush=True)
d = HallucinationDetector()
tp = fp = fn = tn = 0
t0 = time.time()
for i, s in enumerate(samples):
    r = d.analyze(s['text'])
    pred = any(x.verdict == 'contradicted' for x in r.results)
    actual = s['label'] == 'FALSE'
    if pred and actual: tp += 1
    elif pred and not actual: fp += 1
    elif not pred and actual: fn += 1
    else: tn += 1
    if (i + 1) % 500 == 0:
        el = time.time() - t0
        p = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = 2 * p * rec / max(p + rec, 0.001)
        print(f'[{i+1}/{len(samples)}] P={p:.3f} R={rec:.3f} F1={f1:.3f} | {el:.0f}s', flush=True)
elapsed = time.time() - t0
p = tp / max(tp + fp, 1)
rec = tp / max(tp + fn, 1)
f1 = 2 * p * rec / max(p + rec, 0.001)
acc = (tp + tn) / max(tp + fp + fn + tn, 1)
print(f'\n=== 最终 ===', flush=True)
print(f'Precision={p:.3f} Recall={rec:.3f} F1={f1:.3f} Acc={acc:.3f}', flush=True)
print(f'TP={tp} FP={fp} FN={fn} TN={tn}', flush=True)
print(f'耗时={elapsed:.0f}s 速度={elapsed/len(samples)*1000:.0f}ms/条', flush=True)
