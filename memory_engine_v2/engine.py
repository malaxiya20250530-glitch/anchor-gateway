# -*- coding: utf-8 -*-
'''Memory Engine v2 —— 统一入口。

整合所有子系统：
  Embedder  → 向量嵌入
  Store     → 持久化存储
  Writer    → 写入管道
  Retriever → 混合检索
  Compressor→ 压缩合并
  Decay     → 衰减遗忘

用法：
  from memory_engine_v2 import MemoryEngine
  engine = MemoryEngine()
  engine.remember('DAG uses queue scheduler', tags=['architecture'])
  results = engine.recall('how does dag work')
  engine.forget_old()  # 应用衰减
  engine.compress()    # 压缩记忆
'''

import time
from pathlib import Path

from memory_engine_v2.embedder import Embedder, cosine_similarity
from memory_engine_v2.store import MemoryStore
from memory_engine_v2.retriever import Retriever
from memory_engine_v2.compressor import Compressor
from memory_engine_v2.decay import DecayManager
from memory_engine_v2.writer import MemoryWriter


class MemoryEngine:
    '''
    Memory Engine v2 —— 统一记忆接口。

    remember()  → 写入记忆
    recall()    → 语义检索
    forget_old()→ 衰减清理
    compress()  → 压缩合并
    context()   → 生成 DAG 规划上下文
    '''

    def __init__(self, store_dir: str | None = None, embed_dim: int = 256):
        self.embedder = Embedder(dim=embed_dim)
        self.store = MemoryStore(store_dir=store_dir, embedder=self.embedder)
        self.retriever = Retriever(self.store, self.embedder)
        self.writer = MemoryWriter(self.store, self.embedder)
        self.compressor = Compressor(self.store)
        self.decay = DecayManager(self.store)

    # ── 核心 API ────────────────────────────────────────

    def remember(self, content: str, mem_type: str = 'project',
                 tags: list[str] | None = None,
                 confidence: float = 0.5) -> str:
        '''写入一条记忆。返回记忆 ID。'''
        return self.writer.write(content, mem_type=mem_type,
                                 tags=tags, confidence=confidence)

    def recall(self, query: str, top_k: int = 5,
               mem_type: str | None = None,
               tags: list[str] | None = None,
               min_importance: float = 0.0) -> list[dict]:
        '''语义检索记忆。'''
        return self.retriever.search(
            query, top_k=top_k, mem_type=mem_type,
            tags=tags, min_importance=min_importance
        )

    def recall_similar(self, mem_id: str, top_k: int = 5) -> list[dict]:
        '''查找相似记忆。'''
        return self.retriever.search_similar(mem_id, top_k=top_k)

    def forget_old(self) -> dict:
        '''应用衰减并清理。'''
        return self.decay.apply_decay()

    def compress(self) -> dict:
        '''压缩记忆。'''
        return self.compressor.compress()

    def context(self, query: str = '', top_k: int = 8) -> dict:
        '''
        生成 DAG 规划上下文。

        返回结构化上下文供规划器注入。
        '''
        if query:
            relevant = self.recall(query, top_k=top_k, min_importance=0.3)
        else:
            # 无查询时返回最重要的记忆
            all_mems = sorted(self.store.all(),
                              key=lambda m: m.get('importance', 0), reverse=True)
            relevant = all_mems[:top_k]

        return {
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'total_memories': self.store.count(),
            'relevant_memories': [
                {
                    'content': m.get('content', ''),
                    'importance': m.get('importance', 0),
                    'tags': m.get('tags', []),
                    'type': m.get('type', 'project'),
                }
                for m in relevant
            ],
            'stats': self.store.stats(),
        }

    def stats(self) -> dict:
        '''存储统计。'''
        return self.store.stats()


# ── 全局单例 ──────────────────────────────────────────────

_engine: MemoryEngine | None = None


def get_engine() -> MemoryEngine:
    '''获取全局记忆引擎实例。'''
    global _engine
    if _engine is None:
        _engine = MemoryEngine()
    return _engine


# ── CLI 入口 ──────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    engine = MemoryEngine()

    if len(sys.argv) < 2:
        print('Memory Engine v2 CLI')
        print('  用法: python3 -m memory_engine_v2.engine <命令> [参数]')
        print('  命令: stats | search <query> | context [query] | compress | decay')
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == 'stats':
        import json
        print(json.dumps(engine.stats(), ensure_ascii=False, indent=2))

    elif cmd == 'search' and len(sys.argv) > 2:
        results = engine.recall(sys.argv[2])
        for r in results:
            score = r.get('_score', 0)
            bar = '█' * max(1, int(score * 20))
            print(f'  [{r["id"]}] {score:.3f} {bar}')
            print(f'    {r.get("content","")[:100]}')
            print()

    elif cmd == 'context':
        query = sys.argv[2] if len(sys.argv) > 2 else ''
        ctx = engine.context(query)
        import json
        print(json.dumps(ctx, ensure_ascii=False, indent=2))

    elif cmd == 'compress':
        result = engine.compress()
        print(f'压缩完成: {result}')

    elif cmd == 'decay':
        result = engine.forget_old()
        print(f'衰减完成: {result}')

    else:
        print(f'未知命令: {cmd}')
