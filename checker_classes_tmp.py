# 修复 RetrievalAugmentedChecker - 直接用检索模块，不通过 engine.retrieval_check 避免递归
import re
from typing import Optional
from checker_registry import Checker, checker


@checker
class RetrievalAugmentedChecker(Checker):
    """检查: 多事实检索增强校验 — 从知识库检索多条相关事实聚合判决

    Truth Router 集成: 当单个 fact 比对无明确结论时，
    利用检索管线从 kb_core + fact_store.db 找多条相关事实交叉验证。
    填补了"单事实比对盲区"——有些幻觉需要多条事实对照才能发现。

    直接调用 retrieval 模块，避免通过 engine.retrieval_check 造成递归。
    """
    weight = 0.82
    _last_checks = []
    _in_check = False  # 递归守卫

    def check(self, claim: str, fact: str, engine=None) -> Optional[tuple]:
        if engine is None or RetrievalAugmentedChecker._in_check:
            return None

        # 快速跳过：claim 和 fact 高度重叠时不需要检索增强
        c_set = set(claim)
        f_set = set(fact)
        if c_set and f_set:
            overlap = len(c_set & f_set) / max(len(c_set), len(f_set))
            if overlap > 0.7:
                return None

        try:
            RetrievalAugmentedChecker._in_check = True

            from truth_router.retrieval import retrieve
            retrieval = retrieve(claim, max_results=5)

            facts = retrieval.get('facts', [])
            if not facts:
                return None

            contradicted_checks = []
            verified_checks = []

            for f in facts:
                # 跳过与输入 fact 相同的事实
                if f['fact'] == fact:
                    continue
                # 直接用引擎的基础比较（会再次遍历检查器链，但 _in_check=True 会跳过本检查器）
                v, c = engine._compare_with_fact(claim, f['fact'])
                if v == 'contradicted' and c > 0.5:
                    contradicted_checks.append(c)
                elif v == 'verified' and c > 0.5:
                    verified_checks.append(c)
                self._last_checks.append({
                    'fact': f['fact'][:60],
                    'verdict': v,
                    'confidence': round(c, 4),
                })

            if contradicted_checks:
                avg = sum(contradicted_checks) / len(contradicted_checks)
                return ("contradicted", min(avg * 0.9, 0.95))

            if len(verified_checks) >= 2:
                avg = sum(verified_checks) / len(verified_checks)
                return ("verified", min(avg * 0.85, 0.92))

        except Exception:
            pass
        finally:
            RetrievalAugmentedChecker._in_check = False

        return None
