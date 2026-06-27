#!/usr/bin/env python3
"""健康检查 + HA 基础 — 心跳 / 选主 / 就绪探测 / 负载均衡权重。

用法:
    from ha_health import HealthChecker, LeaderElection

    # 健康检查
    hc = HealthChecker()
    hc.add_check("kb", lambda: os.path.exists("kb_legal.json"))
    status = hc.run_all()  # {"status": "healthy", "checks": {...}}

    # 选主 (基于 Redis 或文件锁)
    le = LeaderElection(node_id="node-1")
    if le.is_leader():
        run_scheduler()  # 只有主节点执行定时任务

    # 就绪探测 (K8s readinessProbe 兼容)
    hc.readiness_endpoint()  # 返回 200 或 503
"""

import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from security_logger import get_security_logger


# ═══════════════════════════════════════════════════════════
# 健康检查器
# ═══════════════════════════════════════════════════════════

class HealthChecker:
    """可扩展的健康检查框架。

    支持三种探测:
      - liveness: 进程是否存活（K8s livenessProbe）
      - readiness: 是否可接收流量（K8s readinessProbe）
      - startup: 启动是否完成（K8s startupProbe）
    """

    def __init__(self):
        self._checks: dict[str, dict] = {}  # name → {fn, type, timeout}
        self._startup_at = time.time()
        self._slog = get_security_logger()

    def add_check(self, name: str, fn: Callable[[], bool],
                  check_type: str = "readiness",
                  timeout_sec: float = 5.0):
        """添加健康检查。

        Args:
            name: 检查名称
            fn: 返回 bool 的检查函数
            check_type: "liveness" / "readiness" / "startup"
            timeout_sec: 超时秒数
        """
        self._checks[name] = {
            "fn": fn, "type": check_type, "timeout": timeout_sec
        }

    def run_all(self) -> dict:
        """运行所有健康检查，返回完整状态"""
        results = {}
        all_healthy = True
        now = datetime.now(timezone.utc).isoformat()

        for name, check in self._checks.items():
            try:
                ok = check["fn"]()
                results[name] = {
                    "status": "pass" if ok else "fail",
                    "type": check["type"],
                }
                if not ok:
                    all_healthy = False
            except Exception as e:
                results[name] = {
                    "status": "error",
                    "type": check["type"],
                    "error": str(e)[:100],
                }
                all_healthy = False
                self._slog.error(event="health_check_error",
                                 message=f"{name}: {e}")

        return {
            "status": "healthy" if all_healthy else "unhealthy",
            "timestamp": now,
            "uptime_sec": round(time.time() - self._startup_at, 1),
            "node": socket.gethostname(),
            "checks": results,
        }

    def is_ready(self) -> bool:
        """就绪探测 — 所有 readiness 检查通过"""
        for name, check in self._checks.items():
            if check["type"] == "readiness":
                try:
                    if not check["fn"]():
                        return False
                except Exception:
                    return False
        return True

    def is_alive(self) -> bool:
        """存活探测 — 所有 liveness 检查通过"""
        for name, check in self._checks.items():
            if check["type"] == "liveness":
                try:
                    if not check["fn"]():
                        return False
                except Exception:
                    return False
        return True

    def readiness_response(self) -> tuple[int, str]:
        """返回 HTTP 状态码和 JSON body（K8s readinessProbe 兼容）"""
        status = self.run_all()
        code = 200 if self.is_ready() else 503
        return code, json.dumps(status, ensure_ascii=False)

    def liveness_response(self) -> tuple[int, str]:
        """返回 HTTP 状态码和 JSON body（K8s livenessProbe 兼容）"""
        status = self.run_all()
        code = 200 if self.is_alive() else 500
        return code, json.dumps(status, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 选主 (Leader Election)
# ═══════════════════════════════════════════════════════════

class LeaderElection:
    """基于文件锁的轻量选主 — 无 Redis/etcd 依赖。

    多机部署时，所有节点共享一个 NFS/共享存储路径即可。
    也支持基于 HTTP 的对等协商。
    """

    def __init__(self, node_id: str = None,
                 lock_dir: str = None,
                 ttl_sec: float = 30.0):
        self._node_id = node_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._lock_dir = Path(lock_dir or "/tmp/ha-leader")
        self._ttl = ttl_sec
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        self._slog = get_security_logger()

    @property
    def node_id(self) -> str:
        return self._node_id

    def is_leader(self) -> bool:
        """检查当前节点是否为 Leader。

        文件锁机制:
          1. 读取 lock 文件，检查 TTL
          2. 若 TTL 过期或无 lock，尝试获取
          3. 写入自己的 node_id + 过期时间
        """
        lockfile = self._lock_dir / "leader.lock"
        now = time.time()

        try:
            if lockfile.exists():
                content = lockfile.read_text().strip()
                if "|" in content:
                    leader_id, expires = content.split("|", 1)
                    if float(expires) > now:
                        return leader_id == self._node_id
        except (ValueError, OSError):
            pass

        # 尝试获取锁（原子写入）
        try:
            tmp = lockfile.with_suffix(".tmp")
            tmp.write_text(f"{self._node_id}|{now + self._ttl}")
            tmp.rename(lockfile)  # 原子操作（POSIX）
            self._slog.audit(action="leader_acquired", subject=self._node_id,
                             detail="获取 Leader 锁")
            return True
        except OSError:
            return False

    def get_leader(self) -> Optional[str]:
        """获取当前 Leader 的 node_id"""
        lockfile = self._lock_dir / "leader.lock"
        try:
            if lockfile.exists():
                content = lockfile.read_text().strip()
                if "|" in content:
                    leader_id, expires = content.split("|", 1)
                    if float(expires) > time.time():
                        return leader_id
        except (ValueError, OSError):
            pass
        return None

    def step_down(self) -> None:
        """主动放弃 Leader 身份"""
        lockfile = self._lock_dir / "leader.lock"
        try:
            content = lockfile.read_text().strip()
            if content.startswith(self._node_id):
                lockfile.unlink()
                self._slog.audit(action="leader_stepped_down",
                                 subject=self._node_id)
        except (FileNotFoundError, OSError):
            pass


# ═══════════════════════════════════════════════════════════
# 对等节点发现 & 负载均衡权重
# ═══════════════════════════════════════════════════════════

class PeerRegistry:
    """对等节点注册表 — 共享文件/NFS 存储。

    每个节点定期写入心跳文件，其他节点读取获取对等列表。
    """

    def __init__(self, registry_dir: str = None, heartbeat_interval: float = 10.0):
        self._dir = Path(registry_dir or "/tmp/ha-peers")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._node_id = f"{socket.gethostname()}:{os.getpid()}"
        self._interval = heartbeat_interval

    def heartbeat(self, port: int = 8800, weight: float = 1.0,
                  metadata: dict = None) -> None:
        """写入心跳文件"""
        hb = {
            "node_id": self._node_id,
            "host": socket.gethostname(),
            "port": port,
            "weight": weight,
            "last_seen": time.time(),
            "metadata": metadata or {},
        }
        hb_file = self._dir / f"{self._node_id}.json"
        tmp = hb_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(hb))
        tmp.rename(hb_file)

    def get_peers(self, max_age_sec: float = 30.0) -> list[dict]:
        """获取所有存活对等节点"""
        peers = []
        now = time.time()
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if now - data.get("last_seen", 0) < max_age_sec:
                    peers.append(data)
            except (json.JSONDecodeError, OSError):
                pass
        return sorted(peers, key=lambda p: p.get("weight", 1.0), reverse=True)

    def get_peer_count(self) -> int:
        """存活节点数"""
        return len(self.get_peers())

    def cleanup(self, max_age_sec: float = 120.0) -> int:
        """清理过期心跳文件"""
        count = 0
        now = time.time()
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if now - data.get("last_seen", 0) > max_age_sec:
                    f.unlink()
                    count += 1
            except (json.JSONDecodeError, OSError):
                f.unlink()
                count += 1
        return count
