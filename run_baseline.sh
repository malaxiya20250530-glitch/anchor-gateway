#!/usr/bin/env bash
# 一键复现 baseline — 基线回放脚本
# 用法: bash run_baseline.sh [--full]
set -e

cd "$(dirname "$0")"

echo "📊 Baseline Replay"
echo "  时间: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# 验证关键文件 hash
python3 -c "
import json, hashlib
with open('benchmark/baseline_meta.json') as f:
    meta = json.load(f)
for fname in ['hallucination_detector.py', 'checker_classes.py', 'checker_registry.py', 'kb_core.json']:
    with open(fname, 'rb') as f:
        current = hashlib.sha256(f.read()).hexdigest()[:12]
    stored = meta.get(f'{fname}_sha256', '?')
    status = '✅' if current == stored else '⚠️ 已变更'
    print(f'  {status} {fname}: {current} (基线: {stored})')
"

echo ""
echo "🏃 运行基准测试..."

MODE="--fast"
if [ "$1" = "--full" ]; then
    MODE=""
    echo "  模式: 完整（含知识图谱）"
else
    echo "  模式: 快速"
fi

python3 benchmark/run.py $MODE 2>&1

echo ""
echo "📄 对比基线:"
python3 -c "
import json
with open('benchmark/baseline_meta.json') as f:
    meta = json.load(f)
print(f'  基线 F1: {meta[\"f1\"]}')
print(f'  基线 FP: {meta[\"fp\"]}')
print(f'  基线 FN: {meta[\"fn\"]}')
print(f'  基线 TP: {meta[\"tp\"]}, TN: {meta[\"tn\"]}')
"
