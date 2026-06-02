"""Show VERIFIED crawler hits from Caddy's access log.

Independent, server-side confirmation that Google/Bing actually fetched our
pages/feed — complements the URL Inspection API in checker.py.

User-Agent alone is NOT trusted: scanners spoof "Googlebot" to look benign
while probing for secrets (.env, key.json, .git/config). We verify each
claimed bot by reverse-DNS:
  1. PTR lookup on the client IP -> hostname
  2. hostname must end in a legitimate bot domain (googlebot.com, google.com,
     search.msn.com, ...)
  3. forward-resolve that hostname back -> must include the original IP
     (defeats forged PTR records)
Only hits passing all three are counted as real. Everything else (including
UA-spoofed scanners) is reported separately as 'spoofed/unverified'.

Run on the box:  sudo uv run crawlers.py
(needs sudo to read /var/log/caddy/access.log)
"""
import json
import os
import socket
import sys
from collections import defaultdict

LOG = os.environ.get("CADDY_LOG", "/var/log/caddy/access.log")

# UA substring -> label
BOTS = {
    "googlebot": "Googlebot",
    "google-inspectiontool": "Google Inspection",
    "feedfetcher-google": "Google FeedFetcher",
    "google-read-aloud": "Google ReadAloud",
    "apis-google": "APIs-Google",
    "bingbot": "Bingbot",
}

# a verified bot's PTR hostname must end with one of these
LEGIT_DOMAINS = (".googlebot.com", ".google.com", ".search.msn.com",
                 ".crawl.yahoo.net")


def classify(ua):
    ual = (ua or "").lower()
    for needle, label in BOTS.items():
        if needle in ual:
            return label
    if "google" in ual:
        return "Google (other)"
    return None


_verify_cache = {}


def verify_ip(ip):
    """True if IP is a genuine search-engine crawler (PTR + forward-confirm)."""
    if ip in _verify_cache:
        return _verify_cache[ip]
    ok = False
    try:
        host = socket.gethostbyaddr(ip)[0].lower()           # PTR
        if host.endswith(LEGIT_DOMAINS):
            # forward-confirm: hostname must resolve back to this IP
            _, _, ips = socket.gethostbyname_ex(host)
            ok = ip in ips
    except (socket.herror, socket.gaierror, OSError):
        ok = False
    _verify_cache[ip] = ok
    return ok


def main():
    if not os.path.exists(LOG):
        raise SystemExit(f"no log at {LOG} (is Caddy access logging enabled + deployed?)")

    verified = defaultdict(lambda: defaultdict(int))   # key -> label -> count
    spoofed = defaultdict(lambda: defaultdict(int))
    v_totals = defaultdict(int)
    s_totals = defaultdict(int)
    lines = 0

    for line in open(LOG):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        lines += 1
        req = e.get("request", {})
        ua = (req.get("headers", {}).get("User-Agent") or [""])[0]
        label = classify(ua)
        if not label:
            continue
        ip = req.get("remote_ip") or req.get("client_ip") or ""
        host = req.get("host", "")
        uri = req.get("uri", "")
        key = f"{host}{uri}"

        if ip and verify_ip(ip):
            verified[key][label] += 1
            v_totals[label] += 1
        else:
            spoofed[key][f"{label} (claimed, ip {ip})"] += 1
            s_totals["spoofed/unverified"] += 1

    print(f"parsed {lines} log entries\n")

    print("=== VERIFIED crawler hits (real Google/Bing) ===")
    if not v_totals:
        print("  none yet — no genuine crawler has fetched anything.\n")
    else:
        for label, n in sorted(v_totals.items(), key=lambda x: -x[1]):
            print(f"  {label:<22} {n}")
        print("\n  per-URL:")
        for key in sorted(verified):
            parts = ", ".join(f"{l}×{n}" for l, n in sorted(verified[key].items()))
            print(f"    {key}\n        {parts}")

    print(f"\n=== SPOOFED / unverified (UA claims a bot, failed rDNS) ===")
    if not s_totals:
        print("  none")
    else:
        print(f"  {s_totals['spoofed/unverified']} hits — ignore these, they are scanners.")
        for key in sorted(spoofed):
            parts = ", ".join(f"{l}×{n}" for l, n in sorted(spoofed[key].items()))
            print(f"    {key}\n        {parts}")


if __name__ == "__main__":
    main()
