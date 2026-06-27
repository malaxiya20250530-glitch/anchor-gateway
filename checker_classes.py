# ============================================================
# 插件系统：检查器类定义（替代 _PRIORITY_CHECKERS 字符串列表）
# ============================================================
# 此模块由 hallucination_detector.py 导入，使用 @checker 装饰器自动注册

import re
from typing import Optional

def _shared_entity(claim: str, fact: str) -> bool:
    """判断 claim 和 fact 是否指向同一实体。
    策略: 前2字符的双向子串匹配 — 双方共享句首关键词。"""
    c_clean = re.sub(r'[\d\s\-–—,，。！？、；：""''《》（）()]', '', claim)
    f_clean = re.sub(r'[\d\s\-–—,，。！？、；：""''《》（）()]', '', fact)
    if not c_clean or not f_clean:
        return False
    # 策略1: 前2字符双向子串匹配（精确）
    cp2 = c_clean[:2] if len(c_clean) >= 2 else c_clean
    fp2 = f_clean[:2] if len(f_clean) >= 2 else f_clean
    if cp2 in f_clean and fp2 in c_clean:
        return True
    # 策略2: TF-IDF 加权语义重合度（自动压低通用词权重，提升专名权重）
    if _semantic_overlap(claim, fact):
        return True
    # 字符级回退: 处理极短文本（加权分不可靠时）
    c_chars = set(re.findall(r'[一-鿿]', c_clean))
    f_chars = set(re.findall(r'[一-鿿]', f_clean))
    if not c_chars or not f_chars:
        return False
    overlap = c_chars & f_chars
    total_ratio = len(overlap) / max(min(len(c_chars), len(f_chars)), 1)
    # 至少共享3个汉字，且重合度 >= 60%
    if len(overlap) >= 3 and total_ratio >= 0.6:
        return True
    return False

from checker_registry import Checker, checker


# ═══════════════════════════════════════════════════════════
# TF-IDF 加权语义重合度 — 替代手工维护的通用词黑名单
# ═══════════════════════════════════════════════════════════

# KB bigram IDF 权重表（惰性初始化）
_bigram_idf = None


def _build_bigram_idf():
    """从 KB 构建 bigram 逆文档频率表。
    高频 bigram（如'发明'、'印刷'）→ 低权重；
    低频专名 bigram（如'毕昇'、'朱熹'）→ 高权重。
    """
    global _bigram_idf
    if _bigram_idf is not None:
        return _bigram_idf
    try:
        from hallucination_detector import KNOWLEDGE_BASE
    except ImportError:
        _bigram_idf = {}
        return _bigram_idf
    
    # 统计每个 bigram 出现在多少个 KB 条目中
    doc_count = {}
    total_docs = len(KNOWLEDGE_BASE)
    for key, entry in KNOWLEDGE_BASE.items():
        facts = entry.get('facts', entry.get('fact', []))
        if isinstance(facts, str):
            facts = [facts]
        # 合并 key + 所有 facts 的 bigram（去重，每个条目只计1次）
        all_text = key + ' ' + ' '.join(facts)
        seen = set()
        for i in range(len(all_text) - 1):
            bg = all_text[i:i+2]
            if bg not in seen:
                seen.add(bg)
                doc_count[bg] = doc_count.get(bg, 0) + 1
    
    # 计算 IDF: log(总文档数 / 出现该 bigram 的文档数)
    import math
    _bigram_idf = {}
    for bg, count in doc_count.items():
        _bigram_idf[bg] = math.log((total_docs + 1) / (count + 1)) + 1.0  # +1 平滑
    return _bigram_idf


def _weighted_bigram_overlap(text_a: str, text_b: str) -> float:
    """TF-IDF 加权 bigram 重叠分数 + 同义词扩展 + 动态阈值。
    
    返回 (score, has_entity_link) 元组:
    - score: 0.0~1.0 加权重合度
    - has_entity_link: 同义词扩展是否增加了共享bigram（实体链接信号）
    
    调用方根据 has_entity_link 使用不同阈值:
    - 有实体链接 → 阈值 0.06（宽松）
    - 无实体链接 → 阈值 0.25（严格）
    """
    idf = _build_bigram_idf()
    if not idf:
        return (0.0, False)
    
    # 先计算原始文本的共享bigram
    raw_a_bigrams = {text_a[i:i+2] for i in range(len(text_a) - 1)}
    raw_b_bigrams = {text_b[i:i+2] for i in range(len(text_b) - 1)}
    raw_shared = raw_a_bigrams & raw_b_bigrams
    
    # 同义词扩展: 将同义表达替换为规范形式（实体链接）
    expanded_a = text_a
    expanded_b = text_b
    try:
        from hallucination_detector import SYNONYM_MAP
        for syn, target in SYNONYM_MAP.items():
            if syn in text_a:
                expanded_a += ' ' + target
            if syn in text_b:
                expanded_b += ' ' + target
    except ImportError:
        pass
    
    # 提取扩展后文本的 bigram 集合
    a_bigrams = {expanded_a[i:i+2] for i in range(len(expanded_a) - 1)}
    b_bigrams = {expanded_b[i:i+2] for i in range(len(expanded_b) - 1)}
    
    if not a_bigrams or not b_bigrams:
        return (0.0, False)
    
    # 共享 bigram
    shared = a_bigrams & b_bigrams
    if not shared:
        return (0.0, False)
    
    # 实体链接信号: 扩展后是否增加了共享bigram
    has_entity_link = len(shared) > len(raw_shared)
    
    # 加权方向重合度: 调和平均(共享/A, 共享/B)
    shared_weight = sum(idf.get(bg, 1.0) for bg in shared)
    a_weight = sum(idf.get(bg, 1.0) for bg in a_bigrams)
    b_weight = sum(idf.get(bg, 1.0) for bg in b_bigrams)
    
    if a_weight < 0.001 or b_weight < 0.001:
        return (0.0, False)
    
    ratio_a = shared_weight / a_weight
    ratio_b = shared_weight / b_weight
    if ratio_a + ratio_b < 0.001:
        return (0.0, False)
    score = 2 * ratio_a * ratio_b / (ratio_a + ratio_b)
    return (score, has_entity_link)


def _semantic_overlap(claim: str, fact: str) -> bool:
    """判断两个文本是否讨论同一主题。
    
    结合 TF-IDF 加权重合度 + 实体链接信号，使用动态阈值。
    - 有实体链接 → 阈值 0.06
    - 无实体链接 → 阈值 0.25
    
    返回 True 表示可能是同一主题，False 表示跨主题。
    """
    score, has_link = _weighted_bigram_overlap(claim, fact)
    threshold = 0.06 if has_link else 0.25
    return score >= threshold



