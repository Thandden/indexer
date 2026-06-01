"""Drive the two-domain experiment end to end.

For each test page it:
  1. creates the page on the TARGET app (coffeeclubguide.site)
  2. registers that URL with the HUB app (ozymandias.space) under a bucket
  3. fires the WebSub ping when the bucket is in the feed

Buckets isolate the mechanisms so you learn WHICH one indexed a page:
  control = page exists, linked/fed nowhere   (baseline — should NOT index)
  hub     = hub link only
  websub  = feed/ping only
  both    = hub link + feed/ping

Usage:
    uv run seed.py --hub https://ozymandias.space --target https://coffeeclubguide.site
    (defaults to localhost:5000 / :5001 for a local dry run)
"""
import argparse
import sys
import requests

API_KEY = "poc-secret-key-change-me"
WEBSUB_HUB = "https://pubsubhubbub.appspot.com/"

# The test set. Same content style across buckets so the only variable is the
# mechanism, not the page. Add/dup these to grow sample size per bucket.
PAGES = [
    {"slug": "pour-over-basics", "bucket": "control",
     "title": "Pour Over Basics",
     "summary": "A short guide to pour over coffee.",
     "body": "Pour over brewing rewards a steady hand and a slow pour. "
             "Start with a rinse, bloom for thirty seconds, then pour in stages."},
    {"slug": "grind-size-guide", "bucket": "hub",
     "title": "Grind Size Guide",
     "summary": "Matching grind size to brew method.",
     "body": "Grind size is the lever most people ignore. Coarse for press, "
             "medium for drip, fine for espresso. Adjust to taste and time."},
    {"slug": "water-temperature", "bucket": "websub",
     "title": "Water Temperature",
     "summary": "Why brew temperature matters.",
     "body": "Off-boil water around ninety-three degrees extracts cleanly. "
             "Too hot scorches; too cool leaves the cup thin and sour."},
    {"slug": "bean-storage", "bucket": "both",
     "title": "Bean Storage",
     "summary": "Keeping beans fresh longer.",
     "body": "Air, light, heat, and moisture are the enemies of fresh beans. "
             "An opaque airtight container at room temperature wins."},
]


def post(url, **kw):
    r = requests.post(url, headers={"X-API-Key": API_KEY}, timeout=15, **kw)
    if not r.ok:
        print(f"  ! {url} -> {r.status_code} {r.text}", file=sys.stderr)
        return None
    return r.json()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hub", default="http://localhost:5000",
                   help="hub app base URL (ozymandias.space)")
    p.add_argument("--target", default="http://localhost:5001",
                   help="target app base URL (coffeeclubguide.site)")
    args = p.parse_args()
    hub, target = args.hub.rstrip("/"), args.target.rstrip("/")
    feed = f"{hub}/feed.xml"

    pinged = False
    for pg in PAGES:
        print(f"[{pg['bucket']:7}] {pg['slug']}")

        # 1. create the page on the target domain
        created = post(f"{target}/api/pages", json={
            "slug": pg["slug"], "title": pg["title"],
            "summary": pg["summary"], "body": pg["body"]})
        if not created:
            continue
        page_url = created["url"]
        print(f"  created: {page_url}")

        # 2. register with the hub under its bucket (control still recorded,
        #    just never linked/fed — gives the checker something to poll)
        reg = post(f"{hub}/submit", json={
            "url": page_url, "bucket": pg["bucket"],
            "title": pg["title"], "summary": pg["summary"]})
        if reg:
            print(f"  registered: bucket={reg['bucket']} hub_id={reg['hub_id']}")

        # 3. WebSub ping once per run if any fed bucket is present
        if pg["bucket"] in ("websub", "both"):
            pinged = True

    if pinged:
        w = requests.post(WEBSUB_HUB,
                          data={"hub.mode": "publish", "hub.url": feed}, timeout=15)
        print(f"\nwebsub ping ({feed}): {w.status_code}")
    else:
        print("\nwebsub ping: skipped (no fed buckets)")

    print("\nseeded. now run checker.py periodically to watch index state.")


if __name__ == "__main__":
    main()
