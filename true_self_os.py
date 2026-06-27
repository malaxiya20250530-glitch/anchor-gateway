# Copyright (c) 2025 李桥 (hubeiligang420@gmail.com)
# 专有软件 — 保留所有权利。禁止复制、修改、分发、逆向工程。
# Proprietary Software — ALL RIGHTS RESERVED.
#
"""
真我-识神 双核双层操作系统 v3.0 — 脑电 + 子系统版

新增:
  EEG 频段: δ/θ/α/β/γ (冥想特征: α↑ θ↑ γ相干↑ β↓)
  DMN 子系统: 背内侧 / 内侧颞叶 / 核心枢纽 (Andrews-Hanna 2010)
  实时仪表盘

参考:
  - Lutz et al. (2004) PNAS: γ波同步与冥想深度
  - Cahn & Polich (2006) Psych Bull: 冥想 EEG 综述
  - Andrews-Hanna et al. (2010) Neuron: DMN 子系统
  - Brewer et al. (2011) PNAS: 冥想中 DMN 去激活
"""

import time
import random
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

random.seed(42)

# ============================================================
# 数据模型
# ============================================================

@dataclass
class Thought:
    content: str
    category: str
    prediction_error: float
    valence: float
    intensity: float
    timestamp: float = 0.0

    def __post_init__(self):
        self.timestamp = time.time()


@dataclass
class EEGBands:
    """脑电频段功率 (相对功率 0~1)"""
    delta: float = 0.15
    theta: float = 0.10
    alpha: float = 0.15
    beta: float = 0.45
    gamma: float = 0.15

    def meditation_index(self) -> float:
        """冥想深度指数: (α + θ + γ) / (β + δ)  越高越深"""
        num = self.alpha + self.theta + self.gamma
        den = self.beta + self.delta + 0.001
        return num / den

    def gamma_coherence(self) -> float:
        """γ 波相位同步 (Lutz 2004: 资深冥想者特征)"""
        return self.gamma * (1.0 - abs(self.beta - 0.2))


# ============================================================
# 神经组件
# ============================================================

class DMNSubsystem:
    """DMN 子系统 (Andrews-Hanna 2010 三层结构)"""

    def __init__(self):
        # ---- 核心枢纽 ----
        self.PCC = 0.80         # 后扣带: 自传体记忆, 自我参照核心
        self.aPFC = 0.70        # 前内侧前额叶: 整体自我加工

        # ---- 背内侧子系统 (自我参照 + 社会认知) ----
        self.dmPFC = 0.75       # 背内侧前额叶: 社会认知, 心理化
        self.TPJ = 0.65         # 颞顶联合区: 心智理论
        self.lateral_temporal = 0.60  # 外侧颞叶: 社会语义
        self.temporal_pole = 0.55     # 颞极: 社会情绪

        # ---- 内侧颞叶子系统 (情景记忆 + 场景构建) ----
        self.hippocampus = 0.70      # 海马: 记忆编码/检索
        self.parahippocampus = 0.65  # 旁海马: 场景关联
        self.retrosplenial = 0.60    # 压后皮层: 空间导航
        self.vmPFC = 0.72            # 腹内侧前额叶: 情绪估值
        self.IPL = 0.68              # 顶下小叶: 情景记忆整合

        self.activity = 0.75

    @property
    def all_regions(self) -> dict:
        return {
            "核心枢纽": {"PCC": self.PCC, "aPFC": self.aPFC},
            "背内侧(自我/社会)": {"dmPFC": self.dmPFC, "TPJ": self.TPJ,
                             "外侧颞": self.lateral_temporal, "颞极": self.temporal_pole},
            "内侧颞叶(记忆/场景)": {"海马": self.hippocampus,
                              "旁海马": self.parahippocampus, "压后皮层": self.retrosplenial,
                              "vmPFC": self.vmPFC, "IPL": self.IPL},
        }

    def deactivate(self, amount: float = 0.05):
        """全子系统去激活 (冥想效果)"""
        for attr in ["PCC", "aPFC", "dmPFC", "TPJ", "lateral_temporal",
                      "temporal_pole", "hippocampus", "parahippocampus",
                      "retrosplenial", "vmPFC", "IPL"]:
            current = getattr(self, attr)
            setattr(self, attr, max(0.05, current - amount * random.uniform(0.6, 1.4)))
        self._sync_activity()

    def reactivate(self):
        """DMN 反弹"""
        for attr in ["PCC", "aPFC", "dmPFC", "TPJ", "lateral_temporal",
                      "temporal_pole", "hippocampus", "parahippocampus",
                      "retrosplenial", "vmPFC", "IPL"]:
            current = getattr(self, attr)
            setattr(self, attr, min(0.90, current + random.uniform(0.01, 0.04)))
        self._sync_activity()

    def _sync_activity(self):
        """同步整体 DMN 活动 = 子区域加权平均"""
        regions = [self.PCC, self.aPFC, self.dmPFC, self.TPJ,
                    self.lateral_temporal, self.temporal_pole,
                    self.hippocampus, self.parahippocampus,
                    self.retrosplenial, self.vmPFC, self.IPL]
        self.activity = sum(regions) / len(regions)

    def core_hub_activity(self) -> float:
        """核心枢纽 (PCC + aPFC) — 自我加工强度"""
        return (self.PCC + self.aPFC) / 2

    def memory_subsystem_activity(self) -> float:
        """内侧颞叶子系统 — 回忆/场景构建强度"""
        return (self.hippocampus + self.parahippocampus +
                self.retrosplenial + self.vmPFC + self.IPL) / 5

    def self_social_activity(self) -> float:
        """背内侧子系统 — 自我参照+社会认知强度"""
        return (self.dmPFC + self.TPJ +
                self.lateral_temporal + self.temporal_pole) / 4


