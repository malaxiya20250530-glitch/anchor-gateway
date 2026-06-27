# -*- coding: utf-8 -*-
'''
Memory Gateway — Memory Engine 统一读写网关

整合三层记忆读写、JSONL迁移、会话摘要生成，
为 Truth Router / AnchorEngine 提供统一上下文接口。

目录结构:
  .memory/
  ├── project/
  │   ├── architecture.md   ← 架构决策、设计原则
  │   ├── decisions.md      ← 关键决策记录(ADR)
  │   └── roadmap.md        ← Bug记录、优化方向
  ├── user/
  │   ├── preferences.md    ← 用户偏好
  │   └── habits.md         ← 使用习惯、编码风格
  └── session/
      ├── latest.md         ← 最新会话摘要
      └── archive/          ← 历史会话归档

用法:
  python3 memory_gateway.py init          # 初始化/迁移所有记忆
  python3 memory_gateway.py status        # 查看记忆状态
  python3 memory_gateway.py summary       # 生成会话上下文
  python3 memory_gateway.py archive       # 归档当前会话
'''

import json
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MEMORY_ROOT = ROOT / '.memory'
PROJECT_DIR = MEMORY_ROOT / 'project'
USER_DIR = MEMORY_ROOT / 'user'
SESSION_DIR = MEMORY_ROOT / 'session'
SESSION_LATEST = SESSION_DIR / 'latest.md'
SESSION_ARCHIVE = SESSION_DIR / 'archive'

# JSONL 数据源
CODEX_MEMORIES = Path.home() / '.codex' / 'memories'
CODEX_MEMORIES_V2 = Path.home() / '.codex' / 'memories_v2'
REASONIX_MEMORY = Path.home() / '.reasonix' / 'memory'

# Codex 状态数据库
STATE_DB = Path.home() / '.codex' / 'state_5.sqlite'


# ── 工具函数 ──────────────────────────────────────────────

def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _ensure_dirs():
    for d in (PROJECT_DIR, USER_DIR, SESSION_DIR, SESSION_ARCHIVE):
        d.mkdir(parents=True, exist_ok=True)


def _read_jsonl(path: Path) -> list:
    '''读取 JSONL 文件，返回条目列表'''
    entries = []
    if not path.exists():
        return entries
    try:
        for line in path.read_text(encoding='utf-8').strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    entries.append(entry)
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return entries


