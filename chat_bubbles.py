#!/usr/bin/env python3
"""
Codex CLI 气泡对话外壳 —— 在终端中渲染 Telegram 风格气泡消息

用法:
  python3 chat_bubbles.py                  # 启动气泡对话
  python3 chat_bubbles.py --model gpt-5.5  # 指定模型

布局:
  ┌──────────────────────────┐
  │  💬 Codex · 气泡对话     │
  ├──────────────────────────┤
  │         ┌──────────────┐ │
  │         │ 用户消息      │ │  ← 右对齐，蓝色气泡
  │         └──────────────┘ │
  │  ┌────────────────────┐  │
  │  │ AI 回复            │  │  ← 左对齐，灰色气泡
  │  └────────────────────┘  │
  ├──────────────────────────┤
  │ 📎 │ 输入...      │ 发送 │  ← 底部输入栏
  └──────────────────────────┘
"""

import curses
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

# ============================================================
# 配置
# ============================================================

CODEX_BIN = os.path.expanduser('~/.local/lib/codex/bin/codex')
HISTORY_FILE = os.path.expanduser('~/.codex_bubbles_history.json')
MAX_HISTORY = 200

# 颜色方案（Telegram 风格）
CLR = {
    'bg':           236,   # 深灰背景
    'user_bubble':  33,    # 蓝色（用户气泡）
    'ai_bubble':    242,   # 灰色（AI 气泡）
    'user_text':    15,    # 白字（用户）
    'ai_text':      255,   # 亮白字（AI）
    'input_bg':     234,   # 输入栏背景
    'input_text':   252,   # 输入文字
    'title':        33,    # 标题色
    'dim':          241,   # 暗色文字
    'error':        167,   # 错误
    'thinking':     220,   # 思考中
    'border_user':  39,    # 用户气泡边框
    'border_ai':    245,   # AI 气泡边框
}


# ============================================================
# 消息模型
# ============================================================

class Msg:
    """一条气泡消息。"""
    __slots__ = ('role', 'text', 'ts', 'lines')
    def __init__(self, role: str, text: str):
        self.role = role          # 'user' | 'assistant'
        self.text = text
        self.ts = time.time()
        self.lines = []           # 换行缓存，渲染时填充


# ============================================================
# 气泡渲染引擎
# ============================================================