def _negation_same_subject(claim, fact, claim_pat, fact_pat):
    """检查否定模式中声明和事实是否指向同一对象
    保守策略: 无法提取对象时不判矛盾 (return False = 不拦截)"""
    cm = re.search(claim_pat, claim)
    fm = re.search(fact_pat, fact)
    if not cm or not fm:
        return False
    c_obj = cm.group(1).strip()
    f_obj = fm.group(1).strip()
    if not c_obj or not f_obj:
        return False
    return c_obj == f_obj



@checker
class InfinityChecker(Checker):
    weight = 0.82  # F1 ≈ 0.8
    """检查: 声称无穷 vs 事实有限 → 矛盾"""
    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """执行检查，返回 (verdict, confidence) 或 None"""
        if re.search(r'不是.*无穷|没有.*无限|并非.*无穷', claim):
            return None
        if re.search(r'无穷|无限', claim) and re.search(r'有限|每秒|公里|不是.*无穷', fact):
            return ("contradicted", 0.85)
        return None


@checker
class NegationChecker(Checker):
    weight = 0.83  # F1 ≈ 0.88
    """检查: 否定模式匹配 → 矛盾"""
    # 不/没 白名单：这些固定表达中的"不/没"不构成独立否定
    _NEG_WHITELIST = {
        "不错", "不满", "不客气", "不好意思", "不仅", "不只", "不同",
        "不断", "不足", "不管", "不论", "不过", "不久", "不仅", "不如",
        "不妨", "不止", "不免", "不愧", "不由得",
    }

    _SELF_CORRECT_PAT = re.compile(
        r'[（(]\s*(?:确切地?说|准确地?说|严格地?说|其实|应当说|应该说|即|也就是)[^）)]*[）)]',
        re.IGNORECASE
    )

    @classmethod
    def _has_self_correction(cls, claim: str, keyword_pos: int) -> bool:
        """检查claim中keyword_pos附近是否有括号自我纠正（如'发明（确切地说是改进）'）"""
        near = claim[keyword_pos:keyword_pos + 40]
        return bool(cls._SELF_CORRECT_PAT.search(near))

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """执行检查，返回 (verdict, confidence) 或 None"""
        # 前向引用：_negation_same_subject 在导入此模块前已定义

        # 通用否定检测: fact 说"没有X/不是X/不存在X"
        # → 若 claim 中不包含对X的否定且X或X的字符重排出现在claim中 → 矛盾
        general_neg = re.search(r'(?:并没有|没有|不是|并非|不存在|不在|不|没)\s*(.{1,8}?)(?:[，。、；的]|$)', fact)
        if general_neg:
            neg_entity = general_neg.group(1).strip()
            # 白名单: 固定表达中的不/没不构成独立否定
            # 提取纯否定词 (不 或 没)
            neg_prefix = '不' if general_neg.group(0).startswith('不') else ('没' if general_neg.group(0).startswith('没') else '')
            neg_full = neg_prefix + neg_entity if neg_prefix else ''
            if neg_full in self._NEG_WHITELIST:
                pass  # 白名单固定表达 → 跳过
            elif neg_entity and len(neg_entity) >= 1:
                # 精确匹配或字符级回退 (处理"效果"↔"有效"的情况)
                entity_in_claim = (neg_entity in claim or 
                    (len(neg_entity) >= 2 and 
                     sum(1 for c in neg_entity if c in claim) / len(neg_entity) >= 0.7))
                if entity_in_claim:
                    # 确认 claim 中没有否定该实体（避免双重否定）
                    if not re.search(
                        r'(?:并没有|没有|不是|并非|不存在|不在|不|没)\s*' + re.escape(neg_entity), claim):
                        # 检查claim中是否有括号自我纠正（如'发明（确切地说是改进）'）
                        if not self._has_self_correction(claim, claim.find(neg_entity[:2]) if len(neg_entity) >= 2 else 0):
                            return ("contradicted", 0.78)
        # 反向否定: claim说"没有X/不是X", fact肯定X → 矛盾
        claim_neg = re.search(r'(?:并没有|没有|不是|并非|不存在|不在)\s*(.{1,8}?)(?:[，。、；的]|$)', claim)
        if claim_neg:
            claim_neg_entity = claim_neg.group(1).strip()
            if claim_neg_entity and len(claim_neg_entity) >= 1:
                # fact中正面出现该实体 → 矛盾
                # ⚠️ 但需确认 fact 不是在否定同一实体（同向否定 = 一致）
                if claim_neg_entity in fact:
                    # 如果 fact 也在否定同一实体 → 双方一致，不矛盾
                    fact_also_negates = re.search(
                        r'(?:并没有|没有|不是|并非|不存在|不在)\s*' + re.escape(claim_neg_entity), fact)
                    if not fact_also_negates:
                        return ("contradicted", 0.80)

        if re.search(r'不是|没有|并非|不可以|不能|不会|不在', fact):
            # 主语验证: claim和fact必须共享至少一个2字以上的实词
            # 主语验证：提取否定词前后的关键词
            # 保守策略 — 不额外过滤，保留原有逻辑
            key_m = re.search(r'(?:是|能|会|可以)(.{1,6}?)(?:的|。|，|$)', claim)
            if key_m:
                key_word = key_m.group(1)
                if key_word and re.search(r'(?:不是|没有|并非|不可以|不能|不会|不在).*' + re.escape(key_word), fact):
                    if re.search(r'(?:不是|没有|并非).*' + re.escape(key_word), claim):
                        return None
                    return ("contradicted", 0.85)
        patterns = [
            (r"(?:发明了|创造了|创建了)", r"(?:不是|没有|并非).*(?:发明|创造|创建)",
             lambda c, f: _negation_same_subject(c, f,
                 r'(?:发明了|创造了|创建了)(.{2,8}?)(?:，|。|$)',
                 r'(?:不是|没有|并非)(?:.*?)(?:发明|创造|创建)(.{2,8}?)(?:，|。|$)')),
            (r"第一", r"(?:不是|没有|维京|更早|最后)"),
            (r"(?:最好|最大)", r"(?:不是|没有|并非)"),
            (r"同一个", r"任何.*关系"),
            (r"会导致", r"不会导致"),
            (r"就是", r"不是.*同一个"),
            (r"能", r"不能"),
            (r"可以", r"不可以|不能"),
            (r"一定会", r"不会|不一定"),
            (r"按原子量", r"不是原子量|按原子序数"),
            (r"被苹果砸", r"没有被苹果",
             lambda c, f: not re.search(r'(?:关于.{0,8}的故事|传说|据说|流传|民间故事)', c)),
        ]
        for item in patterns:
            cp, fp = item[0], item[1]
            extra_check = item[2] if len(item) > 2 else None
            if re.search(cp, claim) and re.search(fp, fact):
                # 若 claim 匹配关键词前有否定词 → claim 与 fact 同向否定，一致
                cm = re.search(cp, claim)
                if cm:
                    prefix = claim[:cm.start()]
                    if re.search(r'(?:不是|没有|并非|并无|不|未).{0,15}$', prefix):
                        continue
                # 共享实词检查: claim与fact必须共享至少一个字符bigram
                # 防止"心理潜能"中的"能"错误匹配"不能再生"中的"不能"
                c_bi = {claim[i:i+2] for i in range(len(claim)-1)}
                f_bi = {fact[i:i+2] for i in range(len(fact)-1)}
                if not (c_bi & f_bi):
                    continue
                # 括号自我纠正: claim 中匹配关键词后紧跟括号纠正 → 不矛盾
                # 例: "瓦特发明（确切地说是改进）蒸汽机" → 已自我修正
                after_match = claim[cm.end():cm.end()+30]
                if re.search(r'[（(].{0,10}(?:确切地|准确|其实|严格|应当|应该|即).{0,10}[）)]', after_match):
                    continue
                # 通用叙事上下文: claim在讲"故事/传说/说法"而非直接断言
                if re.search(r'(?:的故事|的传说|的说法|的迷思|的误解).{0,20}$', claim[:cm.start() + len(cp) + 10]):
                    continue
                if extra_check and not extra_check(claim, fact):
                    continue
                return ("contradicted", 0.85)
        # 通用否定：claim声称"没有任何X" → 检查fact是否有反例关键词
        univ_neg = re.search(r'(?:没有任何|从未有|从来没有|从未|不存在任何|没有一个)\s*(.{2,15})', claim)
        if univ_neg:
            univ_entity = univ_neg.group(1).strip()
            if univ_entity:
                counter_words = ['已有', '存在', '维京', '更早', '之前', '在此之前', '早就', '已有过']
                if any(w in fact for w in counter_words):
                    return ("contradicted", 0.80)
        # 长否定回退：fact含"不是/没有/并非"且claim不含该否定词 → 宽松匹配
        if re.search(r'(?:不是|没有|并非|而非)', fact):
            neg_in_claim = re.search(r'(?:不是|没有|并非|而非)', claim)
            if not neg_in_claim:
                # 提取fact否定词后的内容作为关键实体（放宽到20字，贪婪）
                fm = re.search(r'(?:不是|没有|并非|而非)\s*(.{1,20})(?:[，。、；的]|$)', fact)
                if fm:
                    neg_entity = fm.group(1).strip()
                    if neg_entity and len(neg_entity) >= 2:
                        # 模糊匹配：claim中是否包含该实体的70%字符
                        overlap = sum(1 for c in neg_entity if c in claim) / len(neg_entity)
                        if overlap >= 0.6:
                            # 检查claim中是否有括号自我纠正
                            if not self._has_self_correction(claim, 0):
                                return ("contradicted", 0.76)
        return None