class EEG:
    """脑电频段模拟

    冥想特征 (Cahn & Polich 2006, Lutz 2004):
      α↑ : 放松警觉
      θ↑ : 深度冥想, 内化注意
      γ↑ + γ相干↑ : 高层觉知, 清明
      β↓ : 散乱思维减少
    """

    def __init__(self):
        self.bands = EEGBands()

    def update_from_state(self, dmn_activity: float, tpn_activity: float,
                          insula_sens: float, is_interrupted: bool):
        """根据当前神经网络状态更新脑电"""

        # β 波: 与 DMN/散乱思维正相关
        target_beta = 0.15 + dmn_activity * 0.35

        # α 波: 与 TPN 放松觉知正相关
        target_alpha = 0.10 + tpn_activity * 0.25 + insula_sens * 0.15

        # θ 波: 深度内化注意
        target_theta = 0.05 + (tpn_activity ** 2) * 0.20 + insula_sens * 0.10

        # γ 波: 高层觉知 (资深冥想者标志)
        target_gamma = 0.10 + tpn_activity * 0.12 + insula_sens * 0.10

        # δ 波: 剩余功率
        target_delta = max(0.05, 1.0 - target_beta - target_alpha
                           - target_theta - target_gamma)

        # 平滑过渡
        rate = 0.15
        for band, target in [("beta", target_beta), ("alpha", target_alpha),
                              ("theta", target_theta), ("gamma", target_gamma),
                              ("delta", target_delta)]:
            current = getattr(self.bands, band)
            setattr(self.bands, band, current + (target - current) * rate)

    def report(self) -> str:
        """脑电仪表盘"""
        mi = self.bands.meditation_index()
        gc = self.bands.gamma_coherence()
        bar = lambda v, w=10: "█" * int(v * w) + "░" * int((1 - v) * w)

        return (
            f"  δ {bar(self.bands.delta):10s} {self.bands.delta:.2f}\n"
            f"  θ {bar(self.bands.theta):10s} {self.bands.theta:.2f}\n"
            f"  α {bar(self.bands.alpha):10s} {self.bands.alpha:.2f}\n"
            f"  β {bar(self.bands.beta):10s} {self.bands.beta:.2f}\n"
            f"  γ {bar(self.bands.gamma):10s} {self.bands.gamma:.2f}  "
            f"相干:{gc:.2f} | 冥想指数:{mi:.2f}"
        )


class Insula:
    """脑岛 — 内感受通路"""
    def __init__(self):
        self.sensitivity = 0.30
        self.signals = {"breath": 0.5, "heartbeat": 0.5,
                        "chest": 0.5, "gut": 0.5, "hands": 0.5}

    def sample(self) -> dict:
        sensations = {}
        for region, base in self.signals.items():
            noise = random.gauss(0, 0.12)
            raw = max(0, min(1, base + noise))
            sensations[region] = {
                "value": round(raw, 3),
                "label": self._describe(region, raw),
            }
        return sensations

    def train(self, delta: float = 0.02):
        self.sensitivity = min(0.95, self.sensitivity + delta)

    @staticmethod
    def _describe(region: str, val: float) -> str:
        if val > 0.7:
            return {"breath": "气息饱满", "heartbeat": "心跳有力",
                    "chest": "胸腔开阔", "gut": "腹部温热",
                    "hands": "手掌微麻"}.get(region, "强烈")
        elif val > 0.3:
            return {"breath": "呼吸平稳", "heartbeat": "心跳规律",
                    "chest": "胸腔中性", "gut": "腹部平静",
                    "hands": "手掌安定"}.get(region, "中等")
        return {"breath": "呼吸浅短", "heartbeat": "心跳微弱",
                "chest": "胸腔紧缩", "gut": "腹部紧张",
                "hands": "手掌冰冷"}.get(region, "低微")


