# 更新日志

## [2026-06-03]
- 🔒 核心模块源码加密 (32个 .py → .pye)
- 🐛 修复 GraphContradictionChecker 3个推理bug
- 🛡️ 叙事标记前置检测 (的传说/的故事 → unverifiable)
- 🛡️ AttributionChecker 客体一致性检查
- 📊 新增 coverage_report.py 检查器覆盖率统计
- 🔗 新增 update_entity_id.py 实体映射闭环
- 🧪 新增 test_graph_checker.py (11/11通过)
- 🌐 仓库改名 anchor-llm-in-truth
- 📄 双语 README 合并

## [2026-06-02]
- ✅ 14个检查器 + F1权重决策
- ✅ 否定归一化预处理 (9组双否定模式)
- ✅ DeepSeek 集成测试 (6用例全通过)
- ✅ 注入防御12条防线

## [2026-05-31]
- 仓库创建
- 责任链模式重构 (13层嵌套 → 6层)
- @checker 装饰器自动注册
