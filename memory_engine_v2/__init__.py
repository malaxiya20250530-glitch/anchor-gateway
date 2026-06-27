# -*- coding: utf-8 -*-
'''Memory Engine v2 —— 可检索 + 可压缩 + 可遗忘 + 可影响推理的长期记忆系统。'''

from memory_engine_v2.embedder import Embedder, cosine_similarity, encode, similarity
from memory_engine_v2.store import MemoryStore
from memory_engine_v2.retriever import Retriever, retrieve
from memory_engine_v2.compressor import Compressor, compress_store
from memory_engine_v2.decay import DecayManager, decay_store
from memory_engine_v2.writer import MemoryWriter
from memory_engine_v2.engine import MemoryEngine, get_engine

__all__ = [
    'Embedder', 'cosine_similarity', 'encode', 'similarity',
    'MemoryStore', 'Retriever', 'retrieve',
    'Compressor', 'compress_store',
    'DecayManager', 'decay_store',
    'MemoryWriter', 'MemoryEngine', 'get_engine',
]

__version__ = '2.0.0'
