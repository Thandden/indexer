"""Summarise results.csv into a per-bucket table.

Reads the checker's append-only log and reports, per bucket:
  - n              urls in the bucket
  - crawled        how many have ever been crawled (lastCrawlTime seen)
  - indexed        how many reached "Submitted and indexed"
  - first_crawl    earliest time-to-first-crawl in the bucket (from seed)
  - first_index    earliest time-to-first-index
  - latest state   most recent coverageState breakdown

Run on the box:  uv run summary.py
Or copy results.csv locally and run it here.
"""
import csv
import os
from collections import defaultdict
from datetime import datetime

RESULTS = os.path.join(os.path.dirname(__file__), "results.csv")

# bucket order = method complexity, control first
ORDER = ["control", "apiredirect", "hub", "websub",
         "apiredirect+hub", "apiredirect+websub", "hub+websub",
         "apiredirect+hub+websub"]


def parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def main():
    if not os.path.exists(RESULTS):
        raise SystemExit("no results.csv yet")

    rows = list(csv.DictReader(open(RESULTS)))
    if not rows:
        raise SystemExit("results.csv empty")

    # per-url history
    by_url = defaultdict(list)
    for r in rows:
        by_url[r["url"]].append(r)

    # earliest check overall = experiment start reference
    all_checks = sorted(parse(r["checked_at"]) for r in rows if parse(r["checked_at"]))
    t0 = all_checks[0]

    # aggregate per bucket
    buckets = defaultdict(lambda: {
        "urls": set(), "crawled": set(), "indexed": set(),
        "first_crawl": None, "first_index": None, "latest": {}})

    # latest state per url (by checked_at)
    latest_check = max(all_checks)
    for url, hist in by_url.items():
        hist.sort(key=lambda r: r["checked_at"])
        bucket = hist[-1]["bucket"]
        b = buckets[bucket]
        b["urls"].add(url)

        for r in hist:
            ct = parse(r["checked_at"])
            crawled = bool(r["lastCrawlTime"])
            indexed = r["coverageState"] == "Submitted and indexed"
            if crawled:
                b["crawled"].add(url)
                if b["first_crawl"] is None or ct < b["first_crawl"]:
                    b["first_crawl"] = ct
            if indexed:
                b["indexed"].add(url)
                if b["first_index"] is None or ct < b["first_index"]:
                    b["first_index"] = ct

        # latest coverage state for this url
        state = hist[-1]["coverageState"] or "—"
        b["latest"][state] = b["latest"].get(state, 0) + 1

    def hrs(t):
        return f"+{(t - t0).total_seconds()/3600:4.1f}h" if t else "   —  "

    print(f"\nexperiment start (t0): {t0.isoformat()}")
    print(f"latest check:          {latest_check.isoformat()}")
    print(f"elapsed:               {(latest_check - t0).total_seconds()/3600:.1f}h\n")

    hdr = f"{'bucket':<24} {'n':>2} {'crawl':>6} {'index':>6} {'1st-crawl':>9} {'1st-index':>9}"
    print(hdr)
    print("-" * len(hdr))
    seen = set()
    for bucket in ORDER + sorted(set(buckets) - set(ORDER)):
        if bucket in seen or bucket not in buckets:
            continue
        seen.add(bucket)
        b = buckets[bucket]
        n = len(b["urls"])
        print(f"{bucket:<24} {n:>2} {len(b['crawled']):>6} {len(b['indexed']):>6} "
              f"{hrs(b['first_crawl']):>9} {hrs(b['first_index']):>9}")

    # current-state breakdown
    print("\ncurrent state breakdown:")
    for bucket in ORDER:
        if bucket not in buckets:
            continue
        states = buckets[bucket]["latest"]
        parts = ", ".join(f"{v}×{k}" for k, v in sorted(states.items()))
        print(f"  {bucket:<24} {parts}")


if __name__ == "__main__":
    main()
