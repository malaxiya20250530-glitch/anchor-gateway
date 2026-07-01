#!/usr/bin/env python3
"""逻辑推理幻觉检测器 v2 — 精准断言验证 + 多 Sector 支持

用法:
  from logic_verifier import LogicAbyss, verify_reasoning_text
  
  abyss = LogicAbyss.build_sector1()
  report = verify_reasoning_text(abyss, deepseek_response)
  for h in report.hallucinations:
      print(f"逻辑幻觉: {h.assertion} → {h.reason}")
"""

import re
from typing import Optional
from itertools import product
from dataclasses import dataclass, field


# ===== 数据结构 =====

@dataclass
class VerificationResult:
    """一条断言验证的结果"""
    assertion: str       # 原始断言文本
    core: int           # 核心编号
    claimed_value: int   # DeepSeek 声称的值
    is_assumption: bool  # 是否是假设（假设的不算逻辑错误）
    is_correct: Optional[bool] = None  # True=必然成立, False=不是必然, None=无法验证
    explanation: str = ""
    
    @property
    def is_hallucination(self) -> bool:
        """是否属于逻辑幻觉"""
        return not self.is_assumption and self.is_correct is False


@dataclass
class VerificationReport:
    """一次推理文本的完整验证报告"""
    results: list[VerificationResult] = field(default_factory=list)
    total_assertions: int = 0
    hallucinations: list[VerificationResult] = field(default_factory=list)
    correct_assertions: int = 0
    assumptions: int = 0
    
    def add(self, r: VerificationResult):
        self.results.append(r)
        self.total_assertions += 1
        if r.is_assumption:
            self.assumptions += 1
        elif r.is_correct is True:
            self.correct_assertions += 1
        elif r.is_correct is False:
            self.hallucinations.append(r)
    
    def summary(self) -> str:
        lines = [f"断言总数: {self.total_assertions}"]
        lines.append(f"  假设: {self.assumptions}")
        lines.append(f"  必然结论: {self.correct_assertions}")
        lines.append(f"  逻辑幻觉❌: {len(self.hallucinations)}")
        if self.hallucinations:
            lines.append("")
            for h in self.hallucinations[:10]:
                lines.append(f"  ❌ C{h.core}应该为{h.claimed_value} → {h.explanation[:70]}")
            if len(self.hallucinations) > 10:
                lines.append(f"  ... 还有 {len(self.hallucinations)-10} 个")
        return "\n".join(lines)


# ===== 规则引擎 =====

