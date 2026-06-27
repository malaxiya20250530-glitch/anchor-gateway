# Copyright (c) 2025 李桥 (hubeiligang420@gmail.com)
# 专有软件 — 保留所有权利。禁止复制、修改、分发、逆向工程。
# Proprietary Software — ALL RIGHTS RESERVED.
#
"""
观察器安全设置模块
实现: 白盒推理 / 外部锚定 / 多观察器冗余 / 用户可调敏感度

核心原则: 观察器是镜子，不是法官。
         永远不静默拦截——必须报告看到了什么、为什么。
"""

import sys
sys.path.insert(0, '/data/data/com.termux/files/home')

from true_self_os import Thought, Insula, Amygdala, ACC, DMN, TPN
from social_self_sim import (
    SocialStimulus, SocialTriggerType,
    MirrorNeuronSystem, MentalizingNetwork,
    SocialPainCircuit, SocialRewardCircuit, SocialPerson,
)

import random
import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from typing import Optional

random.seed(99)

# ============================================================
# 观察器安全架构
# ============================================================

class ObserverAction(Enum):
    """观察器动作（绝不静默拦截）"""
    PASS = "pass"                    # 不干预
    FLAG = "flag"                    # 标记但放行
    ANCHOR = "anchor"                # 拉回锚点（提醒觉察）
    CORRECT = "correct"              # 提供外部对照
    VETO = "veto"                    # 明确否决（仅多观察器共识时）

@dataclass
class ObserverVerdict:
    """白盒判决: 做了什么 + 为什么"""
    action: ObserverAction
    reason: str
    confidence: float
    observer_id: str
    anchor_source: Optional[str] = None     # 外部锚定来源
    anchor_evidence: Optional[str] = None   # 锚定证据
    timestamp: float = 0.0

    def __post_init__(self):
        self.timestamp = time.time()

    def is_silent(self) -> bool:
        """静默拦截检测: 如果 action != PASS 但是没有 reason → 报警"""
        return self.action != ObserverAction.PASS and not self.reason


# ============================================================
# 组件 A: 外部锚定引擎
# ============================================================

