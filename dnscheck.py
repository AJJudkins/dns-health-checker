"""DNS health checker: resolve domains, report records and latency.

Uses dnspython when installed (A, AAAA, MX, NS, TXT); otherwise falls back to
the standard-library socket resolver (A/AAAA only).
"""
import argparse
import json
import socket
import time
from pathlib import Path

try:  # optional dependency
    import dns.resolver
    HAVE_DNSPYTHON = True
except ImportError:  # pragma: no cover
    HAVE_DNSPYTHON = False

SLOW_MS = 200.0


def resolve_socket(domain):
    """Stdlib fallback: returns {record_type: [values]}."""
    out = {"A": [], "AAAA": []}
    for fam, key in ((socket.AF_INET, "A"), (socket.AF_INET6, "AAAA")):
        try:
            infos = socket.getaddrinfo(domain, None, fam, socket.SOCK_STREAM)
            out[key] = sorted({i[4][0] for i in infos})
        except socket.gaierror:
            pass
    if not (out["A"] or out["AAAA"]):
        raise LookupError("no records / resolution failed")
    return out


def resolve_dnspython(domain, record_types=("A", "AAAA", "MX", "NS", "TXT")):
    out = {}
    for rt in record_types:
        try:
            ans = dns.resolver.resolve(domain, rt, lifetime=3)
            out[rt] = sorted(str(r) for r in ans)
        except Exception:
            out[rt] = []
    if not any(out.values()):
        raise LookupError("no records / resolution failed")
    return out


def default_resolver(domain):
    return resolve_dnspython(domain) if HAVE_DNSPYTHON else resolve_socket(domain)


def check_domain(domain, resolver=default_resolver, clock=time.perf_counter):
    start = clock()
    try:
        records = resolver(domain)
        status = "ok"
        error = None
    except Exception as exc:
        records, status, error = {}, "fail", str(exc)
    latency = round((clock() - start) * 1000, 1)
    if status == "ok" and latency > SLOW_MS:
        status = "slow"
    return {"domain": domain, "status": status, "latency_ms": latency,
            "records": records, "error": error}


def check_all(domains, resolver=default_resolver):
    return [check_domain(d, resolver) for d in domains]


def summarize(results):
    total = len(results)
    ok = sum(r["status"] in ("ok", "slow") for r in results)
    lat = [r["latency_ms"] for r in results if r["status"] != "fail"]
    return {"total": total, "resolved": ok, "failed": total - ok,
            "avg_latency_ms": round(sum(lat) / len(lat), 1) if lat else None}


def demo_resolver(domain):
    """Canned offline resolver (RFC 5737 documentation addresses) for --demo."""
    if domain.endswith(".invalid"):
        raise LookupError("NXDOMAIN")
    if domain == "example.org":
        time.sleep(0.25)
    return {"A": ["192.0.2.10"], "AAAA": []}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check DNS resolution for a list of domains.")
    ap.add_argument("file", help="text file with one domain per line (# for comments)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="use a canned offline resolver instead of real DNS")
    args = ap.parse_args(argv)
    domains = [l.strip() for l in Path(args.file).read_text().splitlines()
               if l.strip() and not l.startswith("#")]
    results = check_all(domains, demo_resolver if args.demo else default_resolver)
    if args.json:
        print(json.dumps({"summary": summarize(results), "results": results}, indent=2))
        return
    print(f"resolver: {'dnspython' if HAVE_DNSPYTHON else 'socket (A/AAAA only)'}")
    for r in results:
        a = ",".join(r["records"].get("A", [])[:2]) or r["error"] or "-"
        print(f"{r['domain']:<28} {r['status']:<5} {r['latency_ms']:>7} ms  {a}")
    s = summarize(results)
    print(f"\n{s['resolved']}/{s['total']} resolved, avg latency {s['avg_latency_ms']} ms")


if __name__ == "__main__":
    main()
