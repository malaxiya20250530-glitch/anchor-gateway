#!/usr/bin/env python3
"""
KB 实体服务 — 生产级三层架构
================================
L1: 内存缓存 (dict + TTL, 亚毫秒)
L2: 本地 KB (kb_core.json + entities_mega.json, 1-2ms)
L3: 文件缓存 (kb_cache.json, TTL 7天)
L4: Wikipedia 异步补充 (后台线程, 非阻塞)

核心理念: Wikipedia 只是背景丰富源，不是关键路径。

用法:
  from kb_entity_service import EntityService
  svc = EntityService()
  result = svc.resolve("人工智能")  # 同步，亚毫秒
  svc.enrich_async("量子计算")     # 异步补充（后台）
"""

import json, time, threading, re, os
from pathlib import Path
from collections import OrderedDict
from typing import Optional, Dict, Any, List, Tuple

# 安全：外部数据输入净化
from prompt_injection_defense import sanitize_input, KBPoisonGuard

ROOT = Path(__file__).parent

# ── 配置 ──────────────────────────────────────────────
MEMORY_CACHE_MAX = 2000        # 内存最多缓存实体数
MEMORY_TTL_SECONDS = 86400 * 7  # 内存 TTL: 7 天
FILE_CACHE_TTL_SECONDS = 86400 * 30  # 文件缓存 TTL: 30 天
CACHE_FILE = ROOT / "kb_cache.json"
BACKGROUND_WORKER_INTERVAL = 30  # 后台补充间隔（秒）
BACKGROUND_BATCH_SIZE = 5       # 每批补充数


class TTLCache:
    """带 TTL 的内存缓存（LRU 淘汰）"""

    def __init__(self, max_size: int = 2000, default_ttl: int = 86400 * 7):
        self._store: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._max = max_size
        self._ttl = default_ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                return None
            value, expiry = self._store[key]
            if time.time() > expiry:
                del self._store[key]
                return None
            # LRU: 移到末尾
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: int = None):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            else:
                # 淘汰最旧
                while len(self._store) >= self._max:
                    self._store.popitem(last=False)
            ttl = ttl or self._ttl
            self._store[key] = (value, time.time() + ttl)

    def size(self) -> int:
        return len(self._store)

    def keys(self) -> list:
        return list(self._store.keys())


class CircuitBreaker:
    """熔断器 — Wikipedia 挂了不影响主链路"""

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60):
        self._threshold = failure_threshold
        self._recovery = recovery_timeout
        self._failures = 0
        self._last_failure = 0.0
        self._open = False

    def is_open(self) -> bool:
        if not self._open:
            return False
        if time.time() - self._last_failure > self._recovery:
            self._open = False
            self._failures = 0
            return False
        return True

    def record_failure(self):
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self._threshold:
            self._open = True

    def record_success(self):
        self._failures = 0


