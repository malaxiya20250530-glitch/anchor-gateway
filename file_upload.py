#!/usr/bin/env python3
"""Codex CLI 文件上传桥接器 —— 在终端对话框中快速引用本地文件。

用法:
  python3 file_upload.py <文件路径> [文件路径2 ...]
  python3 file_upload.py --json <文件路径>       # JSON 格式输出
  python3 file_upload.py --termux-pick           # Termux 文件选择器

功能:
  - 读取文本文件，格式化为 LLM 友好的 Markdown 代码块
  - 支持图片路径引用（配合 imagegen skill）
  - 支持 Termux 的 termux-storage-get 文件选择
  - 输出可直接粘贴到 Codex CLI 对话框中
"""

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ============================================================
# 配置
# ============================================================

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB 上限
TEXT_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.scss',
    '.json', '.yaml', '.yml', '.toml', '.xml', '.csv', '.tsv',
    '.md', '.rst', '.txt', '.log', '.sh', '.bash', '.zsh',
    '.c', '.cpp', '.h', '.hpp', '.rs', '.go', '.java', '.kt',
    '.swift', '.rb', '.php', '.sql', '.r', '.m', '.mm',
    '.cfg', '.ini', '.conf', '.env', '.gitignore', '.dockerignore',
    '.tex', '.bib', '.Makefile', '.cmake', '.gradle',
}

IMAGE_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg',
    '.ico', '.tiff', '.tif',
}

BINARY_SKIP = {
    '.db', '.sqlite', '.sqlite3', '.so', '.o', '.a', '.class',
    '.pyc', '.pyo', '.exe', '.dll', '.bin', '.dat', '.pkl',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.mp3', '.mp4', '.avi', '.mov', '.wav', '.flac',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
}


def _is_text_file(filepath: str) -> bool:
    """判断是否为可读文本文件。"""
    ext = Path(filepath).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    if ext in BINARY_SKIP or ext in IMAGE_EXTENSIONS:
        return False
    # 未知扩展名：检测内容是否为文本
    try:
        with open(filepath, 'rb') as fh:
            chunk = fh.read(4096)
        if not chunk:
            return True
        if b'\x00' in chunk:
            return False
        try:
            chunk.decode('utf-8')
            return True
        except UnicodeDecodeError:
            return False
    except OSError:
        return False


def _is_image_file(filepath: str) -> bool:
    """判断是否为图片文件。"""
    ext = Path(filepath).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def _read_text_file(filepath: str) -> str:
    """读取文本文件内容，自动检测编码。"""
    encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as fh:
                return fh.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        return fh.read()


def _get_language_from_ext(filepath: str) -> str:
    """根据扩展名返回 Markdown 代码块语言标识。"""
    ext_to_lang = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.jsx': 'jsx', '.tsx': 'tsx', '.html': 'html', '.css': 'css',
        '.scss': 'scss', '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
        '.toml': 'toml', '.xml': 'xml', '.md': 'markdown', '.sh': 'bash',
        '.bash': 'bash', '.zsh': 'bash', '.c': 'c', '.cpp': 'cpp',
        '.h': 'c', '.hpp': 'cpp', '.rs': 'rust', '.go': 'go',
        '.java': 'java', '.kt': 'kotlin', '.swift': 'swift',
        '.rb': 'ruby', '.php': 'php', '.sql': 'sql', '.r': 'r',
    }
    ext = Path(filepath).suffix.lower()
    return ext_to_lang.get(ext, '')


def _format_text_file(filepath: str, content: str) -> str:
    """将文本文件格式化为 LLM 友好的 Markdown 输出。"""
    lang = _get_language_from_ext(filepath)
    size_kb = len(content.encode('utf-8')) / 1024
    lines = content.count('\n') + 1

    parts = [
        f"### 📄 `{filepath}`",
        f"- 大小: {size_kb:.1f} KB | 行数: {lines}",
        "",
        f"```{lang}",
        content,
        "```",
    ]
    return '\n'.join(parts)


def _format_image_file(filepath: str) -> str:
    """格式化为图片引用（供 imagegen skill 使用）。"""
    abs_path = os.path.abspath(filepath)
    size_kb = os.path.getsize(filepath) / 1024
    return (
        f"### 🖼️ `{filepath}`\n"
        f"- 类型: 图片 | 大小: {size_kb:.1f} KB\n"
        f"- 路径: `{abs_path}`\n"
        f"- 提示: 使用 `view_image` 工具或 imagegen skill 处理此图片"
    )


def _format_binary_file(filepath: str) -> str:
    """格式化为二进制文件警告。"""
    size_kb = os.path.getsize(filepath) / 1024
    ext = Path(filepath).suffix.lower()
    return (
        f"### ⚠️ `{filepath}`\n"
        f"- 类型: 二进制文件 ({ext}) | 大小: {size_kb:.1f} KB\n"
        f"- 无法直接读取内容，仅作为路径引用"
    )


