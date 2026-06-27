#!/usr/bin/env python3
"""灾难恢复 — 定时备份 / 快照 / 恢复演练 / 完整性校验。

零外部依赖，纯 Python 标准库。

用法:
    from disaster_recovery import BackupManager

    bm = BackupManager(backup_dir="./backups")

    # 备份
    bm.backup("kb_legal.json")         # 单文件
    bm.snapshot(["*.json", "*.db"])    # glob 快照

    # 恢复
    bm.restore("kb_legal.json", "2026-06-02T12:00:00")

    # 演练
    bm.drill()  # 自动执行备份→恢复→校验，输出报告

目录结构:
    backups/
    ├── 2026-06-02T12:00:00Z/
    │   ├── kb_legal.json
    │   ├── kb_medical.json
    │   └── manifest.json
    ├── 2026-06-02T13:00:00Z/
    │   └── ...
    └── drill_reports/
"""

import glob as glob_mod
import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from security_logger import get_security_logger


class BackupManager:
    """文件级备份管理器 — 增量快照 + 恢复演练"""

    def __init__(self, backup_dir: str = None,
                 source_dir: str = None,
                 retention_days: int = 30):
        self._source = Path(source_dir or os.getcwd())
        self._backup_root = Path(backup_dir or (self._source / "backups"))
        self._retention = retention_days
        self._slog = get_security_logger()
        self._backup_root.mkdir(parents=True, exist_ok=True)

    # ── 备份 ────────────────────────────────────

    def snapshot(self, patterns: list[str] = None,
                 tag: str = "") -> str:
        """创建完整快照 — 匹配 glob 模式的所有文件。

        Args:
            patterns: glob 模式列表，默认备份所有 JSON/DB/TXT
            tag: 快照标签（如 "pre-deploy"）
        Returns:
            快照目录名（ISO 时间戳）
        """
        if patterns is None:
            patterns = ["*.json", "*.db", "*.jsonl", "*.txt", "*.yaml", "*.yml",
                       "*.py", "*.toml", "*.cfg", "*.ini", "*.idx", "*.manifest"]

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        snap_dir = self._backup_root / ts
        snap_dir.mkdir(parents=True, exist_ok=True)

        files_copied = []
        total_bytes = 0

        for pattern in patterns:
            for filepath in self._source.glob(pattern):
                if self._should_skip(filepath):
                    continue
                rel = filepath.relative_to(self._source)
                dest = snap_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(filepath, dest)
                size = filepath.stat().st_size
                files_copied.append(str(rel))
                total_bytes += size

        # 写入 manifest
        manifest = {
            "ts": ts,
            "tag": tag,
            "source_dir": str(self._source),
            "files": files_copied,
            "total_files": len(files_copied),
            "total_bytes": total_bytes,
            "checksums": {f: self._sha256(snap_dir / f) for f in files_copied},
        }
        with open(snap_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        self._slog.audit(
            action="backup_snapshot", subject=ts,
            detail=f"{len(files_copied)} files, {total_bytes} bytes" + (f", tag={tag}" if tag else "")
        )

        self._cleanup_old()
        return ts

    def backup(self, filepath: str) -> str:
        """备份单个文件"""
        return self.snapshot(patterns=[filepath], tag=f"single:{filepath}")

    # ── 恢复 ────────────────────────────────────

    def restore(self, filepath: str, snapshot_ts: str,
                dry_run: bool = False) -> bool:
        """从指定快照恢复文件。

        Args:
            filepath: 要恢复的文件（相对路径）
            snapshot_ts: 快照时间戳
            dry_run: 仅校验不实际恢复
        Returns:
            是否成功
        """
        snap_dir = self._backup_root / snapshot_ts
        if not snap_dir.exists():
            self._slog.error(event="restore_fail",
                             message=f"快照不存在: {snapshot_ts}")
            return False

        src = snap_dir / filepath
        if not src.exists():
            self._slog.error(event="restore_fail",
                             message=f"快照中无此文件: {filepath}")
            return False

        # 校验 checksum
        manifest_path = snap_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            expected = manifest.get("checksums", {}).get(filepath)
            if expected:
                actual = self._sha256(src)
                if actual != expected:
                    self._slog.error(event="restore_checksum_fail",
                                     message=f"{filepath}: 校验和不匹配")
                    return False

        if dry_run:
            self._slog.audit(action="restore_dry_run", subject=filepath,
                             detail=f"校验通过 (快照: {snapshot_ts})")
            return True

        # 执行恢复
        dest = self._source / filepath
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

        self._slog.audit(action="restore", subject=filepath,
                         detail=f"已从快照 {snapshot_ts} 恢复")
        return True

    def restore_all(self, snapshot_ts: str, dry_run: bool = False) -> dict:
        """恢复整个快照的所有文件。返回每个文件的恢复结果。"""
        snap_dir = self._backup_root / snapshot_ts
        manifest_path = snap_dir / "manifest.json"
        if not manifest_path.exists():
            return {"error": "manifest 不存在"}

        with open(manifest_path) as f:
            manifest = json.load(f)

        results = {}
        for filepath in manifest.get("files", []):
            results[filepath] = self.restore(filepath, snapshot_ts, dry_run=dry_run)
        return results

    # ── 演练 ────────────────────────────────────

    def drill(self) -> dict:
        """恢复演练 — 备份→恢复→校验，输出报告。

        自动执行完整恢复流程到临时目录，验证完整性后清理。
        """
        report = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "steps": [],
        }

        # Step 1: 创建快照
        snap_ts = self.snapshot(tag="drill")
        report["snapshot"] = snap_ts
        report["steps"].append({"step": "snapshot", "status": "ok"})

        # Step 2: 恢复到临时目录
        snap_dir = self._backup_root / snap_ts
        with tempfile.TemporaryDirectory() as tmpdir:
            for filepath in self._list_snapshot_files(snap_ts):
                src = snap_dir / filepath
                dest = Path(tmpdir) / filepath
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

            report["steps"].append({"step": "restore_to_temp", "status": "ok",
                                    "files": len(self._list_snapshot_files(snap_ts))})

            # Step 3: 校验所有文件
            manifest_path = snap_dir / "manifest.json"
            with open(manifest_path) as f:
                manifest = json.load(f)

            verify_ok = 0
            verify_fail = 0
            for filepath, expected_hash in manifest.get("checksums", {}).items():
                actual = self._sha256(Path(tmpdir) / filepath)
                if actual == expected_hash:
                    verify_ok += 1
                else:
                    verify_fail += 1

            report["steps"].append({
                "step": "verify", "status": "ok" if verify_fail == 0 else "fail",
                "verified": verify_ok, "failed": verify_fail,
            })

        # 保存报告
        drill_dir = self._backup_root / "drill_reports"
        drill_dir.mkdir(exist_ok=True)
        report_path = drill_dir / f"drill_{snap_ts}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        self._slog.audit(
            action="drill_complete", subject=snap_ts,
            detail=f"演练{'通过' if verify_fail == 0 else '失败'}: {verify_ok} 文件校验"
        )

        return report

    # ── 查询 ────────────────────────────────────

    def list_snapshots(self) -> list[dict]:
        """列出所有快照"""
        snaps = []
        for d in sorted(self._backup_root.iterdir(), reverse=True):
            if d.is_dir() and d.name not in ("drill_reports",):
                manifest = d / "manifest.json"
                info = {"ts": d.name}
                if manifest.exists():
                    with open(manifest) as f:
                        m = json.load(f)
                        info.update({
                            "tag": m.get("tag", ""),
                            "files": m.get("total_files", 0),
                            "bytes": m.get("total_bytes", 0),
                        })
                snaps.append(info)
        return snaps

    def list_snapshot_files(self, snapshot_ts: str) -> list[str]:
        return self._list_snapshot_files(snapshot_ts)

    # ── 内部 ────────────────────────────────────

    def _list_snapshot_files(self, snapshot_ts: str) -> list[str]:
        snap_dir = self._backup_root / snapshot_ts
        manifest = snap_dir / "manifest.json"
        if manifest.exists():
            with open(manifest) as f:
                return json.load(f).get("files", [])
        return []

    def _should_skip(self, path: Path) -> bool:
        skip_patterns = ["__pycache__", ".git", "backups", "node_modules",
                        ".so", ".tar.gz", ".egg-info"]
        path_str = str(path)
        return (path.name.startswith(".") and path.name not in (".gitignore",)) or \
               any(p in path_str for p in skip_patterns) or \
               path.is_dir()

    def _sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _cleanup_old(self) -> None:
        """清理超过保留天数的旧快照"""
        cutoff = time.time() - self._retention * 86400
        for d in self._backup_root.iterdir():
            if d.is_dir() and d.name not in ("drill_reports",):
                try:
                    ts = datetime.strptime(d.name[:19], "%Y-%m-%dT%H:%M:%S")
                    if ts.timestamp() < cutoff:
                        shutil.rmtree(d)
                        self._slog.audit(action="backup_cleanup", subject=d.name,
                                         detail="过期快照已清理")
                except (ValueError, OSError):
                    pass
