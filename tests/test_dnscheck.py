import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dnscheck as d


def fake_ok(domain):
    return {"A": ["192.0.2.10"], "AAAA": []}


def fake_fail(domain):
    raise LookupError("NXDOMAIN")


def test_successful_resolution():
    r = d.check_domain("example.test", fake_ok)
    assert r["status"] == "ok" and r["records"]["A"] == ["192.0.2.10"]


def test_failure_captured():
    r = d.check_domain("bad.test", fake_fail)
    assert r["status"] == "fail" and "NXDOMAIN" in r["error"]


def test_slow_flagged_with_fake_clock():
    ticks = iter([0.0, 0.5])
    r = d.check_domain("slow.test", fake_ok, clock=lambda: next(ticks))
    assert r["status"] == "slow" and r["latency_ms"] == 500.0


def test_summary():
    res = d.check_all(["a", "b"], lambda x: fake_ok(x) if x == "a" else fake_fail(x))
    s = d.summarize(res)
    assert (s["total"], s["resolved"], s["failed"]) == (2, 1, 1)


def test_socket_fallback_uses_getaddrinfo(monkeypatch):
    import socket
    def fake(host, port, fam, typ):
        return [(fam, typ, 0, "", ("192.0.2.1", 0))] if fam == socket.AF_INET else []
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert d.resolve_socket("x.test")["A"] == ["192.0.2.1"]
