#!/usr/bin/env python3
"""
知识图谱模块 — 从 KNOWLEDGE_BASE 自动构建实体关系图
支持实体解析、关系推理、冲突检测（纯 Python 标准库）
"""

import re
from typing import Optional
from collections import defaultdict


# ── 实体提取 ────────────────────────────────────────────

# 正则模式：提取文本中的结构化信息
RE_YEAR_SPAN = re.compile(r'(\d{3,4})\s*[-–—年]\s*(\d{3,4})?\s*年?')  # 1328-1398年
RE_BIRTH = re.compile(r'(生于|出生于|出生[于在]?)\s*(\d{3,4})\s*年?')  # 出生于1328年
RE_INVENTED = re.compile(r'([一-鿿]{2,4})(发明了?|创造了?|改进了?)([一-鿿]{2,6})')  # 蔡伦改进 / 毕昇发明
RE_PERSON_INTRO = re.compile(r'^([一-鿿]{1,4})(于|在|的)')  # 毕昇于... → 毕昇
RE_FOUNDED = re.compile(r'(\S{2,4})于?(\d{3,4})年(建立|创立|成立|建国)')  # 于1368年建立
RE_LOCATED = re.compile(r'(\S{2,8})(位于|在)(\S{2,8})')  # 故宫位于北京
RE_IS_A = re.compile(r'(\S{2,8})(是|属于)(\S{2,12})')  # 地球是行星
RE_NOT_CLAIM = re.compile(r'([一-鿿]{1,4}?)(不是|没有|不在)')  # 只匹配否定词
RE_CAPITAL = re.compile(r'(首都[是为])(\S{2,6})')  # 首都是长安
RE_DURING = re.compile(r'(在|于)(\S{2,6})(时期|年间|朝代)')  # 在唐代


class Entity:
    """知识图谱节点"""
    def __init__(self, name: str, etype: str, props: dict = None):
        self.name = name
        self.etype = etype      # PERSON / EVENT / PERIOD / CONCEPT / LOCATION / FACT
        self.props = props or {}

    def __repr__(self):
        return f"<{self.etype}:{self.name}>"


class Relation:
    """知识图谱边"""
    def __init__(self, subj: str, rel: str, obj: str, source: str = ""):
        self.subj = subj      # 主体实体名
        self.rel = rel         # 关系类型
        self.obj = obj         # 客体实体名或值
        self.source = source   # 知识来源

    def __repr__(self):
        return f"({self.subj})-[{self.rel}]->({self.obj})"


# ── 图谱构建 ────────────────────────────────────────────

class KnowledgeGraph:
    """实体关系图"""

    def __init__(self):
        self.entities: dict[str, Entity] = {}
        self.relations: list[Relation] = []
        self._index_by_type: dict[str, list[str]] = defaultdict(list)  # etype → [name, ...]

    def add_entity(self, name: str, etype: str, **props):
        if name not in self.entities:
            self.entities[name] = Entity(name, etype, props)
            self._index_by_type[etype].append(name)
        else:
            self.entities[name].props.update(props)

    def add_relation(self, subj: str, rel: str, obj: str, source: str = ""):
        self.relations.append(Relation(subj, rel, obj, source))

    def find_entity(self, name: str) -> Optional[Entity]:
        return self.entities.get(name)

    def find_by_type(self, etype: str) -> list[Entity]:
        return [self.entities[n] for n in self._index_by_type.get(etype, [])]

    def query_relations(self, subj: str = None, rel: str = None, obj: str = None) -> list[Relation]:
        """查询匹配的关系"""
        results = []
        for r in self.relations:
            if subj and r.subj != subj:
                continue
            if rel and r.rel != rel:
                continue
            if obj and r.obj != obj:
                continue
            results.append(r)
        return results

    def get_neighbors(self, name: str) -> list[tuple[str, str]]:
        """获取某实体的所有邻居 (关系, 邻居名)"""
        neighbors = []
        for r in self.relations:
            if r.subj == name:
                neighbors.append((r.rel, r.obj))
            if r.obj == name:
                neighbors.append((f"<-{r.rel}", r.subj))
        return neighbors

    def stats(self) -> dict:
        return {
            "entities": len(self.entities),
            "relations": len(self.relations),
            "by_type": {k: len(v) for k, v in self._index_by_type.items()},
        }


# ── 知识库解析器 ────────────────────────────────────────

