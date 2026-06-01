"""Show confirmed crawler hits from Caddy's access log.

Independent, server-side confirmation that Google (or any bot) actually
fetched our pages/feed — complements the URL Inspection API in checker.py.
Caddy logs the real client IP + User-Agent (which Flask, behind the proxy,
cannot see).

Run on the box:  sudo uv run crawlers.py
(needs sudo to read /var/log/caddy/access.log)
"""
import json
import os
import sys
from collections import defaultdict

LOG = os.environ.get("CADDY_LOG", "/var/log/caddy/access.log")

# substrings that identify crawlers we care about (lowercased match)
BOTS = {
    "googlebot": "Googlebot",
    "google-inspectiontool": "Google Inspection",
    "feedfetcher-google": "Google FeedFetcher",
    "google-read-aloud": "Google ReadAloud",
    "apis-google": "APIs-Google",
    "google-site-verification": "Google SiteVerify",
    "bingbot": "Bingbot",
}


def classify(ua):
    ual = (ua or "").lower()
    for needle, label in BOTS.items():
        if needle in ual:
            return label
    if "google" in ual:
        return "Google (other)"
    return None  # ignore non-bot traffic


def main():
    if not os.path.exists(LOG):
        raise SystemExit(f"no log at {LOG} (is Caddy access logging enabled + deployed?)")

    # per (host+path): {bot_label: count, first_ts}
    hits = defaultdict(lambda: defaultdict(int))
    first_seen = {}
    bot_totals = defaultdict(int)
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
        host = req.get("host", "")
        uri = req.get("uri", "")
        key = f"{host}{uri}"
        hits[key][label] += 1
        bot_totals[label] += 1
        ts = e.get("ts")
        if key not in first_seen or (ts and ts < first_seen[key]):
            first_seen[key] = ts

    print(f"parsed {lines} log entries\n")

    if not bot_totals:
        print("No crawler hits yet. (Google hasn't fetched anything.)")
        return

    print("crawler hit totals:")
    for label, n in sorted(bot_totals.items(), key=lambda x: -x[1]):
        print(f"  {label:<22} {n}")

    print("\nper-URL crawler hits:")
    for key in sorted(hits):
        parts = ", ".join(f"{lbl}×{n}" for lbl, n in sorted(hits[key].items()))
        print(f"  {key}\n      {parts}")


if __name__ == "__main__":
    main()