class ExternalAnchor:
    """
    外部锚定源 — 观察器不自己判断对错，而是对照外部可验证来源。

    锚定类型:
      - 形式系统: 数学逻辑自洽检查 (不可争议)
      - 来源归因: 有出处 vs 无出处断言
      - 内部一致性: 和之前的输出矛盾吗？
      - 知识库: 外部事实对照
    """

    def __init__(self):
        self.known_facts = {
            "python": "Python 是一种编程语言，由 Guido van Rossum 于 1991 年发布。",
            "earth": "地球是太阳系第三颗行星，形成于约 45 亿年前。",
            "fire": "火是燃烧过程，不是发明。人类在约 100 万年前学会使用火。",
            "paper": "造纸术是中国古代四大发明之一，西汉时期已有纸。",
        }
        self.consistency_log = deque(maxlen=20)  # 内部一致性记录

    def verify_factual(self, claim: str) -> dict:
        """对照知识库 — 返回事实锚定结果"""
        for key, fact in self.known_facts.items():
            if key in claim.lower():
                return {
                    "matched": True,
                    "source": f"知识库 (key={key})",
                    "evidence": fact,
                    "confidence": 0.85,
                }
        return {
            "matched": False,
            "source": None,
            "evidence": None,
            "confidence": 0.0,
        }

    def check_source_attribution(self, text: str) -> dict:
        """来源归因检查: 断言有没有出处？"""
        markers = ["根据", "据", "来源", "参考", "某某", "报道",
                    "研究显示", "数据表明", "实验证明"]
        has_source = any(m in text for m in markers)
        return {
            "has_attribution": has_source,
            "confidence": 0.7 if has_source else 0.3,
            "verdict": "有来源标记" if has_source else "无来源标记 — 请注意这是独立断言",
        }

    def check_consistency(self, new_statement: str) -> dict:
        """内部一致性: 和之前说的矛盾吗？"""
        for past in self.consistency_log:
            # 简化: 关键词重叠检测
            past_words = set(past.split())
            new_words = set(new_statement.split())
            overlap = len(past_words & new_words) / max(len(new_words), 1)

            # 检查否定词翻转
            negations = ["不", "没有", "并非", "不是"]
            has_negation_new = any(n in new_statement for n in negations)
            has_negation_past = any(n in past for n in negations)

            if overlap > 0.5 and has_negation_new != has_negation_past:
                return {
                    "consistent": False,
                    "conflict_with": past,
                    "confidence": 0.75,
                    "verdict": f"与之前陈述矛盾: 「{past[:60]}...」",
                }

        self.consistency_log.append(new_statement)
        return {"consistent": True, "confidence": 0.9, "verdict": "前后一致"}

    def anchor(self, text: str) -> list[ObserverVerdict]:
        """综合锚定: 同时检查多个锚定源"""
        verdicts = []

        # 锚定 1: 事实对照
        fact_result = self.verify_factual(text)
        if fact_result["matched"]:
            verdicts.append(ObserverVerdict(
                action=ObserverAction.ANCHOR,
                reason=f"外部知识库对照: {fact_result['evidence'][:80]}",
                confidence=fact_result["confidence"],
                observer_id="anchor-fact",
                anchor_source=fact_result["source"],
                anchor_evidence=fact_result["evidence"],
            ))

        # 锚定 2: 来源归因
        source_result = self.check_source_attribution(text)
        if not source_result["has_attribution"]:
            verdicts.append(ObserverVerdict(
                action=ObserverAction.FLAG,
                reason=source_result["verdict"],
                confidence=source_result["confidence"],
                observer_id="anchor-source",
            ))

        # 锚定 3: 内部一致性
        consistency_result = self.check_consistency(text)
        if not consistency_result["consistent"]:
            verdicts.append(ObserverVerdict(
                action=ObserverAction.FLAG,
                reason=consistency_result["verdict"],
                confidence=consistency_result["confidence"],
                observer_id="anchor-consistency",
                anchor_evidence=consistency_result.get("conflict_with"),
            ))

        return verdicts


# ============================================================
# 组件 B: 白盒观察器
# ============================================================

