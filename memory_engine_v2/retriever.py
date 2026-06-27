# -*- coding: utf-8 -*-
'''记忆检索引擎 —— 双通道：语义搜索 + 结构过滤 + 混合排序。

检索流程：
  query → 语义向量 → 余弦相似度 → top-k 候选
        → 结构过滤（type, tags, importance）→ 混合排序 → 返回结果
'''

import time
from memory_engine_v2.embedder import Embedder, cosine_similarity
from memory_engine_v2.store import MemoryStore


class Retriever:
    '''记忆检索引擎。'''

    def __init__(self, store: MemoryStore, embedder: Embedder | None = None):
        self.store = store
        self.embedder = embedder or Embedder()

    def search(self, query: str, top_k: int = 5,
               mem_type: str | None = None, tags: list[str] | None = None,
               min_importance: float = 0.0,
               semantic_weight: float = 0.6,
               importance_weight: float = 0.3,
               recency_weight: float = 0.1) -> list[dict]:
        '''
        混合检索。

        参数：
          query: 查询文本
          top_k: 返回条数
          mem_type: 记忆类型过滤
          tags: 标签过滤（AND）
          min_importance: 最小重要性阈值
          semantic_weight: 语义相似度权重
          importance_weight: 重要性权重
          recency_weight: 时间衰减权重
        '''
        candidates = self.store.all()

        # 结构过滤
        if mem_type:
            candidates = [m for m in candidates if m.get('type') == mem_type]
        if tags:
            candidates = [m for m in candidates
                          if all(t in (m.get('tags') or []) for t in tags)]
        if min_importance > 0:
            candidates = [m for m in candidates
                          if m.get('importance', 0) >= min_importance]

        if not candidates:
            return []

        # 计算查询向量
        query_vec = self.embedder.encode(query)
        now = int(time.time())

        # 混合打分
        scored = []
        for mem in candidates:
            sem_sim = cosine_similarity(query_vec, mem.get('embedding', []))
            importance = mem.get('importance', 0.5)
            age = now - mem.get('timestamp', now)
            recency = 1.0 / (1.0 + age / 86400.0)  # 按天衰减

            score = (semantic_weight * sem_sim +
                     importance_weight * importance +
                     recency_weight * recency)

            # 对于纯过滤查询（无文本），语义权重为 0
            if not query.strip():
                score = (importance_weight * importance +
                         recency_weight * recency)

            scored.append((score, mem))
            # 标记访问
            mem['last_accessed'] = now
            mem['access_count'] = mem.get('access_count', 0) + 1

        # 排序并返回 top-k
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, mem in scored[:top_k]:
            mem['_score'] = round(score, 4)
            mem['_semantic_sim'] = round(
                cosine_similarity(query_vec, mem.get('embedding', [])), 4
            )
            results.append(mem)

        return results

    def search_by_tags(self, tags: list[str], top_k: int = 10) -> list[dict]:
        '''按标签精确搜索。'''
        return self.search('', top_k=top_k, tags=tags,
                           semantic_weight=0, importance_weight=0.7,
                           recency_weight=0.3)

    def search_similar(self, mem_id: str, top_k: int = 5) -> list[dict]:
        '''查找与指定记忆最相似的其他记忆。'''
        mem = self.store.get(mem_id)
        if not mem:
            return []
        query_vec = mem.get('embedding', [])
        if not query_vec:
            return []

        scored = []
        for other in self.store.all():
            if other['id'] == mem_id:
                continue
            sim = cosine_similarity(query_vec, other.get('embedding', []))
            scored.append((sim, other))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for sim, m in scored[:top_k]:
            m['_score'] = round(sim, 4)
            results.append(m)
        return results


# ── 便捷函数 ──────────────────────────────────────────────

def retrieve(query: str, store: MemoryStore | None = None,
             top_k: int = 5, **kwargs) -> list[dict]:
    '''快捷检索。'''
    s = store or MemoryStore()
    r = Retriever(s)
    return r.search(query, top_k=top_k, **kwargs)
