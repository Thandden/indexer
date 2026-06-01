"""Drive the indexing experiment end to end.

Tests every combination of three methods (hub, websub, apiredirect) plus a
control, with N samples each, so you can see which method — alone or combined —
actually gets pages indexed.

For each page it:
  1. creates the page on the TARGET app (coffeeclubguide.site)
  2. registers it with the HUB app under its bucket (applies hub + websub)
  3. (apiredirect method) pings the Google Indexing API at the hub's /r/<id>
     redirector, which 301s to the target — production-faithful API use that
     needs ownership of the HUB only, not the target.
  4. fires ONE WebSub ping at the end if any fed bucket exists

Buckets (canonical: methods sorted, '+'-joined, or 'control'):
  control, apiredirect, hub, websub,
  apiredirect+hub, apiredirect+websub, hub+websub, apiredirect+hub+websub

apiredirect requires SA_KEY (service-account JSON, OWNER of the HUB property
ozymandias.space). Omit --with-api to skip those buckets.

Usage:
    SA_KEY=/path/to/sa.json uv run seed.py --with-api \\
        --hub https://ozymandias.space --target https://coffeeclubguide.site
"""
import argparse
import itertools
import sys
import requests

API_KEY = "poc-secret-key-change-me"
WEBSUB_HUB = "https://pubsubhubbub.appspot.com/"
SAMPLES = 3   # urls per bucket

# coffee-themed content fragments; varied per page so pages aren't identical
TOPICS = [
    ("Pour Over Basics", "A short guide to pour over coffee.",
     "Pour over brewing rewards a steady hand and a slow pour."),
    ("Grind Size Guide", "Matching grind size to brew method.",
     "Grind size is the lever most people ignore when dialling in a cup."),
    ("Water Temperature", "Why brew temperature matters.",
     "Off-boil water around ninety-three degrees extracts cleanly."),
    ("Bean Storage", "Keeping beans fresh longer.",
     "Air, light, heat, and moisture are the enemies of fresh beans."),
    ("Espresso Ratios", "Dialling in a balanced shot.",
     "A classic ratio is one part coffee to two parts liquid espresso."),
    ("Cold Brew Method", "Smooth low-acid coffee at home.",
     "Steep coarse grounds in cold water for sixteen hours, then strain."),
    ("Milk Texturing", "Microfoam for flat whites and lattes.",
     "Stretch the milk briefly, then submerge the tip to spin a tight whirlpool."),
    ("Filter Choice", "Paper, metal, and cloth filters compared.",
     "Paper traps oils for a clean cup; metal lets body and sediment through."),
]


def buckets():
    """All 8 method combinations as canonical bucket names."""
    out = ["control"]
    methods = ["apiredirect", "hub", "websub"]  # sorted order for canonical names
    for r in (1, 2, 3):
        for combo in itertools.combinations(methods, r):
            out.append("+".join(combo))
    return out


def post(url, **kw):
    r = requests.post(url, headers={"X-API-Key": API_KEY}, timeout=15, **kw)
    if not r.ok:
        print(f"  ! {url} -> {r.status_code} {r.text}", file=sys.stderr)
        return None
    return r.json()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hub", default="http://localhost:5000")
    p.add_argument("--target", default="http://localhost:5001")
    p.add_argument("--with-api", action="store_true",
                   help="fire the Indexing API for 'api' buckets (needs SA_KEY)")
    p.add_argument("--samples", type=int, default=SAMPLES)
    args = p.parse_args()
    hub, target = args.hub.rstrip("/"), args.target.rstrip("/")
    feed = f"{hub}/feed.xml"

    idx_service = None
    if args.with_api:
        from google_index import get_service
        idx_service = get_service()

    topic_cycle = itertools.cycle(TOPICS)
    pinged = False
    api_count = 0

    for bucket in buckets():
        methods = set() if bucket == "control" else set(bucket.split("+"))
        if "apiredirect" in methods and not args.with_api:
            print(f"[{bucket}] skipped (no --with-api)")
            continue

        for i in range(args.samples):
            title, summary, body = next(topic_cycle)
            slug = f"{bucket.replace('+', '-')}-{i+1}"
            print(f"[{bucket}] {slug}")

            created = post(f"{target}/api/pages", json={
                "slug": slug, "title": f"{title} {i+1}",
                "summary": summary, "body": body})
            if not created:
                continue
            page_url = created["url"]

            reg = post(f"{hub}/submit", json={
                "url": page_url, "bucket": bucket,
                "title": f"{title} {i+1}", "summary": summary})
            if not reg:
                continue

            if "websub" in methods:
                pinged = True
            if "apiredirect" in methods:
                # ping the API at the hub's redirector (we own the hub); the
                # 301 carries the crawl to the target we don't own
                from google_index import publish
                try:
                    publish(idx_service, reg["redirect_url"])
                    api_count += 1
                except Exception as e:
                    print(f"  ! indexing api: {e}", file=sys.stderr)

    if pinged:
        w = requests.post(WEBSUB_HUB,
                          data={"hub.mode": "publish", "hub.url": feed}, timeout=15)
        print(f"\nwebsub ping ({feed}): {w.status_code}")
    if idx_service:
        print(f"indexing api: {api_count} urls pinged")
    print("\nseeded. run checker.py periodically to watch index state.")


if __name__ == "__main__":
    main()