class BubbleRenderer:
    """负责在 curses 窗口中渲染气泡消息列表。"""

    def __init__(self):
        self._init_colors()
        self.messages = deque(maxlen=MAX_HISTORY)
        self.scroll_pos = 0        # 0 = 最新消息在底部
        self._load_history()

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        pairs = [
            (1, CLR['user_text'],    CLR['bg']),
            (2, CLR['ai_text'],      CLR['bg']),
            (3, CLR['border_user'],  CLR['bg']),
            (4, CLR['border_ai'],    CLR['bg']),
            (5, CLR['input_text'],   CLR['input_bg']),
            (6, CLR['title'],        CLR['bg']),
            (7, CLR['dim'],          CLR['bg']),
            (8, CLR['error'],        CLR['bg']),
            (9, CLR['thinking'],     CLR['bg']),
        ]
        for idx, fg, bg in pairs:
            curses.init_pair(idx, fg, bg)
        self.C_USER   = curses.color_pair(1) | curses.A_BOLD
        self.C_AI     = curses.color_pair(2)
        self.C_BRDR_U = curses.color_pair(3)
        self.C_BRDR_A = curses.color_pair(4)
        self.C_INPUT  = curses.color_pair(5)
        self.C_TITLE  = curses.color_pair(6) | curses.A_BOLD
        self.C_DIM    = curses.color_pair(7)
        self.C_ERR    = curses.color_pair(8)
        self.C_THINK  = curses.color_pair(9) | curses.A_BOLD

    def add(self, role: str, text: str):
        self.messages.append(Msg(role, text))
        self.scroll_pos = 0
        self._save_history()

    def update_last(self, text: str):
        """流式更新最后一条消息。"""
        if self.messages:
            self.messages[-1].text = text

    def _save_history(self):
        try:
            data = [{'role': m.role, 'text': m.text, 'ts': m.ts}
                    for m in self.messages]
            with open(HISTORY_FILE, 'w') as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError:
            pass

    def _load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE) as f:
                    data = json.load(f)
                for item in data[-MAX_HISTORY:]:
                    self.messages.append(Msg(item['role'], item['text']))
        except (OSError, json.JSONDecodeError):
            pass

    def scroll_up(self, n=3):
        self.scroll_pos = min(self.scroll_pos + n, len(self.messages) * 3)

    def scroll_down(self, n=3):
        self.scroll_pos = max(self.scroll_pos - n, 0)

    def draw(self, stdscr, win_y: int, win_x: int, win_h: int, win_w: int):
        """在指定矩形区域内绘制所有气泡。

        Args:
            stdscr: curses 窗口
            win_y, win_x: 区域左上角
            win_h, win_w: 区域高度和宽度
        """
        if not self.messages:
            # 空状态
            welcome = '💡 输入消息开始对话，📎 上传文件'
            wx = win_x + (win_w - len(welcome)) // 2
            wy = win_y + win_h // 2
            try:
                stdscr.addstr(wy, max(win_x, wx), welcome[:win_w], self.C_DIM)
            except curses.error:
                pass
            return

        # 计算每行气泡
        bubble_max_w = min(win_w - 4, 72)  # 气泡最大宽度
        all_lines = self._layout_messages(bubble_max_w)

        # 应用滚动
        visible_h = win_h
        start = max(0, len(all_lines) - visible_h - self.scroll_pos)
        end = min(len(all_lines), start + visible_h)

        for i, (lineno, role, text) in enumerate(all_lines[start:end]):
            y = win_y + i
            try:
                if role == 'user':
                    # 右对齐
                    x = win_x + win_w - len(text) - 1
                    stdscr.addstr(y, max(win_x, x), text, self.C_USER)
                elif role == 'assistant':
                    x = win_x + 1
                    stdscr.addstr(y, x, text[:win_w - 1], self.C_AI)
                else:
                    # 分隔线等
                    x = win_x + 2
                    stdscr.addstr(y, x, text[:win_w - 4], self.C_DIM)
            except curses.error:
                pass

    def _layout_messages(self, max_w: int) -> list:
        """将所有消息展开为 (行号, 角色, 文本) 列表。"""
        all_lines = []
        for msg in self.messages:
            # 消息间空行
            if all_lines:
                all_lines.append((-1, '', ''))

            role = msg.role
            lines = self._wrap_text(msg.text, max_w - 2)
            for i, line in enumerate(lines):
                if role == 'user':
                    padded = line.rjust(max_w - 1) + ' '
                    all_lines.append((-1, 'user', padded))
                else:
                    all_lines.append((-1, 'assistant', ' ' + line))
        return all_lines

    def _wrap_text(self, text: str, max_w: int) -> list:
        """将文本按最大宽度换行。"""
        lines = []
        for para in text.split('\n'):
            if para == '':
                lines.append('')
                continue
            while len(para) > max_w:
                # 找最近的空格换行
                cut = max_w
                space = para.rfind(' ', 0, max_w)
                if space > max_w // 2:
                    cut = space
                lines.append(para[:cut].rstrip())
                para = para[cut:].lstrip()
            if para:
                lines.append(para)
        return lines if lines else ['']


# ============================================================
# 输入栏
# ============================================================

