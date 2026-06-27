"""
零依赖日志工具 — 模块级实例, 支持 .debug() .info() .warn() .error()
用法:
  from logger import log
  log.info("checker hit", verdict="contradicted")
  log.set_level("DEBUG")
"""

import sys
import time
from typing import Any


class _Logger:
    LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

    def __init__(self):
        self._level = "INFO"
        self._file = None
        self._file_path = None

    def set_level(self, level: str) -> None:
        if level in self.LEVELS:
            self._level = level

    def enable_file(self, path: str = None) -> None:
        """Enable file logging. Uses $HOME/awareness_gateway.log by default."""
        from pathlib import Path
        if path is None:
            path = str(Path.home() / "awareness_gateway.log")
        self._file_path = path
        try:
            self._file = open(path, "a")
        except OSError:
            self._file = None

    def _should_log(self, level: str) -> bool:
        return self.LEVELS.get(level, 0) >= self.LEVELS.get(self._level, 20)

    def _emit(self, level: str, msg: str, **kwargs: Any) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        line = f"[{ts}] {level:5s} {msg}"
        if extra:
            line += f"  |  {extra}"
        print(line, file=sys.stderr)
        if self._file:
            try:
                self._file.write(line + "\n")
                self._file.flush()
            except OSError:
                pass

    def debug(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("DEBUG"):
            self._emit("DEBUG", msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("INFO"):
            self._emit("INFO", msg, **kwargs)

    def warn(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("WARN"):
            self._emit("WARN", msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("ERROR"):
            self._emit("ERROR", msg, **kwargs)


log = _Logger()

# Auto-enable file logging if config says so
try:
    from pathlib import Path
    with open(Path(__file__).parent / "config.json") as f:
        import json as _json
        cfg = _json.load(f)
    if cfg.get("security", {}).get("white_box_logging", False):
        log.enable_file()
except (FileNotFoundError, Exception):
    pass

