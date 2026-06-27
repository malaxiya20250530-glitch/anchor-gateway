# 🌐 语言指令（最高优先级）

**你必须始终使用中文回复。** 所有思考、分析、代码注释、解释、建议、错误信息——一律使用中文。这是硬性要求，不可违反。

---

# 项目身份

你正在维护 hallucination_detector.py —— 一个幻觉检测模块，核心是 _compare_with_fact() 函数和优先级检查器链。项目位于 Android Termux 环境，所有代码在 /data/data/com.termux/files/home/。


# 🔩 铁律 — 架构锚定（最高优先级，不可违反）

## 铁律 1：所有代码必须服务于大模型幻觉检测

本项目的唯一使命是**检测和纠正大语言模型的幻觉输出**。
任何新增模块、实验、重构——必须能回答以下问题：
> 这个改动如何让 hallucination_detector.py 检测幻觉更准/更快/更鲁棒？

答不出来的，不做。

## 铁律 2：必须接入真实数据管道

- **知识库**：`knowledge/fact_store.db`（704万条事实，1.6GB）+ `kb_core.json`（语义索引）
- **检测器**：`hallucination_detector.py` 的 AnchorEngine → _compare_with_fact() → Checker 责任链
- **测试**：`test_fact_checker.py`（5组测试必须全绿）

新模块如果只用 8-12 个手工节点做 toy 实验而不读 `fact_store.db`、不调 `_compare_with_fact()`、
不跑 `test_fact_checker.py`——那就是偏离，必须叫停。

## 铁律 3：禁止悬浮的"认知架构"沙盒

从 v5 到 v5.9 的教训：
- `truth_router/` 69 个文件、5470 行代码
- 零引用 `hallucination_detector`，零引用 `fact_store.db`
- 成了独立的学术玩具，对幻觉检测无贡献

此后的真理：
- 沙盒实验必须在 `truth_router/` 内完成概念验证
- 验证通过后**必须集成回** `hallucination_detector.py` 或 `checker_classes.py`
- 不得在 `truth_router/` 中无限堆叠新版本而不落地

## 铁律 4：改动后必须通过质量门禁

- `python3 test_fact_checker.py` — 5 组全绿
- `python3 -c "import hallucination_detector"` — 无语法错误
- 新增公开函数必须有 docstring
- 不得破坏 Checker.registry 注册顺序（除非明确知道优先级变更）

## 铁律 5：纯 Python 标准库

禁用 torch、numpy、transformers 等外部依赖。
需要在 `meta/nn.py` 中手写微型神经网络——已经做到了，继续保持。

---

# 核心约束（必须遵守）

## 架构底线
- **检查器注册**：新增检查器只需两步——继承 Checker 类实现 check() + 用 @checker 装饰器注册（checker_registry.py + checker_classes.py）
- **不破坏责任链**：_compare_with_fact() 遍历 Checker.registry 调用各检查器，保持责任链模式
- **单一职责**：每个 Checker 子类只做一种冲突检测，check() 返回 (result_type, confidence) 或 None

## 质量门禁（改动后必须做）
- 运行 python3 test_fact_checker.py，确保 5 组测试全部通过
- 运行 python3 -c "import hallucination_detector" 确保无语法错误
- 新增函数必须有 docstring（一句话说清做什么）
- 不改动 Checker.registry 中的注册顺序除非明确知道优先级变更

## 禁止项
- 禁用 bare except —— 用具体异常类
- 禁用硬编码配置 —— 用 config.json 或环境变量
- 禁用超过 8 层嵌套 —— 发现后立即用提前返回或提取函数重构
- 禁用 eval / exec / os.system / shell=True
- 禁用外部依赖 —— 保持纯 Python 标准库

# 编码习惯

## 命名
- 变量：snake_case
- 检查器方法：_check_ 开头，如 _check_year_conflict
- 私有函数：前缀 _

