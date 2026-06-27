# 📢 推广素材包

> 复制粘贴即可使用，每条已针对平台风格优化

---

## 🇨🇳 知乎 (回答"如何检测大模型幻觉")

**标题**: 我写了个零依赖的 LLM 幻觉检测器，14 个检查器 + 608 条知识库

先说结论：检测大模型幻觉确实很难，但可以通过**管道式责任链**做到实用的准确率。

我花了大半年写了这个项目，核心思路是四层级联检测：

1. **知识库匹配** — 608 条结构化事实（含医疗 45 条 + 法律 52 条垂直领域）
2. **向量混合检索** — BM25 + TF-IDF 找最相关事实
3. **联网交叉验证** — DuckDuckGo + Wikipedia 多源印证
4. **绝对化断言检测** — 抓"一定""绝对"类表述

每层有 14 个专项检查器（年号冲突/数字矛盾/位置错误/因果关系…），各自带 F1 权重，加权投票出最终结论。

最狠的一点：**零外部依赖**，纯 Python 标准库，不用 pip install。

```bash
python3 hallucination_detector.py "朱元璋发明了火锅"
# → 🔴 矛盾 90%  证据：朱元璋是明朝开国皇帝，1328-1398 年
```

还内置了：
- OpenAI 兼容网关（接入即用）
- API 计费系统（free/basic/pro/enterprise 四档）
- 可视化仪表盘
- 跨平台 Cython 加密编译

GitHub: https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth
欢迎 Star，也欢迎提 Issue 交流思路。

---

## 🇨🇳 掘金 (技术文章)

**标题**: 从 13 层嵌套到 14 检查器责任链：LLM 幻觉检测器的重构之路

### 背景

大模型会胡说八道，这不是秘密。但怎么系统地检测？我一开始写了个函数 _compare_with_fact()，后来嵌套了 13 层 if-else 没法维护……

### 重构

把 13 层嵌套拆成 14 个独立检查器，每个只做一种冲突检测：

```
YearConflictChecker    → 年份矛盾
NumericConflictChecker → 数值偏差 > 8%
NegationChecker        → 否定冲突
LocationConflictChecker→ 地点错误
CausalChecker          → 因果关系
...
```

然后用 `Checker.registry` 责任链 + F1 权重加权决策。

### 效果

- 单元测试 5 组全部通过
- DeepSeek 端到端实测 14 题零崩溃
- 知识库命中率显著提升

### 项目亮点

- 17,733 行 Python / 61 模块 / 0 外部依赖
- 内置 API 计费 + 仪表盘 + 加密编译
- GitHub Actions 四平台云编译 .so

GitHub: https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth

---

## 🇨🇳 V2EX (/share 节点)

**标题**: [分享创造] 写了个零外部依赖的大模型幻觉检测中间件

纯 Python 标准库，clone 下来直接跑，不需要 pip install。

```bash
python3 hallucination_detector.py "朱元璋发明了火锅"
# → 🔴 矛盾 90%
```

功能清单：
- 14 个检查器责任链
- 608 条知识库（医疗/法律/通用）
- OpenAI 兼容网关
- API 计费 (free/basic/pro/enterprise)
- 可视化仪表盘
- 跨平台加密编译 (.so)

仓库: https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth
觉得有用的话点个 Star，感谢！

---

## 🌍 Reddit r/LocalLLaMA

**Title**: [Project] Zero-dependency LLM hallucination detector — 14 checkers, 608 facts, OpenAI-compatible gateway

I built a middleware that sits between your LLM and users, detecting hallucinations in real-time.

**Why it's different:**
- **Zero dependencies** — pure Python stdlib, works anywhere Python 3.13 runs
- **Pipeline architecture** — KB → Vector Search → Web Cross-validation → Absolute Claim Detection
- **14 weighted checkers** — year conflicts, numeric deviation, negation, location, causality...
- **Self-evolving** — user feedback → auto KB update
- **Built-in billing** — API key management with tiered plans
- **Medical + Legal KBs** — 45 medical facts, 52 legal facts for vertical deployment

**Quick try:**
```bash
git clone https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth
python3 hallucination_detector.py "Edison invented the light bulb"
```

Would love feedback from the LocalLLaMA community!

---

## 🌍 Hacker News (Show HN)

**Title**: Show HN: Hallucination Detector — Zero-dependency LLM safety middleware

I spent 8 months building a hallucination detection system. It's a drop-in middleware that works like a CDN for AI safety — intercepting LLM outputs before they reach users.

- 14 weighted checkers in a responsibility chain
- 608 facts across general, medical, and legal domains
- 4-stage detection pipeline
- Built-in billing with API key management
- Compiles to .so for production deployment

Zero external dependencies. Pure Python stdlib.

GitHub: https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth

---

## 🐦 Twitter/X

LLM outputs can be wrong. I built a safety net.

Zero dependencies. 14 checkers. 608 facts. OpenAI-compatible.

```bash
python3 hallucination_detector.py "Zhu Yuanzhang invented hotpot"
# → CONTRADICTED 90%
```

🔗 github.com/malaxiya20250530-glitch/anchor-llm-in-truth

#LLM #AI #OpenSource #Python #MachineLearning

---

## 🎥 B站/YouTube 脚本 (60秒)

```
[0-5s]   黑屏字幕: "大模型会骗人吗？"
[5-10s]  终端录屏: python3 hallucination_detector.py "朱元璋发明了火锅"
[10-15s] 输出 🔴 矛盾 90%
[15-25s] 架构动画: 14检查器 → 责任链 → 加权投票
[25-35s] 仪表盘展示: 实时幻觉率曲线
[35-45s] 网关演示: curl 调用返回带觉察标记的 JSON
[45-55s] 代码行数/Star 数/开源链接
[55-60s] "点个 Star，让 AI 不再胡说八道"
```
