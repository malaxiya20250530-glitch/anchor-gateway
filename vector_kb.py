#!/usr/bin/env python3
import re
"""
向量知识库 — 纯 Python 实现（零外部依赖）
用字符 n-gram TF-IDF 做中文语义向量检索
"""

import json
import math
from pathlib import Path
from collections import Counter
from typing import Optional


def _ngrams(text: str, n: int = 2) -> list[str]:
    """提取字符 n-gram，中文天然适合 2-gram + 3-gram"""
    grams = []
    for size in (2, 3):
        for i in range(len(text) - size + 1):
            grams.append(text[i:i+size])
    return grams


def _tfidf_vector(texts: list[str]):
    """计算 TF-IDF 向量（拟合 + 转换一步完成）"""
    # 文档频率
    df = Counter()
    all_grams = []
    for t in texts:
        grams = _ngrams(t)
        all_grams.append(Counter(grams))
        df.update(set(grams))
    
    N = len(texts)
    vocab = list(df.keys())
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    
    vectors = []
    for grams_counter in all_grams:
        vec = [0.0] * len(vocab)
        for gram, tf in grams_counter.items():
            if gram in vocab_idx:
                idf = math.log((N + 1) / (df[gram] + 1)) + 1
                vec[vocab_idx[gram]] = tf * idf
        # L2 归一化
        norm = math.sqrt(sum(v*v for v in vec))
        if norm > 0:
            vec = [v/norm for v in vec]
        vectors.append(vec)
    
    return vectors, vocab, vocab_idx, df, N


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度"""
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class VectorKnowledgeBase:
    """轻量向量知识库 — 纯 Python，无需 GPU"""

    def __init__(self, kb_path: str = None, lazy: bool = True):
        if kb_path is None:
            kb_path = str(Path(__file__).parent / "kb_user.json")
        self.kb_path = kb_path
        self.entries: dict[str, str] = {}      # key → fact_text
        self.texts: list[str] = []              # 所有事实文本
        self.keys: list[str] = []               # 对应的 KB 键
        self.vectors: list[list[float]] = []    # TF-IDF 向量
        self.vocab: list[str] = []
        self.vocab_idx: dict[str, int] = {}
        self.search_cache: dict[str, list] = {} # claim → [(key, fact, sim)]
        self._loaded = False
        if not lazy:
            self._load()
            self._loaded = True

    def _load(self):
        """从 JSON 知识库 + hallucination_detector.KNOWLEDGE_BASE 加载并向量化"""
        data = {}
        try:
            with open(self.kb_path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # 加载用户 KB
        for key, entry in data.items():
            if key.startswith("_"):
                continue
            facts = entry.get("facts", [])
            for fact in facts:
                self.entries[key] = fact
                self.texts.append(fact)
                self.keys.append(key)

        # 加载内置 KNOWLEDGE_BASE
        try:
            from hallucination_detector import KNOWLEDGE_BASE
            for key, entry in KNOWLEDGE_BASE.items():
                if key in self.entries:
                    continue
                if isinstance(entry, dict):
                    facts = entry.get("facts", [])
                    for fact in facts:
                        self.entries[key] = fact
                        self.texts.append(fact)
                        self.keys.append(key)
                elif isinstance(entry, str):
                    self.entries[key] = entry
                    self.texts.append(entry)
                    self.keys.append(key)
        except ImportError:
            pass

        if self.texts:
            self._build_index()

    def _build_index(self):
        """构建 TF-IDF 索引"""
        self.vectors, self.vocab, self.vocab_idx, self._df, self._N = _tfidf_vector(self.texts)

    def add(self, key: str, fact: str):
        """动态添加一条事实到索引（惰性加载）"""
        if not self._loaded:
            self._load()
            self._loaded = True
        if key in self.entries:
            return
        self.entries[key] = fact
        self.texts.append(fact)
        self.keys.append(key)
        self._build_index()  # 简单重建（生产环境可增量更新）

    def search(self, claim: str, top_k: int = 3, threshold: float = 0.15) -> list[tuple[str, str, float]]:
        """向量检索：返回 [(key, fact_text, similarity), ...]（惰性加载）"""
        if not self._loaded:
            self._load()
            self._loaded = True
        # 缓存命中
        if claim in self.search_cache:
            return [(k, f, s) for k, f, s in self.search_cache[claim] if s >= threshold]

        if not self.vectors:
            return []

        # 查询向量化
        q_grams = Counter(_ngrams(claim))
        q_vec = [0.0] * len(self.vocab)
        for gram, tf in q_grams.items():
            if gram in self.vocab_idx:
                idf = math.log((self._N + 1) / (self._df.get(gram, 0) + 1)) + 1
                q_vec[self.vocab_idx[gram]] = tf * idf
        norm = math.sqrt(sum(v*v for v in q_vec))
        if norm > 0:
            q_vec = [v/norm for v in q_vec]

        # 相似度排序
        results = []
        for i, vec in enumerate(self.vectors):
            sim = _cosine_similarity(q_vec, vec)
            if sim >= threshold:
                results.append((self.keys[i], self.texts[i], sim))

        results.sort(key=lambda x: x[2], reverse=True)
        results = results[:top_k]
        self.search_cache[claim] = results
        return results


# 全局单例
_vkb: Optional[VectorKnowledgeBase] = None

def get_vector_kb() -> VectorKnowledgeBase:
    global _vkb
    if _vkb is None:
        _vkb = VectorKnowledgeBase()
    return _vkb


# ============================================================
# BM25 关键词检索
# ============================================================

class BM25Retriever:
    """纯 Python BM25 实现 — 关键词精确匹配"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: list[str] = []
        self.keys: list[str] = []
        self.doc_term_freqs: list[dict] = []  # 每篇文档的词频
        self.doc_lengths: list[int] = []
        self.avgdl: float = 0.0
        self.idf: dict = {}
        self.N: int = 0

    def index(self, texts: list[str], keys: list[str]):
        """构建 BM25 索引"""
        self.documents = texts
        self.keys = keys
        self.N = len(texts)
        # 分词：中文按字符 2-gram，英文按空格
        tokenized = [self._tokenize(t) for t in texts]
        self.doc_lengths = [len(toks) for toks in tokenized]
        self.avgdl = sum(self.doc_lengths) / max(self.N, 1)

        # 文档词频
        self.doc_term_freqs = []
        df = {}  # 文档频率
        for toks in tokenized:
            tf = {}
            for tok in toks:
                tf[tok] = tf.get(tok, 0) + 1
            self.doc_term_freqs.append(tf)
            for tok in set(toks):
                df[tok] = df.get(tok, 0) + 1

        # IDF
        self.idf = {}
        for term, n in df.items():
            self.idf[term] = math.log((self.N - n + 0.5) / (n + 0.5) + 1)

    def _tokenize(self, text: str) -> list[str]:
        """分词：中文 2-gram + 英文单词"""
        tokens = []
        # 英文单词
        for m in re.finditer(r'[A-Za-z]+', text):
            tokens.append(m.group().lower())
        # 中文 2-gram
        for i in range(len(text) - 1):
            if '一' <= text[i] <= '鿿' and '一' <= text[i+1] <= '鿿':
                tokens.append(text[i:i+2])
        return tokens

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, str, float]]:
        """BM25 检索，返回 [(key, text, score), ...]"""
        if self.N == 0:
            return []
        q_tokens = self._tokenize(query)
        scores = []
        for i in range(self.N):
            score = 0.0
            dl = self.doc_lengths[i]
            tf = self.doc_term_freqs[i]
            for qt in q_tokens:
                if qt not in self.idf:
                    continue
                f = tf.get(qt, 0)
                if f == 0:
                    continue
                numerator = f * (self.k1 + 1)
                denominator = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                score += self.idf[qt] * numerator / denominator
            if score > 0:
                scores.append((self.keys[i], self.documents[i], score))
        scores.sort(key=lambda x: x[2], reverse=True)
        return scores[:top_k]