class EntityService:
    """
    实体服务 — 四层降级架构

    1. 内存缓存 (L1)  →  亚毫秒
    2. 本地 KB (L2)   →  1-2ms, kb_core.json + entities_mega.json
    3. 文件缓存 (L3)  →  5-10ms, kb_cache.json
    4. Wikipedia (L4)  →  200-2000ms, 后台异步
    """

    def __init__(self):
        self._mem_cache = TTLCache(max_size=MEMORY_CACHE_MAX, default_ttl=MEMORY_TTL_SECONDS)
        self._local_kb: Dict[str, Any] = {}
        self._local_entities: Dict[str, Any] = {}
        self._file_cache: Dict[str, Any] = {}
        self._pending_queue: List[str] = []
        self._breaker = CircuitBreaker()
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._stats = {"l1_hits": 0, "l2_hits": 0, "l3_hits": 0, "l4_fetches": 0, "misses": 0}

        # 启动时预加载
        self._preload()

    # ── 预加载 ─────────────────────────────────────────

    def _preload(self):
        """启动预热: 加载本地 KB + 实体库 + 文件缓存"""
        t0 = time.time()

        # 加载 kb_core.json
        core_path = ROOT / "kb_core.json"
        if core_path.exists():
            with open(core_path) as f:
                core = json.load(f)
            for key, entry in core.items():
                if not key.startswith("_"):
                    facts = entry.get("facts", [])
                    if facts:
                        self._local_kb[key] = {
                            "facts": facts,
                            "source": entry.get("source", "kb_core"),
                            "first_fact": facts[0] if facts else "",
                        }

        # 加载 entities_mega.json
        entity_path = ROOT / "entities_mega.json"
        if entity_path.exists():
            with open(entity_path) as f:
                entities = json.load(f)
            for e in entities:
                name = e.get("name", "")
                if name:
                    self._local_entities[name] = e

        # 加载文件缓存
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE) as f:
                    raw = json.load(f)
                # 检查 TTL
                now = time.time()
                for key, entry in raw.items():
                    if now - entry.get("cached_at", 0) < FILE_CACHE_TTL_SECONDS:
                        self._file_cache[key] = entry
            except Exception:
                pass

        elapsed = (time.time() - t0) * 1000
        kb_count = len(self._local_kb)
        ent_count = len(self._local_entities)
        fc_count = len(self._file_cache)
        print(f"⚡ EntityService 预热完成 ({elapsed:.0f}ms)")
        print(f"   L2 本地 KB: {kb_count} 键")
        print(f"   L2 实体库:  {ent_count} 个")
        print(f"   L3 文件缓存: {fc_count} 个")

    # ── 核心查询 ──────────────────────────────────────

    def resolve(self, query: str) -> Optional[Dict[str, Any]]:
        """
        解析实体 — 四层降级查询。
        永远不阻塞，最坏情况返回 None（由调用方决定 fallback）。
        """
        q = query.strip().lower()
        if not q:
            return None

        # L1: 内存缓存
        cached = self._mem_cache.get(q)
        if cached:
            self._stats["l1_hits"] += 1
            return cached

        # L2: 本地 KB + 实体库
        result = self._search_local(q)
        if result:
            self._stats["l2_hits"] += 1
            self._mem_cache.set(q, result)
            return result

        # L3: 文件缓存
        if q in self._file_cache:
            self._stats["l3_hits"] += 1
            entry = self._file_cache[q]
            result = {
                "key": q,
                "facts": entry.get("facts", []),
                "source": "file_cache",
                "entity": entry.get("entity"),
            }
            self._mem_cache.set(q, result)
            return result

        # L4: 加入后台补充队列（不阻塞！）
        self._stats["misses"] += 1
        self._enqueue_background(q)
        return None

    def _search_local(self, query: str) -> Optional[Dict[str, Any]]:
        """在本地 KB 中搜索（精确 + 模糊匹配）"""
        q = query.lower().replace(" ", "_")

        # 精确匹配 kb_core
        if q in self._local_kb:
            kb = self._local_kb[q]
            return {"key": q, "facts": kb["facts"], "source": "kb_core"}

        # 精确匹配 entities
        if q in self._local_entities:
            ent = self._local_entities[q]
            return {"key": q, "entity": ent, "source": "entities_mega"}

        # 模糊匹配: 检查 query 是否是某个键的子串
        for key, kb in self._local_kb.items():
            if q in key.lower() or key.lower() in q:
                return {"key": key, "facts": kb["facts"], "source": "kb_core(fuzzy)"}

        # 中文首字符匹配
        if len(q) >= 2:
            prefix = q[:2]
            for key, kb in self._local_kb.items():
                if key.lower().startswith(prefix):
                    return {"key": key, "facts": kb["facts"], "source": "kb_core(prefix)"}

        return None

    # ── 异步补充 ──────────────────────────────────────

    def enrich_async(self, query: str):
        """将实体加入后台补充队列"""
        self._enqueue_background(query)

    def _enqueue_background(self, query: str):
        """加入队列，触后台 Worker"""
        if query not in self._pending_queue:
            self._pending_queue.append(query)
        self._ensure_worker()

    def _ensure_worker(self):
        """确保后台 Worker 在运行"""
        if self._worker and self._worker.is_alive():
            return
        self._running = True
        self._worker = threading.Thread(target=self._background_loop, daemon=True)
        self._worker.start()

    def _background_loop(self):
        """后台循环: 定期从队列取实体，异步补充"""
        while self._running and self._pending_queue:
            time.sleep(BACKGROUND_WORKER_INTERVAL)

            if self._breaker.is_open():
                continue  # 熔断中，跳过

            # 取一批
            batch = []
            while self._pending_queue and len(batch) < BACKGROUND_BATCH_SIZE:
                q = self._pending_queue.pop(0)
                # 避免重复：检查是否已经缓存
                if self._mem_cache.get(q) or q in self._file_cache:
                    continue
                batch.append(q)

            if batch:
                self._fetch_batch(batch)

    def _fetch_batch(self, queries: list):
        """批量从 Wikipedia 获取实体信息"""
        import urllib.request, urllib.parse, urllib.error
        import random

        API = "https://zh.wikipedia.org/w/api.php"
        HEADERS = {"User-Agent": "Anchor-KB/1.0 EntityService"}

        try:
            params = {
                "action": "query",
                "prop": "extracts|info",
                "exintro": 1,
                "explaintext": 1,
                "exlimit": min(20, len(queries)),
                "inprop": "url",
                "titles": "|".join(queries),
                "format": "json",
            }
            url = API + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers=HEADERS)

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            for page in data.get("query", {}).get("pages", {}).values():
                title = page.get("title", "")
                extract = page.get("extract", "")
                if title and extract and len(extract) > 50:
                    # 安全净化：过滤 Wikipedia 中可能的注入内容
                    extract = sanitize_input(extract)
                    title = sanitize_input(title)
                    key = title.lower().replace(" ", "_")
                    # KB 投毒检测：过滤恶意条目
                    check_entry = {"facts": [extract[:500]], "source": "wikipedia"}
                    safe, reason = KBPoisonGuard.scan_entry(key, check_entry)
                    if not safe:
                        self._stats.setdefault("skipped_poison", 0)
                        self._stats["skipped_poison"] += 1
                        continue
                    entry = {
                        "key": key,
                        "title": title,
                        "facts": [extract[:500]],
                        "entity": {"name": title, "extract": extract[:500]},
                        "cached_at": time.time(),
                    }
                    # 写入 L3 文件缓存
                    self._file_cache[key] = entry
                    # 写入 L1 内存缓存
                    self._mem_cache.set(key, {
                        "key": key,
                        "facts": [extract[:500]],
                        "source": "wikipedia",
                    })
                    self._stats["l4_fetches"] += 1

            self._breaker.record_success()
            self._flush_cache()

        except urllib.error.HTTPError as e:
            if e.code == 429:
                self._breaker.record_failure()
                # 429 时把查询放回队列
                for q in queries:
                    if q not in self._pending_queue:
                        self._pending_queue.append(q)
            else:
                self._breaker.record_failure()
        except Exception:
            self._breaker.record_failure()

    def _flush_cache(self):
        """持久化文件缓存"""
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._file_cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── 统计与监控 ─────────────────────────────────────

    def stats(self) -> dict:
        """返回服务统计"""
        return {
            **self._stats,
            "mem_cache_size": self._mem_cache.size(),
            "local_kb_size": len(self._local_kb),
            "file_cache_size": len(self._file_cache),
            "pending_queue": len(self._pending_queue),
            "breaker_open": self._breaker.is_open(),
        }

    def warm_cache(self, top_n: int = 100):
        """预热: 将 TOP-N 高频实体加载到内存缓存"""
        # 从 kb_core 取最常见的键
        import re
        priority_keys = [
            "人工智能", "机器学习", "深度学习", "python", "java",
            "量子计算", "区块链", "云计算", "5g", "北京",
            "上海", "中国", "美国", "日本", "爱因斯坦",
            "牛顿", "dna", "相对论", "进化论", "宇宙",
        ]
        count = 0
        for pk in priority_keys:
            result = self._search_local(pk)
            if result:
                self._mem_cache.set(pk, result)
                count += 1

        # 再从 kb_core 批量加载
        for key in list(self._local_kb.keys())[:top_n - count]:
            q = key.lower().replace("_", " ")
            if not self._mem_cache.get(q):
                kb = self._local_kb[key]
                self._mem_cache.set(q, {"key": key, "facts": kb["facts"], "source": "kb_core"})

        print(f"🔥 预热完成: {self._mem_cache.size()} 条目在 L1")

    def shutdown(self):
        """优雅关闭"""
        self._running = False
        self._flush_cache()