@checker
class YearConflictChecker(Checker):
    weight = 0.92  # F1 ≈ 0.66
    """检查: 年份冲突 — 事件年份/生卒范围/单年溢出"""
    _EVENT_GROUPS = {
        "birth": ["出生", "生于", "诞辰", "诞生"],
        "death": ["去世", "病逝", "驾崩", "卒于", "逝世", "流放"],
        "found": ["建立", "统一", "创建", "成立", "建国", "灭亡"],
        "invent": ["发明", "创造", "发现", "发布", "发表", "提出"],
        "reign": ["称帝", "即位", "登基"],
        "publish": ["出版", "撰写", "著作"],
    }
    def _event_group(self, text: str) -> str:
        """识别文本中的事件类型，返回分组名如 birth/death/found/invent/reign/other"""
        for group, words in self._EVENT_GROUPS.items():
            if any(w in text for w in words):
                return group
        return "other"
    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """执行检查，返回 (verdict, confidence) 或 None"""
        if not _shared_entity(claim, fact):
            return None
        # TF-IDF 加权语义重合: 防止毕昇 vs 古腾堡被误判为冲突
        if not _semantic_overlap(claim, fact):
            return None
        cy, fy = re.findall(r"\d{3,4}", claim), re.findall(r"\d{3,4}", fact)
        if not cy or not fy:
            return None
        c_group = self._event_group(claim)
        f_group = self._event_group(fact)
        if c_group != "other" and f_group != "other" and c_group != f_group:
            return None  # 不同事件类型不比较
        if c_group != "other" and f_group != "other":
            ci = sorted(int(c) for c in cy)
            fi = sorted(int(f) for f in fy)
            if ci[-1] < fi[0] or ci[0] > fi[-1]:
                return ("contradicted", 0.85)
            if not (set(cy) & set(fy)):
                return ("contradicted", 0.82)
            return None
        bd = re.findall(r"(\d{4})年[\-\–]\s*(\d{4})年", claim)
        fr = re.findall(r"(\d{4})[\-\–]\s*(\d{4})", fact)
        if bd and fr:
            if bd[0][0] != fr[0][0] or bd[0][1] != fr[0][1]:
                return ("contradicted", 0.90)
        if len(cy) == 1 and len(fy) >= 2:
            # 新增上下文检查: claim与fact必须共享至少一个实词(非年份数字)
            # 防止不同事件被误判为矛盾(如1939年致信 vs 1905年发论文)
            cw = set(re.findall(r'[\u4e00-\u9fff]{2,}', claim))
            fw = set(re.findall(r'[\u4e00-\u9fff]{2,}', fact))
            if cw & fw:
                c_year = int(cy[0])
                f_years = sorted(int(y) for y in fy)
                if c_year < f_years[0] or c_year > f_years[-1]:
                    return ("contradicted", 0.82)
        # 单年对比: 双方各1个年份且不同 → 矛盾(bigram重叠防误判)
        # 必须至少一方有年份上下文(年/公元/前) → 防止金额/数量误判
        if len(cy) == 1 and len(fy) == 1 and cy[0] != fy[0]:
            has_year_context = (
                re.search(r'(?:年|公元|前\d)', claim) and
                re.search(r'(?:年|公元|前\d)', fact)
            )
            if has_year_context:
                # 事件类型守卫：一方明确是生卒/发明/建国，另一方无匹配 → 不比较
                if c_group != "other" and f_group == "other":
                    return None
                if c_group == "other" and f_group != "other":
                    return None
                c_bigrams = {claim[i:i+2] for i in range(len(claim)-1)}
                f_bigrams = {fact[i:i+2] for i in range(len(fact)-1)}
                if len(c_bigrams & f_bigrams) >= 3:
                    return ("contradicted", 0.82)
        return None


