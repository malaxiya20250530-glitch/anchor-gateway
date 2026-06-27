# 黄金基准集 (Golden Benchmark)

总计 **862** 条，按 8 个 Checker 分类。

| Checker | 样本数 | TRUE | FALSE | 难度 |
|---------|--------|------|-------|------|
| year_conflict | 306 | 108 | 198 | easy |
| negation | 146 | 81 | 65 | easy |
| knowledge_base | 119 | 73 | 46 | easy |
| temporal_order | 100 | 71 | 29 | medium |
| graph_relation | 91 | 68 | 23 | medium |
| numeric_conflict | 79 | 32 | 47 | easy |
| location_conflict | 21 | 20 | 1 | easy |

## 格式
```json
{
  "id": "gold_00001",
  "text": "秦朝是中国第一个大一统王朝，由秦始皇嬴政于公元前221年建立",
  "label": "TRUE",
  "category": "秦",
  "checker": [
    "year_conflict",
    "numeric_conflict",
    "negation",
    "temporal_order",
    "location_conflict",
    "graph_relation"
  ],
  "difficulty": "easy"
}
```
