# 项目历程与优化方向

- v5-v5.9 教训：truth_router/ 69文件5470行零引用主检测器，成为悬浮学术玩具  \[置信度: 0.95\]
- bare except 曾导致异常被静默吞掉，已全部替换为具体异常类  \[置信度: 0.9\]
- 13层嵌套导致 _compare_with_fact 无法维护，已拆分为责任链模式  \[置信度: 0.9\]
- test_fact_checker.py 5组测试全部通过  \[置信度: 0.95\]
- 同义词映射 + bigram 语义回退突破关键词天花板  \[置信度: 0.85\]
- 双协议 Ollama/OpenAI SSE 网关对接真实 LLM  \[置信度: 0.85\]
- 单元测试: python3 test_fact_checker.py（5组测试必须全绿）  \[置信度: 0.95\]
- 语法检查: python3 -c "import hallucination_detector"  \[置信度: 0.95\]
- 事实核查: python3 hallucination_detector.py "朱元璋发明了火锅"  \[置信度: 0.9\]
- 启动网关: python3 awareness_gateway.py --port 8800 --mock  \[置信度: 0.9\]
- 记忆查询: python3 codex_memory.py threads|context|memories  \[置信度: 0.9\]
- 责任链模式：_compare_with_fact() 遍历 Checker.registry，每个检查器返回 (result_type, confidence) 或 None
- @checker 装饰器自动注册检查器，Checker.registry 按注册顺序决定优先级
- 知识库：fact_store.db（704万条事实，1.6GB）+ kb_core.json（语义索引）
- 锚定引擎 AnchorEngine 驱动幻觉检测主流程
- 纯 Python 标准库，禁用 torch/numpy/transformers 等外部依赖
- meta/nn.py 手写微型神经网络，满足推理需求
- v5-v5.9 教训：truth_router/ 69文件5470行零引用主检测器，成为悬浮学术玩具
- bare except 曾导致异常被静默吞掉，已全部替换为具体异常类
- 13层嵌套导致 _compare_with_fact 无法维护，已拆分为责任链模式
- 同义词映射 + bigram 语义回退突破关键词天花板
- 双协议 Ollama/OpenAI SSE 网关对接真实 LLM
- 单元测试: python3 test_fact_checker.py（5组测试必须全绿）
- 语法检查: python3 -c "import hallucination_detector"
- 事实核查: python3 hallucination_detector.py "朱元璋发明了火锅"
- 启动网关: python3 awareness_gateway.py --port 8800 --mock
- 记忆查询: python3 codex_memory.py threads|context|memories
- migrate命令完成8文件迁移  \[置信度: 0.95\]

> 最后更新: 2026-06-10 12:57:53 UTC

- 已完成: Truth Router MVP 三层路由(上下文→检索→校验→评分)  \[_2026-06-10 12:58:18 UTC_\]
- 已完成: Memory Engine 三层记忆填充(project/user/session)  \[_2026-06-10 12:58:18 UTC_\]