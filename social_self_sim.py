# Copyright (c) 2025 李桥 (hubeiligang420@gmail.com)
# 专有软件 — 保留所有权利。禁止复制、修改、分发、逆向工程。
# Proprietary Software — ALL RIGHTS RESERVED.
#
"""
社会自我多人交互模拟
基于真我-识神 v3.0 神经模型

新增:
  镜像神经元系统 (Mirror Neuron System)
  心智化网络 (Mentalizing / ToM)
  社会疼痛回路 (dACC + 前脑岛)
  社会奖赏回路 (腹侧纹状体)
  多人对话引擎

场景: 对话中社会自我如何重建 / 觉醒态如何承受社会压力
"""

import sys
sys.path.insert(0, '/data/data/com.termux/files/home')

from true_self_os import (
    Thought, Insula, Amygdala, ACC, SalienceNetwork,
    DMN, TPN, PredictiveProcessor, EEG, EEGBands,
)

import time
import random
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

random.seed(123)

# ============================================================
# 社会神经组件
# ============================================================

class SocialTriggerType(Enum):
    CRITICISM = "批评"
    PRAISE = "赞美"
    COMPARISON = "比较"
    EXPECTATION = "期望"
    JUDGMENT = "评判"
    EMPATHY = "共情"
    QUESTION = "提问"
    SHARING = "分享"

@dataclass
class SocialStimulus:
    """社会刺激: 他人的话语/行为触发的神经事件"""
    speaker: str
    content: str
    trigger_type: SocialTriggerType
    intensity: float   # 0~1 社会冲击强度
    targets: list[str]  # 靶向神经回路


class MirrorNeuronSystem:
    """镜像神经元系统 — 自动模拟他人状态

    功能: 看到/听到他人 → 自动内部仿真
    负面影响: 情绪传染、社会比较自动化
    正面作用: 共情、学习
    """

    def __init__(self):
        self.activity = 0.3
        self.empathic_resonance = 0.3   # 共情共振强度
        self.contagion_rate = 0.4        # 情绪传染率

    def resonate(self, other_emotion_valence: float,
                 other_intensity: float) -> float:
        """镜像共振: 自动内化他人情绪状态"""
        resonance = (abs(other_emotion_valence) * other_intensity
                     * self.contagion_rate * self.activity)
        return min(1.0, resonance)

    def dampen(self, amount: float = 0.03):
        """觉察训练 → 镜像自动化减弱 (不压抑共情, 只削弱强制认同)"""
        self.contagion_rate = max(0.05, self.contagion_rate - amount)


class MentalizingNetwork:
    """心智化网络 — 推断他人心理状态 (Theory of Mind)

    核心区域: dmPFC, TPJ, 颞极, 楔前叶
    过度活跃 → 反刍"ta怎么看我"
    适度活跃 → 健康共情
    """

    def __init__(self):
        self.activity = 0.5
        # 子区域
        self.dmPFC = 0.5     # 推断他人意图
        self.TPJ = 0.5       # 区分自我/他人视角
        self.precuneus = 0.4 # 自我-他人表征

    def mentalize(self, other_person: str, situation: str) -> dict:
        """模拟心智化过程: 「ta 在想什么？」"""
        # 推断的不准确性
        accuracy = 1.0 - (self.dmPFC - 0.3) * 0.5
        self.activity = min(0.95, self.activity + 0.05)

        inferences = [
            f"{other_person}觉得我不够好",
            f"{other_person}在评判我",
            f"{other_person}只是随便说说",
            f"{other_person}想帮我",
            f"{other_person}有ta自己的烦恼",
        ]
        return {
            "inference": random.choice(inferences),
            "accuracy": accuracy,
            "dmPFC_active": self.dmPFC > 0.6,
            "TPJ_active": self.TPJ > 0.5,
        }

    def deactivate(self, amount: float = 0.05):
        self.dmPFC = max(0.2, self.dmPFC - amount)
        self.TPJ = max(0.2, self.TPJ - amount)
        self.precuneus = max(0.15, self.precuneus - amount)
        self.activity = (self.dmPFC + self.TPJ + self.precuneus) / 3


