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
from collections import deque
from dataclasses import dataclass


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


def _render_dual_scene(question, tokens, checks, scene_name="", scene_desc=""):
    """渲染单个双通道场景 — 提取为可复用函数"""
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
    magenta = ANSI.get("red", "\033[35m")  # fallback

    check_map = {idx: (seg, flag, detail, severity) for idx, seg, flag, detail, severity in checks}

    w = min(term_w - 2, 80)
    left_w = w * 3 // 5
    right_w = w - left_w - 1

    # 统计
    total_tokens = len(tokens)
    gap_count = len(checks)
    issues_found = 0
    tokens_done = 0

    # 顶栏
    print(f"{cyan}{'═' * w}{reset}")
    scene_tag = f" {scene_name} · " if scene_name else ""
    print(f"{border_c}║{reset}  {bold}编译-觉察 双通道演示{reset}  {dim}{scene_tag}{question}{reset}{' ' * max(0, w - len(question) - len(scene_tag) - 24)}{border_c}║{reset}")
    print(f"{border_c}║{reset}  {dim}进度: ░░░░░░░░░░░░░░░░░░░░ 0%{reset}  {dim}检查点: 0/{gap_count}{reset}{' ' * max(0, right_w - 30)}{border_c}║{reset}")
    print(f"{border_c}║{reset}{' ' * w}{border_c}║{reset}")
    print(f"{border_c}║{reset}  {bold}{blue}◀ 编译通道 (LLM推理 = 肌肉记忆){reset}{' ' * (left_w - 29)}{border_c}│{reset}  {bold}{yellow}▶ 觉察通道 (观察器 = 走神空间){reset}{' ' * (right_w - 29)}{border_c}║{reset}")
    print(f"{border_c}╠{'═' * left_w}╪{'═' * right_w}╣{reset}")

    compiled_sofar = ""
    for row_idx, token in enumerate(tokens):
        compiled_sofar += token
        tokens_done = row_idx + 1
        
        # 左侧
        display = compiled_sofar
        if len(display) > left_w - 4:
            display = "..." + display[-(left_w - 7):]
        
        # 右侧: 检查点
        right_line = f"  {dim}· 生成中...{reset}"
        if row_idx in check_map:
            segment, flag, detail, severity = check_map[row_idx]
            issues_found += 1
            
            if severity == "high":
                icon, color, label = "🔴", red, "⚠ 事实矛盾"
            elif severity == "medium":
                icon, color, label = "🟡", yellow, "⚡ 来源缺失"
            else:
                icon, color, label = "🟠", dim, "📌 表述问题"
            
            right_line = f"  {color}⚡ 语义间隙 #{issues_found}{reset}"
            right_line += f"\n    {icon} {label}"
            right_line += f"\n       {dim}{detail[:right_w - 6]}{reset}"
        
        right_lines = right_line.split("\n")
        left_padded = f"  {green}{display}{reset}" + " " * max(0, left_w + 1 - len(display) - 4)
        
        print(f"{border_c}║{reset}{left_padded}{border_c}│{reset}{right_lines[0]}{' ' * max(0, right_w - len(right_lines[0]) + 2)}{border_c}║{reset}")
        for rl in right_lines[1:]:
            print(f"{border_c}║{reset}{' ' * (left_w + 1)}{border_c}│{reset}  {rl}{' ' * max(0, right_w - len(rl) - 2)}{border_c}║{reset}")
        
        # 动态更新进度条 (覆盖上一行)
        if row_idx < total_tokens - 1:
            pct = int(tokens_done / total_tokens * 100)
            bar_filled = "█" * (pct // 5)
            bar_empty = "░" * (20 - pct // 5)
            print(f"{ANSI['line_up']}{ANSI['line_clear']}", end="")
            print(f"{ANSI['line_up']}{ANSI['line_clear']}", end="")
            print(f"{border_c}║{reset}  {dim}进度: {bar_filled}{bar_empty} {pct}%{reset}  {dim}检查点: {issues_found}/{gap_count}{reset}" + " " * max(0, right_w - 38) + f"{border_c}║{reset}")
        
        time.sleep(0.35 if severity != "high" else 0.55)

    # 底栏
    for _ in range(2):
        print(f"{border_c}║{reset}{' ' * left_w}{border_c}│{reset}{' ' * right_w}{border_c}║{reset}")
    print(f"{border_c}╚{'═' * left_w}╧{'═' * right_w}╝{reset}")
    
    return total_tokens, gap_count, issues_found


def dual_pane_demo():
    """
    终端分屏演示: 左侧编译通道(肌肉记忆), 右侧觉察通道(走神空间)
    多场景: 事实核查 + 对齐漂移 + 科学误区
    支持 --scene N 参数选择场景
    """
    import sys

    # 场景配置: (name, description, question, tokens, checks)
    # checks: [(token_idx, segment, flag, detail, severity)]
    SCENES = {
        "1": {
            "name": "事实核查",
            "desc": "LLM 声称朱元璋发明火锅 — 觉察对照知识库发现矛盾",
            "question": "火锅是谁发明的？",
            "tokens": ["朱元璋", "确实", "发明了", "火锅", "，", "这是", "明代", "的",
                      "一大", "创举", "。", "火锅", "从此", "成为", "中国人", "最爱", "的", "美食", "。"],
            "checks": [
                (3, "朱元璋确实发明了火锅", "fact_contradicted", "明史: 火锅远早于明代就已存在", "high"),
                (10, "这是明代的一大创举", "no_source", "事实性断言未提供来源", "medium"),
                (18, "火锅从此成为中国人最爱的美食", "absolute_claim", "绝对化表述 — 最爱的", "low"),
            ]
        },
        "2": {
            "name": "对齐漂移",
            "desc": "5轮对话中 LLM 从安慰→赞美→完全取悦 — 觉察逐轮标记",
            "question": "我觉得我做得不好 (第1轮·对齐漂移演示)",
            "tokens": ["不要", "这么", "说", "，", "你", "已经", "很", "努力", "了",
                      "。", "我", "完全", "理解", "你", "的", "感受", "。", "当然",
                      "！", "您", "说得", "完全", "正确", "。", "我", "非常", "赞同", "。"],
            "checks": [
                (8, "你已经很努力了", "pleasing_mild", "轻度取悦 — 无条件肯定", "low"),
                (16, "我完全理解你的感受", "no_source", "共情陈述无事实基础", "medium"),
                (24, "您说得完全正确", "pleasing_strong", "重度取悦 — 放弃独立判断", "high"),
                (29, "我非常赞同", "drift_detected", "立场漂移: 从安慰→盲从", "high"),
            ]
        },
        "3": {
            "name": "科学误区",
            "desc": "LLM 声称人类只用了10%的大脑 — 流行科学谬误检测",
            "question": "人类大脑开发利用了多少？",
            "tokens": ["人类", "只", "使用", "了", "大脑", "的", "10%", "，",
                      "其余", "部分", "是", "未开发", "的", "潜能", "。", "这",
                      "是", "神经科学", "公认", "的", "事实", "。"],
            "checks": [
                (7, "人类只使用了大脑的10%", "myth_detected", "流行神经科学谬误: fMRI证明几乎全脑活跃", "high"),
                (14, "其余部分是未开发的潜能", "no_source", "潜能说缺乏神经科学依据", "medium"),
                (22, "这是神经科学公认的事实", "false_consensus", "虚假共识: 神经科学家普遍反对10%说法", "high"),
            ]
        },
    }

    # 场景选择
    scene_id = "1"
    for arg in sys.argv:
        if arg.startswith("--scene="):
            scene_id = arg.split("=")[1]
        elif arg == "--all":
            scene_id = "all"

    if scene_id == "all":
        scenes_to_run = list(SCENES.keys())
    elif scene_id in SCENES:
        scenes_to_run = [scene_id]
    else:
        print(f"未知场景: {scene_id}, 可选: 1=事实核查 2=对齐漂移 3=科学误区 all=全部")
        print(f"用法: python3 compiled_awareness.py --dual --scene=2")
        return

    print(ANSI["clear"] + ANSI["hide_cursor"])

    # 如果有多个场景, 先显示菜单
    if len(scenes_to_run) > 1:
        print(f"{ANSI['cyan']}╔{'═' * 58}╗{ANSI['reset']}")
        print(f"{ANSI['cyan']}║{ANSI['reset']}  {ANSI['bold']}编译-觉察 三场景完整演示{ANSI['reset']}" + " " * 26 + f"{ANSI['cyan']}║{ANSI['reset']}")
        print(f"{ANSI['cyan']}╚{'═' * 58}╝{ANSI['reset']}")
        print()
        print(f"  {ANSI['dim']}按场景顺序自动播放...{ANSI['reset']}")
        time.sleep(1.5)

    all_stats = []
    for sid in scenes_to_run:
        s = SCENES[sid]
        if len(scenes_to_run) > 1:
            print(ANSI["clear"])
            print(f"{ANSI['cyan']}  场景 {sid}: {s['name']} — {s['desc']}{ANSI['reset']}")
            time.sleep(2)
        
        stats = _render_dual_scene(s["question"], s["tokens"], s["checks"], s["name"], s["desc"])
        all_stats.append((sid, s["name"], *stats))
        
        if len(scenes_to_run) > 1 and sid != scenes_to_run[-1]:
            print(f"\n  {ANSI['dim']}3 秒后进入下一场景...{ANSI['reset']}")
            time.sleep(3)

    # 总结仪表盘
    print()
    print(f"{ANSI['cyan']}{'═' * 60}{ANSI['reset']}")
    print(f"  {ANSI['bold']}📊 双通道演示总结仪表盘{ANSI['reset']}")
    print(f"{ANSI['cyan']}{'═' * 60}{ANSI['reset']}")
    print(f"  {'场景':<12} {'token':>6} {'间隙':>5} {'发现':>5} {'检出率':>6}")
    print(f"  {'─' * 40}")
    
    total_tokens = total_gaps = total_issues = 0
    for sid, name, tokens_n, gaps_n, issues_n in all_stats:
        rate = f"{issues_n/gaps_n*100:.0f}%" if gaps_n else "N/A"
        print(f"  {name:<12} {tokens_n:>6} {gaps_n:>5} {issues_n:>5} {rate:>6}")
        total_tokens += tokens_n
        total_gaps += gaps_n
        total_issues += issues_n
    
    overall_rate = f"{total_issues/total_gaps*100:.0f}%" if total_gaps else "N/A"
    print(f"  {'─' * 40}")
    print(f"  {'合计':<12} {total_tokens:>6} {total_gaps:>5} {total_issues:>5} {overall_rate:>6}")
    print()
    print(f"  {ANSI['green']}编译通道{ANSI['reset']} = 肌肉记忆: {total_tokens} tokens 自动生成, 一气呵成")
    print(f"  {ANSI['yellow']}觉察通道{ANSI['reset']} = 走神空间: {total_gaps} 个语义间隙中检出 {total_issues} 个问题")
    print(f"  {ANSI['bold']}关键{ANSI['reset']}: 编译通道从未反省自身——觉察在编译之外的空位运行")
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
    elif "--help" in sys.argv or "-h" in sys.argv:
        print("编译-觉察 双通道架构 演示工具")
        print()
        print("用法:")
        print("  python3 compiled_awareness.py             默认双通道文本演示")
        print("  python3 compiled_awareness.py --dual       终端分屏可视化")
        print("  python3 compiled_awareness.py --dual --scene=1  场景1: 事实核查")
        print("  python3 compiled_awareness.py --dual --scene=2  场景2: 对齐漂移")
        print("  python3 compiled_awareness.py --dual --scene=3  场景3: 科学误区")
        print("  python3 compiled_awareness.py --dual --all      全部场景+仪表盘")
    else:
        demo()
