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
        # cohort = slug prefix before the bucket name (e.g. /c2-control-1).
        # group key keeps cohorts separate so the outage batch and a fresh
        # batch don't merge in the summary.
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        bucket_slug = bucket.replace("+", "-")
        if bucket_slug in slug and not slug.startswith(bucket_slug):
            cohort = slug.split(bucket_slug)[0].rstrip("-")
        else:
            cohort = "c1"  # original, unprefixed batch
        key = f"[{cohort}] {bucket}"
        b = buckets[key]
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

    def sort_key(key):
        # key looks like "[c1] hub+websub" — sort by cohort, then bucket order
        cohort, _, bkt = key.partition("] ")
        cohort = cohort.lstrip("[")
        rank = ORDER.index(bkt) if bkt in ORDER else len(ORDER)
        return (cohort, rank)

    ordered = sorted(buckets, key=sort_key)

    hdr = f"{'cohort/bucket':<30} {'n':>2} {'crawl':>6} {'index':>6} {'1st-crawl':>9} {'1st-index':>9}"
    print(hdr)
    print("-" * len(hdr))
    last_cohort = None
    for key in ordered:
        cohort = key.split("]")[0].lstrip("[")
        if cohort != last_cohort:
            print(f"--- cohort {cohort} ---")
            last_cohort = cohort
        b = buckets[key]
        bkt = key.partition("] ")[2]
        print(f"{bkt:<30} {len(b['urls']):>2} {len(b['crawled']):>6} {len(b['indexed']):>6} "
              f"{hrs(b['first_crawl']):>9} {hrs(b['first_index']):>9}")

    # current-state breakdown
    print("\ncurrent state breakdown:")
    for key in ordered:
        states = buckets[key]["latest"]
        parts = ", ".join(f"{v}×{k}" for k, v in sorted(states.items()))
        print(f"  {key:<32} {parts}")


if __name__ == "__main__":
    main()
