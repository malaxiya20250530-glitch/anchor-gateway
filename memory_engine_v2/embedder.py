# -*- coding: utf-8 -*-
'''向量嵌入层 —— 纯 Python，混合 n-gram 随机投影。

原理：
  文本 → 提取混合 n-gram（中文1-2字，英文3字）
  → 每个 n-gram 映射到稀疏随机向量
  → 叠加 → L2 归一化 → 余弦相似度

特点：
  - 确定性（同文本同向量）
  - 中英文混合支持
  - 子词级相似性捕获
'''

import math
import re

DEFAULT_DIM = 256
DEFAULT_SPARSE = 12


# ── 哈希与向量生成 ─────────────────────────────────────────

def _hash_to_seed(s: str) -> int:
    '''FNV-1a 哈希，确定性映射为整数。'''
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _sparse_vector(seed: int, dim: int, sparse: int) -> list[float]:
    '''从种子生成稀疏随机向量。'''
    vec = [0.0] * dim
    state = seed
    for _ in range(sparse):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        idx = state % dim
        sign = 1.0 if (state >> 30) & 1 else -1.0
        vec[idx] = sign
    return vec


# ── n-gram 提取 ───────────────────────────────────────────

def _is_cjk(ch: str) -> bool:
    '''判断是否为 CJK 字符。'''
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x2A6DF)


def _extract_ngrams(text: str) -> list[str]:
    '''混合 n-gram 提取：中文 uni+bigram，英文 trigram。'''
    text = text.strip()
    if not text:
        return []

    ngrams = []

    # 分离中英文段落
    segments = re.split(r'([a-z0-9]+)', text.lower())
    for seg in segments:
        if not seg:
            continue
        if re.match(r'^[a-z0-9]+$', seg):
            # 英文/数字 → trigram
            padded = ' ' + seg + ' '
            for i in range(len(padded) - 2):
                ngrams.append(padded[i:i+3])
        else:
            # 中文/混合 → unigram + bigram
            chars = [c for c in seg if not c.isspace()]
            for i, ch in enumerate(chars):
                ngrams.append(ch)  # unigram
                if i + 1 < len(chars):
                    ngrams.append(ch + chars[i+1])  # bigram

    return ngrams if ngrams else [text[:3] if len(text) >= 3 else text]


# ── 归一化与相似度 ─────────────────────────────────────────

def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm < 1e-12:
        return vec[:]
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    '''余弦相似度 [-1, 1]。'''
    if len(a) != len(b):
        raise ValueError(f'维度不匹配: {len(a)} vs {len(b)}')
    dot = sum(ai * bi for ai, bi in zip(a, b))
    na = math.sqrt(sum(ai * ai for ai in a))
    nb = math.sqrt(sum(bi * bi for bi in b))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


# ── 嵌入器 ────────────────────────────────────────────────

class Embedder:
    '''混合 n-gram 随机投影嵌入器。'''

    def __init__(self, dim: int = DEFAULT_DIM, sparse: int = DEFAULT_SPARSE):
        self.dim = dim
        self.sparse = sparse

    def encode(self, text: str) -> list[float]:
        '''将文本编码为 dim 维单位向量。'''
        ngrams = _extract_ngrams(text)
        if not ngrams:
            return [0.0] * self.dim

        acc = [0.0] * self.dim
        for ng in ngrams:
            seed = _hash_to_seed(ng)
            sv = _sparse_vector(seed, self.dim, self.sparse)
            for i in range(self.dim):
                acc[i] += sv[i]

        return _l2_normalize(acc)

    def batch_encode(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]

    def similarity(self, text_a: str, text_b: str) -> float:
        return cosine_similarity(self.encode(text_a), self.encode(text_b))


# ── 默认实例 ──────────────────────────────────────────────

_default = Embedder()


def encode(text: str) -> list[float]:
    return _default.encode(text)


def similarity(text_a: str, text_b: str) -> float:
    return _default.similarity(text_a, text_b)


# ── 自检 ──────────────────────────────────────────────────

if __name__ == '__main__':
    e = Embedder(dim=128)
    tests = [
        # 中文
        ('责任链模式', '检查器责任链'),
        ('幻觉检测引擎', '事实核查模块'),
        ('幻觉检测引擎', '今天天气不错'),
        # 英文
        ('dag scheduler uses queue', 'pipeline executor uses queue'),
        ('python test runner', 'python unit test framework'),
        ('python test runner', 'I like pizza'),
        # 中英混合
        ('checker 责任链', 'checker registry 优先级'),
    ]
    print(f'嵌入维度: {e.dim}, 稀疏度: {e.sparse}\n')
    for a, b in tests:
        sim = e.similarity(a, b)
        bar = '█' * max(0, int(abs(sim) * 20))
        print(f'  {sim:+.3f} {bar}')
        print(f'    "{a}"  ↔  "{b}"\n')