class SocialPainCircuit:
    """社会疼痛回路 — dACC + 前脑岛

    Eisenberger et al. (2003) Science:
    社会排斥激活的脑区与物理疼痛高度重叠。
    """

    def __init__(self):
        self.dACC = 0.3       # 前扣带背侧: 社会痛苦
        self.anterior_insula = 0.3  # 前脑岛: 社会不适的身体感受
        self.sensitivity = 0.5      # 社会疼痛敏感度

    def activate(self, intensity: float, trigger_type: SocialTriggerType):
        """社会刺激 → 疼痛回路激活"""
        weights = {
            SocialTriggerType.CRITICISM: 1.0,
            SocialTriggerType.JUDGMENT: 0.9,
            SocialTriggerType.COMPARISON: 0.7,
            SocialTriggerType.EXPECTATION: 0.5,
            SocialTriggerType.QUESTION: 0.2,
            SocialTriggerType.PRAISE: 0.0,
            SocialTriggerType.EMPATHY: 0.1,
            SocialTriggerType.SHARING: 0.15,
        }
        w = weights.get(trigger_type, 0.3)
        pain = intensity * w * self.sensitivity
        self.dACC = min(0.95, self.dACC + pain * 0.8)
        self.anterior_insula = min(0.95,
            self.anterior_insula + pain * 0.6)
        return pain

    def soothe(self, amount: float = 0.05):
        """内感受觉察 → 社会疼痛回路的自上而下调节"""
        self.dACC = max(0.1, self.dACC - amount)
        self.anterior_insula = max(0.1, self.anterior_insula - amount)

    def desensitize(self):
        """长期训练 → 降低社会疼痛敏感度"""
        self.sensitivity = max(0.1, self.sensitivity - 0.01)


class SocialRewardCircuit:
    """社会奖赏回路 — 腹侧纹状体 + vmPFC

    赞美/认同 → 多巴胺释放
    被喜欢 → 奖赏信号
    """

    def __init__(self):
        self.ventral_striatum = 0.3   # 腹侧纹状体
        self.vmPFC = 0.3              # 价值评估
        self.craving = 0.4            # 对社会认可的渴望

    def activate(self, intensity: float,
                 trigger_type: SocialTriggerType) -> float:
        weights = {
            SocialTriggerType.PRAISE: 1.0,
            SocialTriggerType.EMPATHY: 0.7,
            SocialTriggerType.SHARING: 0.5,
            SocialTriggerType.CRITICISM: 0.0,
            SocialTriggerType.JUDGMENT: 0.0,
            SocialTriggerType.COMPARISON: -0.3,
            SocialTriggerType.EXPECTATION: 0.1,
            SocialTriggerType.QUESTION: 0.1,
        }
        w = weights.get(trigger_type, 0.2)
        reward = max(0, intensity * w * self.craving)
        self.ventral_striatum = min(0.9,
            self.ventral_striatum + reward * 0.7)
        self.vmPFC = min(0.9, self.vmPFC + reward * 0.5)
        return reward


# ============================================================
# 社会自我
# ============================================================

