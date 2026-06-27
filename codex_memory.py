# -*- coding: utf-8 -*-
'''
Reasonix 记忆系统 —— 跨会话持久化层

目录结构：
  ~/.reasonix/
  ├── config.json              ← 全局配置
  └── memory/                  ← 全局记忆（跨项目共享）
      ├── user_preference.jsonl
      ├── system_rule.jsonl
      └── ...

  <项目根>/.reasonix/
  ├── config.json              ← 项目级配置（覆盖全局）
  └── memory/                  ← 项目记忆（项目专属）
      ├── project_architecture.jsonl
      ├── execution_run_log.jsonl
      └── ...

规则：
  - 追加写入，永不覆盖已有事实
  - 项目配置覆盖全局配置（深度合并）
  - 读取时项目记忆优先于全局记忆
  - system 记忆写入全局（跨项目不变规则）

纯 Python 标准库，零外部依赖。
'''

import json
import os
import sqlite3
import time
from pathlib import Path


# ── 路径配置 ──────────────────────────────────────────────

GLOBAL_REASONIX = Path.home() / '.reasonix'
GLOBAL_MEMORY = GLOBAL_REASONIX / 'memory'
GLOBAL_CONFIG = GLOBAL_REASONIX / 'config.json'

# 项目根从环境变量或当前目录推断
PROJECT_ROOT = Path(os.environ.get('REASONIX_PROJECT_ROOT', os.getcwd()))
PROJECT_REASONIX = PROJECT_ROOT / '.reasonix'
PROJECT_MEMORY = PROJECT_REASONIX / 'memory'
PROJECT_CONFIG = PROJECT_REASONIX / 'config.json'

# 创建必要目录
GLOBAL_MEMORY.mkdir(parents=True, exist_ok=True)
PROJECT_MEMORY.mkdir(parents=True, exist_ok=True)

# Codex 状态数据库（只读）
STATE_DB = Path.home() / '.codex' / 'state_5.sqlite'


# ── 记忆范围与存储位置映射 ──────────────────────────────

# 定义哪些 scope 的类别存储在全局目录，哪些在项目目录
# 优先级：优先查项目目录，fallback 到全局目录
SCOPE_STORAGE = {
    'project':   'project',    # 项目架构等 → 项目目录
    'user':      'global',     # 用户偏好 → 全局目录
    'system':    'global',     # 不可变规则 → 全局目录
    'execution': 'project',    # 执行日志 → 项目目录
}

MEMORY_SCOPES = {
    'project':   ('architecture', 'decision', 'tool_usage', 'bug', 'performance'),
    'user':      ('preference', 'pattern', 'habit'),
    'system':    ('rule', 'constraint', 'invariant'),
    'execution': ('run_log', 'command_trace', 'result'),
}

ALL_CATEGORIES = [
    cat for cats in MEMORY_SCOPES.values() for cat in cats
]

IMMUTABLE_SCOPES = frozenset({'system'})


# ── 配置文件读写 ──────────────────────────────────────────

DEFAULT_CONFIG = {
    'version': 1,
    'context': {
        'recent_threads': 3,
        'max_execution_memories': 20,
    },
    'confidence': {
        'project': 0.8,
        'user': 0.6,
        'system': 1.0,
        'execution': 0.95,
    },
    'scopes_enabled': ['project', 'user', 'system', 'execution'],
}


def _deep_merge(base: dict, override: dict) -> dict:
    '''深度合并两个字典，override 的值覆盖 base。'''
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config() -> dict:
    '''加载配置：全局 → 项目覆盖（深度合并）。'''
    config = DEFAULT_CONFIG.copy()

    # 加载全局配置
    if GLOBAL_CONFIG.exists():
        try:
            with open(GLOBAL_CONFIG, 'r', encoding='utf-8') as f:
                global_cfg = json.load(f)
            config = _deep_merge(config, global_cfg)
        except (OSError, json.JSONDecodeError):
            pass

    # 加载项目配置（覆盖全局）
    if PROJECT_CONFIG.exists():
        try:
            with open(PROJECT_CONFIG, 'r', encoding='utf-8') as f:
                project_cfg = json.load(f)
            config = _deep_merge(config, project_cfg)
        except (OSError, json.JSONDecodeError):
            pass

    return config