# ============================================================
# 混合检索器：BM25 + TF-IDF 加权融合
# ============================================================

class HybridRetriever:
    """BM25（关键词）+ TF-IDF 向量（语义）加权融合"""

    def __init__(self, vector_kb, bm25_weight: float = 0.4):
        self.vkb = vector_kb
        self.bm25 = BM25Retriever()
        self.bm25_weight = bm25_weight  # BM25 权重，剩余 1-bm25_weight 给向量
        self._index_built = False

    def _ensure_index(self):
        if not self._index_built and self.vkb.texts:
            self.bm25.index(self.vkb.texts, self.vkb.keys)
            self._index_built = True

    def search(self, query: str, top_k: int = 3, threshold: float = 0.1) -> list[tuple[str, str, float]]:
        """混合检索：BM25 关键词 + TF-IDF 语义 加权"""
        self._ensure_index()

        # BM25 检索
        bm25_results = {key: (fact, score) for key, fact, score in self.bm25.search(query, top_k=20)}

        # 向量检索
        vec_results = {key: (fact, score) for key, fact, score in self.vkb.search(query, top_k=20, threshold=0.0)}

        # 合并打分：加权
        all_keys = set(bm25_results.keys()) | set(vec_results.keys())
        merged = []
        w_bm = self.bm25_weight
        w_vec = 1.0 - self.bm25_weight

        # 归一化各分数到 [0, 1]
        max_bm = max([s for _, s in bm25_results.values()], default=1.0) or 1.0
        max_vec = max([s for _, s in vec_results.values()], default=1.0) or 1.0

        for key in all_keys:
            bm_s = (bm25_results[key][1] / max_bm) if key in bm25_results else 0.0
            vec_s = (vec_results[key][1] / max_vec) if key in vec_results else 0.0
            combined = w_bm * bm_s + w_vec * vec_s
            if combined >= threshold:
                fact = bm25_results.get(key, vec_results.get(key, (None,)))[0]
                merged.append((key, fact, combined))

        merged.sort(key=lambda x: x[2], reverse=True)
        return merged[:top_k]


