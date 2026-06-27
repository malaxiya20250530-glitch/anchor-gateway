#!/usr/bin/env python3
"""
轻量嵌入检索 — 纯Python标准库 TF-IDF + 余弦相似度

用法:
  searcher = EmbeddingSearcher()
  searcher.build_index(KNOWLEDGE_BASE)
  results = searcher.search("秦朝持续了将近三百年")
  # → [("秦", 0.72), ("汉", 0.45), ...]
"""

import re, math, json
from collections import Counter
from pathlib import Path
from typing import Optional


class EmbeddingSearcher:
    """Bigram TF-IDF 嵌入检索引擎"""

    def __init__(self):
        self.vocab: list[str] = []
        self.idf: dict[str, float] = {}
        self.doc_vectors: dict[str, list[float]] = {}
        self.kb_entries: dict = {}
        self._built = False

    def _tokenize(self, text: str) -> Counter:
        """将文本转换为bigram计数向量"""
        # 提取所有连续字符bigram
        bigrams = [text[i:i+2] for i in range(len(text)-1)]
        # 也加入单字（捕捉关键词）
        unigrams = list(text)
        return Counter(bigrams + unigrams)

    def build_index(self, kb: dict):
        """从知识库构建TF-IDF索引"""
        self.kb_entries = kb

        # 1. 构建词汇表
        all_tokens = set()
        for key, entry in kb.items():
            # 索引: 键名 + 所有事实
            doc_text = key + ' ' + ' '.join(entry.get('facts', []))
            tokens = self._tokenize(doc_text)
            all_tokens.update(tokens.keys())

        self.vocab = sorted(all_tokens)
        vocab_index = {t: i for i, t in enumerate(self.vocab)}
        doc_count = len(kb)

        # 2. 计算IDF
        df = Counter()
        doc_tokens = {}
        for key, entry in kb.items():
            doc_text = key + ' ' + ' '.join(entry.get('facts', []))
            tokens = self._tokenize(doc_text)
            doc_tokens[key] = tokens
            for t in set(tokens.keys()):
                df[t] += 1

        self.idf = {t: math.log((doc_count + 1) / (df[t] + 1)) + 1.0
                    for t in self.vocab}

        # 3. 计算文档TF-IDF向量
        for key, entry in kb.items():
            tokens = doc_tokens[key]
            vec = [0.0] * len(self.vocab)
            total = sum(tokens.values()) or 1
            for t, count in tokens.items():
                if t in vocab_index:
                    tf = count / total
                    vec[vocab_index[t]] = tf * self.idf.get(t, 0)
            # L2归一化
            norm = math.sqrt(sum(v*v for v in vec)) or 1.0
            self.doc_vectors[key] = [v / norm for v in vec]

        self._built = True

    def _query_vector(self, text: str) -> list[float]:
        """计算查询文本的TF-IDF向量"""
        tokens = self._tokenize(text)
        vec = [0.0] * len(self.vocab)
        total = sum(tokens.values()) or 1
        for t, count in tokens.items():
            if t in self.idf:
                tf = count / total
                idx = self.vocab.index(t)
                vec[idx] = tf * self.idf[t]
        norm = math.sqrt(sum(v*v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def search(self, query: str, top_k: int = 5, min_score: float = 0.1) -> list[tuple[str, float]]:
        """搜索最匹配的KB条目，返回 [(key, score), ...]"""
        if not self._built:
            return []

        q_vec = self._query_vector(query)
        scores = []

        for key, d_vec in self.doc_vectors.items():
            # 余弦相似度
            dot = sum(q * d for q, d in zip(q_vec, d_vec))
            if dot >= min_score:
                scores.append((key, dot))

        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]


# ── 全局单例 ──
_searcher: Optional[EmbeddingSearcher] = None


def get_searcher(kb: dict = None) -> EmbeddingSearcher:
    """获取全局嵌入检索引擎（懒加载）"""
    global _searcher
    if _searcher is None and kb:
        _searcher = EmbeddingSearcher()
        _searcher.build_index(kb)
    return _searcher


def init_searcher(kb_path: str = None):
    """初始化嵌入检索引擎"""
    global _searcher
    if kb_path is None:
        kb_path = str(Path(__file__).parent / 'kb_core.json')

    with open(kb_path) as f:
        kb = json.load(f)

    _searcher = EmbeddingSearcher()
    _searcher.build_index(kb)
    return _searcher