def upload_file(filepath: str, max_size: int = MAX_FILE_SIZE) -> dict:
    """处理单个文件上传，返回结构化结果。

    Args:
        filepath: 文件路径
        max_size: 文件大小上限（字节）

    Returns:
        dict: {path, type, size, content, error}
    """
    result = {
        'path': filepath,
        'type': 'unknown',
        'size': 0,
        'content': '',
        'error': None,
    }

    if not os.path.exists(filepath):
        result['error'] = f'文件不存在: {filepath}'
        return result

    if not os.path.isfile(filepath):
        result['error'] = f'不是普通文件: {filepath}'
        return result

    try:
        file_size = os.path.getsize(filepath)
        result['size'] = file_size
    except OSError as exc:
        result['error'] = f'无法读取文件大小: {exc}'
        return result

    if file_size > max_size:
        result['error'] = (
            f'文件过大: {file_size / 1024 / 1024:.1f}MB '
            f'(上限 {max_size / 1024 / 1024:.0f}MB)'
        )
        return result

    try:
        if _is_image_file(filepath):
            result['type'] = 'image'
            result['content'] = _format_image_file(filepath)
        elif _is_text_file(filepath):
            content = _read_text_file(filepath)
            result['type'] = 'text'
            result['content'] = _format_text_file(filepath, content)
        else:
            result['type'] = 'binary'
            result['content'] = _format_binary_file(filepath)
    except PermissionError as exc:
        result['error'] = f'权限不足: {exc}'
    except OSError as exc:
        result['error'] = f'读取失败: {exc}'

    return result


def upload_files(filepaths: list, max_size: int = MAX_FILE_SIZE) -> list:
    """批量上传文件。"""
    return [upload_file(fp, max_size) for fp in filepaths]


def format_output(results: list, output_format: str = 'markdown') -> str:
    """将上传结果格式化为最终输出。"""
    if output_format == 'json':
        return json.dumps(results, ensure_ascii=False, indent=2)

    parts = []
    success_count = sum(1 for r in results if r['error'] is None)
    error_count = sum(1 for r in results if r['error'] is not None)

    parts.append(f"## 📎 文件上传结果 ({success_count} 成功, {error_count} 失败)\n")

    for r in results:
        if r['error']:
            parts.append(f"- ❌ `{r['path']}` — {r['error']}")
        else:
            parts.append(f"- ✅ `{r['path']}` ({r['type']}, {r['size']/1024:.1f}KB)")

    parts.append("")

    for r in results:
        if r['error'] is None and r['content']:
            parts.append(r['content'])
            parts.append("")

    return '\n'.join(parts)


def termux_file_picker() -> list:
    """使用 Termux API 打开文件选择器。

    Returns:
        选中的文件路径列表，失败返回空列表
    """
    if shutil.which('termux-storage-get') is None:
        print("⚠️ termux-storage-get 不可用，请确保安装了 Termux:API", file=sys.stderr)
        return []

    try:
        result = subprocess.run(
            ['termux-storage-get', '--content-file'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"⚠️ 文件选择器返回错误: {result.stderr}", file=sys.stderr)
            return []
        path = result.stdout.strip()
        return [path] if path else []
    except subprocess.TimeoutExpired:
        print("⚠️ 文件选择器超时", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("⚠️ termux-storage-get 未安装", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser(
        description='Codex CLI 文件上传桥接器 — 在终端对话框中引用本地文件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python3 file_upload.py main.py config.json
  python3 file_upload.py --json src/*.py
  python3 file_upload.py --termux-pick
  python3 file_upload.py --max-size 5MB large_file.log
        ''',
    )
    parser.add_argument(
        'files', nargs='*',
        help='要上传的文件路径（支持多个）',
    )
    parser.add_argument(
        '--max-size', default='10MB',
        help='文件大小上限（默认 10MB）',
    )
    parser.add_argument(
        '--json', action='store_true',
        help='以 JSON 格式输出结果',
    )
    parser.add_argument(
        '--termux-pick', action='store_true',
        help='使用 Termux 文件选择器',
    )

    args = parser.parse_args()

    # 解析文件大小上限
    max_size = MAX_FILE_SIZE
    size_str = args.max_size.upper().strip()
    if size_str.endswith('MB'):
        try:
            max_size = int(float(size_str[:-2]) * 1024 * 1024)
        except ValueError:
            pass
    elif size_str.endswith('KB'):
        try:
            max_size = int(float(size_str[:-2]) * 1024)
        except ValueError:
            pass

    # 获取文件列表
    files = list(args.files)
    if args.termux_pick:
        picked = termux_file_picker()
        if picked:
            files.extend(picked)

    if not files:
        parser.print_help()
        sys.exit(1)

    # 去重
    seen = set()
    unique_files = []
    for fp in files:
        abs_path = os.path.abspath(fp)
        if abs_path not in seen:
            seen.add(abs_path)
            unique_files.append(fp)

    # 执行上传
    results = upload_files(unique_files, max_size)
    output_format = 'json' if args.json else 'markdown'
    print(format_output(results, output_format))

    has_errors = any(r['error'] is not None for r in results)
    sys.exit(1 if has_errors else 0)


if __name__ == '__main__':
    main()
