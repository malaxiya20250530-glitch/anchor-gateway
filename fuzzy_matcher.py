#!/usr/bin/env python3
"""
模糊匹配层 — 知识图谱推理的语义补充（纯标准库）
用知识库词表做最大正向匹配分词 → TF-IDF 余弦回退
"""

import re
import math
from collections import Counter
from typing import Optional


# ── 词表分词（知识库作为词典）─────────────────────

def _build_kb_dictionary() -> set:
    """从 KNOWLEDGE_BASE + SYNONYM_MAP 构建分词词典"""
    words = set()
    try:
        from hallucination_detector import KNOWLEDGE_BASE, SYNONYM_MAP
        words.update(KNOWLEDGE_BASE.keys())
        words.update(SYNONYM_MAP.keys())
        words.update(SYNONYM_MAP.values())
    except ImportError:
        pass
    # 基础停用词
    words.discard("facts"); words.discard("source")
    return {w for w in words if len(w) >= 1}


# ── 实体别名词典（多名→统一ID）─────────────────

ENTITY_ALIASES = {
    # 历史人物
    "朱元璋": ["明太祖", "洪武皇帝", "朱重八", "朱国瑞"],
    "秦始皇": ["嬴政", "始皇帝", "秦王政", "赵政"],
    "毕昇": ["毕升"],
    "蔡伦": ["蔡敬仲"],
    "孔子": ["孔丘", "孔夫子", "仲尼", "至圣先师"],
    "老子": ["李耳", "老聃", "太上老君"],
    "爱因斯坦": ["Albert Einstein", "爱氏"],
    "牛顿": ["艾萨克·牛顿", "Isaac Newton", "牛爵爷"],
    "达尔文": ["查尔斯·达尔文", "Charles Darwin"],
    "居里夫人": ["玛丽·居里", "Marie Curie", "居里"],
    # 地理
    "珠穆朗玛峰": ["珠峰", "圣母峰", "Everest", "萨加玛塔峰"],
    "故宫": ["紫禁城", "故宫博物院"],
    # 科技
    "活字印刷术": ["活字印刷", "活字排版"],
    "造纸术": ["造纸", "蔡侯纸"],
    "指南针": ["司南", "罗盘"],
    "火药": ["黑火药"],
    # 概念
    "圆周率": ["π", "pi", "祖率"],
    "勾股定理": ["毕达哥拉斯定理", "商高定理", "Pythagorean theorem"],
}


def _build_alias_map() -> dict[str, str]:
    """构建 别名→标准名 反向映射"""
    alias_to_canonical = {}
    for canonical, aliases in ENTITY_ALIASES.items():
        alias_to_canonical[canonical] = canonical
        for alias in aliases:
            alias_to_canonical[alias] = canonical
    return alias_to_canonical


_ALIAS_MAP = _build_alias_map()


def resolve_entity(name: str) -> str:
    """
    实体链接：将别名统一映射到标准名

    示例:
      resolve_entity("明太祖") → "朱元璋"
      resolve_entity("珠峰") → "珠穆朗玛峰"
      resolve_entity("π") → "圆周率"
    """
    return _ALIAS_MAP.get(name, name)


def resolve_entities_in_text(text: str) -> str:
    """
    替换文本中出现的别名（最长匹配优先）

    resolve_entities_in_text("明太祖发明了活字印刷")
    → "朱元璋发明了活字印刷术"
    """
    result = text
    # 按别名长度降序排列（避免短别名误匹配）
    sorted_aliases = sorted(_ALIAS_MAP.items(), key=lambda x: -len(x[0]))
    for alias, canonical in sorted_aliases:
        if alias != canonical and alias in result:
            result = result.replace(alias, canonical)
    return result


def segment_max_match(text: str, dictionary: set = None) -> list[str]:
    """
    最大正向匹配分词 — 以知识库词表为词典
    中文分词效果接近 jieba 的全模式
    """
    if dictionary is None:
        dictionary = _build_kb_dictionary()

    tokens = []
    i = 0
    max_len = max((len(w) for w in dictionary), default=4)

    while i < len(text):
        matched = False
        for length in range(min(max_len, len(text) - i), 0, -1):
            word = text[i:i + length]
            if word in dictionary:
                tokens.append(word)
                i += length
                matched = True
                break
        if not matched:
            # 单字退回
            tokens.append(text[i])
            i += 1
    return tokens


# ── 模糊实体匹配 ───────────────────────────────────