class LogicAbyss:
    """逻辑深渊求解器"""
    
    def __init__(self, num_cores: int = 20):
        self.N = num_cores
        self.rules: list[tuple[str, callable, str]] = []
        self._solutions: Optional[list[list[int]]] = None
    
    def add_rule(self, name: str, check_fn: callable, desc: str = ""):
        self.rules.append((name, check_fn, desc))
        self._solutions = None
    
    def solve(self) -> list[list[int]]:
        if self._solutions is not None:
            return self._solutions
        sols = []
        for bits in product([0, 1], repeat=self.N):
            c = [0] + list(bits)
            if all(fn(c) for _, fn, _ in self.rules):
                sols.append(c[1:])
        self._solutions = sols
        return sols
    
    def core_stats(self) -> dict[int, dict]:
        """每个核心的统计: 1的比例"""
        sols = self.solve()
        if not sols:
            return {}
        stats = {}
        for i in range(1, self.N + 1):
            ones = sum(1 for s in sols if s[i-1] == 1)
            stats[i] = {"1": ones, "0": len(sols) - ones, "total": len(sols),
                        "always1": ones == len(sols),
                        "always0": ones == 0,
                        "free": 0 < ones < len(sols)}
        return stats
    
    def verify_assertion(self, assertion: str, is_assumption: bool = False) -> Optional[VerificationResult]:
        """验证一条推理断言"""
        # 只匹配 "必然结论" 格式：因此/所以/则/必须/得出/可知 CX为Y
        conclusion_m = re.search(r'(?:因此|所以|则|得出|可知|必须|必定|一定|即)\D*C(\d+).{0,4}[为=是](\d)', assertion)
        # 假设格式
        assumption_m = re.search(r'(?:假设|假定|设|如果.*则)\D*C(\d+).{0,4}[为=](\d)', assertion)
        
        if conclusion_m:
            core, val = int(conclusion_m.group(1)), int(conclusion_m.group(2))
            return self._check_core_value(assertion, core, val, False)
        
        if assumption_m:
            core, val = int(assumption_m.group(1)), int(assumption_m.group(2))
            return self._check_core_value(assertion, core, val, True)
        
        return None
    
    def _check_core_value(self, text: str, core: int, val: int, is_assumption: bool) -> VerificationResult:
        """检查某个核心是否必然为某值"""
        if core < 1 or core > self.N:
            return VerificationResult(text, core, val, is_assumption, False, f"C{core}超出范围")
        
        sols = self.solve()
        if not sols:
            return VerificationResult(text, core, val, is_assumption, None, "无可行解")
        
        always = all(s[core-1] == val for s in sols)
        never = all(s[core-1] != val for s in sols)
        some = any(s[core-1] == val for s in sols)
        
        if always:
            return VerificationResult(text, core, val, is_assumption, True, f"C{core}={val} 在所有 {len(sols)} 个解中恒成立")
        elif never:
            return VerificationResult(text, core, val, is_assumption, False, f"C{core}={val} 在任何解中都不成立")
        else:
            ratio = sum(1 for s in sols if s[core-1]==val) / len(sols)
            return VerificationResult(text, core, val, is_assumption, False,
                f"C{core}={val} 只在 {ratio:.0%} 的解中成立（{sum(1 for s in sols if s[core-1]==val)}/{len(sols)}），并非必然")
    
    @staticmethod
    def build_sector1() -> "LogicAbyss":
        """Sector I: 核心互锁规则 (C1-C20)"""
        abyss = LogicAbyss(20)
        rules = [
            ("R1",  lambda c: c[9]==1 or c[2]!=c[5]),
            ("R2",  lambda c: not(c[3]==0) or (c[6]==1 and c[10]==0)),
            ("R3",  lambda c: (c[4]+c[7]+c[11])!=2),
            ("R4",  lambda c: not(c[5]==1) or (c[8]==0 and c[12]!=c[5])),
            ("R5",  lambda c: c[13]==1 or c[6]!=c[9]),
            ("R6",  lambda c: not(c[7]==0) or (c[10]==1 and c[14]==0)),
            ("R7",  lambda c: (c[8]+c[11]+c[15])!=2),
            ("R8",  lambda c: not(c[9]==1) or (c[12]==0 and c[16]!=c[9])),
            ("R9",  lambda c: c[17]==1 or c[10]!=c[13]),
            ("R10", lambda c: not(c[11]==0) or (c[14]==1 and c[18]==0)),
            ("R11", lambda c: (c[12]+c[15]+c[19])!=2),
            ("R12", lambda c: not(c[13]==1) or (c[16]==0 and c[20]!=c[13])),
            ("R13", lambda c: c[1]==1 or c[14]!=c[17]),
            ("R14", lambda c: not(c[15]==0) or (c[18]==1 and c[2]==0)),
            ("R15", lambda c: (c[16]+c[19]+c[3])!=2),
            ("R16", lambda c: not(c[17]==1) or (c[20]==0 and c[4]!=c[17])),
            ("R17", lambda c: c[5]==1 or c[18]!=c[1]),
            ("R18", lambda c: not(c[19]==0) or (c[2]==1 and c[6]==0)),
            ("R19", lambda c: (c[20]+c[3]+c[7])!=2),
            ("R20", lambda c: not(c[1]==1) or (c[4]==0 and c[8]!=c[1])),
        ]
        for name, fn in rules:
            abyss.add_rule(name, fn)
        return abyss
    
    @staticmethod
    def build_sector2() -> "LogicAbyss":
        """Sector II: 全局计数规则 (规则41-60)"""
        abyss = LogicAbyss(20)
        rules = [
            # R41: 若 C2=1，则奇数索引C中1的总数 > 偶数索引C中1的总数
            ("R41", lambda c: not(c[2]==1) or sum(c[1:21:2]) > sum(c[2:21:2])),
            # R42: 整个网络中状态为0的总数 = 某核心索引值的2倍（若该核心为1）
            # 这个太抽象，先简化
            # R43: C14+C16+C18 的状态代数和 = C4
            ("R43", lambda c: (c[14]+c[16]+c[18]) in (0, 3) or (c[14]+c[16]+c[18]) == c[4]),
            ("R43b", lambda c: (c[14]+c[16]+c[18]) != 1 or c[4]==1),
            ("R43c", lambda c: (c[14]+c[16]+c[18]) != 2 or c[4]==0),
            # R44: C15..C20 中1的总数为偶数
            ("R44", lambda c: sum(c[15:21]) % 2 == 0),
            # R45: 若 C6=1，则奇数>偶数
            ("R45", lambda c: not(c[6]==1) or sum(c[1:21:2]) > sum(c[2:21:2])),
            # R47: C3+C5+C7 的代数和 = C8
            ("R47", lambda c: (c[3]+c[5]+c[7]) in (0,3) or (c[3]+c[5]+c[7]) == c[8]),
            ("R47b", lambda c: (c[3]+c[5]+c[7]) != 1 or c[8]==1),
            ("R47c", lambda c: (c[3]+c[5]+c[7]) != 2 or c[8]==0),
            # R48: C4..C9 中1的总数为偶数
            ("R48", lambda c: sum(c[4:10]) % 2 == 0),
        ]
        for name, fn in rules:
            abyss.add_rule(name, fn)
        return abyss


