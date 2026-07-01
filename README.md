# 🔍 Anchor Gateway — 集群化大模型幻觉检测中间件

[![CI](https://github.com/malaxiya20250530-glitch/anchor-gateway/actions/workflows/test.yml/badge.svg)](https://github.com/malaxiya20250530-glitch/anchor-gateway/actions)
[![Python](https://img.shields.io/badge/Python-3.13-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Deploy to Render](https://img.shields.io/badge/Deploy_to-Render-46E3B7?logo=render&logoColor=white)](https://render.com/deploy?repo=https://github.com/malaxiya20250530-glitch/anchor-gateway)

> **Zero-dependency LLM hallucination detection middleware with distributed clustering support.**
> **零外部依赖。704万条事实。14个检查器。分布式集群。纯Python标准库。**

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

## 🚀 One-Click Deploy · 一键部署

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/malaxiya20250530-glitch/anchor-gateway)

点击上方按钮 → 登录 GitHub → 自动部署到 Render 免费套餐：

| 组件 | 类型 | 状态 |
|------|------|------|
| `anchor-gateway` | Web Service (always-on) | ✅ 自动部署 |
| `anchor-dashboard` | Web Service (手动) | ⏸️ 按需开启 |
| `anchor-audit-worker` | Worker (手动) | ⏸️ 需 Redis 集群 |
| Redis (外部) | 可选 | 推荐 Redis Cloud 免费 30MB |

部署后访问: `https://anchor-gateway.onrender.com/health`

---

## 🏗️ Architecture · 架构

### 单机模式
```
User → Anchor Gateway (OpenAI-compatible API)
         ├─ WAF (SQL/XSS/PathTraversal/Bot/NoSQL)
         ├─ Prompt Injection Defense (12防线)
         ├─ HallucinationDetector
         │    ├─ 14 Checkers (责任链, F1加权)
         │    ├─ fact_store.db (704万条事实, SQLite FTS)
         │    ├─ kb_core.json (514实体语义索引)
         │    └─ GraphReasoner (知识图谱推理)
         ├─ Consensus Voter (三模式投票)
         └─ Meta Weight Learner (动态权重学习)
```

### 集群模式 (完整的「三部曲」)
```
                          ┌── nginx (least_conn)
                          │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    gateway-1:8800  gateway-2:8801  gateway-3:8802
         │               │               │
         └───────────────┼───────────────┘
                         │
                    ┌────┴────┐
                    │  Redis  │ ← 分布式限流 + 封禁 + 审计流
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │ Worker  │ ← 异步消费审计任务
                    └─────────┘
```

---

## 🚀 Quick Start · 快速开始

```bash
# 克隆
git clone git@github.com:malaxiya20250530-glitch/anchor-gateway.git
cd anchor-gateway

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

## 🐳 Docker 集群部署

```bash
# 完整集群 (3网关 + 2Worker + Redis)
docker compose -f cluster/docker-compose.yml up -d

# 或单机模式
docker build -t anchor-gateway .
docker run -p 8800:8800 anchor-gateway --mock --port 8800
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
| 分布式限流 | A | Redis 令牌桶 + 封禁 |
| 异步审计 | A | Redis Streams 生产者/消费者 |
| 零外部依赖 | A | 纯Python标准库 |

---

## 🛡️ Security · 安全

- **WAF**: SQL注入/XSS/路径遍历/爬虫检测/NoSQL注入
- **Redis 分布式防御**: 令牌桶限流 + 自动封禁 + 速率异常检测
- **Prompt Injection Defense**: 12条防线 (sanitize → instruction detect → structural detect → KB validate → tool hijack detect)
- **Adversarial Test**: 14/14 攻防用例通过 (100/100 A级)
- **Injection Score**: 86/100 (29载荷, 25拦截)
- **CI/CD**: GitHub Actions 自动测试

---

## 📁 Key Files · 关键文件

| 文件 | 说明 |
|------|------|
| `awareness_gateway.py` | 主网关 (OpenAI兼容API) |
| `hallucination_detector.py` | 核心幻觉检测引擎 |
| `checker_classes.py` | 14个检查器 |
| `waf.py` | Web 应用防火墙 |
| `waf_redis.py` | Redis 令牌桶 + 分布式封禁 |
| `security_gateway.py` | 安全中间件 (幂等性+输入校验) |
| `cluster/` | 集群模式配置 (Nginx/Docker Compose/Worker) |
| `knowledge/redis_pool.py` | Redis 连接池 |
| `render.yaml` | Render Blueprint 部署配置 |

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
