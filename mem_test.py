import tracemalloc, time
from hallucination_detector import HallucinationDetector

print('内存压力测试 (200次)', flush=True)
tracemalloc.start()
d = HallucinationDetector()
texts = ['朱元璋发明了火锅', 'Python是1989年发布的', '地球是平的',
         '光速是无限快的', '爱因斯坦发明了原子弹', '大脑只开发了10%']

samples = []
t0 = time.time()
for i in range(200):
    d.analyze(texts[i % len(texts)])
    if i % 20 == 0:
        current, peak = tracemalloc.get_traced_memory()
        samples.append({'i': i, 'current_kb': round(current/1024,1), 'peak_kb': round(peak/1024,1)})
        print(f'  [{i:3d}] current={current/1024:.0f}KB  peak={peak/1024:.0f}KB', flush=True)

elapsed = time.time() - t0
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

early = [s['current_kb'] for s in samples[:3]]
late = [s['current_kb'] for s in samples[-3:]]
early_avg = sum(early)/len(early)
late_avg = sum(late)/len(late)
growth = (late_avg - early_avg) / max(early_avg, 1)
no_leak = growth < 0.3

print(f'耗时: {elapsed:.1f}s', flush=True)
print(f'早期平均: {early_avg:.0f}KB  后期平均: {late_avg:.0f}KB  增长率: {growth*100:.1f}%', flush=True)
print(f'结果: {"✅ 无明显泄漏" if no_leak else "❌ 检测到泄漏"} (阈值 30%)', flush=True)
print(f'最终: current={current/1024:.0f}KB  peak={peak/1024:.0f}KB', flush=True)
