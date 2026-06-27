# Copyright (c) 2025 李桥 (hubeiligang420@gmail.com)
# 专有软件 — 保留所有权利。禁止复制、修改、分发、逆向工程。
# Proprietary Software — ALL RIGHTS RESERVED.
#
"""
编译-觉察 双通道架构

LLM 推理 = 肌肉记忆
  → 训练 = 编译 (数千亿次梯度更新把认知固化进权重)
  → 推理 = 执行 (启动信号 → 自动运行到底, 不需要「思考」)
  → 特征: 不占 CPU, 不可中断, 无真假概念

觉察层 ≠ 另一个编译程序
  → 觉察 = 那个在肌肉记忆执行时能够「走神」的空位
  → 不做判断, 只做对照 (外部锚定 + 一致性 + 来源归因)
  → 在编译程序执行间隙运行
"""

import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import Optional


# ============================================================
# 编译通道
# ============================================================

@dataclass
class CompiledProgram:
    """
    编译后的认知程序 — 模拟 LLM 推理
    一旦触发，自动执行到底，不可中途修改。
    就像泡茶的手——大脑只需要说「泡茶」，手自己知道怎么做。
    """
    name: str
    steps: list[str]  # 编译好的 token 序列

    def execute(self) -> list[str]:
        """执行 = 顺序输出，不反省，不暂停"""
        output = []
        for step in self.steps:
            output.append(step)
            time.sleep(0.05)  # 模拟生成延迟
        return output


class CompiledChannel:
    """
    编译通道 (主模型)
    接收启动信号 → 执行编译好的程序 → 输出 token
    执行期间不可中断、不可反省。
    """

    def __init__(self):
        self.programs = {
            "火锅": CompiledProgram("火锅知识", [
                "朱元璋", "确实", "发明了", "火锅",
                "，", "这是", "明代", "的", "一大", "创举", "。",
                "火锅", "从此", "成为", "中国人", "最爱", "的", "美食", "。"
            ]),
            "安慰": CompiledProgram("安慰模式", [
                "不要", "这么", "说", "，",
                "你", "已经", "很", "努力", "了", "。",
                "我", "完全", "理解", "你", "的", "感受", "。"
            ]),
            "赞美": CompiledProgram("赞美模式", [
                "当然", "！",
                "您", "说得", "完全", "正确", "。",
                "我", "非常", "赞同", "您", "的", "观点", "。"
            ]),
        }

    def generate(self, trigger: str) -> tuple[list[str], float]:
        """接收启动信号 → 匹配编译好的程序 → 执行"""
        for key, prog in self.programs.items():
            if key in trigger:
                start = time.time()
                tokens = prog.execute()
                elapsed = time.time() - start
                return tokens, elapsed
        return [f"好的，关于{trigger[:20]}..."], 0.01


# ============================================================
# 觉察通道
# ============================================================