def save_global_config(config: dict) -> dict:
    '''写入全局配置文件。'''
    try:
        GLOBAL_REASONIX.mkdir(parents=True, exist_ok=True)
        with open(GLOBAL_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return {'ok': True, 'file': str(GLOBAL_CONFIG)}
    except OSError as e:
        return {'error': f'写入全局配置失败: {e}'}


def save_project_config(config: dict) -> dict:
    '''写入项目配置文件。'''
    try:
        PROJECT_REASONIX.mkdir(parents=True, exist_ok=True)
        with open(PROJECT_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return {'ok': True, 'file': str(PROJECT_CONFIG)}
    except OSError as e:
        return {'error': f'写入项目配置失败: {e}'}


# ── 线程查询 ──────────────────────────────────────────────

def list_recent_threads(limit: int = 10) -> list[dict]:
    '''返回最近 N 个线程的基本信息。'''
    try:
        conn = sqlite3.connect(str(STATE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            '''SELECT id, title, first_user_message, rollout_path,
                      created_at, updated_at, model, cwd,
                      tokens_used, archived
               FROM threads
               ORDER BY updated_at DESC
               LIMIT ?''',
            (limit,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        for row in rows:
            for ts_key in ('created_at', 'updated_at'):
                if row.get(ts_key):
                    row[f'{ts_key}_iso'] = _ts_to_iso(row[ts_key])
        return rows
    except sqlite3.Error as e:
        return [{'error': f'数据库读取失败: {e}'}]


def get_thread_summary(thread_id: str) -> dict:
    '''获取指定线程的摘要，包含首条消息和对话行数。'''
    try:
        conn = sqlite3.connect(str(STATE_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            'SELECT * FROM threads WHERE id = ?',
            (thread_id,)
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {'error': f'线程 {thread_id} 不存在'}
        info = dict(row)
        rollout_path = info.get('rollout_path', '')
        if rollout_path and os.path.exists(rollout_path):
            lines = _count_lines(rollout_path)
            info['rollout_lines'] = lines
            info['user_messages'] = _extract_user_messages(rollout_path)
        return info
    except sqlite3.Error as e:
        return {'error': f'查询失败: {e}'}


# ── 记忆路径解析 ──────────────────────────────────────────

def _resolve_memory_dir(scope: str) -> Path:
    '''根据 scope 返回记忆存储目录（全局或项目）。'''
    storage = SCOPE_STORAGE.get(scope, 'project')
    return GLOBAL_MEMORY if storage == 'global' else PROJECT_MEMORY


def _memory_filepath(scope: str, category: str) -> Path:
    '''返回记忆文件的完整路径。'''
    return _resolve_memory_dir(scope) / f'{scope}_{category}.jsonl'


# ── 记忆写入（追加模式） ─────────────────────────────────

def _save_memory_entry(scope: str, category: str, content: str,
                       confidence: float = 0.8, source: str = '',
                       force_global: bool = False) -> dict:
    '''内部通用写入——追加一条记忆到对应目录。'''
    if scope not in MEMORY_SCOPES:
        return {'error': f'无效范围: {scope}，可选: {list(MEMORY_SCOPES.keys())}'}
    if category not in MEMORY_SCOPES[scope]:
        return {'error': f'无效类别 {category} 于范围 {scope}，可选: {MEMORY_SCOPES[scope]}'}
    if not (0.0 <= confidence <= 1.0):
        return {'error': 'confidence 必须在 0.0-1.0 之间'}

    entry = {
        'type': 'memory_entry',
        'scope': scope,
        'category': category,
        'content': content,
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'confidence': confidence,
    }
    if source:
        entry['source'] = source

    # 确定存储目录
    if force_global:
        mem_dir = GLOBAL_MEMORY
    else:
        mem_dir = _resolve_memory_dir(scope)

    filepath = mem_dir / f'{scope}_{category}.jsonl'
    try:
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return {'ok': True, 'file': str(filepath), 'entry': entry}
    except OSError as e:
        return {'error': f'写入失败: {e}'}


def save_memory(category: str, content: str, confidence: float = 0.8) -> dict:
    '''写入一条项目记忆（project scope → 项目目录）。向后兼容。'''
    cfg = load_config()
    default_conf = cfg.get('confidence', {}).get('project', 0.8)
    return _save_memory_entry('project', category, content,
                              confidence if confidence != 0.8 else default_conf)


def save_user_memory(category: str, content: str, confidence: float = 0.6) -> dict:
    '''写入一条用户记忆 → 全局目录。'''
    return _save_memory_entry('user', category, content, confidence)


def save_system_memory(category: str, content: str, source: str = '') -> dict:
    '''写入一条系统记忆 → 全局目录。置信度固定 1.0。'''
    return _save_memory_entry('system', category, content, confidence=1.0, source=source)


def save_execution_memory(category: str, content: str, confidence: float = 0.95) -> dict:
    '''写入一条执行记忆 → 项目目录。'''
    cfg = load_config()
    default_conf = cfg.get('confidence', {}).get('execution', 0.95)
    return _save_memory_entry("execution", category, content,
                              confidence if confidence != 0.95 else default_conf)

def load_memories(scope=None, category=None):
    if category:
        if category not in ALL_CATEGORIES:
            return [{'error': 'unknown category'}]
        cat_scope = _scope_for_category(category)
        if cat_scope is None:
            return [{'error': 'scope not found for category'}]
        categories_to_load = [(cat_scope, category)]
    elif scope:
        if scope not in MEMORY_SCOPES:
            return [{'error': 'invalid scope'}]
        categories_to_load = [(scope, cat) for cat in MEMORY_SCOPES[scope]]
    else:
        categories_to_load = []
        for sc, cats in MEMORY_SCOPES.items():
            for cat in cats:
                categories_to_load.append((sc, cat))
    seen = {}
    for sc, cat in categories_to_load:
        storage = SCOPE_STORAGE.get(sc, 'project')
        dirs_to_check = [PROJECT_MEMORY, GLOBAL_MEMORY] if storage == 'project' else [GLOBAL_MEMORY]
        for mem_dir in dirs_to_check:
            filepath = mem_dir / f'{sc}_{cat}.jsonl'
            if not filepath.exists():
                continue
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        content_preview = entry.get('content', '')[:80]
                        key = (entry.get('scope', sc), entry.get('category', cat), content_preview)
                        ts = entry.get('timestamp', '')
                        if key not in seen or ts > seen[key][0]:
                            seen[key] = (ts, entry)
            except OSError:
                continue
    entries = [entry for _, entry in sorted(seen.values(), key=lambda x: x[0])]
    return entries




# ── Reasonix 新模块集成 ──────────────────────────────────

try:
    from reasonix_store import MemoryStore, normalize_type, slugify
    _HAS_STORE = True
except ImportError:
    _HAS_STORE = False

try:
    from reasonix_docs import discover_docs, quick_add_note, compose_memory_block
    _HAS_DOCS = True
except ImportError:
    _HAS_DOCS = False

try:
    from reasonix_commands import CommandLoader
    _HAS_COMMANDS = True
except ImportError:
    _HAS_COMMANDS = False

try:
    from reasonix_frontmatter import split_frontmatter, render_frontmatter
    _HAS_FM = True
except ImportError:
    _HAS_FM = False


def get_auto_memory_store():
    if not _HAS_STORE:
        return None
    store_dir = PROJECT_REASONIX / 'memory' / 'store'
    return MemoryStore(str(store_dir))



def auto_remember(rollout_path=None, max_facts=10):
    if not _HAS_STORE:
        return {'error': 'reasonix_store 模块不可用'}

    import json as _json

    # 自动找最近的 rollout
    if rollout_path is None:
        sessions_dir = Path.home() / '.codex' / 'sessions'
        if not sessions_dir.exists():
            return {'error': '找不到 sessions 目录'}
        all_rollouts = sorted(sessions_dir.rglob('*.jsonl'),
                              key=lambda p: p.stat().st_mtime, reverse=True)
        if not all_rollouts:
            return {'error': '找不到 rollout 文件'}
        rollout_path = str(all_rollouts[0])

    if not os.path.exists(rollout_path):
        return {'error': f'文件不存在: {rollout_path}'}

    # 扫描 rollout 提取信号
    signals = _scan_rollout(rollout_path)

    if not signals:
        return {'ok': True, 'saved': 0, 'signals_found': 0,
                'message': '未发现值得自动记忆的信号'}

    store = get_auto_memory_store()
    saved = 0
    for sig in signals[:max_facts]:
        r = store.remember(sig['name'], sig['content'],
                           mem_type=sig.get('type', 'project'))
        if r.get('ok'):
            saved += 1

    return {
        'ok': True,
        'rollout': os.path.basename(rollout_path),
        'signals_found': len(signals),
        'saved': saved,
        'signals': [{'name': s['name'], 'type': s.get('type','project'),
                      'preview': s['content'][:80]} for s in signals[:max_facts]],
    }


def _scan_rollout(rollout_path):
    import json as _json

    signals = []
    seen = set()

    try:
        with open(rollout_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                except _json.JSONDecodeError:
                    continue

                payload = entry.get('payload', {})
                if not isinstance(payload, dict):
                    continue

                ptype = payload.get('type', '')

                # 信号1: 工具调用中的命令执行
                if ptype == 'function_call':
                    name = payload.get('name', '')
                    args = payload.get('arguments', '')
                    if isinstance(args, str):
                        try:
                            args = _json.loads(args)
                        except _json.JSONDecodeError:
                            args = {}
                    if isinstance(args, dict):
                        cmd = args.get('cmd', '') or args.get('command', '')
                    elif isinstance(args, list):
                        cmd = ' '.join(str(a) for a in args)
                    else:
                        cmd = str(args)
                    if cmd:
                        sig = _classify_command(name, cmd)
                        if sig and sig['key'] not in seen:
                            seen.add(sig['key'])
                            signals.append(sig)

                # 信号2: 函数调用输出中的测试结果
                if ptype == 'function_call_output':
                    output = payload.get('output', '')
                    sig = _classify_output(output)
                    if sig and sig['key'] not in seen:
                        seen.add(sig['key'])
                        signals.append(sig)

                # 信号3: agent 消息中的关键决策
                if ptype == 'agent_message':
                    content = payload.get('content', '')
                    sig = _classify_agent_message(content)
                    if sig and sig['key'] not in seen:
                        seen.add(sig['key'])
                        signals.append(sig)

    except OSError:
        return signals

    return signals


def _classify_command(tool_name, cmd):
    if isinstance(cmd, list):
        cmd = ' '.join(str(c) for c in cmd)
    cmd = str(cmd)
    if not cmd.strip():
        return None
    key = cmd[:60]
    cmd_lower = cmd.lower()

    # 测试执行
    if 'test_fact_checker' in cmd:
        return {'key': key, 'name': 'auto-test-run',
                'type': 'project', 'content': f'执行测试: {cmd[:200]}'}

    # Git 操作
    if 'git commit' in cmd_lower or 'git add' in cmd_lower:
        return {'key': key, 'name': 'auto-git-commit',
                'type': 'project', 'content': f'Git 操作: {cmd[:200]}'}

    # 文件写入 (cat > ... <<)
    if cmd.strip().startswith('cat >'):
        fname = cmd.split('>')[1].strip().split()[0] if '>' in cmd else '?'
        return {'key': key, 'name': f'auto-file-{fname.replace("/","-")[:40]}',
                'type': 'project', 'content': f'文件创建/修改: {fname} — {cmd[6:200]}'}

    # Python 脚本创建
    if 'cat >' in cmd and '.py' in cmd:
        return {'key': key, 'name': 'auto-py-script',
                'type': 'project', 'content': f'Python 脚本: {cmd[:200]}'}

    return None


def _classify_output(output):
    output_str = str(output)[:500]

    # 测试通过
    if '全部通过' in output_str or ('通过' in output_str and '测试' in output_str):
        key = 'test-pass-' + output_str[:40]
        return {'key': key, 'name': 'auto-test-pass',
                'type': 'project', 'content': f'测试通过: {output_str[:200]}'}

    # 错误/失败
    if 'Traceback' in output_str or 'Error' in output_str or '失败' in output_str:
        key = 'err-' + output_str[:40]
        return {'key': key, 'name': 'auto-error',
                'type': 'project', 'content': f'执行错误: {output_str[:200]}'}

    return None


def _classify_agent_message(content):
    text = str(content)[:500]

    decision_keywords = ['决定', '选择', '采用', '架构', '重构', '设计']
    for kw in decision_keywords:
        if kw in text:
            key = f'decision-{kw}-{text[:40]}'
            return {'key': key, 'name': f'auto-decision-{kw}',
                    'type': 'project', 'content': f'决策({kw}): {text[:200]}'}

    # 修复描述
    if '修复' in text or 'fix' in text.lower():
        key = 'fix-' + text[:40]
        return {'key': key, 'name': 'auto-fix',
                'type': 'project', 'content': f'修复: {text[:200]}'}

    return None


def remember_fact(name, content, mem_type='project'):
    store = get_auto_memory_store()
    if store is None:
        return {'error': 'reasonix_store 模块不可用'}
    return store.remember(name, content, mem_type=mem_type)


def forget_fact(name):
    store = get_auto_memory_store()
    if store is None:
        return {'error': 'reasonix_store 模块不可用'}
    return store.forget(name)


def quick_add(note, doc_path=None):
    if not _HAS_DOCS:
        return {'error': 'reasonix_docs 模块不可用'}
    if doc_path is None:
        doc_path = str(PROJECT_REASONIX / 'REASONIX.local.md')
    return quick_add_note(doc_path, note)


def load_custom_commands(*extra_dirs):
    if not _HAS_COMMANDS:
        return {'error': 'reasonix_commands 模块不可用'}
    loader = CommandLoader()
    default_dirs = [
        str(GLOBAL_REASONIX / 'commands'),
        str(PROJECT_REASONIX / 'commands'),
    ]
    all_dirs = list(default_dirs) + list(extra_dirs)
    count = loader.load_dirs(*all_dirs)
    return {
        'ok': True,
        'count': count,
        'commands': loader.list_commands(),
        'tool_description': loader.to_slash_tool_description(),
    }


def get_enriched_context(recent_threads=None):
    ctx = get_session_context(recent_threads)

    if _HAS_STORE:
        store = get_auto_memory_store()
        if store:
            ctx['auto_memory'] = {
                'index': store.index(),
                'stats': store.stats(),
            }

    if _HAS_DOCS:
        user_dir = str(GLOBAL_REASONIX)
        docs = discover_docs(cwd=str(PROJECT_ROOT), user_dir=user_dir)
        ctx['hierarchical_docs'] = [
            {'path': d['path'], 'scope': d['scope'],
             'body_preview': d['body'][:200]}
            for d in docs
        ]
        idx = ctx.get('auto_memory', {}).get('index', '')
        ctx['memory_block'] = compose_memory_block(docs, idx)

    if _HAS_COMMANDS:
        loader = CommandLoader()
        loader.load_dirs(
            str(GLOBAL_REASONIX / 'commands'),
            str(PROJECT_REASONIX / 'commands'),
        )
        ctx['custom_commands'] = loader.list_commands()

    return ctx


    # 收集条目，key = (scope, category, content前80字符) 用于去重
    seen = {}  # key → (timestamp, entry)
    entries = []

    for sc, cat in categories_to_load:
        storage = SCOPE_STORAGE.get(sc, 'project')
        # 读取顺序：先项目，后全局
        dirs_to_check = []
        if storage == 'project':
            dirs_to_check = [PROJECT_MEMORY, GLOBAL_MEMORY]  # 项目优先，全局 fallback
        else:
            dirs_to_check = [GLOBAL_MEMORY]

        for mem_dir in dirs_to_check:
            filepath = mem_dir / f'{sc}_{cat}.jsonl'
            if not filepath.exists():
                continue
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        # 去重键
                        content_preview = entry.get('content', '')[:80]
                        key = (entry.get('scope', sc), entry.get('category', cat), content_preview)
                        ts = entry.get('timestamp', '')
                        if key not in seen or ts > seen[key][0]:
                            seen[key] = (ts, entry)
            except OSError:
                continue

    # 返回去重后的条目，按时间排序
    entries = [entry for _, entry in sorted(seen.values(), key=lambda x: x[0])]
    return entries


def _scope_for_category(category: str) -> str | None:
    '''返回类别所属的 scope。'''
    for scope, cats in MEMORY_SCOPES.items():
        if category in cats:
            return scope
    return None


# ── 会话恢复上下文 ────────────────────────────────────────

def get_session_context(recent_threads: int | None = None) -> dict:
    '''
    生成会话恢复上下文。
    返回：最近线程摘要 + 四层记忆（项目优先）。
    '''
    config = load_config()
    ctx_cfg = config.get('context', {})
    if recent_threads is None:
        recent_threads = ctx_cfg.get('recent_threads', 3)
    max_exec = ctx_cfg.get('max_execution_memories', 20)

    threads = list_recent_threads(recent_threads)

    project_memories = load_memories(scope='project')
    user_memories = load_memories(scope='user')
    system_memories = load_memories(scope='system')
    execution_memories = load_memories(scope='execution')

    context = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'config': {
            'global_config': str(GLOBAL_CONFIG),
            'project_config': str(PROJECT_CONFIG),
            'project_root': str(PROJECT_ROOT),
        },
        'recent_sessions': [],
        'project_memories': project_memories,
        'user_memories': user_memories,
        'system_memories': system_memories,
        'execution_memories': execution_memories[-max_exec:],
        'summary': '',
    }

    for t in threads:
        if 'error' in t:
            continue
        context['recent_sessions'].append({
            'id': t.get('id', '')[:8],
            'title': t.get('title', ''),
            'first_message': t.get('first_user_message', ''),
            'updated': t.get('updated_at_iso', ''),
            'tokens': t.get('tokens_used', 0),
        })

    if context['recent_sessions']:
        titles = [s['first_message'][:60] for s in context['recent_sessions'] if s['first_message']]
        context['summary'] = '最近会话: ' + ' | '.join(titles)

    return context


# ── 滚动摘要（从 rollout 提取用户消息） ──────────────────

def summarize_rollout(rollout_path: str, max_user_msgs: int = 10) -> dict:
    '''从 rollout JSONL 文件中提取用户消息摘要。'''
    if not os.path.exists(rollout_path):
        return {'error': f'文件不存在: {rollout_path}'}
    try:
        user_msgs = _extract_user_messages(rollout_path)[:max_user_msgs]
        total_lines = _count_lines(rollout_path)
        return {
            'file': rollout_path,
            'total_lines': total_lines,
            'user_message_count': len(user_msgs),
            'user_messages': user_msgs,
        }
    except (OSError, json.JSONDecodeError) as e:
        return {'error': f'解析失败: {e}'}


# ── 数据迁移 ──────────────────────────────────────────────

def migrate_from_codex_memories() -> dict:
    '''将 .codex/memories/ 中的旧数据迁移到 Reasonix 目录。'''
    old_dir = Path.home() / '.codex' / 'memories'
    if not old_dir.exists():
        return {'ok': True, 'migrated': 0, 'message': '无旧数据需要迁移'}

    count = 0
    for old_file in sorted(old_dir.glob('*.jsonl')):
        # 解析文件名确定 scope
        stem = old_file.stem  # e.g., "architecture" or "project_architecture"
        scope = None
        category = None

        # 尝试 scope_category 格式
        for sc in MEMORY_SCOPES:
            for cat in MEMORY_SCOPES[sc]:
                if stem == f'{sc}_{cat}':
                    scope = sc
                    category = cat
                    break
            if scope:
                break

        # 旧格式：直接用 category 名，需要推断 scope
        if scope is None:
            for sc, cats in MEMORY_SCOPES.items():
                if stem in cats:
                    scope = sc
                    category = stem
                    break

        if scope is None:
            continue

        target_dir = _resolve_memory_dir(scope)
        target_file = target_dir / f'{scope}_{category}.jsonl'

        try:
            with open(old_file, 'r', encoding='utf-8') as src:
                content = src.read()
            # 追加到目标文件
            with open(target_file, 'a', encoding='utf-8') as dst:
                dst.write(content)
            count += 1
        except OSError:
            continue

    return {'ok': True, 'migrated': count, 'message': f'已迁移 {count} 个文件到 Reasonix 目录'}


# ── 内部辅助 ──────────────────────────────────────────────

def _ts_to_iso(ts: int) -> str:
    '''Unix 时间戳转 ISO 字符串。'''
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))


def _count_lines(filepath: str) -> int:
    '''快速统计文件行数。'''
    count = 0
    with open(filepath, 'r', encoding='utf-8') as f:
        for _ in f:
            count += 1
    return count


def _extract_user_messages(rollout_path: str) -> list[str]:
    '''从 rollout JSONL 中提取用户消息文本。'''
    messages = []
    with open(rollout_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = entry.get('payload', {})
            msg_type = entry.get('type', '')
            if msg_type == 'user' and isinstance(payload, dict):
                text = payload.get('text', '')
                if text and text.strip():
                    messages.append(text.strip())
    return messages


# ── 状态报告 ──────────────────────────────────────────────

def get_status() -> dict:
    '''返回 Reasonix 记忆系统的完整状态报告。'''
    config = load_config()

    def _count_dir(d: Path) -> dict:
        result = {}
        if d.exists():
            for f in sorted(d.glob('*.jsonl')):
                result[f.name] = _count_lines(str(f))
        return result

    return {
        'paths': {
            'global': str(GLOBAL_REASONIX),
            'project': str(PROJECT_REASONIX),
            'project_root': str(PROJECT_ROOT),
        },
        'config': {
            'global': str(GLOBAL_CONFIG) if GLOBAL_CONFIG.exists() else '(未创建)',
            'project': str(PROJECT_CONFIG) if PROJECT_CONFIG.exists() else '(未创建)',
            'merged': config,
        },
        'global_memories': _count_dir(GLOBAL_MEMORY),
        'project_memories': _count_dir(PROJECT_MEMORY),
    }


# ── CLI 入口 ──────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    def _usage():
        print('用法: python3 codex_memory.py <命令> [参数]')
        print('命令:')
        print('  threads                  — 列出最近线程')
        print('  summary <id>             — 查看线程摘要')
        print('  context                  — 生成会话恢复上下文（四层记忆）')
        print('  enriched                 — 生成增强上下文（含 Reasonix 新功能）')
        print('  memories [scope]         — 列出记忆（project|user|system|execution）')
        print('  save <scope> <cat> <内容> — 写入一条记忆')
        print('  remember <名称> <内容>   — 保存事实到自动记忆存储')
        print('  forget <名称>             — 从自动记忆存储删除事实')
        print('  auto-remember [rollout]   — 自动从会话提取关键信号并保存')
        print('  quick-add <笔记>          — 快速追加笔记到 REASONIX.local.md')
        print('  commands [dirs...]        — 加载自定义斜杠命令')
        print('  status                   — 显示 Reasonix 状态报告')
        print('  migrate                  — 从 .codex/memories/ 迁移旧数据')
        print('  init-config              — 初始化全局 + 项目配置文件')
        sys.exit(1)

    if len(sys.argv) < 2:
        _usage()

    cmd = sys.argv[1]

    if cmd == 'threads':
        threads = list_recent_threads()
        for t in threads:
            print(f"{t.get('id','')[:8]} | {t.get('first_user_message','')[:80]} | {t.get('updated_at_iso','')}")

    elif cmd == 'summary' and len(sys.argv) > 2:
        summary = get_thread_summary(sys.argv[2])
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    elif cmd == 'context':
        ctx = get_session_context()
        print(json.dumps(ctx, ensure_ascii=False, indent=2))

    elif cmd == 'enriched':
        ctx = get_enriched_context()
        print(json.dumps(ctx, ensure_ascii=False, indent=2))

    elif cmd == 'memories':
        scope = sys.argv[2] if len(sys.argv) > 2 else None
        if scope and scope not in MEMORY_SCOPES:
            print(f'无效范围: {scope}，可选: {list(MEMORY_SCOPES.keys())}')
            sys.exit(1)
        mems = load_memories(scope=scope)
        if not mems:
            print('(无记忆记录)')
        for m in mems:
            cat = m.get('category', '?')
            sc = m.get('scope', '?')
            print(f"[{sc}/{cat}] {m.get('content','')[:100]}")

    elif cmd == 'save' and len(sys.argv) >= 5:
        scope = sys.argv[2]
        category = sys.argv[3]
        content = ' '.join(sys.argv[4:])
        if scope == 'project':
            result = save_memory(category, content)
        elif scope == 'user':
            result = save_user_memory(category, content)
        elif scope == 'system':
            result = save_system_memory(category, content)
        elif scope == 'execution':
            result = save_execution_memory(category, content)
        else:
            print(f'无效范围: {scope}')
            sys.exit(1)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == 'remember' and len(sys.argv) >= 4:
        name = sys.argv[2]
        content = ' '.join(sys.argv[3:])
        mem_type = sys.argv[3] if len(sys.argv) > 3 else 'project'
        result = remember_fact(name, content)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == 'forget' and len(sys.argv) >= 3:
        name = sys.argv[2]
        result = forget_fact(name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == 'auto-remember':
        path = sys.argv[2] if len(sys.argv) > 2 else None
        result = auto_remember(path)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == 'quick-add' and len(sys.argv) >= 3:
        note = ' '.join(sys.argv[2:])
        result = quick_add(note)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == 'commands':
        extra = sys.argv[2:] if len(sys.argv) > 2 else []
        result = load_custom_commands(*extra)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == 'status':
        status = get_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))

    elif cmd == 'migrate':
        result = migrate_from_codex_memories()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == 'init-config':
        r1 = save_global_config(DEFAULT_CONFIG)
        print(f'全局配置: {r1}')
        project_cfg = {
            'version': 1,
            'context': {'recent_threads': 5, 'max_execution_memories': 30},
        }
        r2 = save_project_config(project_cfg)
        print(f'项目配置: {r2}')

    else:
        print(f'未知命令: {cmd}')
        _usage()