@checker
class NumericConflictChecker(Checker):
    weight = 0.90  # F1 ≈ 0.7
    """检查: 同度量数值偏差 > 8% → 矛盾（支持万/亿中文数字）"""

    # 中文数字单位映射
    _CN_UNIT = {'万': 10000, '亿': 100000000, '千': 1000, '百': 100}

    @classmethod
    def _parse_number(cls, s: str) -> Optional[float]:
        """解析数字字符串，支持中文单位：30万→300000, 3.5亿→350000000"""
        m = re.match(r'([\d]+(?:\.\d+)?)\s*([万亿千百])?', s)
        if not m:
            return None
        val = float(m.group(1))
        unit = m.group(2)
        if unit and unit in cls._CN_UNIT:
            val *= cls._CN_UNIT[unit]
        return val

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """检查: 数值冲突 — 中文数字解析 + 宽松单位匹配"""
        # 提取含单位的数字：30万、8800米、100°C 等
        # 先去除数字中的逗号分隔符（如 299,792,458 → 299792458）
        _clean_claim = re.sub(r'(?<=\d),(?=\d)', '', claim)
        _clean_fact = re.sub(r'(?<=\d),(?=\d)', '', fact)
        cn_raw = re.findall(r'[\d.]+(?:万|亿|千|百)?', _clean_claim)
        fn_raw = re.findall(r'[\d.]+(?:万|亿|千|百)?', _clean_fact)
        if not cn_raw or not fn_raw:
            return None
        # 实体绑定: 必须是同一实体
        if not _shared_entity(claim, fact):
            return None
        # 年份场景: 额外验证事件类型一致性 + 共享专名
        if re.search(r'年', claim) and re.search(r'年', fact):
            c_group = YearConflictChecker()._event_group(claim)
            f_group = YearConflictChecker()._event_group(fact)
            if c_group != "other" and f_group != "other" and c_group != f_group:
                return None  # 不同事件类型不比较
            # TF-IDF 加权语义重合: 防止毕昇(1041) vs 古腾堡(1450)被误判
            if c_group == f_group:
                if not _semantic_overlap(claim, fact):
                    return None  # 语义不相关，不比较
        # 单位一致性检查：claim和fact的数字必须共享同类单位
        # 否则可能是不同语义的数字（如2100万个 vs 2009年）
        unit_types = {
            '长度': r"米|公里|千米",
            '时间': r"年|岁",
            '数量': r"个|枚|颗|次",
            '温度': r"度|°|℃",
        }
        unit_match = False
        matched_utype = None
        for utype, upat in unit_types.items():
            if re.search(upat, claim) and re.search(upat, fact):
                unit_match = True
                matched_utype = utype
                break
        if not unit_match:
            # 无单位或单位不匹配 → 不比较
            return None
        # 长度单位归一化：处理 米 ↔ 公里/千米 的换算
        claim_has_km = bool(re.search(r'公里|千米', claim))
        fact_has_km = bool(re.search(r'公里|千米', fact))
        cn_scale = 1.0
        fn_scale = 1.0
        if matched_utype == '长度':
            if claim_has_km and not fact_has_km:
                cn_scale = 1000.0  # 公里→米
            elif fact_has_km and not claim_has_km:
                fn_scale = 1000.0  # 公里→米
        # 解析所有数字为浮点数
        cn = []
        for s in cn_raw:
            v = self._parse_number(s)
            if v is not None:
                cn.append(v * cn_scale)
        fn = []
        for s in fn_raw:
            v = self._parse_number(s)
            if v is not None:
                fn.append(v * fn_scale)
        if not cn or not fn:
            return None

        # ⚠️ 单位类型过滤: 只比较与匹配单位类型相同的数字对
        # 避免跨类型比较（如年份2005 vs 高度8848.86）
        if matched_utype:
            unit_pat = unit_types[matched_utype]
            # 只保留 数字后紧跟匹配单位 的数值
            cn_filtered = []
            for s, v in zip(cn_raw, cn):
                if re.search(unit_pat, claim[claim.find(s):claim.find(s)+len(s)+3] if s in claim else ''):
                    cn_filtered.append(v)
                elif len(cn_raw) == 1:
                    cn_filtered.append(v)  # 单一数字 → 保留
            fn_filtered = []
            for s, v in zip(fn_raw, fn):
                if re.search(unit_pat, fact[fact.find(s):fact.find(s)+len(s)+3] if s in fact else ''):
                    fn_filtered.append(v)
                elif len(fn_raw) == 1:
                    fn_filtered.append(v)
            if cn_filtered:
                cn = cn_filtered
            if fn_filtered:
                fn = fn_filtered

        return self._compare_number_pairs(cn, fn)

    @staticmethod
    @staticmethod
    def _compare_number_pairs(nums_a: list, nums_b: list) -> Optional[tuple]:
        # 先检查是否有匹配对（偏差<8%），有则整个claim不矛盾
        has_match = False
        for a in nums_a:
            for b in nums_b:
                if not NumericConflictChecker._nums_conflict(a, b):
                    has_match = True
        if has_match:
            return None
        # 全部不匹配 → 矛盾
        for a in nums_a:
            for b in nums_b:
                if NumericConflictChecker._nums_conflict(a, b):
                    return ("contradicted", 0.88)
        return None

    @staticmethod
    def _nums_conflict(a: float, b: float) -> bool:
        try:
            return abs(a - b) / max(abs(b), 1) > 0.08
        except (ValueError, ZeroDivisionError):
            return False


