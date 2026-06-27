#!/usr/bin/env python3
"""
联网验证模块 — 零外部 API 依赖
用 DuckDuckGo HTML 搜索 + SQLite 持久化缓存（78 小时 TTL）
"""

import re
import time
import json
import hashlib
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import quote
from typing import Optional
from logger import log


DB_PATH = Path(__file__).parent / "web_cache.db"
CACHE_TTL = 78 * 3600  # 78 小时


def _hash_claim(claim: str) -> str:
    """对 claim 做 SHA256 取前 16 位作为缓存键"""
    return hashlib.sha256(claim.encode()).hexdigest()[:16]


def _extract_snippets(html: str) -> list[str]:
    """从 DuckDuckGo HTML 结果页提取摘要片段（多模式 fallback）"""
    snippets = []
    # 模式 1: 新版 DDG snippet class
    for m in re.finditer(r'class="result__snippet"[^>]*>(.*?)</', html, re.DOTALL):
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        text = re.sub(r'\s+', ' ', text)
        if len(text) > 20:
            snippets.append(text)
    # 模式 2: 旧版 DDG 或通用 snippet 提取
    if len(snippets) < 3:
        for m in re.finditer(r'class="[^"]*snippet[^"]*"[^>]*>(.*?)</', html, re.DOTALL):
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            text = re.sub(r'\s+', ' ', text)
            if len(text) > 20 and text not in snippets:
                snippets.append(text)
    # 模式 3: 从 description meta 标签提取
    if len(snippets) < 3:
        for m in re.finditer(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html):
            text = m.group(1).strip()
            if len(text) > 20:
                snippets.append(text)
    # 去重 + 限制
    seen = set()
    unique = []
    for s in snippets:
        if s[:30] not in seen:
            seen.add(s[:30])
            unique.append(s)
    return unique[:5]