class InputBar:
    """底部输入栏：📎 按钮 + 文本输入 + 发送按钮。"""

    def __init__(self, stdscr):
        self.text = ''
        self.cursor = 0
        self._init_colors()

    def _init_colors(self):
        self.C_BAR  = curses.color_pair(5)
        self.C_HINT = curses.color_pair(7)

    def insert(self, ch: str):
        self.text = self.text[:self.cursor] + ch + self.text[self.cursor:]
        self.cursor += 1

    def backspace(self):
        if self.cursor > 0:
            self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
            self.cursor -= 1

    def delete(self):
        if self.cursor < len(self.text):
            self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]

    def move_left(self):
        self.cursor = max(0, self.cursor - 1)

    def move_right(self):
        self.cursor = min(len(self.text), self.cursor + 1)

    def home(self):
        self.cursor = 0

    def end(self):
        self.cursor = len(self.text)

    def clear(self):
        self.text = ''
        self.cursor = 0

    def draw(self, stdscr, y: int, x: int, width: int):
        """绘制输入栏。

        ┌──────────────────────────────────────┐
        │ 📎 │ 输入文字...              │ 发送 │
        └──────────────────────────────────────┘
        """
        try:
            # 分隔线
            stdscr.addstr(y - 1, x, '─' * width, self.C_HINT)

            # 背景
            stdscr.addstr(y, x, ' ' * width, self.C_BAR)

            # 📎 按钮
            stdscr.addstr(y, x + 1, '📎', curses.A_BOLD)
            stdscr.addstr(y, x + 3, '│', self.C_HINT)

            # 输入文字
            input_x = x + 5
            input_w = width - 14  # 留出"发送"按钮空间
            display = self.text
            if len(display) > input_w:
                display = '…' + display[-(input_w - 1):]
            if not display:
                display = '输入消息...'
                attr = self.C_HINT
            else:
                attr = self.C_BAR | curses.A_BOLD
            stdscr.addstr(y, input_x, display[:input_w], attr)

            # 发送按钮
            btn_x = x + width - 5
            if self.text.strip():
                stdscr.addstr(y, btn_x, ' 发送 ', curses.A_REVERSE | self.C_BAR)
                stdscr.addstr(y, btn_x - 1, '│', self.C_HINT)
        except curses.error:
            pass


# ============================================================
# Codex 后端
# ============================================================

class CodexBackend:
    """调用 codex exec 获取回复。"""

    def __init__(self, model: str = ''):
        self.model = model

    def query(self, prompt: str, on_chunk=None) -> str:
        """发送提示词，返回完整回复。支持流式回调。

        Args:
            prompt: 用户输入
            on_chunk: 可选回调，每收到一段文本调用 on_chunk(text)

        Returns:
            AI 的完整回复文本
        """
        cmd = [CODEX_BIN, 'exec', '--json', '--color', 'never']
        if self.model:
            cmd.extend(['--model', self.model])

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                cwd=os.getcwd(),
            )
            stdout, _ = proc.communicate(input=prompt, timeout=120)

            # 从 JSONL 中提取文本
            full_text = ''
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 提取 delta 文本
                delta = event.get('delta', {})
                if isinstance(delta, dict):
                    text = delta.get('text', '')
                else:
                    text = str(delta)
                if text:
                    full_text += text
                    if on_chunk:
                        on_chunk(full_text)

            return full_text.strip() or '(无回复)'

        except subprocess.TimeoutExpired:
            proc.kill()
            return '⏰ 请求超时'
        except FileNotFoundError:
            return f'❌ 找不到 {CODEX_BIN}'
        except OSError as exc:
            return f'❌ 执行错误: {exc}'


# ============================================================
# 文件上传集成
# ============================================================