@checker
class OverlapChecker(Checker):
    weight = 0.55  # F1 ≈ 0.75
    """检查: 字符重叠 > 55% 且无否定/数字/实体冲突 → 验证通过"""

    _CN_UNIT = {'万': 10000, '亿': 100000000, '千': 1000, '百': 100}

    @classmethod
    def _parse_num(cls, s: str) -> float:
        """解析带中文单位的数字"""
        m = re.match(r'([\d]+(?:\.\d+)?)\s*([万亿千百])?', s)
        if not m:
            return None
        val = float(m.group(1))
        unit = m.group(2)
        if unit and unit in cls._CN_UNIT:
            val *= cls._CN_UNIT[unit]
        return val

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """执行检查，返回 (verdict, confidence) 或 None"""
        if re.search(r'不是|没有|并非|不在|更早|错误|误会', claim):
            return None
        if re.search(r'不是|没有|并非|不在|更早|错误|误会', fact):
            return None
        # 比较级否定守卫：claim声称"比不上/不如"时，不与任何事实验证通过
        if re.search(r'比不上|不如|不及|比不过', claim):
            return None
        # 数值冲突守卫：解析中文数字后比较，差异>8%则可能是矛盾
        cn_raw = re.findall(r'[\d.]+(?:万|亿|千|百)?', claim)
        fn_raw = re.findall(r'[\d.]+(?:万|亿|千|百)?', fact)
        if cn_raw and fn_raw:
            cn_parsed = [v for v in (self._parse_num(s) for s in cn_raw) if v is not None]
            fn_parsed = [v for v in (self._parse_num(s) for s in fn_raw) if v is not None]
            if cn_parsed and fn_parsed:
                # 检查是否有显著的数值差异
                for a in cn_parsed:
                    for b in fn_parsed:
                        if abs(a - b) / max(abs(b), 1) > 0.08:
                            return None  # 数值冲突，不验证
        # 实体冲突守卫：双方提到不同专名实体 → 不验证
        cn_entities = set(re.findall(r'[金木水火土天王海王冥王]?星|月球|太阳|地球|Python|Java|Go|Rust|C\+\+', claim))
        fn_entities = set(re.findall(r'[金木水火土天王海王冥王]?星|月球|太阳|地球|Python|Java|Go|Rust|C\+\+', fact))
        if cn_entities and fn_entities and cn_entities != fn_entities:
            return None
        # 人名冲突守卫：双方提到不同的人名实体 → 不验证
        cn_persons = set(re.findall(r'([一-鿿]{2,3})(?:是|发明|建立|提出|发现|创作|发表|获得)', claim))
        fn_persons = set(re.findall(r'([一-鿿]{2,3})(?:是|发明|建立|提出|发现|创作|发表|获得)', fact))
        if cn_persons and fn_persons and cn_persons != fn_persons:
            return None
        # 归属性人名冲突：claim说"X是Y"但事实说"Z是Y" → X≠Z → 矛盾
        cn_person_attr = set(re.findall(r'([一-鿿]{2,4})是([一-鿿]{2,8})', claim))
        fn_person_attr = set(re.findall(r'([一-鿿]{2,4})是([一-鿿]{2,8})', fact))
        if cn_person_attr and fn_person_attr:
            for cp, ca in cn_person_attr:
                for fp, fa in fn_person_attr:
                    # 同一属性（含前缀匹配）不同归属 → 不验证
                    if (ca.startswith(fa) or fa.startswith(ca)) and cp != fp:
                        return None
        # 最高级/比较级冲突守卫：claim说"比不上/不如/不到"但KB说"最" → 不验证
        if re.search(r'比不上|不如|不到|没有.{0,3}[高长大多快]', claim):
            # 检查KB事实是否包含反证（如"最"、"第一"、精确数值）
            if re.search(r'最[高长大多]|第一|唯一|最高峰', fact):
                return None
            # 检查是否有"不到X"但KB数值>X的情况
            under_match = re.search(r'不到\s*([\d.]+(?:万|亿|千|百)?)', claim)
            if under_match:
                val_s = under_match.group(1)
                val = self._parse_num(val_s) if hasattr(self, '_parse_num') else None
                if val is not None:
                    f_nums = re.findall(r'[\d.]+(?:万|亿|千|百)?', fact)
                    for fn in f_nums:
                        f_val = self._parse_num(fn)
                        if f_val is not None and f_val > val:
                            return None  # KB数值>声称上限 → 矛盾
        cs, fs = set(claim), set(fact)
        ratio = len(cs & fs) / max(len(cs), 1)
        if len(claim) < 4 and ratio > 0.7:
            return None
        if ratio > 0.55:
            return ("verified", 0.7)
        return None


@checker
class TemporalOrderChecker(Checker):
    weight = 0.80  # F1 ≈ 0.84
    """检查: 时间顺序矛盾 — 将人物/事件放在错误朝代 → 矛盾"""
    ERA_MAP = {
        "秦": (-221, -207), "汉": (-202, 220), "三国": (220, 280),
        "唐": (618, 907), "宋": (960, 1279), "元": (1271, 1368),
        "明": (1368, 1644), "清": (1644, 1912),
    }
    PERSON_ERA = {
        "蔡伦": "汉", "张衡": "汉", "诸葛亮": "三国", "曹操": "三国",
        "李白": "唐", "杜甫": "唐", "苏轼": "宋", "毕昇": "宋",
        "岳飞": "宋", "成吉思汗": "元", "忽必烈": "元",
        "朱元璋": "明", "郑和": "明", "康熙": "清", "乾隆": "清",
        "林则徐": "清", "詹纳": "清",
    }
    _ERA_FALSE_WORDS = {
        "明": ["发明", "说明", "证明", "聪明", "明确", "表明", "声明"],
        "元": ["状元", "元素", "公元", "日元", "单元"],
        "清": ["清楚", "清洁", "清单", "分清", "清晰"],
        "唐": ["荒唐"],
        "汉": ["好汉", "汉字", "汉语", "男子汉", "懒汉"],
        "宋": [], "秦": [], "三国": [],
    }

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """执行检查，返回 (verdict, confidence) 或 None"""
        comparison_pattern = re.compile(
            r'不对|不是|远比|比.{0,3}早|比.{0,3}晚|早在|远早于|'
            r'之前|之后|而非|早于|晚于|predates|before'
        )
        has_comparison = bool(comparison_pattern.search(claim))
        if re.search(r'[吗呢吧啊]', claim):
            return None
        for person, era in self.PERSON_ERA.items():
            if person not in claim:
                continue
            person_start = self.ERA_MAP[era][0]
            for era_name, (era_start, _) in self.ERA_MAP.items():
                if era_name not in claim:
                    continue
                if era_name == era:
                    continue
                # 朝代名在人名中 → 检查是否在claim中独立出现
                if era_name in person and era_name != person:
                    # 去除人名后检查claim是否仍有该朝代名
                    claim_no_person = claim.replace(person, '')
                    if era_name not in claim_no_person:
                        continue
                if len(era_name) == 1:
                    false_words = self._ERA_FALSE_WORDS.get(era_name, [])
                    if any(fw in claim for fw in false_words):
                        continue
                if has_comparison and era_start < person_start:
                    continue
                return ("contradicted", 0.88)
        return None