class WebVerifier:
    """轻量联网验证器 — SQLite 持久化缓存"""

    def __init__(self):
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS web_cache (
                    claim_hash TEXT PRIMARY KEY,
                    claim TEXT NOT NULL,
                    snippets TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_web_cache_created
                ON web_cache(created_at)
            """)
            conn.commit()

    def _cache_get(self, claim_hash: str) -> Optional[list[str]]:
        """从 SQLite 读取缓存，过期返回 None"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT snippets, created_at FROM web_cache WHERE claim_hash = ?",
                (claim_hash,)
            ).fetchone()
        if row is None:
            return None
        if time.time() - row["created_at"] > CACHE_TTL:
            self._cache_delete(claim_hash)
            return None
        return json.loads(row["snippets"])

    def _cache_set(self, claim_hash: str, claim: str, snippets: list[str]):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO web_cache (claim_hash, claim, snippets, created_at) VALUES (?, ?, ?, ?)",
                (claim_hash, claim, json.dumps(snippets, ensure_ascii=False), time.time())
            )
            conn.commit()

    def _cache_delete(self, claim_hash: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM web_cache WHERE claim_hash = ?", (claim_hash,))
            conn.commit()

    def cleanup_expired(self) -> int:
        """清理过期缓存条目，返回删除数"""
        with self._connect() as conn:
            cutoff = time.time() - CACHE_TTL
            cur = conn.execute("DELETE FROM web_cache WHERE created_at < ?", (cutoff,))
            conn.commit()
            return cur.rowcount

    def search(self, claim: str, timeout: float = 8.0) -> list[str]:
        """搜索 claim 并返回摘要列表（先查缓存）"""
        claim_hash = _hash_claim(claim)

        # 1. 查缓存
        cached = self._cache_get(claim_hash)
        if cached is not None:
            return cached

        # 2. 网络请求
        query = quote(claim)
        url = f"https://html.duckduckgo.com/html/?q={query}"
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                # 限制响应大小防止 OOM (最大 2MB)
                raw = resp.read(2_097_152)
                html = raw.decode("utf-8", errors="replace")
        except (URLError, OSError, TimeoutError):
            return []

        snippets = _extract_snippets(html)

        # 3. 写入缓存
        if snippets:
            self._cache_set(claim_hash, claim, snippets)

        return snippets

    def verify(self, claim: str, timeout: float = 8.0) -> dict:
        """
        联网验证一条声明
        返回: {verdict, confidence, evidence, source, cached}
        """
        # 先检查是否来自缓存
        claim_hash = _hash_claim(claim)
        from_cache = self._cache_get(claim_hash) is not None
        
        snippets = self.search(claim, timeout=timeout)
        if not snippets:
            return {
                "verdict": "uncertain",
                "confidence": 0.0,
                "evidence": "无法连接搜索服务",
                "source": "web",
                "cached": from_cache,
            }

        # 多粒度匹配: 字符级 + 双词级
        claim_chars = set(claim)
        claim_bigrams = {claim[i:i+2] for i in range(len(claim)-1)}
        best_score = 0.0
        best_snippet = ""

        for s in snippets:
            s_chars = set(s)
            s_bigrams = {s[i:i+2] for i in range(len(s)-1)}
            char_overlap = len(claim_chars & s_chars) / max(len(claim_chars), 1)
            bigram_overlap = len(claim_bigrams & s_bigrams) / max(len(claim_bigrams), 1) if claim_bigrams else 0
            score = char_overlap * 0.4 + bigram_overlap * 0.6
            if score > best_score:
                best_score = score
                best_snippet = s

        if best_score > 0.3:
            return {
                "verdict": "verified",
                "confidence": min(0.7, best_score),
                "evidence": best_snippet[:200],
                "source": "web (DuckDuckGo)",
            }
        elif best_score > 0.1:
            return {
                "verdict": "uncertain",
                "confidence": best_score,
                "evidence": best_snippet[:200] if best_snippet else "无直接相关结果",
                "source": "web (DuckDuckGo)",
            }
        else:
            return {
                "verdict": "uncertain",
                "confidence": 0.1,
                "evidence": "未找到相关网络信息",
                "source": "web",
            }

    def stats(self) -> dict:
        """缓存统计"""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM web_cache").fetchone()["cnt"]
            valid = conn.execute(
                "SELECT COUNT(*) as cnt FROM web_cache WHERE created_at > ?",
                (time.time() - CACHE_TTL,)
            ).fetchone()["cnt"]
        return {"total": total, "valid": valid, "expired": total - valid, "ttl_hours": CACHE_TTL / 3600}



class WikipediaVerifier:
    """Wikipedia API 验证器 — 免费，无需 Key"""

    def __init__(self):
        self.cache: dict[str, tuple[float, str]] = {}
        self.cache_ttl = 86400  # 24 小时

    def search(self, query: str, lang: str = "zh", timeout: float = 8.0, _depth: int = 0) -> str:
        """搜索 Wikipedia 并返回提取的摘要文本"""
        if _depth > 3:
            return ""  # 防止无限递归
        if query in self.cache:
            ts, text = self.cache[query]
            if time.time() - ts < self.cache_ttl:
                return text

        # Wikipedia REST API
        from urllib.parse import quote as _quote
        # TM-012: 语言代码白名单防止 SSRF 子域名注入
        _ALLOWED_LANGS = {"zh","en","ja","ko","fr","de","es","pt","ru","ar"}
        safe_lang = lang if lang in _ALLOWED_LANGS else "en"
        url = f"https://{safe_lang}.wikipedia.org/api/rest_v1/page/summary/{_quote(query)}"
        headers = {"User-Agent": "AwarenessGateway/2.0", "Accept": "application/json"}

        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            extract = data.get("extract", "")
            if extract:
                self.cache[query] = (time.time(), extract)
                return extract
        except Exception as e:
            log.warning("Wikipedia 摘要获取失败: %s", e)

        # 回退：搜索 API
        try:
            search_url = f"https://{safe_lang}.wikipedia.org/w/api.php?action=query&list=search&srsearch={_quote(query)}&format=json&srlimit=1"
            req = Request(search_url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            results = data.get("query", {}).get("search", [])
            if results:
                title = results[0]["title"]
                # 递归获取摘要
                return self.search(title, lang, timeout, _depth=_depth + 1)
        except Exception as e:
            log.warning("Wikipedia 搜索回退失败: %s", e)

        return ""

    def verify(self, claim: str) -> dict:
        """Wikipedia 验证"""
        extract = self.search(claim)
        if not extract:
            return {"verdict": "uncertain", "confidence": 0.0, "evidence": "", "source": "wikipedia"}

        # 简单关键词重叠
        claim_words = set(claim)
        extract_words = set(extract[:500])
        overlap = len(claim_words & extract_words) / max(len(claim_words), 1)

        if overlap > 0.15:
            return {
                "verdict": "verified",
                "confidence": min(0.8, overlap + 0.3),
                "evidence": extract[:300],
                "source": "Wikipedia",
            }
        return {
            "verdict": "uncertain",
            "confidence": overlap,
            "evidence": extract[:200],
            "source": "Wikipedia",
        }


class CrossVerifier:
    """多源交叉验证 — 同时查 DuckDuckGo + Wikipedia，加权综合"""

    def __init__(self):
        self.web = WebVerifier()
        self.wiki = WikipediaVerifier()
        # 源权重：DuckDuckGo 覆盖面广但噪声高，Wikipedia 质量高但覆盖面窄
        self.source_weights = {"web": 0.5, "wikipedia": 0.5}

    def verify(self, claim: str, timeout: float = 15) -> dict:
        """
        多源交叉验证
        返回: {verdict, confidence, evidence, sources, votes}
        """
        import concurrent.futures

        results = {}

        def _fetch_web():
            return self.web.verify(claim, timeout=timeout)

        def _fetch_wiki():
            return self.wiki.verify(claim)

        # 并行请求
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(_fetch_web): "web",
                executor.submit(_fetch_wiki): "wikipedia",
            }
            for future in concurrent.futures.as_completed(futures, timeout=timeout):
                source = futures[future]
                try:
                    results[source] = future.result()
                except Exception as e:
                    log.warning("并发验证子任务失败: %s", e)
                    results[source] = {"verdict": "uncertain", "confidence": 0.0, "evidence": "", "source": source}

        # 加权综合
        votes = {"verified": 0.0, "contradicted": 0.0, "uncertain": 0.0}
        total_weight = 0.0
        for source, r in results.items():
            w = self.source_weights.get(source, 0.3)
            votes[r.get("verdict", "uncertain")] += w * r.get("confidence", 0.0)
            total_weight += w

        # 归一化
        if total_weight > 0:
            for k in votes:
                votes[k] /= total_weight

        # 判定最终 verdict
        if votes["contradicted"] > 0.3:
            final_verdict = "contradicted"
            final_confidence = votes["contradicted"]
        elif votes["verified"] > votes["contradicted"] and votes["verified"] > votes["uncertain"]:
            final_verdict = "verified"
            final_confidence = votes["verified"]
        elif votes["contradicted"] > 0.1:
            final_verdict = "contradicted"
            final_confidence = votes["contradicted"]
        else:
            final_verdict = "uncertain"
            final_confidence = max(votes.values())

        # 组合证据
        evidences = []
        for source, r in results.items():
            if r.get("evidence"):
                evidences.append(f"[{source}] {r['evidence'][:200]}")

        return {
            "verdict": final_verdict,
            "confidence": round(final_confidence, 3),
            "evidence": " | ".join(evidences[:3]),
            "sources": list(results.keys()),
            "votes": {k: round(v, 3) for k, v in votes.items()},
            "details": results,
        }