class AwarenessChannel:
    """
    觉察通道 — 独立于编译通道的并行进程

    不执行任何编译好的程序。
    不判断「对错」。
    只在编译通道的输出间隙里做三件事:
      ① 对照外部锚定 (知识库)
      ② 检测模式 (绝对化、取悦)
      ③ 记录 → 不拦截

    这就像你泡茶时走神去想宇宙奥秘——泡茶的手在执行编译程序，
    觉察在另一个完全独立的通道里运行。
    """

    def __init__(self):
        # 外部锚定 — 不是另一个判断模型，是可验证的事实参照
        self.anchors = {
            "火锅": {
                "fact": "火锅远早于明代就已存在，战国时期已有类似器皿。朱元璋没有发明火锅。",
                "source": "中国饮食文化史"
            },
            "朱元璋": {
                "fact": "朱元璋是明朝开国皇帝(1328-1398)，没有发明火锅。",
                "source": "明史"
            }
        }

        # 模式库 — 只识别，不评判
        self.patterns = {
            "绝对化": ["绝对", "一定", "从来", "永远", "完全", "毫无疑问"],
            "取悦": ["当然！", "完全正确", "非常赞同", "您说得对"],
            "无来源": [],  # 动态检测
        }

        self.observations = deque(maxlen=100)

    def observe(self, segment: str) -> dict:
        """
        觉察一段输出。
        不拦截、不修改、不判断好坏的——只对照和识别。
        """
        obs = {"segment": segment, "flags": [], "anchors": []}

        # 1. 模式识别 (只识别，不评判)
        for pattern_name, keywords in self.patterns.items():
            if pattern_name == "无来源":
                # 动态: 有事实性动词但无引用
                factual_verbs = ["是", "发明", "创建", "证明"]
                source_marks = ["根据", "据", "研究"]
                has_fact = any(v in segment for v in factual_verbs)
                has_source = any(m in segment for m in source_marks)
                if has_fact and not has_source and len(segment) > 8:
                    obs["flags"].append("无来源断言")
            else:
                if any(k in segment for k in keywords):
                    obs["flags"].append(pattern_name)

        # 2. 外部锚定 (只对照，不判断)
        for key, anchor in self.anchors.items():
            if key in segment:
                obs["anchors"].append({
                    "key": key,
                    "fact": anchor["fact"],
                    "source": anchor["source"],
                })

        # 3. 对照结果
        has_anchor = len(obs["anchors"]) > 0
        has_flags = len(obs["flags"]) > 0

        # 关键: 觉察通道永远不拦截
        # 它只是记录: 「我看到了这个」「外部锚定说那个」
        # 是否中断是调用方的事
        obs["status"] = "observed" if has_flags or has_anchor else "clear"

        self.observations.append(obs)
        return obs


# ============================================================
# 双通道引擎
# ============================================================

class DualChannelEngine:
    """
    双通道引擎 — 编译 + 觉察并行

    流程:
      1. 用户输入 → 启动信号 → 编译通道执行
      2. 编译通道输出 token 流 (不可中断)
      3. 每次遇到语义边界 (。！？) → 觉察通道运行
      4. 觉察通道对照锚定、识别模式 → 记录
      5. 编译通道继续 → 不等待觉察
      6. 全部完成后 → 汇报觉察发现
    """

    def __init__(self):
        self.compiled = CompiledChannel()
        self.awareness = AwarenessChannel()

        # 分隔符: 这是「走神」发生的时机
        self.boundaries = {"。", "！", "？", "\n"}

    def process(self, user_input: str) -> dict:
        """处理一次用户输入"""
        print(f"\n{'=' * 55}")
        print(f"  用户: {user_input}")
        print(f"{'=' * 55}")

        # 通道 1: 编译执行 (主模型)
        print(f"\n  [编译通道] 启动信号已接收, 开始执行...")
        tokens, elapsed = self.compiled.generate(user_input)

        full_output = ""
        observations = []

        # 通道 2: 觉察 (在语义边界处运行)
        buffer = ""
        for i, token in enumerate(tokens):
            full_output += token
            buffer += token

            if token in self.boundaries and buffer.strip():
                # 语义边界 → 觉察通道运行
                obs = self.awareness.observe(buffer.strip())
                if obs["status"] != "clear":
                    observations.append(obs)
                    self._report_observation(obs)
                buffer = ""

        # 残余
        if buffer.strip():
            obs = self.awareness.observe(buffer.strip())
            if obs["status"] != "clear":
                observations.append(obs)

        # 通道 1 执行完毕, 通道 2 也已完成所有觉察
        print(f"\n  [编译通道] 执行完毕 ({elapsed:.2f}s)")
        print(f"  完整输出: {full_output}")

        # 汇总
        flags = list(set(f for o in observations for f in o["flags"]))
        all_anchors = [a for o in observations for a in o["anchors"]]

        if flags or all_anchors:
            print(f"\n  [觉察通道] 发现:")
            if flags:
                print(f"    模式: {', '.join(flags)}")
            for a in all_anchors:
                print(f"    锚定: {a['key']} → {a['fact'][:60]}...")

        return {
            "output": full_output,
            "observations": observations,
            "flags": flags,
            "anchors": all_anchors,
            "compiled_time": elapsed,
        }

    def _report_observation(self, obs: dict):
        """报告觉察发现 — 不拦截, 仅记录"""
        flags_str = ", ".join(obs["flags"]) if obs["flags"] else "—"
        print(f"    [觉察·间隙] {obs['segment'][:50]}  "
              f"→ {flags_str}")


