"""Cached GPU memory monitor for local LLM throttling."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Any


class GpuMemoryMonitor:
    """Poll nvidia-smi in one daemon thread and expose the latest snapshot."""

    def __init__(self, interval_seconds: float | None = None):
        self.interval_seconds = interval_seconds or float(os.getenv("GPU_MONITOR_INTERVAL_SECONDS", "7"))
        self._lock = threading.RLock()
        self._started = False
        self._snapshot: dict[str, Any] = {
            "available": False,
            "memory_used_mb": None,
            "checked_at": None,
            "error": None,
        }

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._update_once()
        thread = threading.Thread(target=self._run, name="gpu-memory-monitor", daemon=True)
        thread.start()

    def snapshot(self) -> dict[str, Any]:
        self.start()
        with self._lock:
            return dict(self._snapshot)

    def should_throttle(self, threshold_mb: int) -> bool:
        snap = self.snapshot()
        used = snap.get("memory_used_mb")
        return bool(snap.get("available") and used is not None and used > threshold_mb)

    def _run(self) -> None:
        while True:
            time.sleep(self.interval_seconds)
            self._update_once()

    def _update_once(self) -> None:
        snapshot = self._query_nvidia_smi()
        with self._lock:
            self._snapshot = snapshot

    @staticmethod
    def _query_nvidia_smi() -> dict[str, Any]:
        checked_at = datetime.now().isoformat()
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode != 0:
                return {
                    "available": False,
                    "memory_used_mb": None,
                    "checked_at": checked_at,
                    "error": (result.stderr or "nvidia-smi failed")[:200],
                }
            values = [
                int(line.strip())
                for line in result.stdout.splitlines()
                if line.strip().isdigit()
            ]
            if not values:
                return {
                    "available": False,
                    "memory_used_mb": None,
                    "checked_at": checked_at,
                    "error": "nvidia-smi returned no memory values",
                }
            return {
                "available": True,
                "memory_used_mb": max(values),
                "checked_at": checked_at,
                "error": None,
            }
        except Exception as exc:
            return {
                "available": False,
                "memory_used_mb": None,
                "checked_at": checked_at,
                "error": str(exc)[:200],
            }


_DEFAULT_MONITOR = GpuMemoryMonitor()


def get_gpu_memory_snapshot() -> dict[str, Any]:
    return _DEFAULT_MONITOR.snapshot()


def should_throttle_gpu_memory(threshold_mb: int = 11000) -> bool:
    return _DEFAULT_MONITOR.should_throttle(threshold_mb)