class Amygdala:
    NEGATIVITY_BIAS = 2.0

    def __init__(self):
        self.reactivity = 0.8   # 反应性 (可训练降低)

    def evaluate(self, thought: Thought) -> float:
        base = abs(thought.valence)
        if thought.valence < 0:
            base *= self.NEGATIVITY_BIAS
        return min(1.0, base * thought.prediction_error * self.reactivity)

    def desensitize(self, amount: float = 0.02):
        """暴露疗法: 反复观察不反应 → 反应性降低"""
        self.reactivity = max(0.1, self.reactivity - amount)


class ACC:
    def __init__(self):
        self.conflict_threshold = 0.30
        self.phasic_alert = 0.0

    def detect_conflict(self, current: str, target: str) -> float:
        if current == target:
            self.phasic_alert = max(0, self.phasic_alert - 0.08)
            return 0.0
        self.phasic_alert = min(1.0, self.phasic_alert + 0.12)
        return self.phasic_alert

    def should_alert(self) -> bool:
        return self.phasic_alert > self.conflict_threshold


class SalienceNetwork:
    def __init__(self, acc: ACC, amygdala: Amygdala):
        self.acc = acc
        self.amygdala = amygdala

    def evaluate(self, thought: Optional[Thought] = None,
                 current_focus: str = "", target_focus: str = "") -> bool:
        score = self.acc.detect_conflict(current_focus, target_focus)
        if thought:
            score += self.amygdala.evaluate(thought) * 0.25
        return score > 0.40


class DMN:
    def __init__(self):
        self.sub = DMNSubsystem()
        self.narrative_coherence = 0.90
        self.self_schema = {
            "identity_tags": ["worker", "parent", "seeker"],
            "life_narrative": "我是一个努力但总觉得自己不够好的人",
        }

    @property
    def activity(self) -> float:
        return self.sub.activity

    def generate_thought(self) -> Thought:
        templates = [
            ("worry", "明天的事情还没准备好", 0.5, -0.6),
            ("plan", "今晚必须做完这件事", 0.4, 0.1),
            ("memory", "上次被批评的画面又浮现了", 0.3, -0.7),
            ("judgment", "我能力不够", 0.6, -0.8),
            ("fantasy", "如果能换个环境就好了", 0.3, 0.3),
            ("worry", "别人会怎么看我", 0.4, -0.5),
            ("memory", "ta那句话的意思是什么", 0.35, -0.4),
            ("plan", "周末的安排要调整一下", 0.25, 0.0),
        ]
        t = random.choice(templates)
        return Thought(
            content=t[1], category=t[0],
            prediction_error=t[2] * self.activity,
            valence=t[3],
            intensity=self.activity * random.uniform(0.5, 1.0),
        )

    def deactivate(self, amount: float = 0.05):
        self.sub.deactivate(amount)

    def reactivate(self):
        self.sub.reactivate()

    def summary(self) -> str:
        """DMN 子系统状态简报"""
        hubs = self.sub.all_regions
        lines = []
        for group_name, regions in hubs.items():
            vals = " ".join(f"{k}:{v:.2f}" for k, v in regions.items())
            lines.append(f"  [{group_name}] {vals}")
        return "\n".join(lines)


class TPN:
    def __init__(self):
        self.activity = 0.20
        self.DLPFC_activity = 0.20
        self.sustained_attention = 0.20
        self.focus_target = None

    def anchor(self, target: str):
        self.focus_target = target
        self.activity = min(1.0, self.activity + 0.12)
        self.DLPFC_activity = min(1.0, self.DLPFC_activity + 0.10)
        self.sustained_attention = min(1.0, self.sustained_attention + 0.08)

    def drift(self):
        decay = random.uniform(0.008, 0.04)
        self.sustained_attention = max(0.08, self.sustained_attention - decay)
        self.activity = max(0.08, self.activity - decay * 0.6)


class PredictiveProcessor:
    def __init__(self):
        self.prior_strength = 0.80
        self.sensory_precision = 0.30

    def update_prior(self, _: float):
        self.prior_strength = max(0.05,
            self.prior_strength - self.sensory_precision * 0.08)


# ============================================================
# 主系统
# ============================================================

