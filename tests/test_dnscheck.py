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


import pytest


def _domains(tmp_path, text):
    p = tmp_path / f"d{abs(hash(text))}.txt"
    p.write_text(text)
    return str(p)


def test_exit_codes_demo(tmp_path):
    ok = _domains(tmp_path, "example.com\n")
    bad = _domains(tmp_path, "example.com\nx.invalid\n")
    assert d.main([ok, "--demo"]) == 0
    assert d.main([bad, "--demo"]) == 1


def test_fail_on_slow(tmp_path):
    f = _domains(tmp_path, "example.org\n")  # demo resolver sleeps 250ms for this one
    assert d.main([f, "--demo", "--slow-ms", "50"]) == 0
    assert d.main([f, "--demo", "--slow-ms", "50", "--fail-on-slow"]) == 1


def test_usage_errors(tmp_path, capsys):
    assert d.main([str(tmp_path / "missing.txt")]) == 2
    assert d.main([_domains(tmp_path, "bad domain!\n"), "--demo"]) == 2
    assert d.main([_domains(tmp_path, "# only comments\n"), "--demo"]) == 2
    assert d.main([_domains(tmp_path, "a.com\n"), "--demo", "--resolver", "not-an-ip"]) == 2
    assert d.main([_domains(tmp_path, "a.com\n"), "--demo", "--timeout", "0"]) == 2


def test_resolver_requires_dnspython(monkeypatch):
    monkeypatch.setattr(d, "HAVE_DNSPYTHON", False)
    with pytest.raises(RuntimeError):
        d.make_resolver(["192.0.2.53"])
    assert d.make_resolver(None) is d.resolve_socket


def test_json_output_has_mode(tmp_path, capsys):
    d.main([_domains(tmp_path, "example.com\n"), "--demo", "--json"])
    assert '"mode": "demo (canned data)"' in capsys.readouterr().out


def test_inline_comments_allowed(tmp_path):
    assert d.read_domains(_domains(tmp_path, "a.example # note\n")) == ["a.example"]
