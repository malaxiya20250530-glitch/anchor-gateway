#!/usr/bin/env python3
"""异步审核回调 — 通过 Redis Pub/Sub 触发审核任务。

用法:
    # 推送审核任务
    push_audit_task(redis_client, session_id, text)

    # 启动订阅者
    subscriber = AuditSubscriber(redis_client)
    subscriber.start()
"""

import json
import os
import time
import threading
import logging

logger = logging.getLogger(__name__)

_REDIS_CHANNEL = os.environ.get("AUDIT_CHANNEL", "audit:tasks")
_REDIS_GROUP = os.environ.get("AUDIT_GROUP", "audit-workers")


def push_audit_task(redis_client, session_id: str, text: str,
                    metadata: dict = None) -> bool:
    """非阻塞推送审核任务到 Redis Stream"""
    if not redis_client:
        logger.warning("No Redis; audit task dropped")
        return False
    try:
        data = {
            "session_id": session_id,
            "text": text[:50000],
            "timestamp": time.time(),
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
        }
        redis_client.xadd(_REDIS_CHANNEL, data, maxlen=10000)
        return True
    except Exception as exc:
        logger.error("push_audit_task failed: %s", exc)
        return False


class AuditSubscriber:
    """Redis Streams 消费者 — 异步处理审核结果回调。

    独立线程运行，收到审核完成事件后执行回调。
    """

    def __init__(self, redis_client, callback=None, consumer_id=None):
        self._redis = redis_client
        self._callback = callback
        self._consumer = consumer_id or f"consumer-{os.getpid()}"
        self._thread = None
        self._running = False

    def start(self):
        if not self._redis:
            logger.warning("No Redis; AuditSubscriber not started")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("AuditSubscriber started (consumer=%s)", self._consumer)

    def stop(self):
        self._running = False

    def _run(self):
        # 确保消费者组存在
        try:
            self._redis.xgroup_create(
                _REDIS_CHANNEL, _REDIS_GROUP, id="0", mkstream=True
            )
        except Exception:
            pass  # 组已存在

        while self._running:
            try:
                msgs = self._redis.xreadgroup(
                    _REDIS_GROUP, self._consumer,
                    {_REDIS_CHANNEL: ">"}, count=10, block=2000
                )
                if msgs:
                    for stream_id, entries in msgs:
                        for msg_id, data in entries:
                            self._handle(data)
                            try:
                                self._redis.xack(_REDIS_CHANNEL, _REDIS_GROUP, msg_id)
                            except Exception:
                                pass
            except Exception as exc:
                if self._running:
                    logger.warning("AuditSubscriber loop error: %s", exc)
                    time.sleep(1)

    def _handle(self, data):
        try:
            if self._callback:
                self._callback(data)
        except Exception as exc:
            logger.error("AuditSubscriber callback error: %s", exc)
