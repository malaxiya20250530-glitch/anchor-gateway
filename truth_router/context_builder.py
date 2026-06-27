#!/usr/bin/env python3
"""上下文构建器 — 从 Memory Engine 加载三层记忆注入 Truth Router"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_ROOT = ROOT / ".memory"
PROJECT_DIR = MEMORY_ROOT / "project"
USER_DIR = MEMORY_ROOT / "user"
SESSION_LATEST = MEMORY_ROOT / "session" / "latest.md"


def _read_md(path: Path) -> str:
    """安全读取 Markdown 文件"""
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def build_context() -> dict:
    """构建 Truth Router 上下文

    返回:
        {
            "project": {name: content, ...},
            "user": {name: content, ...},
            "session": str  # 上次会话摘要
        }
    """
    project = {}
    for md_file in sorted(PROJECT_DIR.glob("*.md")) if PROJECT_DIR.exists() else []:
        content = _read_md(md_file)
        if content:
            project[md_file.stem] = content

    user = {}
    for md_file in sorted(USER_DIR.glob("*.md")) if USER_DIR.exists() else []:
        content = _read_md(md_file)
        if content:
            user[md_file.stem] = content

    session = _read_md(SESSION_LATEST)

    return {"project": project, "user": user, "session": session}


def context_as_text(ctx: dict = None) -> str:
    """将上下文字典展平为纯文本，供 LLM prompt 注入"""
    if ctx is None:
        ctx = build_context()

    parts = []

    if ctx.get("session"):
        parts.append(f"【上次会话】\n{ctx['session']}")

    proj = ctx.get("project", {})
    if proj:
        lines = ["【项目记忆】"]
        for name, content in proj.items():
            lines.append(f"## {name}\n{content}")
        parts.append("\n\n".join(lines))

    usr = ctx.get("user", {})
    if usr:
        lines = ["【用户偏好】"]
        for name, content in usr.items():
            lines.append(f"## {name}\n{content}")
        parts.append("\n\n".join(lines))

    return "\n\n---\n\n".join(parts) if parts else ""


def context_summary(ctx: dict = None) -> str:
    """生成紧凑摘要（≤300 字），用于 Router 快速决策"""
    if ctx is None:
        ctx = build_context()

    items = []
    proj = ctx.get("project", {})
    if proj:
        items.append(f"项目记忆: {', '.join(proj.keys())}")

    usr = ctx.get("user", {})
    if usr:
        items.append(f"用户偏好: {', '.join(usr.keys())}")

    session = ctx.get("session", "")
    if session:
        # 提取首行作为摘要
        first_line = session.split("\n")[0].lstrip("# ").strip()
        items.append(f"上次会话: {first_line[:80]}")

    return " | ".join(items) if items else "(无上下文)"


def main() -> None:
    if "--json" in sys.argv:
        print(json.dumps(build_context(), ensure_ascii=False, indent=2))
    elif "--text" in sys.argv:
        print(context_as_text())
    else:
        print(context_summary())


if __name__ == "__main__":
    main()