# ── 单例 ──────────────────────────────────────────────
_service_instance: Optional[EntityService] = None


def get_service() -> EntityService:
    """获取单例服务"""
    global _service_instance
    if _service_instance is None:
        _service_instance = EntityService()
    return _service_instance


# ── CLI ───────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="KB Entity Service")
    parser.add_argument("--query", type=str, help="查询实体")
    parser.add_argument("--warm", type=int, default=100, help="预热条目数")
    parser.add_argument("--stats", action="store_true", help="显示统计")
    parser.add_argument("--bench", type=int, default=1000, help="基准测试次数")
    args = parser.parse_args()

    svc = get_service()
    svc.warm_cache(args.warm)

    if args.stats:
        import pprint
        pprint.pprint(svc.stats())

    if args.query:
        t0 = time.time()
        result = svc.resolve(args.query)
        elapsed = (time.time() - t0) * 1000
        if result:
            print(f"✅ 命中 ({elapsed:.1f}ms) 来源={result['source']}")
            facts = result.get("facts", result.get("entity", {}).get("extract", ""))[:200]
            print(f"   {facts}")
        else:
            print(f"❌ 未命中 ({elapsed:.1f}ms) — 已加入后台补充队列")
            svc.enrich_async(args.query)

    if args.bench:
        print(f"\n⚡ 基准测试 ({args.bench} 次查询)...")
        queries = ["人工智能", "python", "北京", "爱因斯坦", "不存在实体XYZZY"]
        t0 = time.time()
        for i in range(args.bench):
            q = queries[i % len(queries)]
            svc.resolve(q)
        total = (time.time() - t0) * 1000
        avg = total / args.bench
        print(f"   总计: {total:.0f}ms, 平均: {avg:.2f}ms/次, QPS: {args.bench/(total/1000):.0f}")
        import pprint
        pprint.pprint(svc.stats())

    svc.shutdown()