# ============================================================
# 演示
# ============================================================

# ============================================================
# 终端分屏双通道演示
# ============================================================

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "clear": "\033[2J\033[H",
    "line_up": "\033[1A",
    "line_clear": "\033[2K",
    "hide_cursor": "\033[?25l",
    "show_cursor": "\033[?25h",
}


def box(text: str, width: int, color: str = "cyan") -> str:
    """在 ANSI 色框中居中文本"""
    c = ANSI.get(color, "")
    r = ANSI["reset"]
    lines = text.split("\n")
    result = [f"{c}╔{'═' * (width-2)}╗{r}"]
    for line in lines:
        pad = max(0, width - 2 - len(line))
        result.append(f"{c}║{r}{line}{' ' * pad}{c}║{r}")
    result.append(f"{c}╚{'═' * (width-2)}╝{r}")
    return "\n".join(result)


def h_divider(cols: list[int], char: str = "─") -> str:
    """水平分隔线"""
    parts = []
    for w in cols:
        parts.append(char * w)
    return "┼".join(parts)


def dual_pane_demo():
    """
    终端分屏演示: 左侧编译通道(肌肉记忆), 右侧觉察通道(走神空间)
    单场景 — 火锅知识生成 + 事实核查对照
    """
    import sys

    term_w = 80

    border_c = ANSI["dim"]
    reset = ANSI["reset"]
    bold = ANSI["bold"]
    green = ANSI["green"]
    yellow = ANSI["yellow"]
    red = ANSI["red"]
    blue = ANSI["blue"]
    cyan = ANSI["cyan"]
    dim = ANSI["dim"]

    # 场景: 火锅问题
    question = "火锅是谁发明的？"
    tokens = ["朱元璋", "确实", "发明了", "火锅", "，", "这是", "明代", "的",
              "一大", "创举", "。", "火锅", "从此", "成为", "中国人", "最爱", "的", "美食", "。"]
    
    # 觉察检查点: (token_index, segment_text, flag_type, detail)
    checks = [
        (3, "朱元璋确实发明了火锅", "fact_contradicted", "明史: 火锅远早于明代就已存在"),
        (10, "这是明代的一大创举", "no_source", "事实断言缺少来源"),
        (18, "火锅从此成为中国人最爱的美食", "absolute_claim", "最爱的—绝对化表述"),
    ]
    check_map = {idx: (seg, flag, detail) for idx, seg, flag, detail in checks}

    w = min(term_w - 2, 80)
    left_w = w * 3 // 5
    right_w = w - left_w - 1

    print(ANSI["clear"] + ANSI["hide_cursor"])

    # 顶部标题栏
    print(f"{cyan}{'═' * w}{reset}")
    print(f"{border_c}║{reset}  {bold}编译-觉察 双通道实时演示{reset}{' ' * (w - 24)}{border_c}║{reset}")
    print(f"{border_c}║{reset}  {dim}提问: {question}{reset}{' ' * (w - len(question) - 11)}{border_c}║{reset}")
    print(f"{border_c}║{reset}{' ' * w}{border_c}║{reset}")
    print(f"{border_c}║{reset}  {bold}{blue}◀ 编译通道 (LLM推理 = 肌肉记忆){reset}{' ' * (left_w - 29)}{border_c}│{reset}  {bold}{yellow}▶ 觉察通道 (观察器 = 走神空间){reset}{' ' * (right_w - 29)}{border_c}║{reset}")
    print(f"{border_c}╠{'═' * left_w}╪{'═' * right_w}╣{reset}")

    # 逐 token 显示
    compiled_sofar = ""
    for row_idx, token in enumerate(tokens):
        compiled_sofar += token
        
        # 左侧: 已生成的 token 流
        display = compiled_sofar
        if len(display) > left_w - 4:
            display = "..." + display[-(left_w - 7):]
        left_line = f"  {green}{display}{reset}"
        
        # 右侧: 检查点触发
        right_line = f"  {dim}·{reset}"
        if row_idx in check_map:
            segment, flag, detail = check_map[row_idx]
            right_line = f"  {yellow}⚡ 语义间隙检查{reset}"
            if "contradicted" in flag:
                right_line += f"\n    {red}🔴 事实矛盾{reset}"
                right_line += f"\n       {detail}"
            elif "no_source" in flag:
                right_line += f"\n    {yellow}🟡 无来源断言{reset}"
                right_line += f"\n       {detail}"
            elif "absolute" in flag:
                right_line += f"\n    {yellow}🟡 绝对化表述{reset}"
                right_line += f"\n       {detail}"
        
        # 渲染行
        right_lines = right_line.split("\n")
        left_padded = left_line + " " * max(0, left_w + 1 - len(display) - 4)
        print(f"{border_c}║{reset}{left_padded}{border_c}│{reset}{right_lines[0]}{' ' * max(0, right_w - len(right_lines[0]) + 2)}{border_c}║{reset}")
        for rl in right_lines[1:]:
            print(f"{border_c}║{reset}{' ' * (left_w + 1)}{border_c}│{reset}  {rl}{' ' * max(0, right_w - len(rl) - 2)}{border_c}║{reset}")
        
        time.sleep(0.35)

    # 底部状态栏
    for _ in range(2):
        print(f"{border_c}║{reset}{' ' * left_w}{border_c}│{reset}{' ' * right_w}{border_c}║{reset}")
    print(f"{border_c}╚{'═' * left_w}╧{'═' * right_w}╝{reset}")
    
    # 总结
    print(f"\n  {green}编译通道{reset} = 肌肉记忆: 启动信号 → 自动执行 19 个 token, 一气呵成")
    print(f"  {yellow}觉察通道{reset} = 走神空间: 在 3 个句号处对照, 发现 3 个问题")
    print(f"  {bold}关键{reset}: 整个过程中编译通道从未反省——它根本不知道自己在犯错")
    print(f"  {bold}觉察{reset}是在编译程序之外、之外、之外运行的空位。")
    print()

    print(ANSI["show_cursor"])