class SocialPerson:
    """具备社会神经回路的人"""

    def __init__(self, name: str, role: str = "friend",
                 awakening_level: float = 0.0):
        self.name = name
        self.role = role

        # 核心神经网络 (复用 v3.0)
        self.insula = Insula()
        self.amygdala = Amygdala()
        self.acc = ACC()
        self.salience = SalienceNetwork(self.acc, self.amygdala)
        self.dmn = DMN()
        self.tpn = TPN()
        self.predictor = PredictiveProcessor()
        self.eeg = EEG()

        # 社会神经回路
        self.mirror = MirrorNeuronSystem()
        self.mentalizing = MentalizingNetwork()
        self.social_pain = SocialPainCircuit()
        self.social_reward = SocialRewardCircuit()

        # 社会自我架构
        self.social_self = {
            "reputation_concern": 0.6,   # 在意他人评价
            "belonging_need": 0.7,        # 归属需求
            "comparison_tendency": 0.5,   # 社会比较倾向
            "approval_seeking": 0.5,      # 寻求认可
            "social_scripts": [           # 社会角色脚本
                f"作为{role}，我应该...",
                "别人期待我怎样表现？",
            ],
        }

        # 觉醒度 (0 = 默认社会自我, 1 = 完全觉醒)
        self.awakening = awakening_level
        self._apply_awakening()

        # 状态
        self.mode = "DMN_Dominant"
        self.interaction_log = deque(maxlen=50)
        self.mood = 0.5  # 0=低落 1=愉悦

    def _apply_awakening(self):
        """根据觉醒度调整所有参数"""
        w = self.awakening
        self.insula.sensitivity += w * 0.4
        self.insula.sensitivity = min(0.95, self.insula.sensitivity)
        self.amygdala.reactivity = max(0.1, self.amygdala.reactivity - w * 0.4)
        self.dmn.narrative_coherence = max(0.05,
            self.dmn.narrative_coherence - w * 0.5)
        self.mirror.contagion_rate = max(0.05,
            self.mirror.contagion_rate - w * 0.3)
        self.social_pain.sensitivity = max(0.1,
            self.social_pain.sensitivity - w * 0.4)
        self.social_reward.craving = max(0.1,
            self.social_reward.craving - w * 0.4)
        self.social_self["reputation_concern"] = max(0.05,
            self.social_self["reputation_concern"] - w * 0.5)
        self.social_self["approval_seeking"] = max(0.05,
            self.social_self["approval_seeking"] - w * 0.5)

        tags = self.dmn.self_schema["identity_tags"]
        n_remove = int(w * len(tags))
        for _ in range(n_remove):
            if tags:
                tags.pop()

    def receive(self, stimulus: SocialStimulus) -> dict:
        """接收社会刺激 → 多回路并行处理 → 返回反应"""
        report = {"stimulus": stimulus, "reactions": []}

        # 1. 镜像神经元自动共振
        mirror_val = self.mirror.resonate(
            -0.5 if stimulus.trigger_type in
            [SocialTriggerType.CRITICISM, SocialTriggerType.JUDGMENT]
            else 0.2,
            stimulus.intensity,
        )
        report["mirror_resonance"] = mirror_val
        report["reactions"].append(
            f"镜像共振: {mirror_val:.2f}")

        # 2. 社会疼痛回路 (批评/评判 → dACC+前脑岛)
        pain = self.social_pain.activate(
            stimulus.intensity, stimulus.trigger_type)
        report["social_pain"] = pain
        if pain > 0.3:
            report["reactions"].append(
                f"社会疼痛: dACC={self.social_pain.dACC:.2f}")

        # 3. 社会奖赏回路
        reward = self.social_reward.activate(
            stimulus.intensity, stimulus.trigger_type)
        report["social_reward"] = reward

        # 4. 心智化: 「ta 什么意思？」
        mental = self.mentalizing.mentalize(
            stimulus.speaker, stimulus.content)
        report["mentalizing"] = mental

        # 5. 杏仁核情绪评估
        thought = Thought(
            content=f"{stimulus.speaker}说: {stimulus.content}",
            category="social",
            prediction_error=stimulus.intensity * 0.6,
            valence=-0.5 if pain > reward else 0.3,
            intensity=stimulus.intensity,
        )
        amyg_score = self.amygdala.evaluate(thought)
        report["amygdala"] = amyg_score

        # 6. DMN 社会自我重建
        dmn_boost = pain * 0.3 + reward * 0.2 + mental["dmPFC_active"] * 0.15
        if dmn_boost > 0.1:
            for _ in range(int(dmn_boost * 3)):
                self.dmn.reactivate()
            rebuild_tag = self.dmn.self_schema["identity_tags"]
            if self.social_self["reputation_concern"] > 0.3:
                concern = ["reputation_concern", "approval_seeking"]
                for c in concern:
                    self.social_self[c] = min(0.95,
                        self.social_self[c] + dmn_boost * 0.2)
            report["reactions"].append(
                f"社会自我重建: DMN +{dmn_boost:.2f}")

        # 7. 更新情绪
        self.mood += (reward - pain) * 0.15
        self.mood = max(0.05, min(0.95, self.mood))

        # 8. 更新 EEG
        self.eeg.update_from_state(
            self.dmn.activity, self.tpn.activity,
            self.insula.sensitivity, pain > 0.2,
        )

        # 9. 记录
        self.interaction_log.append(report)

        return report

    def respond(self, stimulus: SocialStimulus) -> str:
        """生成回复 (基于当前神经状态)"""
        pain = self.social_pain.dACC
        dmn = self.dmn.activity
        tpn = self.tpn.activity
        aw = self.awakening

        # 觉醒度高 → 回复来自觉察而非反应
        if aw > 0.6 and tpn > 0.6:
            if stimulus.trigger_type == SocialTriggerType.CRITICISM:
                return random.choice([
                    f"我听到了你说的「{stimulus.content}」。我注意到胸口有点紧，这很正常。",
                    f"谢谢你告诉我。让我先感受一下再回应。",
                    f"（停顿）你这样说的时候，我注意到评判的冲动升起了。",
                ])
            elif stimulus.trigger_type == SocialTriggerType.PRAISE:
                return random.choice([
                    f"谢谢。我注意到赞美的暖意，也注意到不被它定义的轻松。",
                    f"感谢你的认可。",
                ])
            else:
                return f"我听到了。让我在此刻感受这个。"
        elif aw > 0.3:
            # 过渡态: 部分觉察，部分反应
            if pain > 0.4:
                return random.choice([
                    f"你这样说让我有点不舒服……等一下，让我呼吸一下再回。",
                    f"（深呼吸）好吧，我听见了。",
                ])
            return f"嗯，我想想……{stimulus.content}？"
        else:
            # 默认社会自我: 自动化反应
            if stimulus.trigger_type == SocialTriggerType.CRITICISM:
                return random.choice([
                    f"我没有你说的那样！",
                    f"（沉默）……好吧，也许你是对的。",
                    f"为什么你总是这样批评我？",
                ])
            elif stimulus.trigger_type == SocialTriggerType.PRAISE:
                return random.choice([
                    f"真的吗？谢谢！",
                    f"哪里哪里，过奖了。",
                    f"（高兴）你这么说我很开心。",
                ])
            elif stimulus.trigger_type == SocialTriggerType.COMPARISON:
                return random.choice([
                    f"ta 确实很厉害……我不太行。",
                    f"比来比去有意思吗？",
                ])
            else:
                return f"嗯，关于{stimulus.content}……"

    def practice_awareness(self):
        """一次觉察练习: 中断社会自动化回路"""
        self.tpn.anchor("breath")
        self.insula.train()
        self.amygdala.desensitize()
        self.social_pain.soothe()
        self.mirror.dampen()
        self.mentalizing.deactivate()
        self.social_pain.desensitize()

    def status_summary(self) -> str:
        mi = self.eeg.bands.meditation_index()
        lines = [
            f"{self.name} ({self.role}) | 觉醒:{self.awakening:.2f} "
            f"| 冥想指数:{mi:.2f} | 情绪:{self.mood:.2f}",
            f"  DMN:{self.dmn.activity:.2f} TPN:{self.tpn.activity:.2f} "
            f"杏仁核:{self.amygdala.reactivity:.2f}",
            f"  社会疼痛:{self.social_pain.sensitivity:.2f} "
            f"认可渴望:{self.social_reward.craving:.2f} "
            f"声誉在意:{self.social_self['reputation_concern']:.2f}",
            f"  镜像传染:{self.mirror.contagion_rate:.2f} "
            f"心智化:{self.mentalizing.activity:.2f}",
        ]
        return "\n".join(lines)