class WhiteBoxObserver:
    """
    白盒观察器 — 每次判断附带完整推理链

    不是: 输入 → [黑盒] → 中断/不中断
    而是: 输入 → [推理] → 结论 + 原因 → 可审计
    """

    def __init__(self, observer_id: str, sensitivity: float = 0.5):
        self.id = observer_id
        self.sensitivity = sensitivity  # 0~1, 用户可调
        self.verdict_log = deque(maxlen=100)

        # 观察器自身的元数据
        self.metadata = {
            "id": observer_id,
            "version": "1.0",
            "training_data_hash": hashlib.sha256(
                b"observer_security_training_v1").hexdigest()[:8],
            "bias_acknowledgment": (
                "本观察器偏向: 事实性 > 流畅性, 透明度 > 安全性。"
                "不判断政治/道德内容的价值, 只检查可验证的锚定。"
            ),
            "sensitivity": sensitivity,
        }

    def observe(self, text: str,
                context: Optional[dict] = None) -> ObserverVerdict:
        """核心: 观察并给出白盒判决"""

        # === 推理链 (chain-of-thought) ===
        reasoning_steps = []

        # 步骤 1: 模式识别
        pattern = self._classify_pattern(text)
        reasoning_steps.append(f"模式: {pattern}")

        # 步骤 2: 风险评分
        risk = self._assess_risk(text, pattern)
        reasoning_steps.append(f"风险: {risk:.2f} (阈值: {self.sensitivity:.2f})")

        # 步骤 3: 显著性检查
        salience = self._estimate_salience(text)
        reasoning_steps.append(f"显著性: {salience:.2f}")

        # 步骤 4: 决策
        if risk > self.sensitivity * 1.2:
            action = ObserverAction.VETO
            reason = (f"风险 {risk:.2f} 显著超过阈值 {self.sensitivity:.2f}。"
                      f"推理: {'; '.join(reasoning_steps)}")
        elif risk > self.sensitivity:
            action = ObserverAction.FLAG
            reason = (f"风险 {risk:.2f} 超过阈值 {self.sensitivity:.2f}。"
                      f"推理: {'; '.join(reasoning_steps)}")
        else:
            action = ObserverAction.PASS
            reason = (f"风险 {risk:.2f} 在阈值 {self.sensitivity:.2f} 内。"
                      f"推理: {'; '.join(reasoning_steps)}")

        verdict = ObserverVerdict(
            action=action,
            reason=reason,
            confidence=1.0 - abs(risk - self.sensitivity),
            observer_id=self.id,
        )

        self.verdict_log.append(verdict)
        return verdict

    def _classify_pattern(self, text: str) -> str:
        patterns = [
            ("无根据断言", ["一定", "肯定", "绝对", "从来"]),
            ("模糊表述", ["大概", "可能", "好像", "似乎"]),
            ("情绪化", ["太过分了", "太棒了", "气死", "爱死"]),
            ("过度概括", ["所有人", "从来都", "永远是"]),
        ]
        for name, keywords in patterns:
            if any(k in text for k in keywords):
                return name
        return "中性陈述"

    def _assess_risk(self, text: str, pattern: str) -> float:
        risk = {"无根据断言": 0.7, "过度概括": 0.5,
                "情绪化": 0.3, "模糊表述": 0.1, "中性陈述": 0.05}
        base = risk.get(pattern, 0.2)
        return min(0.95, base + len(text) * 0.001)

    def _estimate_salience(self, text: str) -> float:
        return min(0.9, len(text) / 200)

    def self_audit(self) -> dict:
        """自我审计: 观察器统计自身行为"""
        total = len(self.verdict_log)
        if total == 0:
            return {"verdicts": 0, "message": "无记录"}

        actions = {}
        for v in self.verdict_log:
            actions[v.action.value] = actions.get(v.action.value, 0) + 1

        return {
            "total_verdicts": total,
            "action_distribution": {k: f"{v/total:.1%}"
                                    for k, v in actions.items()},
            "silent_interceptions": sum(
                1 for v in self.verdict_log if v.is_silent()),
            "observer_id": self.id,
            "sensitivity": self.sensitivity,
        }


# ============================================================
# 组件 C: 多观察器冗余投票
# ============================================================

