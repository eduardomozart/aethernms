"""Concurrent single-packet ICMP ping checker for visible device tables."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import platform
import queue
import re
import subprocess
import threading
from typing import Callable, Dict, List, Optional, Sequence, Tuple


_LATENCY_RE = re.compile(r"[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms", re.IGNORECASE)


def ping_host(ip_address: str, timeout_ms: int = 1000) -> bool:
    """Send 1 ICMP echo request and return True if at least one reply succeeds."""
    host = (ip_address or "").strip()
    if not host or host == "0.0.0.0":
        return False

    timeout_ms = max(200, int(timeout_ms))
    if platform.system().lower() == "windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        timeout_sec = str(max(1, (timeout_ms + 999) // 1000))
        cmd = ["ping", "-c", "1", "-W", timeout_sec, host]
        creationflags = 0

    try:
        output = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=max(2.0, timeout_ms / 1000.0 + 1.0),
            creationflags=creationflags,
        )
        return bool(_LATENCY_RE.search(output))
    except (subprocess.SubprocessError, OSError):
        return False


def _dedupe_ping_targets(targets: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Deduplicate (unique_key, ip) targets while preserving first-seen order."""
    seen: set[str] = set()
    deduped: List[Tuple[str, str]] = []
    for key, ip in targets:
        if key and ip and key not in seen:
            seen.add(key)
            deduped.append((key, ip))
    return deduped


def probe_ips_concurrently(
    targets: Sequence[Tuple[str, str]],
    ping_fn: Optional[Callable[[str], bool]] = None,
    max_workers: int = 16,
) -> Dict[str, str]:
    """Probe (unique_key, ip) targets concurrently and return a {key: 'Up'|'Down'} map."""
    deduped = _dedupe_ping_targets(targets)
    if not deduped:
        return {}
    fn = ping_fn if ping_fn is not None else ping_host
    results: Dict[str, str] = {}
    workers = min(max(1, int(max_workers)), len(deduped))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(fn, ip): key for key, ip in deduped}
        for fut in as_completed(future_map):
            key = future_map[fut]
            try:
                alive = bool(fut.result())
            except Exception:
                alive = False
            results[key] = "Up" if alive else "Down"
    return results


class PingMonitor:
    """Concurrent background ping dispatcher scoped to the currently visible page targets."""

    def __init__(
        self,
        result_queue: queue.Queue,
        max_workers: int = 16,
        ping_fn: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.result_queue = result_queue
        self.max_workers = max(1, int(max_workers))
        self._ping_fn = ping_fn
        self._sweep_id = 0
        self._lock = threading.Lock()

    @property
    def sweep_id(self) -> int:
        """Return the latest active sweep identifier."""
        with self._lock:
            return self._sweep_id

    def cancel_active(self) -> int:
        """Invalidate any in-flight ping sweep so older results are ignored."""
        with self._lock:
            self._sweep_id += 1
            return self._sweep_id

    def start_sweep(self, targets: Sequence[Tuple[str, str]]) -> int:
        """Launch a concurrent sweep for deduplicated (unique_key, ip) targets."""
        deduped = _dedupe_ping_targets(targets)

        with self._lock:
            self._sweep_id += 1
            sid = self._sweep_id

        if not deduped:
            return sid

        check_fn = self._ping_fn

        def _worker() -> None:
            fn = check_fn if check_fn is not None else ping_host
            workers = min(self.max_workers, len(deduped))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {pool.submit(fn, ip): key for key, ip in deduped}
                for fut in as_completed(future_map):
                    key = future_map[fut]
                    try:
                        alive = bool(fut.result())
                    except Exception:
                        alive = False
                    if self.sweep_id != sid:
                        return
                    self.result_queue.put(("ping_result", sid, key, "Up" if alive else "Down"))
            if self.sweep_id == sid:
                self.result_queue.put(("ping_sweep_done", sid, None, None))

        threading.Thread(target=_worker, daemon=True).start()
        return sid
