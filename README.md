# 🔍 Anchor · LLM Hallucination Detector · 大模型幻觉检测器

[![CI](https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth/actions/workflows/test.yml/badge.svg)](https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth/actions)
[![Python](https://img.shields.io/badge/Python-3.13-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Stars](https://img.shields.io/github/stars/malaxiya20250530-glitch/anchor-llm-in-truth?style=social)](https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth)

> **Zero-dependency LLM hallucination detection. 704万 facts. 14 checkers. Pure Python stdlib.**
> **零外部依赖。704万条事实。14个检查器。纯Python标准库。**

---

## ⚡ 5-Second Demo · 5秒体验

```bash
python3 hallucination_detector.py "朱元璋发明了火锅"
```
```
🔴 [contradicted] 朱元璋发明了火锅  (90%)
   Evidence: 朱元璋是明朝开国皇帝，1328-1398 年
```

```bash
python3 hallucination_detector.py "Edison invented the telephone"
# → 🔴 contradicted  贝尔才是电话发明者
```

---

## 🏗️ Architecture · 架构

```
User → Anchor Gateway (OpenAI-compatible API)
         ├─ Prompt Injection Defense (12防线)
         ├─ HallucinationDetector
         │    ├─ 14 Checkers (责任链, F1加权)
         │    ├─ fact_store.db (704万条事实, SQLite FTS)
         │    ├─ kb_core.json (514实体语义索引)
         │    └─ GraphReasoner (知识图谱推理)
         ├─ Consensus Voter (三模式投票)
         └─ Meta Weight Learner (动态权重学习)
```

**三层事实架构：**
```
🟦 L1: Entity Layer (kb_core.json)   → "你在问什么？"
🟨 L2: Fact Layer (fact_store.db)    → "世界上有哪些事实？"
🟪 L3: Trust Layer (belief function) → "哪些事实值得相信？"
```

---

## 🚀 Quick Start · 快速开始

```bash
# 克隆
git clone git@github.com:malaxiya20250530-glitch/anchor-llm-in-truth.git
cd anchor-llm-in-truth

# 事实核查
python3 hallucination_detector.py "朱元璋发明了火锅"

# 启动网关 (OpenAI兼容API)
python3 awareness_gateway.py --mock --port 8800

# 测试
python3 test_fact_checker.py        # 核心测试 (5组)
python3 test_adversarial.py         # 攻防测试 (14用例)
python3 injection_attack_sim.py     # 注入防御评分
```

**API 调用：**
```bash
curl -X POST http://localhost:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Did 朱元璋 invent hotpot?"}]}'
```

---

## 📊 Capabilities · 能力矩阵

| 能力 | 评分 | 说明 |
|------|------|------|
| 核心幻觉检测 | A (90%) | 14检查器责任链 |
| 否定混淆处理 | A (100%) | 9组双否定归一化 |
| 知识库规模 | A | 704万条事实 / 1.8GB |
| 注入防御 | B (86%) | 12条防线 / 29载荷 |
| 诱导性鲁棒性 | A (100%) | 14/14用例通过 |
| 零外部依赖 | A | 纯Python标准库 |

---

## 🛡️ Security · 安全

- **Prompt Injection Defense**: 12条防线 (sanitize → instruction detect → structural detect → KB validate → tool hijack detect)
- **Adversarial Test**: 14/14 攻防用例通过 (100/100 A级)
- **Injection Score**: 86/100 (29载荷, 25拦截)
- **CI/CD**: GitHub Actions 自动解密→测试→F1退化检查

---

## 📁 Key Files · 关键文件

| 文件 | 行数 | 作用 |
|------|------|------|
| `hallucination_detector.py` | 1604 | 核心引擎 |
| `checker_classes.py` | 988 | 14个检查器 |
| `prompt_injection_defense.py` | 1556 | 12条防线 |
| `knowledge/fact_store.db` | 1.8GB | 704万条事实 |
| `kb_core.json` | 134KB | 514实体索引 |

---

## 🧪 Tests · 测试

```bash
python3 test_fact_checker.py          # 核心检测 (5/5 ✅)
python3 test_adversarial.py           # 攻防博弈 (14/14 ✅)
python3 test_graph_checker.py         # 图谱推理 (11/11 ✅)
python3 coverage_report.py            # 检查器覆盖率
```

---

## 🔧 Adding a Checker · 添加检查器

```python
from checker_registry import Checker, checker

@checker
class MyChecker(Checker):
    weight = 0.80
    def check(self, claim: str, fact: str, engine=None):
        if "关键词" in claim and "反例" in fact:
            return ("contradicted", 0.85)
        return None
```

两步：继承 `Checker` + `@checker` 装饰器。自动注册到责任链。

---

Built with ❤️ on Android Termux. Zero dependencies. Pure Python stdlib.