def _clean_name(raw: str) -> str:
    """清理提取出的人名：去掉虚词后缀和时间残片"""
    name = re.sub(r'[是的，,。了]$', '', raw).strip()
    # 过滤明显非人名的残片（时间词/副词开头/过短）
    INVALID_NAME = re.compile(
        r'(?:时期|年代|年间|末年|初年|世纪|朝代|之前|之后|'
        r'^[才就都还也只便即]$|'
        r'^.{0,1}$)'
    )
    if INVALID_NAME.search(name) or len(name) < 2:
        return ''
    return name

def _extract_person_from_fact(fact: str) -> list[tuple[str, str, str]]:
    """从事实文本中提取人物相关三元组"""
    triples = []

    # "朱元璋是明朝开国皇帝，1328-1398 年"
    m = re.match(r'([一-鿿]{1,4})是([一-鿿]{2,12})', fact)
    if m:
        name = _clean_name(m.group(1))
        role = m.group(2).rstrip('，,。')
        triples.append((name, "IS_A", role))

    # 出生年份
    m = RE_BIRTH.search(fact)
    if m:
        name = fact[:m.start()].rstrip('，, ').split('，')[-1].strip()
        if not name or len(name) > 4:
            name_match = re.match(r'([一-鿿]{2,4})', fact)
            if name_match:
                name = _clean_name(name_match.group(1))
        year = m.group(2)
        triples.append((name, "BORN_IN", year))

    # 年份跨度 (1328-1398)
    m = RE_YEAR_SPAN.search(fact)
    if m and m.group(2):
        name_match = re.match(r'([一-鿿]{2,4})', fact)
        if name_match:
            name = _clean_name(name_match.group(1))
            triples.append((name, "BORN_IN", m.group(1)))
            triples.append((name, "DIED_IN", m.group(2)))

    # 发明/改进 — 优先从句首提取人名（处理 "毕昇于北宋年间发明..." 模式）
    m = RE_INVENTED.search(fact)
    if m:
        # 否定上下文检查：组1包含否定词 或 否定词紧邻左侧 → 不提取
        before = fact[:m.start()]
        g1 = m.group(1)  # 提取的人名部分
        if (re.search(r'(?:不是|没有|并非|不在)', before) or
            re.search(r'(?:不是|没有|并非|不在)', g1)):
            pass  # 否定上下文，跳过
        else:
            # 尝试从句首提取真正的人名
            intro_m = RE_PERSON_INTRO.match(fact)
            if intro_m:
                name = _clean_name(intro_m.group(1))
            else:
                name = _clean_name(m.group(1))
            if name:  # _clean_name 可能返回空字符串
                invention = m.group(3).rstrip('，,。的')
                triples.append((name, "INVENTED", invention))

    # 建立
    m = RE_FOUNDED.search(fact)
    if m:
        entity = m.group(1)
        year = m.group(2)
        triples.append((entity, "FOUNDED_IN", year))

    # 位于
    m = RE_LOCATED.search(fact)
    if m:
        triples.append((m.group(1), "LOCATED_AT", m.group(3)))

    # 不是/没有/不在 — 两步提取：先找否定词，再提取前后
    neg_words = re.compile(r'(不是|没有|不在)')
    for neg_m in neg_words.finditer(fact):
        neg = neg_m.group(0)
        pos_end = neg_m.end()
        # 向前取主语
        before = fact[:neg_m.start()].rstrip('，,。的 ')
        subj_match = re.search(r'([一-鿿]{1,4})$', before)
        # 向后取宾语
        after = fact[pos_end:].lstrip('，,。的 ')
        obj_match = re.match(r'([一-鿿]{1,8})', after)
        if subj_match and obj_match:
            subj = subj_match.group(1)
            obj = obj_match.group(1)
            # 清除尾部虚词/结构助词
            obj = re.sub(r'[的之是了等]$', '', obj)
            # 如果 obj 以动作词开头（如"发明火锅"），保留动作宾语（火锅）
            # 如果动作词在中间，截断到动作词之前
            action_match = re.search(r'(发明|创造|发现|造出|制造|制作|建立|产生)', obj)
            if action_match:
                if action_match.start() == 0:
                    # 动作词在开头: "发明火锅" → "火锅"
                    obj = obj[action_match.end():]
                else:
                    # 动作词在中间: "南宋时期才发明活" → "南宋时期才"
                    obj = obj[:action_match.start()]
            # 最终验证：长度>=2 且不含明显的残片标记
            if len(obj) >= 2 and not re.search(r'^(才|就|都|也|还|只)', obj):
                triples.append((subj, "NOT", obj))

    return triples