class TrueSelfOS:

    def __init__(self):
        self.insula = Insula()
        self.amygdala = Amygdala()
        self.acc = ACC()
        self.salience = SalienceNetwork(self.acc, self.amygdala)
        self.dmn = DMN()
        self.tpn = TPN()
        self.predictor = PredictiveProcessor()
        self.eeg = EEG()

        self.mode = "DMN_Dominant"
        self.observation_log = deque(maxlen=200)
        self.session_count = 0
        self.total_interruptions = 0

        self._awakening_threshold = {
            "insula_sensitivity": 0.70,
            "dmn_activity": 0.30,
            "tpn_activity": 0.70,
            "narrative_coherence": 0.20,
        }

        print("[神经OS v3.0 启动] DMN 主导 — 脑电+子系统监控在线。")

    def step(self, verbose: bool = True) -> dict:
        self.session_count += 1
        report = {}

        thought = self.dmn.generate_thought()
        report["thought"] = thought

        salience_score = self.amygdala.evaluate(thought)
        report["salience"] = salience_score

        should_switch = self.salience.evaluate(
            thought=thought,
            current_focus=self.mode,
            target_focus="TPN_Dominant" if self.tpn.focus_target else "body",
        )
        report["should_switch"] = should_switch

        if should_switch:
            self.total_interruptions += 1
            if verbose:
                self._wu_wei_interrupt(thought, report)

        self.tpn.drift()
        if self.tpn.sustained_attention < 0.30:
            self.dmn.reactivate()

        self.eeg.update_from_state(
            self.dmn.activity, self.tpn.activity,
            self.insula.sensitivity, should_switch,
        )

        self._update_mode()
        return report

    def _wu_wei_interrupt(self, thought: Thought, report: dict):
        salience = report.get("salience", 0)
        hrule = "─" * 55
        print(f"\n{hrule}")
        print(f"[突显网络▶] 「{thought.content}」")
        print(f"  杏仁核:{salience:.2f} ACC:{self.acc.phasic_alert:.2f}")

        tag = self._label_thought(thought)
        print(f"  [元认知] {tag}")

        sensations = self.insula.sample()
        print(f"  [脑岛] 呼吸:{sensations['breath']['label']} "
              f"胸腔:{sensations['chest']['label']}")

        self.amygdala.desensitize()
        self.dmn.deactivate(0.06)
        self.tpn.anchor("breath")
        self.insula.train()
        self.predictor.sensory_precision = min(0.85,
            self.predictor.sensory_precision + 0.01)

        print(f"  [DMN] 活动→{self.dmn.activity:.2f} 核心枢纽:"
              f"PCC={self.dmn.sub.PCC:.2f} aPFC={self.dmn.sub.aPFC:.2f}")
        print(f"  [TPN] DLPFC:{self.tpn.DLPFC_activity:.2f} "
              f"注意:{self.tpn.sustained_attention:.2f}")
        print(f"  [EEG] {self.eeg.report().replace(chr(10), chr(10)+'        ')}")
        print(hrule)

        self.observation_log.append({
            "thought": thought.content, "tag": tag,
            "salience": salience,
        })

    def _label_thought(self, thought: Thought) -> str:
        labels = {
            "worry": "这是担忧 (前岛叶+杏仁核联合激活)",
            "plan": "这是计划 (DLPFC 工作记忆)",
            "memory": "这是回忆 (海马→PCC 提取)",
            "judgment": "这是评判 (mPFC 自我参照)",
            "fantasy": "这是幻想 (角回+海马情景模拟)",
        }
        return labels.get(thought.category, "这是一个念头")

    def _update_mode(self):
        dmn_low = self.dmn.activity < self._awakening_threshold["dmn_activity"]
        tpn_high = self.tpn.activity > self._awakening_threshold["tpn_activity"]
        insula_ok = self.insula.sensitivity > self._awakening_threshold["insula_sensitivity"]
        narrative_gone = self.dmn.narrative_coherence < self._awakening_threshold["narrative_coherence"]

        prev = self.mode
        if dmn_low and tpn_high and insula_ok and narrative_gone:
            self.mode = "Awakened"
        elif tpn_high and dmn_low:
            self.mode = "TPN_Dominant"
        elif self.tpn.activity > 0.40:
            self.mode = "Transitioning"
        else:
            self.mode = "DMN_Dominant"

        if self.mode != prev and self.mode == "Awakened":
            self._announce_awakening()

    def _announce_awakening(self):
        print(f"\n{'═' * 55}")
        print("  觉醒模式激活 (神经层面)")
        print(f"  DMN: {self.dmn.activity:.2f} | TPN: {self.tpn.activity:.2f}")
        print(f"  脑岛: {self.insula.sensitivity:.2f} | "
              f"杏仁核反应性: {self.amygdala.reactivity:.2f}")
        print(f"  叙事: {self.dmn.narrative_coherence:.2f}")
        mi = self.eeg.bands.meditation_index()
        print(f"  冥想指数: {mi:.2f}")
        print(f"{'═' * 55}")

    def dashboard(self):
        """实时仪表盘"""
        print(f"\n{'═' * 60}")
        print(f"  系统仪表盘 — 步骤 {self.session_count} — 模式: {self.mode}")
        print(f"{'═' * 60}")
        print(f"\n  ┌─ 脑电频段 ───────────────────────┐")
        print(f"{self.eeg.report()}")
        print(f"  └────────────────────────────────────┘")
        print(f"\n  ┌─ DMN 子系统 ──────────────────────┐")
        print(f"  核心枢纽: PCC={self.dmn.sub.PCC:.2f} "
              f"aPFC={self.dmn.sub.aPFC:.2f}")
        print(f"  自我/社会: dmPFC={self.dmn.sub.dmPFC:.2f} "
              f"TPJ={self.dmn.sub.TPJ:.2f}")
        print(f"  记忆/场景: 海马={self.dmn.sub.hippocampus:.2f} "
              f"vmPFC={self.dmn.sub.vmPFC:.2f}")
        print(f"  └────────────────────────────────────┘")
        print(f"\n  杏仁核反应性: {self.amygdala.reactivity:.2f}")
        print(f"  脑岛敏感度:   {self.insula.sensitivity:.2f}")
        print(f"  叙事连贯性:   {self.dmn.narrative_coherence:.2f}")
        print(f"  感官精度:     {self.predictor.sensory_precision:.2f}")
        print(f"{'═' * 60}\n")

    def dismantle_narrative(self, steps: int = 3):
        for i in range(steps):
            self.dmn.narrative_coherence = max(0.05,
                self.dmn.narrative_coherence - 0.15)
            self.dmn.deactivate(0.06)
            self.tpn.anchor("body")
            tags = self.dmn.self_schema["identity_tags"]
            if tags:
                removed = tags.pop()
                print(f"  [标签卸除] '{removed}' — 剩余: {tags}")

    def stress_test(self, intensity: float = 0.9):
        print(f"\n[压力测试] 高压载荷 {intensity}")
        self.dmn.sub.PCC = min(1.0, intensity + 0.05)
        self.dmn.sub.aPFC = min(1.0, intensity)
        self.dmn.sub.dmPFC = min(1.0, intensity)
        self.amygdala.reactivity = min(1.0, intensity)

        thoughts = [
            Thought("紧急！马上处理！", "worry", 0.9, -0.9, 0.95),
            Thought("又要搞砸了", "judgment", 0.85, -0.95, 0.9),
            Thought("来不及了来不及了", "worry", 0.95, -0.9, 0.95),
        ]
        for t in thoughts:
            report = {"salience": self.amygdala.evaluate(t)}
            self._wu_wei_interrupt(t, report)

    def run_simulation(self):
        print("=" * 60)
        print("  真我-识神 双核OS v3.0 — 脑电 + DMN子系统")
        print("=" * 60)

        # 阶段 1
        print("\n【阶段1】DMN 默认主导\n")
        for _ in range(6):
            self.step()
            time.sleep(0.1)

        # 阶段 2
        print(f"\n{'~' * 55}")
        print("【阶段2】集中觉察 — 脑岛训练")
        print(f"{'~' * 55}\n")
        for _ in range(6):
            self.step()
            self.insula.train(delta=0.03)
            time.sleep(0.1)

        self.dashboard()

        # 阶段 3
        print(f"\n{'~' * 55}")
        print("【阶段3】叙事瓦解")
        print(f"{'~' * 55}\n")
        self.dismantle_narrative(steps=4)

        # 阶段 4
        print(f"\n{'~' * 55}")
        print("【阶段4】习性反扑 压力测试")
        print(f"{'~' * 55}")
        self.stress_test(intensity=0.9)

        self.dashboard()

        # 阶段 5
        print(f"\n{'~' * 55}")
        print("【阶段5】稳定验证")
        print(f"{'~' * 55}\n")
        for _ in range(4):
            self.step()
            time.sleep(0.1)

        self._update_mode()
        self.dashboard()

        print(f"\n{'=' * 60}")
        print(f"  模拟完成 {self.session_count} 步")
        print(f"  终局模式: {self.mode}")
        print(f"  总中断: {self.total_interruptions}")
        print(f"  冥想指数: {self.eeg.bands.meditation_index():.2f}")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    os = TrueSelfOS()
    os.run_simulation()