# 全局混合检索器
_hybrid: Optional[HybridRetriever] = None

def get_hybrid_retriever() -> 'HybridRetriever':
    global _hybrid
    if _hybrid is None:
        _hybrid = HybridRetriever(get_vector_kb(), bm25_weight=0.4)
    return _hybrid


# ============================================================
# SQLite 持久化后备通道
# 当 KNOWLEDGE_BASE 持续扩大、内存压力升高时自动降级
# ============================================================

class SQLiteVectorKB:
    """SQLite 持久化向量库 — 内存受限时的后备方案"""

    def __init__(self, db_path: str = None):
        import sqlite3, os
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "vector_kb.db"
        )
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS vectors (
            key TEXT PRIMARY KEY,
            fact TEXT NOT NULL,
            vec_json TEXT NOT NULL,
            norm REAL NOT NULL DEFAULT 1.0
        )""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS vocab (
            term TEXT PRIMARY KEY,
            idf REAL NOT NULL DEFAULT 1.0
        )""")
        self.conn.commit()

    def add(self, key: str, fact: str):
        """添加条目（不在内存建索引，惰性检索时按需计算）"""
        self.conn.execute(
            "INSERT OR REPLACE INTO vectors(key, fact, vec_json, norm) VALUES(?,?,?,?)",
            (key, fact, "{}", 1.0)
        )
        self.conn.commit()

    def search(self, query: str, top_k: int = 5, threshold: float = 0.1):
        """SQLite 全文搜索 + Jaccard 重排"""
        import math
        rows = self.conn.execute(
            "SELECT key, fact FROM vectors WHERE fact LIKE ? LIMIT 100",
            (f"%{query[:20]}%",)
        ).fetchall()

        results = []
        q_chars = set(query)
        for key, fact in rows:
            f_chars = set(fact)
            overlap = len(q_chars & f_chars)
            union = len(q_chars | f_chars)
            sim = overlap / max(union, 1)
            if sim >= threshold:
                results.append((key, fact, sim))

        results.sort(key=lambda x: x[2], reverse=True)
        return results[:top_k]

    def stats(self) -> dict:
        """返回存储统计"""
        total = self.conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        size = self.conn.execute("SELECT SUM(LENGTH(fact)) FROM vectors").fetchone()[0] or 0
        return {"total_entries": total, "total_bytes": size, "db_path": self.db_path}

    def close(self):
        self.conn.close()


# 自动降级开关
_sqlite_fallback: SQLiteVectorKB | None = None

def get_sqlite_fallback() -> SQLiteVectorKB:
    """获取 SQLite 后备（惰性初始化）"""
    global _sqlite_fallback
    if _sqlite_fallback is None:
        _sqlite_fallback = SQLiteVectorKB()
    return _sqlite_fallback