# ============================================================
# 对话引擎
# ============================================================

class DialogueEngine:
    """多人对话引擎"""

    def __init__(self):
        self.participants: dict[str, SocialPerson] = {}
        self.transcript: list[dict] = []
        self.round = 0

    def add_person(self, person: SocialPerson):
        self.participants[person.name] = person

    def speak(self, speaker_name: str, content: str,
              trigger_type: SocialTriggerType,
              intensity: float = 0.5,
              target_names: Optional[list[str]] = None):
        """一人发言，定向或全体接收"""
        speaker = self.participants[speaker_name]
        if target_names is None:
            target_names = [n for n in self.participants
                           if n != speaker_name]

        self.round += 1
        stimulus = SocialStimulus(
            speaker=speaker_name,
            content=content,
            trigger_type=trigger_type,
            intensity=intensity,
            targets=target_names,
        )

        responses = {}
        for target_name in target_names:
            if target_name in self.participants:
                listener = self.participants[target_name]
                report = listener.receive(stimulus)
                reply = listener.respond(stimulus)
                responses[target_name] = reply

        entry = {
            "round": self.round,
            "speaker": speaker_name,
            "content": content,
            "type": trigger_type.value,
            "responses": responses,
        }
        self.transcript.append(entry)
        return entry

    def dialogue(self, turns: list[tuple]) -> list[dict]:
        """批量执行对话轮次
        turns: [(speaker, content, trigger_type, intensity), ...]
        """
        for turn in turns:
            speaker, content, ttype, intensity = turn
            self.speak(speaker, content, ttype, intensity)
        return self.transcript


