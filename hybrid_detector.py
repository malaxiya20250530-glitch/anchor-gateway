#!/usr/bin/env python3
"""混合幻觉检测器 — 事实检测 + 逻辑推理检测 双引擎

架构:
  hybrid_detector.analyze(text)
    ├─ hallucination_detector (KB事实核查)
    │   ├─ KnowledgeBase → 事实矛盾
    │   └─ DeepSeek复核 → 置信度提升
    └─ logic_verifier (CSP逻辑验证)
        ├─ RuleSet → 推理断言验证
        └─ unsat_core → 规则自洽性
    
用法:
  from hybrid_detector import HybridDetector
  
  detector = HybridDetector()
  report = detector.analyze(llm_response)
  
  for h in report.factual_hallucinations:
      print(f"[事实] {h.claim}")
  for h in report.logic_hallucinations:
      print(f"[逻辑] C{h.core}应该为{h.claimed_value}")
"""

import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataclasses import dataclass, field
from typing import Optional


# ===== 统一报告格式 =====

@dataclass
class FactualHallucination:
    """事实性幻觉"""
    claim: str
    confidence: float
    evidence: str
    source: str

@dataclass
class LogicHallucination:
    """逻辑推理幻觉"""
    assertion: str
    core: int
    claimed_value: int
    actual_range: str
    explanation: str

@dataclass
class LogicInsight:
    """逻辑一致性洞察"""
    total_solutions: int
    deterministic_cores: int
    total_cores: int
    unsat: bool
    unsat_core_rules: list[str] = field(default_factory=list)

@dataclass
class HybridReport:
    input_text: str
    factual_hallucinations: list[FactualHallucination] = field(default_factory=list)
    logic_hallucinations: list[LogicHallucination] = field(default_factory=list)
    logic_insight: Optional[LogicInsight] = None
    
    @property
    def total_hallucinations(self) -> int:
        return len(self.factual_hallucinations) + len(self.logic_hallucinations)
    
    def summary(self) -> str:
        parts = []
        parts.append(f"{'='*60}")
        parts.append(f"  混合幻觉检测报告")
        parts.append(f"{'='*60}")
        parts.append(f"  输入长度: {len(self.input_text)} 字符")
        parts.append(f"")
        parts.append(f"  📖 事实幻觉: {len(self.factual_hallucinations)} 处")
        for h in self.factual_hallucinations[:5]:
            parts.append(f"    🔴 [{h.confidence:.0%}] {h.claim[:50]}...")
        if len(self.factual_hallucinations) > 5:
            parts.append(f"    ... 还有 {len(self.factual_hallucinations)-5} 处")
        parts.append(f"")
        parts.append(f"  🧠 逻辑幻觉: {len(self.logic_hallucinations)} 处")
        for h in self.logic_hallucinations[:10]:
            parts.append(f"    ❌ C{h.core}应该为{h.claimed_value} → {h.explanation[:50]}")
        if len(self.logic_hallucinations) > 10:
            parts.append(f"    ... 还有 {len(self.logic_hallucinations)-10} 处")
        parts.append(f"")
        if self.logic_insight:
            li = self.logic_insight
            parts.append(f"  📊 逻辑深渊状态:")
            if li.unsat:
                parts.append(f"     ❌ UNSAT — 规则集自相矛盾")
                if li.unsat_core_rules:
                    parts.append(f"     🎯 最小矛盾核: {' + '.join(li.unsat_core_rules)}")
            else:
                parts.append(f"     ✅ {li.total_solutions} 个可行解, {li.deterministic_cores}/{li.total_cores} 核恒为定值")
        parts.append(f"")
        parts.append(f"  🚨 总计: {self.total_hallucinations} 处幻觉")
        parts.append(f"{'='*60}")
        return "\n".join(parts)


class HybridDetector:
    """混合幻觉检测器 — 双引擎"""
    
    def __init__(self, enable_deepseek: bool = True, logic_abyss: str = "sector1"):
        self.enable_deepseek = enable_deepseek
        self.logic_abyss_mode = logic_abyss
        self._init_engines()
    
    def _init_engines(self):
        """初始化双引擎"""
        # 引擎 1: 事实检测器
        try:
            from hallucination_detector import HallucinationDetector
            self.fact_detector = HallucinationDetector(
                enable_deepseek=self.enable_deepseek)
        except Exception as e:
            print(f"⚠️ 事实检测器加载失败: {e}")
            self.fact_detector = None
        
        # 引擎 2: 逻辑验证器
        try:
            from logic_verifier import LogicAbyss, verify_reasoning_text
            self.logic_verifier = verify_reasoning_text
            if self.logic_abyss_mode == "sector1":
                self.abyss = LogicAbyss.build_sector1()
            elif self.logic_abyss_mode == "sector1_plus":
                self.abyss = LogicAbyss.build_sector1_plus()
            else:
                self.abyss = LogicAbyss.build_sector1()
        except Exception as e:
            print(f"⚠️ 逻辑验证器加载失败: {e}")
            self.logic_verifier = None
            self.abyss = None
    
    def analyze(self, text: str) -> HybridReport:
        """分析文本，检测事实和逻辑幻觉"""
        report = HybridReport(input_text=text)
        
        # 引擎 1: 事实检测
        if self.fact_detector:
            try:
                fact_result = self.fact_detector.analyze(text)
                for r in fact_result.results:
                    if r.verdict == 'contradicted':
                        report.factual_hallucinations.append(
                            FactualHallucination(
                                claim=r.claim,
                                confidence=r.confidence,
                                evidence=r.evidence,
                                source=r.source,
                            ))
            except Exception as e:
                print(f"⚠️ 事实检测失败: {e}")
        
        # 引擎 2: 逻辑验证
        if self.logic_verifier and self.abyss:
            try:
                logic_report = self.logic_verifier(self.abyss, text)
                for r in logic_report.hallucinations:
                    report.logic_hallucinations.append(
                        LogicHallucination(
                            assertion=r.assertion,
                            core=r.core,
                            claimed_value=r.claimed_value,
                            actual_range=r.explanation,
                            explanation=r.explanation,
                        ))
                
                # 逻辑洞察
                sols = self.abyss.solve()
                stats = self.abyss.core_stats()
                det_cores = sum(1 for s in stats.values() 
                               if s["always1"] or s["always0"])
                
                # UNSAT 检测
                unsat = len(sols) == 0
                unsat_core = []
                if unsat and hasattr(self, '_find_unsat_core'):
                    unsat_core = self._find_unsat_core()
                
                report.logic_insight = LogicInsight(
                    total_solutions=len(sols),
                    deterministic_cores=det_cores,
                    total_cores=self.abyss.N,
                    unsat=unsat,
                    unsat_core_rules=unsat_core,
                )
            except Exception as e:
                print(f"⚠️ 逻辑验证失败: {e}")
        
        return report


def demo():
    """演示: 用 DeepSeek 的推理文本来测试"""
    # 模拟一段包含逻辑幻觉的推理
    mock_reasoning = """
    根据20阶逻辑深渊的规则，我们开始推理。
    首先，由R1可知C2与C5状态相反。假设C9=0，则C2≠C5。
    由R2，若C3=0则C6=1且C10=0。
    通过R13，C14与C17相反除非C1=1。
    经过系统推导，因此C2=1。因此C3=0。因此C6=1。
    因此C10=1。因此C14=1。
    """
    
    detector = HybridDetector(enable_deepseek=False)
    report = detector.analyze(mock_reasoning)
    print(report.summary())


if __name__ == '__main__':
    demo()