def build_from_knowledge_base(kb: dict) -> KnowledgeGraph:
    """从 KNOWLEDGE_BASE 构建知识图谱"""
    kg = KnowledgeGraph()

    for key, entry in kb.items():
        if key.startswith("_"):
            continue
        source = entry.get("source", "")
        facts = entry.get("facts", [])

        # 判断实体类型
        if any(str(i) in key for i in range(10)) or re.match(r'^[\u4e00-\u9fff]{1,2}$', key):
            # 朝代或短关键词
            if key in ('秦', '汉', '唐', '宋', '元', '明', '清', '三国'):
                etype = "PERIOD"
            else:
                etype = "CONCEPT"
        elif any(c in key for c in '，,. '):
            etype = "FACT"
        else:
            etype = "CONCEPT"

        kg.add_entity(key, etype, source=source)

        for fact in facts:
            triples = _extract_person_from_fact(fact)
            for subj, rel, obj in triples:
                # 确保主体实体存在
                if subj not in kg.entities:
                    kg.add_entity(subj, "PERSON")
                if obj not in kg.entities and not obj.isdigit():
                    if rel in ("IS_A", "LOCATED_AT"):
                        kg.add_entity(obj, "CONCEPT")
                    elif rel == "FOUNDED_IN":
                        kg.add_entity(obj, "EVENT")
                kg.add_relation(subj, rel, obj, source)

    return kg


# ── 推理引擎 ────────────────────────────────────────────

class GraphReasoner:
    """基于知识图谱的推理引擎"""

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg

    def check_temporal_conflict(self, person: str, event: str) -> Optional[dict]:
        """
        检查人物与事件的时间冲突
        例：朱元璋(1328-1398) vs 火锅(战国时期) → 朱元璋不可能发明火锅
        """
        person_node = self.kg.find_entity(person)
        if not person_node:
            return None

        # 获取人物生卒年
        born = None
        died = None
        for r in self.kg.query_relations(subj=person):
            if r.rel == "BORN_IN":
                born = int(r.obj)
            elif r.rel == "DIED_IN":
                died = int(r.obj)

        if born is None and died is None:
            return None

        # 获取事件的年份（或相关时间段）
        event_years = self._get_event_years(event)

        if event_years and born:
            event_start, event_end = event_years
            # 如果事件远早于人物出生，则冲突
            if event_end and event_end < born:
                return {
                    "verdict": "contradicted",
                    "confidence": 0.85,
                    "evidence": f"{person}({born}-{died or '?'}年)不可能参与{event_end}年之前的事件",
                    "reasoning": "temporal_conflict",
                }

        # 获取否定关系
        for r in self.kg.query_relations(subj=person, rel="NOT"):
            # 严格匹配: event必须与NOT宾语双向包含且长度比≥0.6
            if ((event in r.obj or r.obj in event) and
                min(len(event), len(r.obj)) / max(len(event), len(r.obj)) >= 0.8):
                return {
                    "verdict": "contradicted",
                    "confidence": 0.9,
                    "evidence": f"已知事实：{person} {r.rel} {r.obj}",
                    "reasoning": "explicit_negation",
                }

        return None

    def _get_event_years(self, event_name: str) -> Optional[tuple[int, int]]:
        """获取事件/概念的时间范围"""
        # 直接查实体
        entity = self.kg.find_entity(event_name)
        if not entity:
            return None

        # 查 FOUNDED_IN 关系
        for r in self.kg.query_relations(subj=event_name, rel="FOUNDED_IN"):
            if r.obj.isdigit():
                year = int(r.obj)
                return (year, year)

        # 查所属朝代
        for r in self.kg.query_relations(subj=event_name):
            if r.rel in ("DURING", "IS_A"):
                period_entity = self.kg.find_entity(r.obj)
                if period_entity and period_entity.etype == "PERIOD":
                    # 从朝代实体获取年份
                    for pr in self.kg.query_relations(subj=r.obj, rel="FOUNDED_IN"):
                        if pr.obj.isdigit():
                            return (int(pr.obj), int(pr.obj) + 300)  # 粗略估计

        # 从 PERIOD 实体的 facts 中解析
        if entity.etype == "PERIOD":
            source = entity.props.get("source", "")
            # 从 hallucination_detector 的 KNOWLEDGE_BASE 中获取年份
            # 这里简化为查关联关系
            for r in self.kg.query_relations(subj=event_name):
                if r.obj.isdigit():
                    year = int(r.obj)
                    return (year, year)

        return None

    def infer_contradiction(self, claim_text: str) -> Optional[dict]:
        """
        综合推理：检测声称是否与知识图谱冲突
        """
        # 尝试匹配 "X 发明了 Y" 或 "X 是 Y 的发明者/创造者" 模式
        m1 = re.match(r'(\S{1,4})(发明了?|创造了?)(\S{1,6})', claim_text)
        m2 = re.match(r'(\S{1,4})(?:是|为)(\S{1,8}?)(?:的)?(?:发明者|创造者|创始人)', claim_text)
        m = m1 or m2
        if m:
            person = m.group(1)
            event = m.group(2) if m is m2 else m.group(3)
            result = self.check_temporal_conflict(person, event)
            if result:
                return result

        # 尝试匹配 "X 在 Y" 或 "X 是 Y" 模式
        m = re.match(r'(\S{1,6})(?:是|在|位于)(\S{1,12})', claim_text)
        if m:
            subj = m.group(1)
            obj = m.group(2)
            for r in self.kg.query_relations(subj=subj, rel="NOT"):
                # 双向包含: obj在r.obj中 或 r.obj在obj中，且长度比>=0.6
                if (obj in r.obj or r.obj in obj) and                    min(len(obj), len(r.obj)) / max(len(obj), len(r.obj)) >= 0.8:
                    return {
                        "verdict": "contradicted",
                        "confidence": 0.9,
                        "evidence": f"已知事实：{subj} 不是 {obj}",
                        "reasoning": "explicit_negation",
                    }

        # 检查发明归属冲突（支持 "X发明了Y" 和 "X是Y发明者" 两种模式）
        m3 = re.match(r'(\S{1,4})(发明了?|创造了?)(\S{1,6})', claim_text)
        m4 = re.match(r'(\S{1,4})(?:是|为)(\S{1,8}?)(?:的)?(?:发明者|创造者|创始人)', claim_text)
        m = m3 or m4
        if m:
            person = m.group(1)
            event = m.group(2) if m is m4 else m.group(3)
            # 先精确匹配
            for r in self.kg.query_relations(rel="INVENTED", obj=event):
                if r.subj != person:
                    return {
                        "verdict": "contradicted",
                        "confidence": 0.8,
                        "evidence": f"{event}由{r.subj}发明，而非{person}",
                        "reasoning": "inventor_conflict",
                    }
            # 模糊匹配：event 可能是简称（"活字印刷" vs "活字印刷术"）
            all_invented = self.kg.query_relations(rel="INVENTED")
            for r in all_invented:
                if ((event in r.obj or r.obj in event) and
                    min(len(event), len(r.obj)) / max(len(event), len(r.obj)) >= 0.8):
                    if r.subj != person:
                        return {
                            "verdict": "contradicted",
                            "confidence": 0.75,
                            "evidence": f"{r.obj}由{r.subj}发明，而非{person}",
                            "reasoning": "inventor_conflict_fuzzy",
                        }

        return None


