"""DNS health checker: resolve domains, report records and latency.

Uses dnspython when installed (A, AAAA, MX, NS, TXT); otherwise falls back to
the standard-library socket resolver (A/AAAA only).
"""
import argparse
import json
import ipaddress
import re
import socket
import sys
import time
from pathlib import Path

try:  # optional dependency
    import dns.exception
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


def make_resolver(nameservers=None, timeout=3.0, record_types=("A", "AAAA", "MX", "NS", "TXT")):
    """Build a resolver callable. Needs dnspython when nameservers are given."""
    if not HAVE_DNSPYTHON:
        if nameservers:
            raise RuntimeError("--resolver requires dnspython (pip install dnspython)")
        return resolve_socket

    def resolve(domain):
        r = dns.resolver.Resolver(configure=True)
        if nameservers:
            r.nameservers = list(nameservers)
        r.lifetime = r.timeout = timeout
        out, errors = {}, []
        for rt in record_types:
            try:
                out[rt] = sorted(str(x) for x in r.resolve(domain, rt))
            except dns.resolver.NXDOMAIN:
                raise LookupError("NXDOMAIN")
            except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
                out[rt] = []
            except dns.exception.Timeout:
                out[rt] = []
                errors.append("timeout")
            except Exception as exc:  # network errors etc.
                out[rt] = []
                errors.append(type(exc).__name__)
        if not any(out.values()):
            raise LookupError(errors[0] if errors else "no records")
        return out

    return resolve


def resolve_dnspython(domain, record_types=("A", "AAAA", "MX", "NS", "TXT")):
    return make_resolver(None, 3.0, record_types)(domain)


def default_resolver(domain):
    return resolve_dnspython(domain) if HAVE_DNSPYTHON else resolve_socket(domain)


def check_domain(domain, resolver=default_resolver, clock=time.perf_counter, slow_ms=None):
    start = clock()
    try:
        records = resolver(domain)
        status = "ok"
        error = None
    except Exception as exc:
        records, status, error = {}, "fail", str(exc)
    latency = round((clock() - start) * 1000, 1)
    if status == "ok" and latency > (SLOW_MS if slow_ms is None else slow_ms):
        status = "slow"
    return {"domain": domain, "status": status, "latency_ms": latency,
            "records": records, "error": error}


def check_all(domains, resolver=default_resolver, slow_ms=None):
    return [check_domain(d, resolver, slow_ms=slow_ms) for d in domains]


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


DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9_]([A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?\.)*[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$")

# Exit codes (for CI / monitoring): 0 = all resolved, 1 = failures (or slow with
# --fail-on-slow), 2 = usage / input error.
EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


def read_domains(path):
    domains = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if not DOMAIN_RE.match(line):
            raise ValueError(f"line {n}: invalid domain name {line!r}")
        domains.append(line)
    if not domains:
        raise ValueError("no domains found in input file")
    return domains


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Check DNS resolution for a list of domains. Real lookups by default; use --demo for canned offline data.",
        epilog="Exit codes: 0 all resolved, 1 failures (or slow with --fail-on-slow), 2 usage/input error.")
    ap.add_argument("file", help="text file with one domain per line (# for comments)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="use a canned offline resolver instead of real DNS")
    ap.add_argument("--resolver", action="append", metavar="IP",
                    help="nameserver IP to query instead of system default (repeatable; needs dnspython)")
    ap.add_argument("--timeout", type=float, default=3.0, help="per-query timeout in seconds (default 3)")
    ap.add_argument("--slow-ms", type=float, default=SLOW_MS, help=f"slow threshold in ms (default {SLOW_MS:.0f})")
    ap.add_argument("--fail-on-slow", action="store_true", help="exit 1 if any lookup is slow")
    args = ap.parse_args(argv)
    if not 0 < args.timeout <= 60:
        print("error: --timeout must be in (0, 60]", file=sys.stderr)
        return EXIT_USAGE
    try:
        domains = read_domains(args.file)
        if args.resolver:
            for ip in args.resolver:
                ipaddress.ip_address(ip)
        resolver = demo_resolver if args.demo else make_resolver(args.resolver, args.timeout)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    results = check_all(domains, resolver, slow_ms=args.slow_ms)
    s = summarize(results)
    mode = "demo (canned data)" if args.demo else ("dnspython" if HAVE_DNSPYTHON else "socket (A/AAAA only)")
    if args.json:
        print(json.dumps({"mode": mode, "summary": s, "results": results}, indent=2))
    else:
        print(f"resolver: {mode}" + (f" via {', '.join(args.resolver)}" if args.resolver and not args.demo else ""))
        for r in results:
            a = ",".join(r["records"].get("A", [])[:2]) or r["error"] or "-"
            print(f"{r['domain']:<28} {r['status']:<5} {r['latency_ms']:>7} ms  {a}")
        print(f"\n{s['resolved']}/{s['total']} resolved, avg latency {s['avg_latency_ms']} ms")
    if s["failed"] or (args.fail_on_slow and any(r["status"] == "slow" for r in results)):
        return EXIT_FAIL
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