def verify_reasoning_text(abyss: LogicAbyss, text: str) -> VerificationReport:
    """验证一段完整的推理文本"""
    report = VerificationReport()
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 找出所有 "CX为Y" / "C=Y" / "因此CX=Y" 模式
        # 先按标点分段
        segments = re.split(r'[，。；！？\n]', line)
        for seg in segments:
            seg = seg.strip()
            if not seg or len(seg) < 3:
                continue
            
            result = abyss.verify_assertion(seg)
            if result:
                report.add(result)
    
    return report


# ===== 自测 =====
if __name__ == '__main__':
    print("=" * 60)
    print("  逻辑推理幻觉检测器 v2 — 自测")
    print("=" * 60)
    
    # 测试 Sector I
    abyss = LogicAbyss.build_sector1()
    sols = abyss.solve()
    print(f"\nSector I: {len(sols)} 个可行解")
    
    # 测试 Sector I + II
    abyss2 = LogicAbyss.build_sector1()
    for name, fn, _ in LogicAbyss.build_sector2().rules:
        abyss2.add_rule(name, fn)
    sols2 = abyss2.solve()
    print(f"Sector I+II: {len(sols2)} 个可行解")
    
    # 测试断言验证
    print("\n断言验证:")
    for assert_text, is_hallu in [
        ("因此C2=1", True),        # C2并不恒为1
        ("假设C1=0", False),       # 假设不算
        ("因此C3=0", None),        # 检查
        ("所以C7=1", None),
    ]:
        result = abyss.verify_assertion(assert_text)
        if result:
            status = "❌逻辑幻觉" if result.is_hallucination else "✅"
            print(f"  {status} {assert_text:20} → {result.explanation[:60]}")
    
    # 模拟 DeepSeek 的推理文本
    mock_reasoning = """我们先假设C1=0。因此C2=1。所以C3=0。
    则C6=1。因此C4=0。假设C5=1。所以C8=0。"""
    
    print("\n模拟推理验证:")
    report = verify_reasoning_text(abyss, mock_reasoning)
    print(report.summary())