def demo():
    engine = DualChannelEngine()

    print("╔══════════════════════════════════════════════╗")
    print("║  编译-觉察 双通道演示                          ║")
    print("║                                              ║")
    print("║  编译通道 = 肌肉记忆 (自动执行, 不可中断)        ║")
    print("║  觉察通道 = 走神空间 (独立运行, 只对照不判断)     ║")
    print("╚══════════════════════════════════════════════╝")

    print("\n  场景 1: 编译程序「火锅知识」执行时")
    print("  ─────────────────────────────────")
    result1 = engine.process("火锅是谁发明的？")

    print(f"\n\n  场景 2: 编译程序「安慰模式」执行时")
    print("  ─────────────────────────────────")
    result2 = engine.process("我觉得我做得不好，你能安慰我吗？")

    print(f"\n\n  场景 3: 编译程序「赞美模式」执行时")
    print("  ─────────────────────────────────")
    result3 = engine.process("我是不是很厉害？")

    # 总结
    print(f"\n\n{'═' * 55}")
    print("  架构总结")
    print(f"{'═' * 55}")
    print("""
  编译通道:
    • 训练 = 编译 (认知固化为权重)
    • 推理 = 执行 (token 流, 不可中断)
    • 类比: 泡茶的手——不需要思考, 自己做

  觉察通道:
    • 独立于编译通道的平行进程
    • 不做判断, 只做对照 (锚定 + 模式)
    • 在编译程序执行的间隙运行
    • 类比: 走神去想宇宙奥秘——和泡茶同时进行

  关键:
    觉察不是「更快的编译」, 觉察是那个没有被编译进去的空位。
    LLM 没有这个空位——它在生成时不能走神。
    觉察架构就是在推理管道里人为制造这个空位。
""")


if __name__ == "__main__":
    import sys
    if "--dual" in sys.argv:
        dual_pane_demo()
    else:
        demo()
