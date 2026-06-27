# Anchor — 项目文件清单

## 核心模块（home 根目录，不可移动）
- `hallucination_detector.py` — 幻觉检测主模块（检查器链 + _compare_with_fact）
- `checker_registry.py` — @checker 装饰器 + Checker 基类
- `checker_classes.py` — 14 个检查器实现
- `consensus_voter.py` — 共识投票聚合
- `entity_index.py` — 实体索引
- `knowledge_graph.py` — 知识图谱
- `fuzzy_matcher.py` — 模糊匹配
- `embedding_search.py` — 嵌入搜索

## 知识库
- `kb_core.json` / `kb_core_new.json` — 核心知识库
- `fact_store.db` → `knowledge/fact_store.db`

## 安全/防御
- `prompt_injection_defense.py` — 提示注入防御
- `injection_hardener.py` — 注入加固
- `alignment_middleware.py` — 对齐中间件
- `content_filter.py` — 内容过滤

## 测试
- `test_fact_checker.py` — 单元测试（5 组场景）
- `benchmark.py` — 性能基准
- `injection_attack_sim.py` — 攻击模拟

## 基础设施
- `awareness_gateway.py` — LLM 网关（Ollama/OpenAI 双协议）
- `api_server.py` — API 服务
- `config.json` — 配置

> ⚠️ 所有文件必须保持在 home 根目录，移动会破坏 Python import 路径。