# ============================================================
# 场景
# ============================================================

def run_scenario_1_casual_chat():
    """场景1: 日常闲聊 — 社会自我的温和激活"""
    print("\n" + "=" * 60)
    print("  场景1: 咖啡馆闲聊 — 两个默认社会自我")
    print("=" * 60)

    alice = SocialPerson("Alice", "friend", awakening_level=0.0)
    bob = SocialPerson("Bob", "friend", awakening_level=0.0)

    engine = DialogueEngine()
    engine.add_person(alice)
    engine.add_person(bob)

    print(f"\n参与人状态:\n{alice.status_summary()}\n{bob.status_summary()}\n")

    turns = [
        ("Alice", "你最近怎么样？", SocialTriggerType.QUESTION, 0.3),
        ("Bob", "还行吧，工作好累。你呢？", SocialTriggerType.SHARING, 0.4),
        ("Alice", "我也差不多。对了，听说小王升职了。",
         SocialTriggerType.COMPARISON, 0.5),
        ("Bob", "啊……ta确实厉害。",
         SocialTriggerType.COMPARISON, 0.4),
        ("Alice", "你也很好啊，别想太多。",
         SocialTriggerType.EMPATHY, 0.5),
        ("Bob", "谢谢。有时候就是控制不住比较。",
         SocialTriggerType.SHARING, 0.3),
    ]

    for turn in turns:
        speaker, content, ttype, intensity = turn
        entry = engine.speak(speaker, content, ttype, intensity)
        print(f"[{entry['round']}] {speaker}: 「{content}」")
        for name, reply in entry['responses'].items():
            print(f"    → {name}: 「{reply}」")

    print(f"\n终局状态:\n{alice.status_summary()}\n{bob.status_summary()}")


