# -*- coding: utf-8 -*-
'''记忆存储层 —— JSONL 持久化 + 向量索引。

每条记忆存储为：
  {
    "id": "mem_xxx",
    "type": "project|user|system|execution",
    "content": "文本内容",
    "embedding": [0.12, -0.44, ...],
    "tags": ["architecture", "dag"],
    "importance": 0.87,
    "decay_rate": 0.02,
    "timestamp": 1710000000,
    "last_accessed": 1715000000,
    "access_count": 12
  }
'''

import json
import os
import time
from pathlib import Path

from memory_engine_v2.embedder import Embedder, cosine_similarity


DEFAULT_STORE_DIR = Path.home() / '.codex' / 'memories_v2'
DEFAULT_STORE_DIR.mkdir(parents=True, exist_ok=True)


class MemoryStore:
    '''记忆持久化存储。'''

    def __init__(self, store_dir: str | Path | None = None, embedder: Embedder | None = None):
        self._dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder or Embedder()
        self._memories: list[dict] = []
        self._id_counter = 0
        self._load_all()

    # ── 读写 ────────────────────────────────────────────

    def _filepath(self, mem_type: str) -> Path:
        return self._dir / f'{mem_type}.jsonl'

    def _load_all(self) -> None:
        '''从磁盘加载所有记忆。'''
        self._memories = []
        max_id = 0
        for mem_type in ('project', 'user', 'system', 'execution'):
            fp = self._filepath(mem_type)
            if not fp.exists():
                continue
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            mem = json.loads(line)
                            self._memories.append(mem)
                            num = int(mem.get('id', 'mem_0').split('_')[1])
                            if num > max_id:
                                max_id = num
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue
        self._id_counter = max_id + 1

    def _save_one(self, mem: dict) -> None:
        '''追加一条记忆到磁盘。'''
        mem_type = mem.get('type', 'project')
        fp = self._filepath(mem_type)
        try:
            with open(fp, 'a', encoding='utf-8') as f:
                f.write(json.dumps(mem, ensure_ascii=False) + '\n')
        except OSError:
            pass

    def _rewrite_type(self, mem_type: str, memories: list[dict]) -> None:
        '''重写指定类型的所有记忆（用于压缩/删除后）。'''
        fp = self._filepath(mem_type)
        try:
            with open(fp, 'w', encoding='utf-8') as f:
                for mem in memories:
                    f.write(json.dumps(mem, ensure_ascii=False) + '\n')
        except OSError:
            pass

    # ── CRUD ────────────────────────────────────────────

    def add(self, content: str, mem_type: str = 'project',
            tags: list[str] | None = None, importance: float = 0.5,
            decay_rate: float = 0.01) -> str:
        '''添加一条记忆，返回记忆 ID。'''
        mem_id = f'mem_{self._id_counter}'
        self._id_counter += 1

        mem = {
            'id': mem_id,
            'type': mem_type,
            'content': content,
            'embedding': self._embedder.encode(content),
            'tags': tags or self._auto_tags(content),
            'importance': max(0.0, min(1.0, importance)),
            'decay_rate': decay_rate,
            'timestamp': int(time.time()),
            'last_accessed': int(time.time()),
            'access_count': 0,
        }
        self._memories.append(mem)
        self._save_one(mem)
        return mem_id

    def get(self, mem_id: str) -> dict | None:
        '''按 ID 获取记忆。'''
        for m in self._memories:
            if m['id'] == mem_id:
                m['last_accessed'] = int(time.time())
                m['access_count'] = m.get('access_count', 0) + 1
                return m
        return None

    def update(self, mem_id: str, **kwargs) -> bool:
        '''更新记忆字段。'''
        mem = self.get(mem_id)
        if not mem:
            return False
        allowed = {'content', 'tags', 'importance', 'decay_rate', 'type'}
        for k, v in kwargs.items():
            if k in allowed:
                mem[k] = v
        if 'content' in kwargs:
            mem['embedding'] = self._embedder.encode(kwargs['content'])
        return True

    def delete(self, mem_id: str) -> bool:
        '''删除一条记忆。'''
        for i, m in enumerate(self._memories):
            if m['id'] == mem_id:
                self._memories.pop(i)
                self._rewrite_all()
                return True
        return False

    def all(self) -> list[dict]:
        '''返回所有记忆。'''
        return self._memories

    def count(self) -> int:
        '''记忆总数。'''
        return len(self._memories)

    def _rewrite_all(self) -> None:
        '''全量重写磁盘（压缩/删除后调用）。'''
        by_type: dict[str, list[dict]] = {}
        for m in self._memories:
            t = m.get('type', 'project')
            by_type.setdefault(t, []).append(m)
        for t, mems in by_type.items():
            self._rewrite_type(t, mems)

    # ── 标签 ────────────────────────────────────────────

    def _auto_tags(self, content: str) -> list[str]:
        '''自动提取标签（简单关键词匹配）。'''
        keywords = {
            'architecture', 'dag', 'pipeline', 'queue', 'checker',
            'test', 'bug', 'performance', 'memory', 'embedding',
            'retrieval', 'decay', 'compression', 'gateway',
            '幻觉', '检测', '责任链', '知识库', '锚定', '嵌入',
        }
        lower = content.lower()
        return sorted([k for k in keywords if k in lower])

    # ── 统计 ────────────────────────────────────────────

    def stats(self) -> dict:
        '''返回存储统计。'''
        types = {}
        for m in self._memories:
            t = m.get('type', 'project')
            types[t] = types.get(t, 0) + 1
        return {
            'total': len(self._memories),
            'by_type': types,
            'avg_importance': (
                sum(m.get('importance', 0) for m in self._memories) / len(self._memories)
                if self._memories else 0
            ),
        }
