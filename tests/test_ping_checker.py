"""Unit tests for Nagios-Sust-inspired single-packet concurrent ping checker."""

from __future__ import annotations

import queue
import subprocess

from pssh_ui.ping_checker import PingMonitor, ping_host, probe_ips_concurrently


def test_ping_host_checks_icmp_reply_regex(monkeypatch):
    def fake_ok(cmd, **_kwargs):
        return (
            "Pinging 10.0.0.1 with 32 bytes of data:\n"
            "Reply from 10.0.0.1: bytes=32 time=2ms TTL=64\n"
        )

    monkeypatch.setattr(subprocess, "check_output", fake_ok)
    assert ping_host("10.0.0.1", timeout_ms=1000) is True

    # Linux/Windows <1ms reply
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *_a, **_kw: "Reply from 10.0.0.2: bytes=32 time<1ms TTL=64\n",
    )
    assert ping_host("10.0.0.2") is True

    # Windows exit-code-0 "Destination host unreachable" must return False
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *_a, **_kw: "Reply from 192.168.1.5: Destination host unreachable.\n",
    )
    assert ping_host("10.0.0.3") is False

    # Subprocess non-zero / timeout raises CalledProcessError -> False
    def fake_fail(*_a, **_kw):
        raise subprocess.CalledProcessError(returncode=1, cmd=["ping"], output="Request timed out.")

    monkeypatch.setattr(subprocess, "check_output", fake_fail)
    assert ping_host("10.0.0.4") is False

    # Invalid / empty targets short-circuit cleanly
    assert ping_host("") is False
    assert ping_host("0.0.0.0") is False


def test_ping_monitor_concurrent_sweep_and_cancellation():
    q: queue.Queue = queue.Queue()
    monitor = PingMonitor(q, max_workers=4, ping_fn=lambda ip: ip.endswith(".1"))

    sid = monitor.start_sweep([("10.0.0.1:22", "10.0.0.1"), ("10.0.0.2:22", "10.0.0.2")])
    assert sid == monitor.sweep_id

    results = {}
    done = False
    while not done:
        kind, r_sid, key, payload = q.get(timeout=3.0)
        assert r_sid == sid
        if kind == "ping_result":
            results[key] = payload
        elif kind == "ping_sweep_done":
            done = True

    assert results == {"10.0.0.1:22": "Up", "10.0.0.2:22": "Down"}

    new_sid = monitor.cancel_active()
    assert new_sid > sid


def test_probe_ips_concurrently_dedupes_and_maps_status():
    calls = []

    def fake_probe(ip: str) -> bool:
        calls.append(ip)
        return ip == "10.0.0.1"

    statuses = probe_ips_concurrently(
        [("10.0.0.1:22", "10.0.0.1"), ("10.0.0.1:22", "10.0.0.1"), ("10.0.0.2:22", "10.0.0.2")],
        ping_fn=fake_probe,
        max_workers=2,
    )
    assert statuses == {"10.0.0.1:22": "Up", "10.0.0.2:22": "Down"}
    assert len(calls) == 2