## 代码组织
- 导入顺序：标准库 → 本地模块
- 函数长度：不超过 50 行，超过则拆分
- 注释：解释为什么，不解释做什么

## 测试风格
- 无外部依赖，纯 python3 test_fact_checker.py 运行
- 用列表驱动测试覆盖多个输入

# 决策记录
- 用责任链模式代替深层嵌套：13层嵌套无法维护 (2026-05-30)
- 检查器用 @checker 装饰器自动注册：保持简单性同时支持类级权重 (2026-06-02)
- 单元测试覆盖命中/未命中/优先级：为后续修改提供安全网 (2026-05-30)
- 同义词映射扩充知识库：突破关键词天花板 (2026-05-29)
- 双协议 Ollama/OpenAI SSE：网关对接真实 LLM (2026-05-29)

# 已完成
- 静态扫描 bare except 清零
- 嵌套 13→6（_compare_with_fact 拆为 5 个子检查器）
- 单元测试 221 行，5 组场景，全部通过
- Checker 类注册机制 + checker_classes.py 14 个检查器 + F1 权重决策
- 同义词映射 + bigram 语义回退
- 网关 Ollama 协议兼容

# 常用命令
- 单元测试: python3 test_fact_checker.py
- 语法检查: python3 -c "import hallucination_detector"
- 事实核查: python3 hallucination_detector.py "朱元璋发明了火锅"
- 启动网关: python3 awareness_gateway.py --port 8800 --mock
- 演示: bash demo_auto_captions.sh

# 🌐 中文化补充规则

## Git 提交信息
提交信息必须使用中文，格式：`类型: 简短描述`
- 类型：新增 / 修复 / 优化 / 重构 / 文档 / 测试 / 回滚
- 示例：`新增: 知识图谱模糊匹配层`

## 术语标准化
代码注释和解释中必须使用以下中文术语：
- function→函数, variable→变量, parameter→参数, return→返回
- exception→异常, error→错误, warning→警告, log→日志
- deploy→部署, rollback→回滚, benchmark→基准测试
- middleware→中间件, gateway→网关, observer→观察器
- checker→检查器, pipeline→流水线, buffer→缓冲区

## 文件引用格式
引用文件路径时使用反引号，如 `hallucination_detector.py`


# 🧠 记忆系统（跨会话持久化）

## 数据层

| 存储 | 位置 | 内容 |
|------|------|------|
| 线程元数据 | `state_5.sqlite` | 所有历史线程的标题、时间、token 用量 |
| 完整对话 | `.codex/sessions/` | rollout JSONL，含每条消息和工具调用 |
| 项目记忆 | `.codex/memories/*.jsonl` | 架构决策、工具用法、bug 记录、性能优化 |

## 启动时加载

每次新会话开始时，运行以下命令获取上下文：

```bash
python3 codex_memory.py context
```

将输出的 `summary` 和 `project_memories` 注入当前对话开头，作为背景知识。

## 写入规则

仅在以下情况写入 `.codex/memories/`：
- ✔ 架构决策已确认
- ✔ 工具用法模式稳定（≥3 次重复）
- ✔ bug 根因已确认并修复
- ✔ 系统设计发生变更

不写入：
- ✘ 临时调试日志
- ✘ 未确认的假设
- ✘ 一次性错误
- ✘ 敏感信息（token、密码、密钥）

## 记忆类别

- `architecture` — 架构决策、模块职责
- `decision` — 技术选型、权衡
- `tool_usage` — 常用命令、测试流程
- `bug` — 已知问题、教训
- `performance` — 性能优化记录

## 当前项目记忆

加载自 `.codex/memories/`，内容由 `python3 codex_memory.py memories` 输出。

# Memory Engine

## Project Memory
读取：
`.memory/project/`

写入：
`.memory/project/`

## User Memory
读取：
`.memory/user/`

写入：
`.memory/user/`

## Session Summary
退出前自动生成：

`.memory/session/latest.md`