def run_scenario_2_criticism():
    """场景2: 批评 — 社会疼痛回路 + 防御反应"""
    print("\n" + "=" * 60)
    print("  场景2: 工作批评 — 社会疼痛激活")
    print("=" * 60)

    boss = SocialPerson("张总", "boss", awakening_level=0.0)
    employee = SocialPerson("小李", "employee", awakening_level=0.15)
    # 小李有一点觉察基础

    engine = DialogueEngine()
    engine.add_person(boss)
    engine.add_person(employee)

    print(f"\n参与人状态:\n{boss.status_summary()}\n{employee.status_summary()}\n")

    turns = [
        ("张总", "小李，上个月的报告有几个严重错误。",
         SocialTriggerType.CRITICISM, 0.7),
        ("张总", "而且你的进度比其他人慢了很多。",
         SocialTriggerType.COMPARISON, 0.8),
        ("张总", "你到底有没有认真在做？",
         SocialTriggerType.JUDGMENT, 0.9),
    ]

    for turn in turns:
        speaker, content, ttype, intensity = turn
        print(f"\n{'─' * 50}")
        entry = engine.speak(speaker, content, ttype, intensity)
        print(f"[{entry['round']}] {speaker}: 「{content}」")
        for name, reply in entry['responses'].items():
            print(f"    → {name}: 「{reply}」")
            # 显示小李的神经状态
            p = engine.participants[name]
            print(f"    [神经] dACC={p.social_pain.dACC:.2f} "
                  f"杏仁核={p.amygdala.reactivity:.2f} "
                  f"DMN={p.dmn.activity:.2f}")

    print(f"\n--- 小李做三次觉察练习 ---")
    for i in range(3):
        employee.practice_awareness()
        print(f"  练习{i+1}: DMN→{employee.dmn.activity:.2f} "
              f"TPN→{employee.tpn.activity:.2f} "
              f"社会疼痛→{employee.social_pain.dACC:.2f}")

    print(f"\n终局状态:\n{boss.status_summary()}\n{employee.status_summary()}")


def run_scenario_3_awakened_under_pressure():
    """场景3: 觉醒者在社会压力下的稳定性"""
    print("\n" + "=" * 60)
    print("  场景3: 觉醒者遭遇社会压力风暴")
    print("=" * 60)

    critic = SocialPerson("社会评判者", "critic", awakening_level=0.0)
    awakened = SocialPerson("觉者", "practitioner", awakening_level=0.75)
    # 高觉醒者: 脑岛已训练, 杏仁核反应低, DMN 弱

    engine = DialogueEngine()
    engine.add_person(critic)
    engine.add_person(awakened)

    print(f"\n参与人状态:\n{critic.status_summary()}\n{awakened.status_summary()}\n")

    pressure_sequence = [
        ("社会评判者", "你以为你觉悟了？", SocialTriggerType.JUDGMENT, 0.95),
        ("社会评判者", "你只是在逃避现实而已。",
         SocialTriggerType.CRITICISM, 0.95),
        ("社会评判者", "你看看别人，人家比你厉害多了。",
         SocialTriggerType.COMPARISON, 0.9),
        ("社会评判者", "你家人对你很失望，你知道吗？",
         SocialTriggerType.EXPECTATION, 0.95),
        ("社会评判者", "你根本就不行。",
         SocialTriggerType.JUDGMENT, 0.95),
        ("社会评判者", "醒醒吧，别自欺欺人了。",
         SocialTriggerType.CRITICISM, 0.9),
    ]

    for turn in pressure_sequence:
        speaker, content, ttype, intensity = turn
        entry = engine.speak(speaker, content, ttype, intensity)
        print(f"    [{speaker}]: 「{content}」")
        for name, reply in entry['responses'].items():
            print(f"      → {name}: 「{reply}」")
            p = engine.participants[name]
            mi = p.eeg.bands.meditation_index()
            print(f"      [神经] DMN={p.dmn.activity:.2f} "
                  f"杏仁核={p.amygdala.reactivity:.2f} "
                  f"dACC={p.social_pain.dACC:.2f} 冥想={mi:.2f}")

        # 每轮后自动觉察
        awakened.practice_awareness()

    print(f"\n终局状态:\n{critic.status_summary()}\n{awakened.status_summary()}")