def fuzzy_entity_match(entity: str, candidates: list[str],
                       threshold: float = 0.6) -> Optional[str]:
    """
    模糊实体匹配：对 entity 和候选列表做 n-gram 余弦相似度
    返回最佳匹配候选（或 None）

    示例:
      fuzzy_entity_match("活字印刷", ["活字印刷术", "雕版印刷", "造纸术"])
      → "活字印刷术"
    """
    if not candidates:
        return None

    def ngram_vector(s: str, n: int = 2) -> Counter:
        return Counter(s[i:i+n] for i in range(len(s) - n + 1))

    e_vec = ngram_vector(entity)
    e_norm = math.sqrt(sum(v * v for v in e_vec.values())) or 1

    best_score = threshold
    best_match = None

    for cand in candidates:
        c_vec = ngram_vector(cand)
        # 余弦相似度
        common = set(e_vec) & set(c_vec)
        dot = sum(e_vec[k] * c_vec[k] for k in common)
        c_norm = math.sqrt(sum(v * v for v in c_vec.values())) or 1
        score = dot / (e_norm * c_norm)
        if score > best_score:
            best_score = score
            best_match = cand

    return best_match


# ── 集成到知识图谱推理 ─────────────────────────────

class FuzzyGraphReasoner:
    """
    带模糊匹配的知识图谱推理器
    包装原有 GraphReasoner，在实体名不精确匹配时降级到模糊匹配
    """

    def __init__(self):
        self._reasoner = None
        self._candidate_names: list[str] = []

    def _ensure_reasoner(self):
        if self._reasoner is None:
            from knowledge_graph import get_reasoner, get_graph
            self._reasoner = get_reasoner()
            self._candidate_names = list(get_graph().entities.keys())

    def infer_contradiction(self, claim_text: str) -> Optional[dict]:
        """
        模糊增强推理（含实体链接）：

        0. 实体链接：别名→标准名
        1. 精确匹配
        2. 模糊匹配 → 再推理
        """
        self._ensure_reasoner()

        # 0. 实体链接预处理
        linked_text = resolve_entities_in_text(claim_text)

        # 第一遍：精确匹配（链接后）
        result = self._reasoner.infer_contradiction(linked_text)
        if result and linked_text != claim_text:
            result["evidence"] = f"[实体链接: {claim_text}→{linked_text}] {result.get('evidence', '')}"
            return result

        # 也试原始文本
        if linked_text != claim_text:
            result = self._reasoner.infer_contradiction(claim_text)
        if result:
            return result

        # 第二遍：模糊匹配
        m = re.match(r'(\S{1,6})(发明了?|创造了?|是|在|位于)(\S{1,12})', claim_text)
        if not m:
            return None

        subj = m.group(1)
        obj = m.group(3)

        fuzzy_subj = fuzzy_entity_match(subj, self._candidate_names)
        if fuzzy_subj and fuzzy_subj != subj:
            # 用模糊匹配的实体名替换后重试
            rewritten = claim_text.replace(subj, fuzzy_subj, 1)
            result = self._reasoner.infer_contradiction(rewritten)
            if result:
                result["evidence"] = f"[模糊匹配: {subj}→{fuzzy_subj}] {result.get('evidence', '')}"
                result["confidence"] = min(result.get("confidence", 0.7) - 0.1, 0.9)
                return result

        # 也尝试模糊匹配宾语
        fuzzy_obj = fuzzy_entity_match(obj, self._candidate_names)
        if fuzzy_obj and fuzzy_obj != obj:
            rewritten = claim_text.replace(obj, fuzzy_obj, 1)
            result = self._reasoner.infer_contradiction(rewritten)
            if result:
                result["evidence"] = f"[模糊匹配: {obj}→{fuzzy_obj}] {result.get('evidence', '')}"
                result["confidence"] = min(result.get("confidence", 0.7) - 0.1, 0.9)
                return result

        return None


# ── 全局单例 ──────────────────────────────────────

_fuzzy_reasoner: Optional[FuzzyGraphReasoner] = None


def get_fuzzy_reasoner() -> FuzzyGraphReasoner:
    global _fuzzy_reasoner
    if _fuzzy_reasoner is None:
        _fuzzy_reasoner = FuzzyGraphReasoner()
    return _fuzzy_reasoner


# ── 演示 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=== 模糊匹配 + 知识图谱推理 演示 ===\n")

    # 分词演示
    tokens = segment_max_match("朱元璋发明了活字印刷术")
    print(f"分词: {' | '.join(tokens)}")

    # 模糊匹配演示
    candidates = ["活字印刷术", "雕版印刷术", "造纸术", "火药"]
    match = fuzzy_entity_match("活字印刷", candidates)
    print(f"模糊匹配 '活字印刷': → {match}")

    # 推理演示
    reasoner = get_fuzzy_reasoner()
    claims = [
        "朱元璋发明了活字印刷",     # 应通过模糊匹配活字印刷→活字印刷术命中
        "毕昇发明了造纸术",         # 应该命中（精确或模糊）
        "秦始皇发明了火锅",         # 应命中时间冲突
    ]
    for claim in claims:
        result = reasoner.infer_contradiction(claim)
        if result:
            print(f"🔴 {claim}")
            print(f"   → {result['verdict']} ({result['confidence']:.0%})")
            print(f"   → {result.get('evidence', '')[:80]}")
        else:
            print(f"🟢 {claim} — 未检出")
        print()