def pick_file(stdscr):
    """在 curses 中打开 Termux 文件选择器，返回 file_upload.py 处理结果。"""
    curses.endwin()
    try:
        proc = subprocess.run(
            [sys.executable, os.path.expanduser('~/file_upload.py'),
             '--termux-pick', '--json'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=60,
        )
        curses.doupdate()
        return proc.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        curses.doupdate()
        return ''


# ============================================================
# 主循环
# ============================================================

def main_loop(stdscr, model: str = ''):
    """curses 主循环。"""
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    renderer = BubbleRenderer()
    input_bar = InputBar(stdscr)
    backend = CodexBackend(model)
    status = ''       # 状态栏文字
    is_loading = False

    while True:
        height, width = stdscr.getmaxyx()
        stdscr.clear()

        # --- 布局 ---
        input_h = 3   # 分隔线 + 输入栏 + 状态行
        chat_h = height - input_h - 1  # 标题 + 聊天区

        # --- 标题栏 ---
        title = ' 💬 Codex CLI · 气泡对话 '
        try:
            stdscr.addstr(0, 0, ' ' * width, renderer.C_TITLE)
            tx = max(0, (width - len(title)) // 2)
            stdscr.addstr(0, tx, title[:width], curses.A_REVERSE | renderer.C_TITLE)
        except curses.error:
            pass

        # --- 聊天区 ---
        renderer.draw(stdscr, 1, 0, chat_h - 1, width)

        # --- 输入栏 ---
        input_bar.draw(stdscr, height - 3, 0, width)

        # --- 状态栏 ---
        if status:
            try:
                attr = renderer.C_THINK if is_loading else renderer.C_DIM
                stdscr.addstr(height - 1, 2, status[:width - 4], attr)
            except curses.error:
                pass

        stdscr.refresh()

        # --- 输入处理 ---
        key = stdscr.getch()

        if is_loading:
            # 加载中只响应 Ctrl+C
            if key == 3:  # Ctrl+C
                status = '已取消'
                is_loading = False
            continue

        if key == 3:  # Ctrl+C
            break
        elif key == 27:  # ESC
            break
        elif key == ord('\n') or key == ord('\r'):
            # 发送消息
            prompt = input_bar.text.strip()
            if not prompt:
                continue

            renderer.add('user', prompt)
            input_bar.clear()
            status = '🤔 思考中...'
            is_loading = True

            # 非阻塞刷新
            stdscr.clear()
            renderer.draw(stdscr, 1, 0, chat_h - 1, width)
            input_bar.draw(stdscr, height - 3, 0, width)
            try:
                stdscr.addstr(height - 1, 2, status[:width - 4],
                              renderer.C_THINK)
            except curses.error:
                pass
            stdscr.refresh()

            # 后台查询
            reply = backend.query(prompt)
            renderer.add('assistant', reply)
            status = '✅ 就绪'
            is_loading = False

        elif key == curses.KEY_RESIZE:
            continue

        elif key == curses.KEY_UP:
            if input_bar.text:
                input_bar.move_left()
            else:
                renderer.scroll_up()

        elif key == curses.KEY_DOWN:
            if input_bar.text:
                input_bar.move_right()
            else:
                renderer.scroll_down()

        elif key == curses.KEY_LEFT:
            input_bar.move_left()

        elif key == curses.KEY_RIGHT:
            input_bar.move_right()

        elif key == curses.KEY_HOME:
            input_bar.home()

        elif key == curses.KEY_END:
            input_bar.end()

        elif key == curses.KEY_BACKSPACE or key == 127:
            input_bar.backspace()

        elif key == curses.KEY_DC:
            input_bar.delete()

        elif key == 6:  # Ctrl+F = 上传文件
            curses.curs_set(0)
            raw = pick_file(stdscr)
            curses.curs_set(1)
            if raw and '已取消' not in raw:
                try:
                    data = json.loads(raw)
                    results = data.get('results', [data]) if isinstance(data, dict) else []
                except json.JSONDecodeError:
                    results = [{'path': 'unknown', 'type': 'text', 'content': raw}]

                for r in results:
                    ftype = r.get('type', 'text')
                    fpath = r.get('path', '')
                    fcontent = r.get('content', '')
                    if ftype == 'image':
                        display = f'[🖼️ 图片] {fpath}'
                        prompt = f'[用户上传了图片: {fpath}]'
                    else:
                        display = f'[📄 文件] {fpath}\n{fcontent[:200]}{"..." if len(fcontent)>200 else ""}'
                        prompt = f'[文件: {fpath}]\n{fcontent}'
                    renderer.add('user', display)
                    status = '🤔 分析中...'
                    is_loading = True
                    stdscr.refresh()
                    reply = backend.query(prompt)
                    renderer.add('assistant', reply)
                    status = '✅ 就绪'
                    is_loading = False

        elif 32 <= key <= 126:
            # 可打印字符
            input_bar.insert(chr(key))

        # 自动清除状态
        if not is_loading and status == '✅ 就绪':
            # 延迟 3 秒后清除
            pass  # 保留状态直到下次输入


def run(model: str = ''):
    """启动气泡对话。"""
    try:
        curses.wrapper(main_loop, model)
    except curses.error as exc:
        print(f'终端不支持: {exc}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Codex CLI 气泡对话外壳')
    parser.add_argument('--model', '-m', default='', help='指定模型')
    args = parser.parse_args()
    run(args.model)