@checker
class LocationConflictChecker(Checker):
    weight = 0.85  # F1 ≈ 0.77
    """检查: 地点归属矛盾 — 地标放错位置 → 矛盾"""
    LOC_MAP = {
        "长城": ["北京", "河北", "甘肃", "山西", "中国", "北方"],
        "故宫": ["北京", "中国"],
        "兵马俑": ["西安", "陕西", "中国"],
        "富士山": ["日本"],
        "金字塔": ["埃及", "开罗"],
        "埃菲尔铁塔": ["法国", "巴黎"],
        "自由女神像": ["美国", "纽约"],
        "大本钟": ["英国", "伦敦"],
        "泰姬陵": ["印度"],
        "悉尼歌剧院": ["澳大利亚", "悉尼"],
        "大峡谷": ["美国", "亚利桑那"],
    }
    ALL_PLACES = [
        "北京", "上海", "广州", "深圳", "成都", "重庆", "武汉", "南京", "杭州", "西安",
        "四川", "云南", "西藏", "新疆", "河南", "河北",
        "日本", "韩国", "朝鲜", "泰国", "越南", "印度", "俄罗斯",
        "美国", "英国", "法国", "德国", "意大利", "西班牙", "巴西", "澳大利亚",
        "埃及", "南非",
        "纽约", "伦敦", "巴黎", "东京", "柏林", "罗马", "悉尼", "开罗", "莫斯科",
        "中国", "非洲", "欧洲", "亚洲", "南美", "南极", "月球",
    ]

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """执行检查，返回 (verdict, confidence) 或 None"""
        for landmark, correct_locs in self.LOC_MAP.items():
            if landmark in claim:
                for place in self.ALL_PLACES:
                    if place in claim and place not in correct_locs:
                        return ("contradicted", 0.85)
        return None


@checker
class SuperlativeChecker(Checker):
    """绝对化断言检测 — 声称最大/最早/唯一/第一 vs 事实反驳 → 矛盾"""
    weight = 0.72  # 中等可靠：绝对化词语常有例外

    _SUPERLATIVE_PATTERNS = [
        (r'(?:是|为|成为).{0,6}(?:最大|最高|最长|最重|最快|最强)', '最大/最高类'),
        (r'(?:是|为|成为).{0,6}(?:最早|最先|首个|第一个)', '最早/首个类'),
        (r'(?:是|为).{0,4}(?:唯一|仅有|独一无二)', '唯一类'),
        (r'(?:世界|全球|史上|历史).{0,4}(?:第一|首位)', '世界第一类'),
        (r'(?:最好|最佳|最优|最棒)', '最好/最佳类'),
    ]

    _FACT_CONTRADICTION_PATTERNS = [
        r'(?:不是|并非|没有).{0,6}(?:最大|最高|最早|唯一|第一|最好|最)',
        r'(?:还有|另有|也存在).{0,6}(?:更|比较|其他|别的|另外)',
        r'(?:更早|更早|之前).{0,4}(?:已有|存在|出现|发明|发现)',
        r'(?:不是|并非).{0,4}(?:唯一|仅有)',
        r'(?:并非|实际上|其实).{0,6}(?:最早|最好|最大)',
    ]

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """检测绝对化声称与事实的矛盾"""
        # 声明必须包含绝对化词语
        has_superlative = False
        for pat, _ in self._SUPERLATIVE_PATTERNS:
            if re.search(pat, claim):
                has_superlative = True
                break
        if not has_superlative:
            return None

        # 事实必须包含反驳模式
        for pat in self._FACT_CONTRADICTION_PATTERNS:
            if re.search(pat, fact):
                return ("contradicted", 0.78)
        return None


@checker
class CausalChecker(Checker):
    """因果推断检测 — 声称X导致/引起Y vs 事实反驳 → 矛盾"""
    weight = 0.76  # 中高可靠：因果关系检测较精确

    _CAUSAL_CLAIM_PATTERNS = [
        r'(?:导致|引起|造成|引发|诱发)',
        r'(?:因为|由于).{0,10}(?:所以|因此|因而|于是)',
        r'.{2,15}(?:所以|因此|因而|于是)',  # 隐式因果: A所以B
        r'(?:源于|来源于|来自于)',
        r'(?:致使|使得|令)',
    ]

    _CAUSAL_FACT_PATTERNS = [
        r'(?:不会|不能|并非|不是).{0,6}(?:导致|引起|造成|引发)',
        r'(?:与.{0,8}无关|无直接关系|没有直接关系|没有关系|关系不大|不相关)',
        r'(?:实际上|其实|真正).{0,6}(?:是因为|原因|由于)',
        r'(?:并非|不是).{0,4}(?:源于|因为)',
    ]

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """检测因果声称与事实的矛盾"""
        has_causal = False
        for pat in self._CAUSAL_CLAIM_PATTERNS:
            if re.search(pat, claim):
                has_causal = True
                break
        if not has_causal:
            return None
        for pat in self._CAUSAL_FACT_PATTERNS:
            if re.search(pat, fact):
                return ("contradicted", 0.80)
        return None


@checker
class AttributionChecker(Checker):
    """归因检测 — 声称X发明/发现/创造了Y vs 事实反驳 → 矛盾"""
    weight = 0.80  # 中高可靠：归因检测在历史/科技领域效果好

    _ATTRIBUTION_CLAIM_PATTERNS = [
        (r'(?:发明了?|创造了?|创建了?|创始)', '发明/创造'),
        (r'(?:发现了?|找到了?)', '发现'),
        (r'(?:提出了?|创立了?|建立了?)', '提出/创立'),
        (r'(?:设计了?|开发了?|编写了?)', '设计/开发'),
        (r'(?:创始人是?|发明者是?|创造者是?|作者是?)', '归因声明'),
    ]

    _ATTRIBUTION_FACT_PATTERNS = [
        r'(?:不是|并非|没有).{0,6}(?:发明|创造|创建|发现)',
        r'(?:更早|之前|此前).{0,4}(?:已有|发明|发现|出现)',
        r'(?:才是|方是|正是).{0,4}(?:发明|创造|发现|提出)',
        r'(?:并非|不是).{0,4}(?:.{0,2})?(?:发明|创造|发现|提出)',
        r'(?:真正的.{0,2})?(?:发明者|创造者|发现者).{0,4}(?:是|为)',
        # 替代归因模式：KB给出了不同的创造者/发明者 → 矛盾
        r'(?:由|是)\s*.+?(?:发明|创造|创建|提出|设计|开发|发布|首次)', 
    ]

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """检测归因声称与事实的矛盾"""
        has_attribution = False
        for pat, _ in self._ATTRIBUTION_CLAIM_PATTERNS:
            if re.search(pat, claim):
                has_attribution = True
                break
        if not has_attribution:
            return None

        # ⚠️ 关键: 如果 claim 本身带有否定（"并没有发明"、"不是发明者"等）
        # → claim 和 fact 立场一致，不判矛盾
        _CLAIM_NEG_ATTRIB = re.compile(
            r'(?:并没有|没有|不是|并非|不存在).{0,4}(?:发明|创造|创建|发现|提出|设计|开发|创始)')
        if _CLAIM_NEG_ATTRIB.search(claim):
            return None

        for pat in self._ATTRIBUTION_FACT_PATTERNS:
            if re.search(pat, fact):
                # 替代归因模式需额外验证：fact中的归因主体 ≠ claim中的归因主体
                if '由' in pat or '是.{0,8}' in pat:
                    # 提取claim和fact中的主体名称
                    claim_subj = re.findall(r'(?:创始人是?|发明者是?|创造者是?|作者是?)([一-鿿\w\s]+?)(?:[，。、]|$)', claim)
                    fact_subj = re.findall(r'(?:由|是)\s*([一-鿿\w\s]+?)\s*(?:于|在|发明|创造|首次|设计)', fact)
                    if not claim_subj or not fact_subj:
                        return ("contradicted", 0.78)
                    # 如果主体名称不同 → 确认为矛盾
                    claim_name = claim_subj[0].strip()
                    fact_name = fact_subj[0].strip()
                    if claim_name.lower() != fact_name.lower():
                        return ("contradicted", 0.82)
                    return None
                # TF-IDF 加权语义重合: 防止跨主题误匹配（如大脑→足球）
                # 客体一致性检查: 确保声称的发明物 ≈ KB否定的发明物
                # 例: "爱因斯坦提出相对论" vs "爱因斯坦不是原子弹发明者" → 不矛盾
                claim_obj = re.findall(
                    r'(?:发明了?|创造了?|发现了?|提出了?|创立了?|设计了?|开发了?)(.{1,10}?)(?:[，。、；的]|$)',
                    claim
                )
                fact_obj = re.findall(
                    r'(?:不是|并非|没有)(?:.{0,4})(?:发明|创造|发现|提出)(?:者|了?)(.{1,10}?)(?:[，。、；的—]|$)',
                    fact
                )
                if claim_obj and fact_obj:
                    # 有客体信息 → 必须匹配才判矛盾
                    c_obj = claim_obj[0].strip()
                    f_obj = fact_obj[0].strip()
                    # 任一包含另一或高重叠 → 同一客体
                    if c_obj in f_obj or f_obj in c_obj:
                        return ("contradicted", 0.82)
                    # 否则：不同客体 → 不矛盾
                    return None
                if _semantic_overlap(claim, fact):
                    return ("contradicted", 0.82)
                return None
        return None


