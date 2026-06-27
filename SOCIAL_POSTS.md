# 📢 推广帖（复制即发）

> 2026-06-03 更新 · 仓库已改名 anchor-llm-in-truth

---

## 🇨🇳 知乎 — "如何检测大模型幻觉？我写了个零依赖方案"

**标题**: 纯Python标准库实现LLM幻觉检测：14个检查器 + 704万条事实，零pip install

---

先说结论：在不引入任何外部依赖的前提下，用**责任链模式 + SQLite FTS + 知识图谱推理**，可以做到实用的幻觉检测准确率。

项目地址：https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth

### 为什么做这个

用过ChatGPT/DeepSeek的都知道，大模型最致命的问题不是"不够聪明"，而是**你不知道它什么时候在胡说**。市面上幻觉检测方案要么调API（贵、慢、隐私问题），要么依赖torch全家桶（Termux跑不起来）。

我的约束很极端：**必须在Android Termux上跑通，纯Python标准库，零pip install**。

### 架构

```
用户输入
  → Entity索引 (kb_core.json, 514实体)
  → Fact检索 (fact_store.db, 704万条, SQLite FTS)
  → 14个检查器责任链 (F1加权投票)
  → 知识图谱推理 (GraphContradictionChecker)
  → 输出: verified/contradicted/unverifiable
```

### 14个检查器（按权重）

| 检查器 | 权重 | 检测目标 |
|--------|------|----------|
| YearConflictChecker | 0.92 | 年份矛盾 |
| NumericConflictChecker | 0.90 | 数值矛盾 |
| ComparativeChecker | 0.86 | 比较关系矛盾 |
| NegationChecker | 0.83 | 否定混淆（双否定归一化） |
| ... | ... | 10个更多 |

### 实测效果

```bash
python3 hallucination_detector.py "朱元璋发明了火锅"
# 🔴 contradicted 90%  证据: 朱元璋是明朝开国皇帝, 1328-1398年

python3 hallucination_detector.py "毕昇发明了活字印刷术"
# 🟢 verified 70%

python3 hallucination_detector.py "爱因斯坦提出了相对论"
# 🟢 verified 70%
```

**测试矩阵全部通过**：核心5组✅ / 攻防14用例✅ / 图谱推理11用例✅ / 注入防御86分

### 安全体系

- 12条Prompt Injection防线（输入清洗→指令检测→结构检测→KB校验→工具劫持检测）
- 29个攻击载荷测试，25个成功拦截
- GitHub Actions CI自动解密→测试→F1退化检查

如果你也在做幻觉检测或者对纯标准库实现感兴趣，欢迎交流。

🔗 https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth

---

## 🌍 Reddit — r/Python

**Title**: I built a zero-dependency LLM hallucination detector with 7M facts and 14 checkers — pure Python stdlib

**Body**:

After getting burned one too many times by ChatGPT making up historical facts, I built a hallucination detector that runs on nothing but Python's standard library.

**What it does:**
Checks LLM outputs against a 7M-fact SQLite knowledge base using a chain-of-responsibility pattern with 14 specialized checkers.

```bash
$ python3 hallucination_detector.py "朱元璋 invented hotpot"
# 🔴 contradicted (90%) — hotpot predates 朱元璋 by 1500+ years
```

**Architecture:**
```
Entity Index (514 entities) → Fact Retrieval (7M rows, SQLite FTS) 
→ 14 Checkers (weighted chain) → Knowledge Graph Reasoner → Output
```

**Checkers include:**
- YearConflict (0.92) — "X happened in 1900" vs KB "X happened in 1800"
- NumericConflict (0.90) — "Mount Everest is 10,000m" vs KB "8,848m"
- NegationChecker (0.83) — double-negative normalization
- AttributionChecker (0.80) — "Edison invented the telephone"
- GraphContradictionChecker (0.78) — multi-hop knowledge graph reasoning

**Security:**
- 12-layer prompt injection defense
- 29 attack vectors tested, 25 blocked (86/100)
- GitHub Actions CI with encrypted source

**Why zero dependencies?**
I develop on Android Termux. No pip, no torch, no numpy. Just Python 3.13 stdlib. Everything from the PBKDF2 key derivation to the XOR stream cipher for source encryption is hand-rolled with stdlib only.

GitHub: https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth

Would love feedback on the checker chain design and KB architecture.

---

## 🐦 Twitter/X — 拆成3条

**1/3** 🧵 Built a zero-dependency LLM hallucination detector. Pure Python stdlib. 7M facts. 14 checkers. Runs on Android Termux.

**2/3** Chain-of-responsibility pattern:
Entity index → SQLite FTS → 14 weighted checkers → Knowledge graph reasoner → verified/contradicted/unverifiable

**3/3** All tests green: 5 core ✅ / 14 adversarial ✅ / 11 graph reasoning ✅ / 86% injection defense score.
github.com/malaxiya20250530-glitch/anchor-llm-in-truth

---

## 💬 V2EX — "大家怎么检测LLM幻觉？我写了个纯标准库方案"

最近被大模型胡说八道搞烦了，写了个幻觉检测器。

特点：
- 纯Python标准库，不装任何包
- SQLite存了704万条事实
- 14个检查器责任链，加权投票
- 双重否定归一化（"不是没有"→"有"）
- 知识图谱推理（"毕昇发明了活字印刷术"→ verified）

跑在Android Termux上，手机上就能用。

GitHub: https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth

欢迎拍砖，特别是检查器设计的建议。

---

## 📋 Hacker News — Show HN

**Title**: Show HN: Anchor — Zero-dependency LLM hallucination detection (7M facts, 14 checkers)

**Body**:

Hi HN,

I built a hallucination detection system for LLM outputs. The constraint: must run with zero external dependencies (pure Python stdlib), because I develop on Android Termux.

How it works:
1. Entity resolution against a 514-entity semantic index
2. Fact retrieval from a 7M-row SQLite database with FTS
3. 14 specialized checkers in a weighted chain of responsibility
4. Knowledge graph reasoning for multi-hop contradiction detection
5. Trust scoring with belief function

Each checker handles one type of hallucination: year conflicts, numeric errors, attribution mistakes, negation confusion, causal contradictions, comparative falsehoods, etc.

Tests: 5 core ✅ / 14 adversarial ✅ / 11 graph ✅

I'd appreciate feedback on the checker chain architecture. Is this the right level of granularity? Should I add more checkers or merge existing ones?

https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth

---

## 📱 即刻 / 小红书 — 短版

🔍 写了个大模型幻觉检测器，纯Python标准库，手机上就能跑

14个检查器 + 704万条事实 + 知识图谱推理 = 专治ChatGPT胡说八道

👉 github.com/malaxiya20250530-glitch/anchor-llm-in-truth

#AI安全 #大模型 #开源 #Python