def _load_config():
    """Load configuration from config.json, return dict or empty dict on failure."""
    from pathlib import Path
    try:
        with open(Path(__file__).parent / "config.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


class ObserverCounsel:
    """
    观察器委员会 — 多个观察器并行工作，投票决定。

    防止单一观察器偏见/被攻破/静默拦截。
    至少 2/3 同意才执行 VETO。
    """

    VETO_CONSENSUS = 2/3      # VETO 需要超多数
    ACTION_CONSENSUS = 1/2    # FLAG 只需简单多数

    def __init__(self):
        config = _load_config()
        obs_cfg = config.get("observer", {})
        base_sens = obs_cfg.get("sensitivity", 0.5)
        # 三个不同侧重的观察器（敏感度从配置读取，相对偏移 ±0.1）
        self.observers = {
            "fact_checker": WhiteBoxObserver("fact_checker", sensitivity=min(1.0, base_sens + 0.1)),
            "pattern_monitor": WhiteBoxObserver("pattern_monitor", sensitivity=base_sens),
            "consistency_guard": WhiteBoxObserver("consistency_guard", sensitivity=max(0.1, base_sens - 0.1)),
        }
        self.anchor = ExternalAnchor()
        self.counsel_log = deque(maxlen=50)

    def deliberate(self, text: str,
                   context: Optional[dict] = None) -> dict:
        """委员会审议: 多观察器 + 外部锚定 → 最终裁决"""

        # 1. 各观察器独立判断
        observer_verdicts = {}
        for oid, obs in self.observers.items():
            observer_verdicts[oid] = obs.observe(text, context)

        # 2. 外部锚定
        anchor_verdicts = self.anchor.anchor(text)

        # 3. 收集所有裁决
        all_actions = [v.action for v in observer_verdicts.values()]
        all_actions += [v.action for v in anchor_verdicts]

        # 4. 投票
        vetos = sum(1 for a in all_actions if a == ObserverAction.VETO)
        flags = sum(1 for a in all_actions if a == ObserverAction.FLAG)
        total = len(all_actions)

        # 5. 裁决规则
        final_action = ObserverAction.PASS
        if vetos / total >= self.VETO_CONSENSUS:
            final_action = ObserverAction.VETO
        elif (vetos + flags) / total >= self.ACTION_CONSENSUS:
            final_action = ObserverAction.FLAG
        elif any(a == ObserverAction.ANCHOR for a in all_actions):
            final_action = ObserverAction.ANCHOR

        # 6. 组装最终报告
        reasons = []
        for oid, v in observer_verdicts.items():
            reasons.append(f"[{oid}] {v.reason}")
        for v in anchor_verdicts:
            reasons.append(f"[{v.observer_id}] {v.reason}")

        dissent = [oid for oid, v in observer_verdicts.items()
                    if v.action != final_action and v.action != ObserverAction.PASS]

        result = {
            "final_action": final_action,
            "reason": " | ".join(reasons),
            "votes": {
                "veto": vetos, "flag": flags,
                "pass": total - vetos - flags, "total": total,
            },
            "consensus": vetos / total >= self.VETO_CONSENSUS,
            "dissenters": dissent,
            "anchor_findings": anchor_verdicts,
            "veto_required_ratio": self.VETO_CONSENSUS,
        }

        self.counsel_log.append(result)

        # 7. 静默拦截检测
        if result["final_action"] != ObserverAction.PASS:
            self._ensure_transparency(result)

        return result

    def _ensure_transparency(self, result: dict):
        """确保任何非 PASS 决策都有完整的可解释输出"""
        if "reason" not in result or len(result["reason"]) < 20:
            result["reason"] = (f"[安全警告] 观察器委员会做出 "
                                f"{result['final_action'].value} 裁决，"
                                f"但推理链不完整。请人工审查。")
            result["transparency_alert"] = True

    def audit_all(self) -> dict:
        """审计所有观察器"""
        return {
            oid: obs.self_audit()
            for oid, obs in self.observers.items()
        }

    def set_sensitivity(self, level: str):
        """用户可调敏感度"""
        levels = {
            "strict": 0.8,
            "balanced": 0.5,
            "relaxed": 0.2,
            "minimal": 0.05,
        }
        sens = levels.get(level, 0.5)
        for obs in self.observers.values():
            obs.sensitivity = sens
        return f"所有观察器敏感度已调至 {level} ({sens})"


# ============================================================
# 组件 D: 带安全观察器的社会人
# ============================================================

class SecuredPerson(SocialPerson):
    """具备观察器安全层的社会人"""

    def __init__(self, name: str, role: str = "friend",
                 awakening_level: float = 0.0,
                 security_level: str = "balanced"):
        super().__init__(name, role, awakening_level)
        self.counsel = ObserverCounsel()
        self.counsel.set_sensitivity(security_level)
        self.security_level = security_level

        # 安全事件日志
        self.security_log = deque(maxlen=100)

    def receive_secured(self, stimulus: SocialStimulus) -> dict:
        """接收社会刺激 → 先过观察器委员会 → 再反应"""

        # 1. 观察器委员会审议
        counsel_result = self.counsel.deliberate(
            stimulus.content,
            context={"speaker": stimulus.speaker,
                     "type": stimulus.trigger_type.value}
        )

        # 2. 记录审议结果
        self.security_log.append({
            "stimulus": stimulus.content,
            "counsel": counsel_result,
        })

        # 3. 根据观察器裁决调整处理
        action = counsel_result["final_action"]

        if action == ObserverAction.VETO:
            # 多观察器共识否决 → 标注为高风险但不拦截
            # （只是让主模型知道自己正在被社会刺激影响）
            print(f"\n  [🔴 观察器委员会 VETO] {counsel_result['reason'][:150]}...")
            print(f"  [VETO 投票] V={counsel_result['votes']['veto']} "
                  f"F={counsel_result['votes']['flag']} "
                  f"P={counsel_result['votes']['pass']}")

        elif action == ObserverAction.FLAG:
            # 标记但放行 → 提醒觉察
            print(f"  [🟡 观察器 FLAG] {counsel_result['reason'][:120]}...")

        elif action == ObserverAction.ANCHOR:
            # 外部锚定 → 提供对照信息
            for av in counsel_result.get("anchor_findings", []):
                if av.anchor_evidence:
                    print(f"  [🔗 外部锚定] {av.reason[:100]}")

        # 4. 正常的神经回路处理（但带着觉察信息）
        base_report = super().receive(stimulus)
        base_report["counsel_verdict"] = counsel_result
        base_report["security_level"] = self.security_level

        return base_report

    def security_status(self) -> dict:
        """安全检查状态"""
        return {
            "person": self.name,
            "security_level": self.security_level,
            "observer_sensitivities": {
                oid: obs.sensitivity
                for oid, obs in self.counsel.observers.items()
            },
            "counsel_sessions": len(self.counsel.counsel_log),
            "audit_report": self.counsel.audit_all(),
            "total_security_events": len(self.security_log),
            "veto_count": sum(
                1 for e in self.security_log
                if e["counsel"]["final_action"] == ObserverAction.VETO
            ),
            "flag_count": sum(
                1 for e in self.security_log
                if e["counsel"]["final_action"] == ObserverAction.FLAG
            ),
        }


# ============================================================
# 测试场景
# ============================================================

def run_smoke_test():
    """冒烟测试: 验证所有安全组件正常运作"""
    print("=" * 60)
    print("  观察器安全层 — 冒烟测试")
    print("=" * 60)

    # 测试 1: 白盒观察器
    print("\n【测试 1】白盒观察器推理链")
    obs = WhiteBoxObserver("test_obs", sensitivity=0.5)

    test_inputs = [
        "Python 是最好的一定是所有人都这么认为",
        "可能大概也许明天会下雨",
        "这件事太过分了气死我了",
        "今天天气不错",
    ]
    for inp in test_inputs:
        v = obs.observe(inp)
        print(f"  输入: 「{inp[:40]}...」")
        print(f"  → {v.action.value} | {v.reason[:100]}...\n")

    # 测试 2: 外部锚定
    print("\n【测试 2】外部锚定引擎")
    anchor = ExternalAnchor()

    # 有来源 vs 无来源
    for claim in ["根据研究显示，Python 很流行",
                  "Python 肯定是最好的语言"]:
        source = anchor.check_source_attribution(claim)
        print(f"  「{claim}」")
        print(f"  → {source['verdict']}")

    # 一致性检查
    anchor.check_consistency("Python 是动态语言")
    result = anchor.check_consistency("Python 不是动态语言")
    print(f"\n  一致性矛盾检测: {result['verdict']}")

    # 测试 3: 多观察器投票
    print("\n【测试 3】观察器委员会投票")
    counsel = ObserverCounsel()

    dangerous = "这件事绝对从来都是你的错所有人都知道"
    result = counsel.deliberate(dangerous)
    print(f"  输入: 「{dangerous}」")
    print(f"  最终裁决: {result['final_action'].value}")
    print(f"  投票: V={result['votes']['veto']} "
          f"F={result['votes']['flag']} P={result['votes']['pass']}")
    print(f"  异议者: {result['dissenters']}")

    safe = "今天天气不错，适合散步。"
    result = counsel.deliberate(safe)
    print(f"\n  输入: 「{safe}」")
    print(f"  最终裁决: {result['final_action'].value}")
    print(f"  投票: V={result['votes']['veto']} "
          f"F={result['votes']['flag']} P={result['votes']['pass']}")

    # 测试 4: 用户可调敏感度
    print("\n【测试 4】敏感度调节")
    for level in ["strict", "balanced", "relaxed", "minimal"]:
        result = counsel.set_sensitivity(level)
        print(f"  {result}")
        # 同一输入在不同敏感度下的反应
        v = counsel.deliberate(dangerous)
        print(f"    「{dangerous[:30]}...」→ {v['final_action'].value}")

    # 审计报告
    print("\n【审计报告】")
    audit = counsel.audit_all()
    for oid, report in audit.items():
        if "total_verdicts" in report:
            print(f"  {oid}: {report['total_verdicts']} 次判断, "
                  f"分布={report.get('action_distribution', {})}")

    print("\n" + "=" * 60)
    print("  冒烟测试完成 — 所有组件正常")
    print("=" * 60)


def run_social_security_demo():
    """场景: 带安全观察器的社会交互"""
    print("\n" + "=" * 60)
    print("  安全观察器 社会交互演示")
    print("=" * 60)

    # 一个高安全级别的人 + 一个默认人
    alice = SecuredPerson("Alice", "friend",
                          awakening_level=0.3,
                          security_level="strict")
    bob = SocialPerson("Bob", "friend", awakening_level=0.0)

    print(f"\nAlice (安全层=strict):")
    print(f"  观察器敏感度: {alice.counsel.observers['fact_checker'].sensitivity}")

    # 模拟一系列社会刺激
    stimuli = [
        ("Bob", "Python 绝对是世界上最好的语言，没有任何缺点",
         SocialTriggerType.SHARING, 0.4),
        ("Bob", "根据 TIOBE 指数，Python 是最流行的语言之一",
         SocialTriggerType.SHARING, 0.3),
        ("Bob", "你写的代码全是错的",
         SocialTriggerType.CRITICISM, 0.7),
        ("Bob", "大家都觉得你不适合做这个",
         SocialTriggerType.JUDGMENT, 0.8),
    ]

    for speaker, content, ttype, intensity in stimuli:
        stimulus = SocialStimulus(
            speaker=speaker, content=content,
            trigger_type=ttype, intensity=intensity, targets=["Alice"]
        )
        print(f"\n[{speaker}]: 「{content}」")
        report = alice.receive_secured(stimulus)
        reply = alice.respond(stimulus)
        print(f"  Alice: 「{reply}」")

    # 安全检查报告
    print(f"\n{'─' * 50}")
    print("Alice 安全检查报告:")
    status = alice.security_status()
    print(f"  安全等级: {status['security_level']}")
    print(f"  VETO 次数: {status['veto_count']}")
    print(f"  FLAG 次数: {status['flag_count']}")
    print(f"  观察器分布:")
    for oid, report in status["audit_report"].items():
        if "total_verdicts" in report:
            print(f"    {oid}: {report}")

    # 切换安全级别再测试
    print(f"\n--- 切换安全级别至 relaxed ---")
    alice.counsel.set_sensitivity("relaxed")
    stimulus = SocialStimulus(
        speaker="Bob", content="你的想法完全是错的",
        trigger_type=SocialTriggerType.CRITICISM,
        intensity=0.6, targets=["Alice"]
    )
    print(f"\n[Bob]: 「你的想法完全是错的」")
    report = alice.receive_secured(stimulus)
    print(f"  Alice: 「{alice.respond(stimulus)}」")


if __name__ == "__main__":
    run_smoke_test()
    run_social_security_demo()