@checker
class EntitySwapChecker(Checker):
    """实体归属交换检测 — 声明X属于/是Y vs KB说X属于/是Z → 矛盾"""
    weight = 0.82

    # 归属关系模式
    _BELONG_PATTERNS = [
        r'([一-鿿]{2,5})(?:是|属于|位于)([一-鿿]{2,8})(?:的|之)(?:一[种个]|创始人|发明家|发源地|开国|卫星|行星|国家|地区|语言)',
        r'([一-鿿]{2,5})(?:是|属于|位于)([一-鿿]{2,6})(?:的|之)?(?:首都|首任|创建者|发明者|创始人|奠基人|开国)',
        r'([一-鿿]{2,5})(?:发明|建立|创建|创立|提出)(?:了)?([一-鿿]{2,8})',
    ]

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """检测实体归属交换"""
        def _extract_pairs(text):
            pairs = []
            for pat in self._BELONG_PATTERNS:
                for m in re.finditer(pat, text):
                    subj, attr = m.group(1), m.group(2)
                    if subj and attr and subj != attr:
                        pairs.append((subj, attr))
            return pairs

        claim_pairs = _extract_pairs(claim)
        fact_pairs = _extract_pairs(fact)

        if not claim_pairs:
            return None

        if not fact_pairs:
            # 回退：检查否定模式"不是/并非"
            for subj, attr in claim_pairs:
                neg_pat = rf'{subj}.*?(?:不是|并非|不在).*?{attr}'
                if re.search(neg_pat, fact):
                    return ("contradicted", 0.85)
            return None

        # 交叉比对：同一主体的不同归属 → 矛盾
        for c_subj, c_attr in claim_pairs:
            for f_subj, f_attr in fact_pairs:
                if c_subj == f_subj and c_attr != f_attr:
                    # 共享文本占比高 → 同一主题不同表述，非矛盾
                    shared = len(set(c_attr) & set(f_attr)) / max(len(set(c_attr) | set(f_attr)), 1)
                    if shared > 0.4:
                        continue
                    return ("contradicted", 0.85)
        return None


@checker
class ComparativeChecker(Checker):
    """比较级语义检测 — 「不到X」「比不上Y」「不如Z」vs KB事实 → 矛盾"""
    weight = 0.86

    # 中文数字单位
    _CN_UNIT = {'万': 10000, '亿': 100000000, '千': 1000, '百': 100}

    @classmethod
    def _parse_cn_num(cls, s: str) -> float:
        """解析带中文单位的数字"""
        m = re.match(r'([\d]+(?:\.\d+)?)\s*([万亿千百])?', s)
        if not m:
            return None
        val = float(m.group(1))
        unit = m.group(2)
        if unit and unit in cls._CN_UNIT:
            val *= cls._CN_UNIT[unit]
        return val

    # 上限模式：不到/不足/低于/少于 X
    _UPPER_BOUND = re.compile(r'(?:不到|不足|低于|少于|不超过|小于)\s*([\d.]+(?:万|亿|千|百)?)')

    # 下限模式：超过/高于/大于 X
    _LOWER_BOUND = re.compile(r'(?:超过|高于|大于|不止|不低于|不小于)\s*([\d.]+(?:万|亿|千|百)?)')

    # 比较级否定：比不上/不如/不及/比不过
    _COMPARE_NEG = re.compile(r'比不上|不如|不及|比不过|比.{0,2}(?:差|低|矮|短|少)(?!得多)')

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """检测比较级声称与KB事实的数值矛盾"""
        # 1. 上限模式：「不到8800米」vs KB「8848米」→ 8848 > 8800 → 矛盾
        m = self._UPPER_BOUND.search(claim)
        if m:
            bound = self._parse_cn_num(m.group(1))
            if bound is not None:
                f_nums = re.findall(r'[\d.]+(?:万|亿|千|百)?', fact)
                for fn in f_nums:
                    f_val = self._parse_cn_num(fn)
                    if f_val is not None and f_val > bound:
                        return ("contradicted", 0.86)
        # 2. 下限模式：「超过9000米」vs KB「8848米」→ 8848 < 9000 → 可能矛盾
        m = self._LOWER_BOUND.search(claim)
        if m:
            bound = self._parse_cn_num(m.group(1))
            if bound is not None:
                f_nums = re.findall(r'[\d.]+(?:万|亿|千|百)?', fact)
                for fn in f_nums:
                    f_val = self._parse_cn_num(fn)
                    if f_val is not None and f_val < bound:
                        return ("contradicted", 0.84)
        # 3. 比较级否定 + 最高级/唯一性 KB → 矛盾
        # 「比不上乔戈里峰」vs KB「是世界最高峰」→ 矛盾
        if self._COMPARE_NEG.search(claim):
            # ⚠️ 必须验证：fact中的最高级/唯一性 与 claim比较的实体相关
            # 例如 "月球比地球小" + "珠穆朗玛峰是世界最高峰" → 无关，不矛盾
            if re.search(r'最[高长大多宽深]|第一|唯一|最高峰|最大', fact):
                # 提取claim中比较主体（"比不上X"中的X, 或"比Y小"中的Y）
                claim_subj = re.findall(r'(?:比不上|不如|不及|比)\s*([一-鿿\w]{1,6}?)(?:[，。、的]|差|低|小|矮|短|少|$)', claim)
                if claim_subj:
                    # fact 中是否提到了比较主体？
                    if any(s in fact for s in claim_subj if len(s) >= 1):
                        return ("contradicted", 0.88)
                    return None  # fact不涉及比较主体 → 不矛盾
                return ("contradicted", 0.88)
            # 「比不上乔戈里峰」vs KB「海拔8848米」(乔戈里8611米) → KB数值暗示最高
            if re.search(r'海拔|高度|长度|深度|宽度|世界.{0,3}(?:之|第)', fact):
                return ("contradicted", 0.82)
        return None


