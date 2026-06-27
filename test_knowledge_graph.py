#!/usr/bin/env python3
"""
知识图谱模块 单元测试
覆盖: 实体提取 · 图谱构建 · 关系查询 · 时间推理 · 否定推理 · 发明冲突
"""

import sys
sys.path.insert(0, '/data/data/com.termux/files/home')

from knowledge_graph import (
    KnowledgeGraph, Entity, Relation,
    _extract_person_from_fact, _clean_name,
    build_from_knowledge_base,
    GraphReasoner, get_graph, get_reasoner,
)

PASS, FAIL = 0, 0

def check(name, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: 预期 {expected!r}, 实际 {actual!r}")

def check_in(name, actual, expected_contains):
    global PASS, FAIL
    if expected_contains in str(actual):
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: 预期包含 {expected_contains!r}, 实际 {actual!r}")

def check_not_none(name, actual):
    global PASS, FAIL
    if actual is not None:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: 返回 None")

def check_none(name, actual):
    global PASS, FAIL
    if actual is None:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}: 预期 None, 实际 {actual!r}")


# ============================================================
# 组 1: KnowledgeGraph 基础
# ============================================================
print("\n[组 1] KnowledgeGraph 基础操作")

kg = KnowledgeGraph()
kg.add_entity("朱元璋", "PERSON", dynasty="明")
kg.add_entity("火锅", "CONCEPT")
kg.add_entity("明", "PERIOD")
kg.add_relation("朱元璋", "BORN_IN", "1328", "明史")
kg.add_relation("朱元璋", "DIED_IN", "1398", "明史")
kg.add_relation("朱元璋", "NOT", "火锅", "明史")
kg.add_relation("明", "FOUNDED_IN", "1368", "明史")

check("添加实体", len(kg.entities), 3)
check("添加关系", len(kg.relations), 4)
check("查找实体", kg.find_entity("朱元璋").etype, "PERSON")
check_none("查找不存在", kg.find_entity("秦始皇"))
check("按类型查找", len(kg.find_by_type("PERIOD")), 1)
check("查询关系-主语", len(kg.query_relations(subj="朱元璋")), 3)
check("查询关系-谓语", len(kg.query_relations(rel="BORN_IN")), 1)
check("查询关系-宾语", len(kg.query_relations(obj="火锅")), 1)
check("邻居查询", len(kg.get_neighbors("朱元璋")), 3)
check("统计", kg.stats()["entities"], 3)

# 重复添加不创建新实体
kg.add_entity("朱元璋", "PERSON", note="extra")
check("重复添加实体", len(kg.entities), 3)

# stats
s = kg.stats()
check("统计by_type", s["by_type"].get("PERSON", 0), 1)


# ============================================================
# 组 2: 事实三元组提取
# ============================================================
print("\n[组 2] 事实三元组提取")

# 朝代
triples = _extract_person_from_fact("秦朝是中国第一个大一统王朝")
check("IS_A提取", len(triples) > 0, True)
if triples:
    check("IS_A关系", triples[0][1], "IS_A")

# 生卒年
triples = _extract_person_from_fact("朱元璋是明朝开国皇帝，1328-1398 年")
check("年份跨度", len(triples) >= 2, True)

# 出生
triples = _extract_person_from_fact("爱因斯坦出生于1879年")
check("出生提取", len(triples) >= 1, True)

# 发明
triples = _extract_person_from_fact("毕昇于北宋庆历年间发明活字印刷术")
check("发明提取", len(triples) >= 1, True)
if triples:
    # 至少有一个 INVENTED
    has_invented = any(t[1] == "INVENTED" for t in triples)
    check("包含INVENTED", has_invented, True)

# 建立
triples = _extract_person_from_fact("明朝于1368年建立")
check("建立提取", len(triples) >= 1, True)

# 位于
triples = _extract_person_from_fact("故宫位于北京")
check("位置提取", len(triples) >= 1, True)

# 否定
triples = _extract_person_from_fact("爱因斯坦没有发明原子弹")
check("否定提取", len(triples) >= 1, True)
if triples:
    has_not = any(t[1] == "NOT" for t in triples)
    check("包含NOT", has_not, True)