def _write_md(path: Path, content: str) -> None:
    '''写入 Markdown 文件'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + '\n', encoding='utf-8')


def _read_md(path: Path) -> str:
    '''安全读取 Markdown 文件'''
    try:
        if path.exists():
            return path.read_text(encoding='utf-8').strip()
    except Exception:
        pass
    return ''


# ── JSONL 迁移 ────────────────────────────────────────────

def _collect_jsonl_entries(*dirs: Path) -> list:
    '''收集所有 JSONL 目录中的记忆条目，去重'''
    seen = set()
    entries = []
    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob('*.jsonl')):
            for entry in _read_jsonl(f):
                content = entry.get('content', '').strip()
                if not content or len(content) < 3:
                    continue
                key = (entry.get('category', ''), content[:80])
                if key in seen:
                    continue
                seen.add(key)
                entries.append(entry)
    return entries


def _categorize_entries(entries: list) -> dict:
    '''将 JSONL 条目按目标文件分类'''
    buckets = {
        'architecture': [],
        'decisions': [],
        'roadmap': [],
        'preferences': [],
        'habits': [],
    }

    for entry in entries:
        category = entry.get('category', '')
        content = entry.get('content', '').strip()
        source = entry.get('source', '')
        confidence = entry.get('confidence', '')

        line = f'- {content}'
        if source:
            line += f'  \\[来源: {source}\\]'
        if confidence:
            line += f'  \\[置信度: {confidence}\\]'

        if category in ('architecture',):
            buckets['architecture'].append(line)
        elif category in ('decision', 'rule', 'constraint', 'invariant'):
            buckets['decisions'].append(line)
        elif category in ('bug', 'performance', 'tool_usage', 'run_log'):
            buckets['roadmap'].append(line)
        elif category in ('preference',):
            buckets['preferences'].append(line)
        elif category in ('habit', 'pattern'):
            buckets['habits'].append(line)
        else:
            buckets['roadmap'].append(line)

    return buckets


def migrate_from_jsonl() -> dict:
    '''从所有 JSONL 源迁移数据到 .memory/ Markdown 文件'''
    _ensure_dirs()
    entries = _collect_jsonl_entries(CODEX_MEMORIES, CODEX_MEMORIES_V2, REASONIX_MEMORY)
    buckets = _categorize_entries(entries)

    results = {}
    file_map = {
        'architecture': PROJECT_DIR / 'architecture.md',
        'decisions': PROJECT_DIR / 'decisions.md',
        'roadmap': PROJECT_DIR / 'roadmap.md',
        'preferences': USER_DIR / 'preferences.md',
        'habits': USER_DIR / 'habits.md',
    }
    titles = {
        'architecture': '# 项目架构记忆\n\n',
        'decisions': '# 关键决策记录\n\n',
        'roadmap': '# 项目历程与优化方向\n\n',
        'preferences': '# 用户偏好\n\n',
        'habits': '# 使用习惯与编码风格\n\n',
    }

    for file_key, lines in buckets.items():
        if not lines:
            results[file_key] = 0
            continue

        path = file_map[file_key]
        content = titles.get(file_key, '# 记忆\n\n')
        content += '\n'.join(lines)
        content += f'\n\n> 最后更新: {_timestamp()}'

        _write_md(path, content)
        results[file_key] = len(lines)

    return {
        'source_entries': len(entries),
        'migrated': results,
        'total_written': sum(results.values()),
    }


# ── 会话摘要 ──────────────────────────────────────────────

def _get_state_db_threads(limit: int = 10) -> list:
    '''从 Codex 状态数据库读取最近线程'''
    if not STATE_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''SELECT thread_id, first_user_message, updated_at
               FROM threads
               WHERE first_user_message IS NOT NULL
               ORDER BY updated_at DESC
               LIMIT ?''',
            (limit,)
        ).fetchall()
        conn.close()
        return [
            {
                'id': row['thread_id'],
                'message': (row['first_user_message'] or '')[:200],
                'updated_at': row['updated_at'],
            }
            for row in rows
        ]
    except Exception:
        return []


def generate_session_summary(archive_current: bool = True) -> str:
    '''生成会话摘要并写入 session/latest.md'''
    _ensure_dirs()

    # 归档当前会话
    if archive_current and SESSION_LATEST.exists():
        old_content = _read_md(SESSION_LATEST)
        if old_content.strip():
            archive_name = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S.md')
            archive_path = SESSION_ARCHIVE / archive_name
            _write_md(archive_path, old_content)

    # 从线程历史生成摘要
    threads = _get_state_db_threads(5)

    lines = [
        '# 会话记忆',
        '',
        f'> 生成时间: {_timestamp()}',
        '',
        '## 最近对话',
        '',
    ]

    if threads:
        for t in threads:
            msg = t['message'].replace('\n', ' ')[:120]
            updated = t.get('updated_at', '')[:19]
            lines.append(f'- [{updated}] {msg}')
    else:
        lines.append('- (无历史对话)')

    # 统计信息
    proj_files = [f.stem for f in PROJECT_DIR.glob('*.md') if _read_md(f)]
    user_files = [f.stem for f in USER_DIR.glob('*.md') if _read_md(f)]
    archive_count = len(list(SESSION_ARCHIVE.glob('*.md')))

    lines += [
        '',
        '## 记忆统计',
        '',
        f'- 项目记忆文件: {", ".join(proj_files) if proj_files else "(空)"}',
        f'- 用户记忆文件: {", ".join(user_files) if user_files else "(空)"}',
        f'- 归档会话数: {archive_count}',
    ]

    content = '\n'.join(lines)
    _write_md(SESSION_LATEST, content)
    return content


# ── 记忆注入 ──────────────────────────────────────────────

def get_context_for_router() -> dict:
    '''获取 Truth Router 可用的完整上下文'''
    _ensure_dirs()

    project = {}
    for md_file in sorted(PROJECT_DIR.glob('*.md')):
        content = _read_md(md_file)
        if content:
            project[md_file.stem] = content

    user = {}
    for md_file in sorted(USER_DIR.glob('*.md')):
        content = _read_md(md_file)
        if content:
            user[md_file.stem] = content

    session = _read_md(SESSION_LATEST)

    return {'project': project, 'user': user, 'session': session}