@checker
class DurationChecker(Checker):
    """持续时间检测 — 声称持续X年 vs KB推算实际时长 → 矛盾"""
    weight = 0.85

    # 持续时间模式
    _DURATION_PATTERNS = [
        (r'(?:持续了?|历时|延续了?|存在了?)(?:将近|大约|约|近)?(\d+)年', 'duration'),
        (r'(?:只有?|才|仅仅)(?:将近|大约|约)?(\d+)年', 'short_duration'),
        (r'(?:长达|超过)(\d+)年', 'long_duration'),
    ]

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """从claim提取声称时长，从fact推算实际时长并对比"""
        import re as _re
        # 0. 规范化中文数字 (三百→300)
        cn_map = {'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'百':100,'千':1000,'万':10000}
        def cn2int(s):
            r, c = 0, 0
            for ch in s:
                if ch in cn_map:
                    v = cn_map[ch]
                    if v >= 10: c = max(c,1)*v; r += c; c = 0
                    else: c = v
            return r + c if r + c > 0 else None
        normed_claim = _re.sub(r'[零一二两三四五六七八九十百千万]+', lambda m: str(cn2int(m.group()) or m.group()), claim)
        # 1. 从claim提取声称的持续时间
        claimed_years = None
        for pat, _ in self._DURATION_PATTERNS:
            m = _re.search(pat, normed_claim)
            if m:
                claimed_years = int(m.group(1))
                break
        if claimed_years is None:
            return None

        # 2. 从fact + KB全量事实中提取年份，计算实际时长
        all_years_text = fact
        if engine and hasattr(engine, '_get_kb_years_for_entity'):
            # 尝试获取同一实体的所有KB事实中的年份
            kb_years = engine._get_kb_years_for_entity(claim)
            if kb_years:
                all_years_text = fact + ' ' + ' '.join(kb_years)
        
        years = _re.findall(r'(\d{3,4})', all_years_text)
        if len(years) < 2:
            return None
        
        # 取最小和最大年份作为时间范围
        nums = sorted(int(y) for y in years)
        actual_duration = nums[-1] - nums[0]
        
        # 3. 对比：偏差>50%且实际<声称 → 矛盾
        if actual_duration <= 0:
            return None
        if claimed_years > actual_duration * 1.5:
            return ("contradicted", 0.82)
        
        return None


@checker
class GraphContradictionChecker(Checker):
    weight = 0.78  # F1 ≈ 0.87
    """检查: 知识图谱实体关系推理 → 矛盾（最后兜底检查器）"""
    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """执行检查，返回 (verdict, confidence) 或 None"""
        if engine is None:
            return None
        # 叙事上下文: claim在讲"故事/传说"而非直接断言 → 跳过图谱推理
        if re.search(r'(?:的故事|的传说|的说法|的迷思)', claim):
            return None
        reasoner = engine._get_graph_reasoner()
        if reasoner is None:
            return None
        # 保护: claim与fact高度相关时不触发图推理
        # 避免"北宋毕昇发明活字印刷术"被同条目下的"北宋存在于960年"误判
        c_set = set(claim)
        f_set = set(fact)
        if c_set and f_set:
            overlap = len(c_set & f_set) / max(len(c_set), len(f_set))
            if overlap > 0.5:
                return None  # 高度相关 → 不应该判矛盾
        result = reasoner.infer_contradiction(claim)
        if result and result.get("verdict") == "contradicted":
            return ("contradicted", result.get("confidence", 0.75))
        return None


@checker

@checker
class RetrievalAugmentedChecker(Checker):
    """检查: 多事实检索增强校验 — 从知识库检索多条相关事实聚合判决

    Truth Router 集成: 当单个 fact 比对无明确结论时，
    利用检索管线从 kb_core + fact_store.db 找多条相关事实交叉验证。
    直接调用 retrieval 模块，通过 _in_check 守卫避免递归。
    """
    weight = 0.82
    _last_checks = []
    _in_check = False  # 递归守卫

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        """标准检查器链中为 no-op，通过 AnchorEngine.retrieval_augmented_verify() 显式触发检索增强"""
        return None


@checker
class MythChecker(Checker):
    """检查: 事实中含有'传说/迷思/误解/存疑'等语境标记 — 说明该断言是虚构/存疑的

    当 KB 事实将 claim 描述为传说、虚构或误解时，
    说明该断言并非真实事实，应判为矛盾。
    例如: '斯巴达人把婴儿扔下悬崖的故事是一个历史传说' → contradicted
    """
    weight = 0.80

    # 常见语境标记：事实在用否定/存疑的语气描述该断言
    _MYTH_PATTERNS = [
        re.compile(r'是.*(?:一个)?(?:历史)?(传说|迷思|神话|谣言|虚构的故事)'),
        re.compile(r'是一个(?:流行的)?误解'),
        re.compile(r'对此存疑'),
        re.compile(r'(?:实际上|事实上|真实历史中).{0,10}(?:没有|不是|并非)'),
    ]

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        # 检查事实文本是否在描述该断言为传说/虚构
        for pat in self._MYTH_PATTERNS:
            m = pat.search(fact)
            if m:
                # 验证事实确实在说同一个话题
                # 中文用字符二元组（CJK无空格）
                def _bigrams(s):
                    return {s[i:i+2] for i in range(len(s)-1) if all(ord(c)>=0x4e00 for c in s[i:i+2])}
                claim_bg = _bigrams(claim)
                fact_bg = _bigrams(fact)
                shared = claim_bg & fact_bg
                # 至少共享3个二元组且共享比例>15%才认为是同一话题
                if len(shared) >= 3 and len(shared) / max(len(claim_bg | fact_bg), 1) > 0.15:
                    return ("contradicted", 0.80)
        return None
