# llm-fact-guard — 零依赖 LLM 幻觉检测中间件

[![PyPI](https://img.shields.io/pypi/v/llm-fact-guard)](https://pypi.org/project/llm-fact-guard/)
[![Python](https://img.shields.io/pypi/pyversions/llm-fact-guard)](https://pypi.org/project/llm-fact-guard/)

---

## 🚀 一行安装

```bash
pip install llm-fact-guard
```

## ⚡ 一行使用

```python
from hallucination_detector import HallucinationDetector

guard = HallucinationDetector()

# DeepSeek / OpenAI / Ollama 任意 LLM 输出
response = "朱元璋发明了火锅的过程非常传奇..."

report = guard.analyze(response)
for r in report.results:
    print(f"{r.verdict}: {r.claim}")
    # contradicted: 朱元璋发明了火锅的过程非常传奇
    # evidence: 朱元璋是明朝开国皇帝，火锅起源可追溯至商周时期
```

## 🔥 为什么需要它

| 场景 | 没有 Guard | 有 Guard |
|------|-----------|---------|
| AI 客服 | 用户被错误信息误导 | 自动拦截并纠正 |
| 教育问答 | 学生学到假知识 | 实时标注可疑内容 |
| 企业 RAG | 幻觉污染知识库 | 入库前自动校验 |
| AI Agent | 错误决策级联放大 | 每步输出都有事实依据 |

## 🛡️ 安全能力

- **14 个检查器链** — KB 匹配 / 年份冲突 / 数字校验 / 否定检测 / 归因分析...
- **WAF 层** — SQL注入 / XSS / 路径穿越 44 项全拦截
- **熔断器** — 上游超时自动降级
- **速率限制** — 防 DDoS / 防滥用
- **SecurityLogger** — JSON 结构化日志，Loki / ES / OpenSearch 可直接接入

## 📊 性能

```
QPS 100 | 3000 请求 0 错误
P50 1.1s | P95 1.8s | P99 3.9s
```

## 🔗 链接

- PyPI: https://pypi.org/project/llm-fact-guard/
- GitHub: https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth
- 联系: hubeiligang420@gmail.com

---

## 🇬🇧 English

**llm-fact-guard** is a zero-dependency hallucination detection middleware for LLMs. Drop it into any OpenAI/DeepSeek/Ollama pipeline and get real-time fact-checking.

### Why

LLMs lie. A lot. Especially in Chinese. This catches them.

### Features

- **14-checker chain** — KB matching, year conflict, numeric validation, negation, attribution...
- **WAF built-in** — 44 OWASP attack vectors blocked
- **Circuit breaker** — auto-degrades on upstream timeout
- **Rate limiter** — DDoS/abuse protection
- **Structured logging** — ready for Loki, Elasticsearch, OpenSearch

### Install

```bash
pip install llm-fact-guard
```

### Use

```python
from hallucination_detector import HallucinationDetector

guard = HallucinationDetector()
report = guard.analyze("Did Einstein invent the atomic bomb?")
# → contradicted: Einstein did not directly invent the atomic bomb
# → evidence: Einstein published E=mc² in 1905; Manhattan Project led by Oppenheimer
```

---

⭐ **Star on GitHub** | 📦 **pip install llm-fact-guard**
