# -*- coding: utf-8 -*-
'''记忆压缩器 —— 聚类 → 合并 → 摘要。

当记忆数超过阈值时触发：
  1. 按语义相似度聚类
  2. 合并相似记忆为一条
  3. 低重要性条目生成一句话摘要
'''

import time
from memory_engine_v2.embedder import cosine_similarity
from memory_engine_v2.store import MemoryStore


class Compressor:
    '''记忆压缩器。'''

    def __init__(self, store: MemoryStore,
                 similarity_threshold: float = 0.6,
                 max_memories: int = 500):
        self.store = store
        self.similarity_threshold = similarity_threshold
        self.max_memories = max_memories

    def should_compress(self) -> bool:
        '''是否需要压缩。'''
        return self.store.count() > self.max_memories

    def compress(self) -> dict:
        '''
        执行压缩：聚类合并相似记忆 + 清理低重要性条目。

        返回压缩统计。
        '''
        memories = self.store.all()
        before = len(memories)
        if before == 0:
            return {'before': 0, 'after': 0, 'merged': 0, 'removed': 0}

        # 按类型分组
        by_type: dict[str, list[dict]] = {}
        for m in memories:
            t = m.get('type', 'project')
            by_type.setdefault(t, []).append(m)

        merged_count = 0
        removed_count = 0
        new_memories: list[dict] = []

        for mem_type, group in by_type.items():
            clustered = self._cluster_by_similarity(group)
            for cluster in clustered:
                if len(cluster) == 1:
                    new_memories.append(cluster[0])
                else:
                    merged = self._merge_cluster(cluster)
                    new_memories.append(merged)
                    merged_count += len(cluster) - 1

            # 移除低重要性记忆
            kept = []
            for m in new_memories:
                if m.get('importance', 0.5) < 0.1:
                    removed_count += 1
                else:
                    kept.append(m)
            new_memories = kept

        # 写回
        self.store._memories = new_memories
        self.store._rewrite_all()

        return {
            'before': before,
            'after': len(new_memories),
            'merged': merged_count,
            'removed': removed_count,
        }

    def _cluster_by_similarity(self, memories: list[dict]) -> list[list[dict]]:
        '''简单贪心聚类：相似度 > 阈值则归入同一簇。'''
        if len(memories) <= 1:
            return [memories]

        clusters: list[list[dict]] = []
        used = set()

        for i, m1 in enumerate(memories):
            if i in used:
                continue
            cluster = [m1]
            used.add(i)
            for j, m2 in enumerate(memories):
                if j in used:
                    continue
                sim = cosine_similarity(
                    m1.get('embedding', []),
                    m2.get('embedding', [])
                )
                if sim >= self.similarity_threshold:
                    cluster.append(m2)
                    used.add(j)
            clusters.append(cluster)

        return clusters

    def _merge_cluster(self, cluster: list[dict]) -> dict:
        '''合并一组相似记忆为一条摘要。'''
        # 保留重要性最高的一条为基础
        base = max(cluster, key=lambda m: m.get('importance', 0))
        contents = [m.get('content', '') for m in cluster]

        # 简单合并策略：取最重要的内容，加上特有标签
        merged_tags = sorted(set(
            tag for m in cluster for tag in (m.get('tags') or [])
        ))
        avg_importance = sum(m.get('importance', 0.5) for m in cluster) / len(cluster)
        max_decay = max(m.get('decay_rate', 0.01) for m in cluster)

        # 生成摘要
        if len(contents) <= 2:
            summary = ' | '.join(contents)
        else:
            summary = base.get('content', '') + f'（等 {len(cluster)} 条相关记忆）'

        return {
            'id': base['id'],
            'type': base.get('type', 'project'),
            'content': summary,
            'embedding': base.get('embedding', []),
            'tags': merged_tags,
            'importance': round(avg_importance, 3),
            'decay_rate': max_decay,
            'timestamp': max(m.get('timestamp', 0) for m in cluster),
            'last_accessed': int(time.time()),
            'access_count': sum(m.get('access_count', 0) for m in cluster),
            '_compressed': True,
        }


# ── 便捷 ──────────────────────────────────────────────────

def compress_store(store: MemoryStore, threshold: float = 0.6) -> dict:
    '''快捷压缩。'''
    c = Compressor(store, similarity_threshold=threshold)
    return c.compress()
