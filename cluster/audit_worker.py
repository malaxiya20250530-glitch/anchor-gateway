#!/usr/bin/env python3
"""异步审核 Worker — Redis Streams 消费者组。

独立进程运行，从审核队列消费任务并执行安全审计。
可横向扩展多个 worker 实例。

用法:
    python3 cluster/audit_worker.py
"""

import json
import os
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("audit-worker")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_REDIS_URL = os.environ.get("REDIS_NODES", "redis://localhost:6379/0")
_REDIS_CHANNEL = os.environ.get("AUDIT_CHANNEL", "audit:tasks")
_REDIS_GROUP = os.environ.get("AUDIT_GROUP", "audit-workers")
_CONSUMER_ID = os.environ.get("AUDIT_CONSUMER", f"worker-{os.getpid()}")


def main():
    logger.info("AuditWorker starting (consumer=%s)", _CONSUMER_ID)

    # 初始化 Redis
    try:
        import redis as redis_mod
        client = redis_mod.from_url(_REDIS_URL, decode_responses=True)
        client.ping()
        logger.info("Connected to Redis: %s", _REDIS_URL)
    except Exception as exc:
        logger.fatal("Redis connection failed: %s", exc)
        sys.exit(1)

    # 初始化安全模块
    try:
        from waf import WAF
        from security_gateway import SecurityGateway
        waf = WAF()
        gateway = SecurityGateway()
        logger.info("Security modules loaded")
    except Exception as exc:
        logger.fatal("Security modules load failed: %s", exc)
        sys.exit(1)

    # 确保消费者组存在
    try:
        client.xgroup_create(_REDIS_CHANNEL, _REDIS_GROUP, id="0", mkstream=True)
    except Exception:
        pass

    logger.info("AuditWorker ready, waiting for tasks...")

    while True:
        try:
            msgs = client.xreadgroup(
                _REDIS_GROUP, _CONSUMER_ID,
                {_REDIS_CHANNEL: ">"}, count=5, block=3000
            )
            if not msgs:
                continue

            for stream_id, entries in msgs:
                for msg_id, data in entries:
                    session_id = data.get("session_id", "?")
                    text = data.get("text", "")
                    logger.info("Processing session=%s text_len=%d",
                                session_id, len(text))

                    # 执行审核
                    waf_result = waf.scan(text, ip="0.0.0.0", endpoint="/async-audit")
                    gateway_result = gateway.audit(text)

                    # 结果记录
                    result = {
                        "session_id": session_id,
                        "waf_blocked": waf_result.blocked,
                        "waf_reason": waf_result.reason,
                        "gateway_status": gateway_result.get("status", "unknown"),
                        "timestamp": time.time(),
                    }
                    logger.info("Result: %s", json.dumps(result))

                    # 确认消费
                    client.xack(_REDIS_CHANNEL, _REDIS_GROUP, msg_id)

        except KeyboardInterrupt:
            logger.info("Shutting down")
            break
        except Exception as exc:
            logger.error("Worker error: %s", exc)
            time.sleep(2)


if __name__ == "__main__":
    main()
