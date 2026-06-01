"""Submit a target to the indexer app, then fire the WebSub ping.

Two modes:
  external url:  uv run submit.py https://other-site.com/page --bucket both
  on-domain:     uv run submit.py --slug my-post --title "..." --body "..." --bucket both

The bucket decides which mechanisms the target is exposed to (see app.py).
WebSub is only pinged for buckets that actually appear in the feed.
"""
import argparse
import sys
import requests

APP_URL = "http://localhost:5000"      # where the Flask app is reachable
API_KEY = "poc-secret-key-change-me"
WEBSUB_HUB = "https://pubsubhubbub.appspot.com/"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url", nargs="?", help="external target URL (omit if using --slug)")
    p.add_argument("--slug", help="mint an on-domain target at /t/<slug> instead")
    p.add_argument("--bucket", default="both",
                   choices=["both", "hub", "websub", "control"])
    p.add_argument("--title")
    p.add_argument("--summary")
    p.add_argument("--body", help="page content (on-domain targets only)")
    p.add_argument("--app", default=APP_URL, help="indexer app base URL")
    p.add_argument("--feed", default=f"{APP_URL}/feed.xml")
    args = p.parse_args()

    if bool(args.url) == bool(args.slug):
        p.error("provide exactly one of: a url (external) OR --slug (on-domain)")

    # 1. register with the app (this is what builds the hub page / feed)
    if args.slug:
        endpoint, payload = "/new-target", {
            "slug": args.slug, "bucket": args.bucket, "title": args.title,
            "summary": args.summary, "body": args.body}
    else:
        endpoint, payload = "/submit", {
            "url": args.url, "bucket": args.bucket, "title": args.title,
            "summary": args.summary}

    r = requests.post(
        f"{args.app}{endpoint}",
        headers={"X-API-Key": API_KEY},
        json=payload,
        timeout=10,
    )
    if not r.ok:
        print(f"submit failed: {r.status_code} {r.text}", file=sys.stderr)
        sys.exit(1)
    print("registered:", r.json())

    # 2. fire WebSub ping for buckets that appear in the feed
    if args.bucket in ("websub", "both"):
        w = requests.post(
            WEBSUB_HUB,
            data={"hub.mode": "publish", "hub.url": args.feed},
            timeout=10,
        )
        # hub returns 204 on success
        print(f"websub ping: {w.status_code}")
    else:
        print("websub ping: skipped (bucket not in feed)")


if __name__ == "__main__":
    main()
