"""Poll Google's URL Inspection API for every submitted URL and log its state.

Ground-truth index check — requires that you OWN the target domains and have
them verified in Search Console, with a service account added as a user on
each property.

Setup (one time):
  1. Google Cloud: create a project, enable "Google Search Console API".
  2. Create a service account, download its JSON key.
  3. In each Search Console property: Settings > Users > add the service
     account's email as a user (Full or Restricted).
  4. export SA_KEY=/path/to/service-account.json

Usage:
    uv run checker.py            # check all URLs once, update DB, append to results.csv

Run it on a decaying cadence (e.g. daily via cron). Indexing happens over
days, not minutes — do not hammer it (quota ~2000/property/day).
"""
import csv
import os
import sqlite3
import sys
from datetime import datetime, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

DB_PATH = os.path.join(os.path.dirname(__file__), "indexer.db")
RESULTS_CSV = os.path.join(os.path.dirname(__file__), "results.csv")
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

# Map the inspection property each URL belongs to. URL Inspection requires the
# 'siteUrl' of the verified property that contains the inspected URL.
# Domain property -> "sc-domain:example.com"; URL-prefix -> "https://example.com/".
# Add an entry per domain you're testing.
SITE_URLS = {
    "coffeeclubguide.site": "sc-domain:coffeeclubguide.site",
    "ozymandias.space": "sc-domain:ozymandias.space",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def property_for(url):
    """Pick the matching Search Console property for a target URL."""
    for host_fragment, site_url in SITE_URLS.items():
        if host_fragment in url:
            return site_url
    return None


def inspect(service, site_url, url):
    body = {"inspectionUrl": url, "siteUrl": site_url}
    resp = service.urlInspection().index().inspect(body=body).execute()
    result = resp.get("inspectionResult", {}).get("indexStatusResult", {})
    # coverageState e.g. "Submitted and indexed", "Crawled - currently not indexed",
    # "Discovered - currently not indexed", "URL is unknown to Google"
    return {
        "coverageState": result.get("coverageState"),
        "lastCrawlTime": result.get("lastCrawlTime"),
        "verdict": resp.get("inspectionResult", {}).get("indexStatusResult", {})
                       .get("verdict"),
    }


def main():
    key_path = os.environ.get("SA_KEY")
    if not key_path or not os.path.exists(key_path):
        sys.exit("set SA_KEY to the service-account JSON key path")
    if not SITE_URLS:
        sys.exit("populate SITE_URLS with your verified Search Console properties")

    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=SCOPES
    )
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM urls ORDER BY id").fetchall()

    new_csv = not os.path.exists(RESULTS_CSV)
    csv_f = open(RESULTS_CSV, "a", newline="")
    writer = csv.writer(csv_f)
    if new_csv:
        writer.writerow(["checked_at", "url", "bucket", "coverageState",
                         "lastCrawlTime", "verdict"])

    checked = 0
    for r in rows:
        site_url = property_for(r["url"])
        if not site_url:
            print(f"skip (no property): {r['url']}", file=sys.stderr)
            continue
        try:
            info = inspect(service, site_url, r["url"])
        except HttpError as e:
            print(f"error {r['url']}: {e}", file=sys.stderr)
            continue

        now = utcnow()
        state = info["coverageState"]
        indexed = state == "Submitted and indexed"
        crawled = bool(info["lastCrawlTime"])

        # record first-crawled / first-indexed timestamps (don't overwrite)
        conn.execute(
            "UPDATE urls SET state = ?, "
            "crawled_at = COALESCE(crawled_at, CASE WHEN ? THEN ? END), "
            "indexed_at = COALESCE(indexed_at, CASE WHEN ? THEN ? END) "
            "WHERE id = ?",
            (state, crawled, now, indexed, now, r["id"]),
        )
        writer.writerow([now, r["url"], r["bucket"], state,
                         info["lastCrawlTime"], info["verdict"]])
        checked += 1
        print(f"{r['bucket']:8} {state or '-':40} {r['url']}")

    conn.commit()
    conn.close()
    csv_f.close()
    print(f"\nchecked {checked} urls -> {RESULTS_CSV}")


if __name__ == "__main__":
    main()