def get_context_summary() -> str:
    '''生成紧凑上下文摘要（≤300字）'''
    ctx = get_context_for_router()
    items = []

    proj = ctx.get('project', {})
    if proj:
        items.append(f'项目记忆: {", ".join(proj.keys())}')

    usr = ctx.get('user', {})
    if usr:
        items.append(f'用户偏好: {", ".join(usr.keys())}')

    session = ctx.get('session', '')
    if session:
        first_line = session.split('\n')[0].lstrip('# ').strip()
        items.append(f'会话: {first_line[:80]}')

    return ' | '.join(items) if items else '(无上下文)'


# ── 记忆管理 ──────────────────────────────────────────────

def remember(target: str, content: str, mode: str = 'append') -> str:
    '''写入一条记忆'''
    file_map = {
        'architecture': PROJECT_DIR / 'architecture.md',
        'decisions': PROJECT_DIR / 'decisions.md',
        'roadmap': PROJECT_DIR / 'roadmap.md',
        'preferences': USER_DIR / 'preferences.md',
        'habits': USER_DIR / 'habits.md',
    }

    if target not in file_map:
        return f'❌ 无效目标 "{target}"，合法值: {", ".join(file_map)}'

    _ensure_dirs()
    path = file_map[target]

    if mode == 'overwrite' or not path.exists():
        titles = {
            'architecture': '# 项目架构记忆\n\n',
            'decisions': '# 关键决策记录\n\n',
            'roadmap': '# 项目历程与优化方向\n\n',
            'preferences': '# 用户偏好\n\n',
            'habits': '# 使用习惯与编码风格\n\n',
        }
        _write_md(path, titles.get(target, '# 记忆\n\n') + f'- {content}')
    else:
        entry = f'\n- {content}  \\[_{_timestamp()}_\\]'
        with open(path, 'a', encoding='utf-8') as f:
            f.write(entry)

    return f'✅ 已写入 {path.name}'


def status() -> dict:
    '''获取 Memory Engine 状态'''
    _ensure_dirs()

    def _count_lines(p: Path) -> int:
        try:
            if p.exists():
                return len(p.read_text(encoding='utf-8').strip().split('\n'))
        except Exception:
            pass
        return 0

    return {
        'project': {
            f.stem: _count_lines(f)
            for f in sorted(PROJECT_DIR.glob('*.md'))
        },
        'user': {
            f.stem: _count_lines(f)
            for f in sorted(USER_DIR.glob('*.md'))
        },
        'session': {
            'latest': _count_lines(SESSION_LATEST),
            'archives': len(list(SESSION_ARCHIVE.glob('*.md'))),
        },
    }


# ── CLI ────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print('用法: python3 memory_gateway.py <命令>')
        print('命令:')
        print('  init       — 初始化所有记忆 (从JSONL迁移 + 生成会话摘要)')
        print('  status     — 查看记忆状态')
        print('  summary    — 生成/刷新会话上下文')
        print('  archive    — 归档当前会话并生成新摘要')
        print('  inject     — 输出 Truth Router 可注入的上下文文本')
        print('  remember <目标> <内容> — 写入一条记忆')
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == 'init':
        print('🔄 从 JSONL 迁移记忆数据...')
        result = migrate_from_jsonl()
        print(f'  源条目: {result["source_entries"]}')
        for k, v in result['migrated'].items():
            print(f'  {k}: {v} 条')
        print(f'  总计写入: {result["total_written"]} 条')

        print('\n📝 生成会话摘要...')
        generate_session_summary(archive_current=False)
        print('  完成')

        print('\n📊 最终状态:')
        print(json.dumps(status(), ensure_ascii=False, indent=2))

    elif cmd == 'status':
        print(json.dumps(status(), ensure_ascii=False, indent=2))

    elif cmd == 'summary':
        generate_session_summary(archive_current=False)
        print(_read_md(SESSION_LATEST))

    elif cmd == 'archive':
        generate_session_summary(archive_current=True)
        print('✅ 会话已归档，新摘要已生成')

    elif cmd == 'inject':
        print(get_context_summary())

    elif cmd == 'remember' and len(sys.argv) >= 4:
        target = sys.argv[2]
        content = ' '.join(sys.argv[3:])
        print(remember(target, content))

    else:
        print(f'❌ 未知命令: {cmd}')
        sys.exit(1)


if __name__ == '__main__':
    main()