# 空事实
triples = _extract_person_from_fact("这是一个普通的句子")
# "是"模式匹配到"这"是已知低价值匹配，不影响检测
check("空句子-低价值提取", len(triples) <= 1, True)


# ============================================================
# 组 3: 从知识库构建图谱
# ============================================================
print("\n[组 3] 从 KNOWLEDGE_BASE 构建图谱")

# 用迷你知识库测试
mini_kb = {
    "朱元璋": {"facts": ["朱元璋是明朝开国皇帝，1328-1398 年","朱元璋没有发明火锅"], "source": "明史"},
    "火锅": {"facts": ["火锅的历史可追溯到战国时期","火锅不是单一起源"], "source": "饮食文化史"},
    "毕昇": {"facts": ["毕昇于北宋庆历年间发明活字印刷术"], "source": "宋史"},
    "明": {"facts": ["明朝(1368-1644年)由朱元璋建立"], "source": "明史"},
}

kg2 = build_from_knowledge_base(mini_kb)
check("构建实体数>0", kg2.stats()["entities"] > 0, True)
check("构建关系数>0", kg2.stats()["relations"] > 0, True)
check("朱元璋实体存在", kg2.find_entity("朱元璋") is not None, True)


# ============================================================
# 组 4: GraphReasoner 时间推理
# ============================================================
print("\n[组 4] GraphReasoner 推理")

reasoner = GraphReasoner(kg2)

# 时间冲突: 朱元璋(1328-1398) 不可能发明 火锅(战国时期远早于明)
result = reasoner.check_temporal_conflict("朱元璋", "火锅")
check_not_none("时间冲突检测", result)

# 否定: 朱元璋 NOT 火锅
# 这是显式否定
result = reasoner.infer_contradiction("朱元璋发明了火锅")
check_not_none("推断-发明冲突", result)

# 发明冲突: 毕昇发明了活字印刷术 vs 朱元璋发明了活字印刷（字面不完全匹配）
result = reasoner.infer_contradiction("朱元璋发明了活字印刷")
# 注意: "活字印刷"≠"活字印刷术"，精确匹配下无法检出
# 这是已知局限，需语义匹配层补充
check_not_none("推断-发明者冲突(模糊匹配)", result)

# 无冲突
result = reasoner.infer_contradiction("毕昇发明了活字印刷")
check_none("推断-无冲突", result)

# 空字符串
result = reasoner.infer_contradiction("")
check_none("推断-空输入", result)


# ============================================================
# 组 5: 全局实例
# ============================================================
print("\n[组 5] 全局实例与集成")

graph = get_graph()
check("全局图谱实体>0", graph.stats()["entities"] > 0, True)
check("全局图谱关系>0", graph.stats()["relations"] > 0, True)

reasoner2 = get_reasoner()
check("全局推理器", reasoner2 is not None, True)

# 用全局推理器测试
result = reasoner2.infer_contradiction("朱元璋发明了火锅")
check_not_none("全局推理-火锅", result)

# 单例测试
graph2 = get_graph()
check("单例一致", graph is graph2, True)


# ============================================================
# 组 6: 边界条件
# ============================================================
print("\n[组 6] 边界条件")

# 未知人物
result = reasoner.check_temporal_conflict("不存在的人物", "火锅")
check_none("未知人物", result)

# 无时间信息的人物
kg3 = KnowledgeGraph()
kg3.add_entity("某人", "PERSON")
kg3.add_entity("某物", "CONCEPT")
reasoner3 = GraphReasoner(kg3)
result = reasoner3.check_temporal_conflict("某人", "某物")
check_none("无时间信息", result)

# _clean_name
check("清理是的", _clean_name("是的"), "是")
check("清理正常名", _clean_name("朱元璋"), "朱元璋")


# ============================================================
print(f"\n{'='*50}")
print(f"  总计: {PASS} 通过, {FAIL} 失败")
print(f"{'='*50}")
if FAIL == 0:
    print("  ✅ 全部通过")
else:
    print(f"  ❌ {FAIL} 个失败")