# ── 初始化 ──────────────────────────────────────────────

_graph_instance: Optional[KnowledgeGraph] = None
_reasoner_instance: Optional[GraphReasoner] = None


def get_graph() -> KnowledgeGraph:
    """获取全局知识图谱实例（懒加载）"""
    global _graph_instance
    if _graph_instance is None:
        from hallucination_detector import KNOWLEDGE_BASE
        _graph_instance = build_from_knowledge_base(KNOWLEDGE_BASE)
    return _graph_instance


def get_reasoner() -> GraphReasoner:
    """获取推理引擎实例"""
    global _reasoner_instance
    if _reasoner_instance is None:
        _reasoner_instance = GraphReasoner(get_graph())
    return _reasoner_instance


def test_demo():
    """快速演示"""
    kg = get_graph()
    reasoner = get_reasoner()

    print(f"图谱统计: {kg.stats()}")

    # 测试推理
    claims = [
        "朱元璋发明了火锅",
        "朱元璋发明了活字印刷",
        "毕昇发明了造纸术",
        "地球是平的",
        "故宫在纽约",
        "秦始皇发明了电",
    ]

    print("\n=== 推理测试 ===")
    for claim in claims:
        result = reasoner.infer_contradiction(claim)
        if result:
            print(f"🔴 {claim}")
            print(f"   → {result['verdict']} ({result['confidence']})")
            print(f"   → {result['evidence']}")
        else:
            print(f"🟢 {claim} — 未检测到冲突")
        print()


if __name__ == "__main__":
    test_demo()


def clear_cache():
    """清除全局缓存（用于测试或重新加载）"""
    global _graph_instance, _reasoner_instance
    _graph_instance = None
    _reasoner_instance = None