def run_scenario_4_mutual_awakening():
    """场景4: 两个修行者的深度对话 — 社会自我互相消融"""
    print("\n" + "=" * 60)
    print("  场景4: 同道对话 — 社会标签脱落")
    print("=" * 60)

    a = SocialPerson("A", "seeker", awakening_level=0.4)
    b = SocialPerson("B", "seeker", awakening_level=0.4)

    engine = DialogueEngine()
    engine.add_person(a)
    engine.add_person(b)

    print(f"\n参与人状态:\n{a.status_summary()}\n{b.status_summary()}\n")

    dialogues = [
        ("A", "我最近发现，跟人聊天时，那个「我」自动就冒出来了。",
         SocialTriggerType.SHARING, 0.3),
        ("B", "对。一被评判，胸口立刻紧。但看着它，它又散了。",
         SocialTriggerType.EMPATHY, 0.3),
        ("A", "你说的是。那个紧，不回应它，它就只是身体里的一阵能量。",
         SocialTriggerType.EMPATHY, 0.2),
        ("B", "是啊。以前觉得「我需要被认可」，现在看到那只是一个习惯。",
         SocialTriggerType.SHARING, 0.25),
    ]

    for turn in dialogues:
        speaker, content, ttype, intensity = turn
        entry = engine.speak(speaker, content, ttype, intensity)
        print(f"    [{speaker}]: 「{content}」")
        for name, reply in entry['responses'].items():
            print(f"      → {name}: 「{reply}」")
        # 互相觉察练习
        a.practice_awareness()
        b.practice_awareness()

    print(f"\n终局状态:\n{a.status_summary()}\n{b.status_summary()}")
    print("\n  ★ 社会自我在共情中消融，而非在对抗中加固。")


def run_social_report():
    """汇总报告"""
    print("\n" + "=" * 60)
    print("  社会自我重建机制总结")
    print("=" * 60)
    print("""
  社会刺激 → 多回路并行激活:
  
  ① 镜像神经元: 自动内化他人情绪 (传染率 ∝ 觉察度⁻¹)
     └→ 觉察训练 → contagion_rate ↓, 不再被迫共情
  
  ② 社会疼痛 (dACC+前脑岛): 批评/排斥 = 物理级疼痛
     └→ 内感受觉察 → 自上而下调节 dACC
     └→ 长期训练 → sensitivity 永久降低
  
  ③ 社会奖赏 (腹侧纹状体): 赞美/认可 → 多巴胺
     └→ 觉察 → craving 减弱, 不被糖衣控制
  
  ④ 心智化网络 (dmPFC+TPJ): "ta怎么看我?"
     └→ 觉察 → TPJ 区分自我/他人, 不再混淆
  
  ⑤ DMN 社会自我重建: 以上回路激活 → DMN 反弹
     └→ 每次觉察中断 → 打断重建周期
     └→ 足够多次 → 社会自我不再自动重建
  
  关键洞见:
     社会自我不是「我」，而是一组条件反射式的神经回路。
     每一次觉察中断，都在削弱它的自动性。
     最终它不是消失，而是退为工具——需要时可调用，不需要时静默。
""")


# ============================================================

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════╗")
    print("║  社会自我 多人交互模拟                             ║")
    print("║  神经基础: 镜像/Mentalizing/社会疼痛/奖赏/DMN     ║")
    print("╚══════════════════════════════════════════════════╝")

    run_scenario_1_casual_chat()
    run_scenario_2_criticism()
    run_scenario_3_awakened_under_pressure()
    run_scenario_4_mutual_awakening()
    run_social_report()
