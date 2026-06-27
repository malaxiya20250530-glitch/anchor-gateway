# -*- coding: utf-8 -*-
'''记忆写入管道 —— 标准化 → 标签提取 → 重要性评分 → 嵌入 → 存储'''

import time
from memory_engine_v2.embedder import Embedder
from memory_engine_v2.store import MemoryStore


class MemoryWriter:
    '''记忆写入器 —— 封装完整的写入管道。'''

    def __init__(self, store: MemoryStore, embedder: Embedder | None = None):
        self.store = store
        self.embedder = embedder or Embedder()
        self._type_freq: dict[str, int] = {}   # 类型写入频率
        self._content_history: list[str] = []    # 近期内容（用于检测重复模式）

    def write(self, content: str, mem_type: str = 'project',
              tags: list[str] | None = None,
              confidence: float = 0.5,
              source: str = 'manual') -> str:
        '''
        写入管道：

        1. 标准化文本
        2. 提取标签
        3. 计算重要性评分
        4. 生成嵌入向量
        5. 持久化存储

        返回记忆 ID。
        '''
        # 1. 标准化
        content = self._normalize(content)

        # 2. 计算重要性
        importance = self._score_importance(content, mem_type, confidence)

        # 3. 衰减率（系统记忆更稳定）
        decay_rates = {
            'architecture': 0.005,
            'decision': 0.01,
            'tool_usage': 0.02,
            'bug': 0.03,
            'performance': 0.015,
        }
        decay_rate = decay_rates.get(
            (tags or [''])[0] if tags else '', 0.01
        )

        # 4. 写入
        mem_id = self.store.add(
            content=content,
            mem_type=mem_type,
            tags=tags,
            importance=importance,
            decay_rate=decay_rate,
        )

        # 5. 记录
        self._type_freq[mem_type] = self._type_freq.get(mem_type, 0) + 1
        self._content_history.append(content)
        if len(self._content_history) > 50:
            self._content_history = self._content_history[-50:]

        return mem_id

    def _normalize(self, text: str) -> str:
        '''标准化文本。'''
        text = text.strip()
        # 截断过长的内容
        if len(text) > 2000:
            text = text[:1997] + '...'
        return text

    def _score_importance(self, content: str, mem_type: str,
                          confidence: float) -> float:
        '''
        重要性评分公式：
          importance = 0.4 × frequency + 0.3 × recency + 0.2 × relevance + 0.1 × confidence
        '''
        # 频率：基于内容相似度检测重复模式
        freq_score = 0.5
        if self._content_history:
            matches = sum(
                1 for h in self._content_history[-10:]
                if self._jaccard_words(h, content) > 0.3
            )
            freq_score = min(1.0, 0.3 + matches * 0.15)

        # 新近度：系统类型记忆默认更高
        recency_score = 0.7 if mem_type == 'system' else 0.5

        # 系统相关性：架构和决策类型更重要
        relevance_map = {
            'architecture': 0.9,
            'decision': 0.85,
            'tool_usage': 0.6,
            'bug': 0.7,
            'performance': 0.65,
            'project': 0.7,
            'user': 0.5,
            'system': 0.95,
            'execution': 0.4,
        }
        relevance_score = relevance_map.get(mem_type, 0.5)

        score = (0.4 * freq_score + 0.3 * recency_score +
                 0.2 * relevance_score + 0.1 * confidence)
        return round(max(0.0, min(1.0, score)), 4)

    @staticmethod
    def _jaccard_words(a: str, b: str) -> float:
        '''词级 Jaccard 相似度。'''
        set_a = set(a.lower().split())
        set_b = set(b.lower().split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)
