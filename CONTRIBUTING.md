# 🤝 贡献指南

感谢你对幻觉检测项目的关注！

## 快速上手

```bash
git clone git@github.com:malaxiya20250530-glitch/anchor-llm-in-truth.git
cd anchor-llm-in-truth
python3 test_fact_checker.py  # 确保全部通过
```

## 新增检查器

只需两步：

1. 在 `checker_classes.py` 继承 `Checker` 并实现 `check()`
2. 添加 `@checker` 装饰器自动注册

```python
from checker_registry import Checker, checker

@checker
class MyChecker(Checker):
    weight = 0.80  # F1 分数

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        # 你的检测逻辑
        # 返回 ("contradicted", 0.85) / ("verified", 0.70) / None
        ...
```

## 新增知识库条目

编辑 `kb_core.json`，格式：

```json
"关键词": {
    "category": "历史",
    "fact": "事实描述",
    "source": "来源"
}
```

行业知识库同理：`kb_medical.json` / `kb_legal.json`

## 质量门禁

- `python3 test_fact_checker.py` 必须通过
- `python3 -c "import hallucination_detector"` 无语法错误
- 新函数 ≤ 50 行
- 禁止 bare except

## 提交规范

```bash
git commit -m "类型: 描述"
# 类型: 新增 / 修复 / 优化 / 重构 / 文档 / 测试
```

## 行为准则

- 友善交流
- 代码审查不针对个人
- 欢迎新手贡献，不清楚直接问

---

Made with ❤️ by [李桥](https://github.com/malaxiya20250530-glitch)
