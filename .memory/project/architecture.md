# 项目架构记忆

- 责任链模式：_compare_with_fact() 遍历 Checker.registry，每个检查器返回 (result_type, confidence) 或 None  \[置信度: 0.95\]
- @checker 装饰器自动注册检查器，Checker.registry 按注册顺序决定优先级  \[置信度: 0.95\]
- 知识库：fact_store.db（704万条事实，1.6GB）+ kb_core.json（语义索引）  \[置信度: 0.95\]
- 锚定引擎 AnchorEngine 驱动幻觉检测主流程  \[置信度: 0.9\]
- 纯 Python 标准库，禁用 torch/numpy/transformers 等外部依赖  \[置信度: 0.99\]
- meta/nn.py 手写微型神经网络，满足推理需求  \[置信度: 0.85\]
- 四层记忆架构：project/user/system/execution  \[置信度: 0.9\]
- Reasonix双目录架构：全局~/.reasonix + 项目.reasonix  \[置信度: 0.9\]

> 最后更新: 2026-06-10 12:57:53 UTC

- 5个优先级检查器链: _check_infinity → _check_negation → _check_year_conflict → _check_numeric → _check_overlap → _semantic_match_kb(bigram回退)  \[_2026-06-10 12:58:16 UTC_\]
- 知识图谱推理(knowledge_graph.py 427行): 实体-关系-实体三元组，支持一步和路径推理  \[_2026-06-10 12:58:16 UTC_\]
- 多源交叉验证: CrossVerifier 三路独立投票(KB匹配+图谱推理+ML共识)，2/3多数决定  \[_2026-06-10 12:58:17 UTC_\]
- 向量检索 vector_kb.py: 双协议支持 Ollama/OpenAI SSE嵌入  \[_2026-06-10 12:58:17 UTC_\]