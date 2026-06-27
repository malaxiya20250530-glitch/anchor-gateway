# 觉察推理网关 — 模块依赖图

```
                           ┌──────────────────────┐
                           │   demo_auto_captions  │
                           │   demo_with_narration │
                           │   demo_full_pipeline  │
                           └──────────┬───────────┘
                                      │ 调用
                                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    awareness_gateway.py                      │
│                    (HTTP 网关 · 主入口)                        │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ /health     │  │ /v1/chat/    │  │ /analyze /logs    │  │
│  │ /metrics    │  │ completions  │  │ /kb /dashboard    │  │
│  └──────┬──────┘  └──────┬───────┘  └────────┬──────────┘  │
│         │                │                    │             │
│         │    ┌───────────┴───────────┐        │             │
│         │    │  call_upstream()      │        │             │
│         │    │  detect_upstream_type │        │             │
│         │    │  ┌─────────────────┐  │        │             │
│         │    │  │ Ollama SSE 解析  │  │        │             │
│         │    │  │ OpenAI SSE 解析  │  │        │             │
│         │    │  │ 重试 + 降级      │  │        │             │
│         │    │  └─────────────────┘  │        │             │
│         │    └───────────────────────┘        │             │
└─────────┼─────────────────────────────────────┼─────────────┘
          │                                     │
          │ 导入                                 │ 导入
          ▼                                     ▼
┌─────────────────────┐              ┌─────────────────────┐
│ hallucination_      │              │ alignment_          │
│ detector.py         │              │ middleware.py       │
│                     │              │                     │
│ FactExtractor       │              │ AlignmentAnalyzer   │
│ AnchorEngine        │              │ ReportFormatter     │
│ KNOWLEDGE_BASE (62) │              │                     │
│ SYNONYM_MAP         │              │ 社会对齐分析         │
│ _PRIORITY_CHECKERS  │              │ 取悦/情绪传染/漂移   │
│                     │              │                     │
│ _check_infinity     │              └─────────────────────┘
│ _check_negation     │
│ _check_year_conflict│
│ _check_numeric      │
│ _check_overlap      │
│ _semantic_match_kb  │
└─────────┬───────────┘
          │ 被导入
          ▼
┌─────────────────────┐     ┌──────────────────────┐
│ observer_proxy.py   │     │ observer_security.py │
│ (独立代理 · 流式)    │     │ (白盒观察器)          │
│ Observer            │     │ 多观察器冗余          │
│ 模式检测 + 锚定      │     │ 外部锚定             │
└─────────────────────┘     └──────────────────────┘

┌─────────────────────┐     ┌──────────────────────┐
│ compiled_awareness  │     │ stress_test.py       │
│ (双通道演示)          │     │ (网关压力测试)        │
│ dual_pane_demo      │     │ 并发/延迟/吞吐量      │
│ 编译=肌肉记忆        │     │ P50/P95/P99         │
│ 觉察=走神空间        │     └──────────────────────┘
└─────────────────────┘

┌─────────────────────┐     ┌──────────────────────┐
│ true_self_os.py     │     │ social_self_sim.py   │
│ (神经模拟 v3.0)      │     │ (多人社会交互)        │
│ DMN/TPN/脑岛/EEG    │     │ 镜像/社会疼痛/心智化   │
└─────────────────────┘     └──────────────────────┘

         ┌──────────────────────┐
         │  test_fact_checker   │
         │  (单元测试 · 221行)    │
         │  5组场景 · 全部通过    │
         └──────────────────────┘
```

## 数据流

```
用户请求
  │
  ▼
awareness_gateway.py (HTTP)
  │
  ├─→ hallucination_detector.py (事实核查)
  │     ├─ KNOWLEDGE_BASE (62条本地知识)
  │     ├─ SYNONYM_MAP (18组同义词)
  │     └─ _PRIORITY_CHECKERS (5个检查器链)
  │
  ├─→ alignment_middleware.py (社会对齐)
  │
  └─→ call_upstream() → Ollama / OpenAI API
        └─ SSE 流式解析 → SemanticSplitter → Observer
```

## 依赖方向

**零外部依赖** — 全部 `import` 均来自 Python 标准库:

| 模块 | 标准库依赖 |
|---|---|
| awareness_gateway | json, re, time, http.server, urllib, collections, threading, argparse |
| hallucination_detector | json, re, time, dataclasses, collections, urllib |
| observer_proxy | json, re, time, urllib, threading, queue |
| compiled_awareness | time, threading, dataclasses, collections |
| stress_test | json, time, threading, urllib, collections, argparse |

**内部依赖** (项目内导入):
```
awareness_gateway → hallucination_detector (可选)
                  → alignment_middleware   (可选)
observer_proxy    → hallucination_detector (可选)
observer_security → true_self_os (可选)
                  → social_self_sim (可选)
test_fact_checker → hallucination_detector
```

所有内部导入均为 `try/except ImportError` 可选模式。
