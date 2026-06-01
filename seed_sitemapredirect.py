"""Add-on seeder: 3 URLs in an isolated 'sitemapredirect' bucket.

Tests one channel in isolation — does listing a /r/<id> redirect in a polled
sitemap (honest set-once lastmod) get the target crawled, with NO hub link,
NO feed, NO API ping? Run alongside the existing 24-URL experiment.

Note: the redirect sitemap must also be SUBMITTED once in Search Console for
ozymandias.space (Sitemaps -> add /sitemap-redirects.xml) so Google polls it.

Usage:
    uv run seed_sitemapredirect.py \\
        --hub https://ozymandias.space --target https://coffeeclubguide.site
"""
import argparse
import sys
import requests

API_KEY = "poc-secret-key-change-me"

PAGES = [
    ("sitemapredirect-1", "Latte Art Basics", "Starting with simple hearts.",
     "Latte art begins with well-textured milk and a steady, close pour."),
    ("sitemapredirect-2", "Decaf Explained", "How decaffeination works.",
     "Decaf coffee has most caffeine removed via water, CO2, or solvent processes."),
    ("sitemapredirect-3", "Cupping at Home", "Tasting coffee like a pro.",
     "Cupping standardises brewing so you can compare beans side by side."),
]


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
    args = p.parse_args()
    hub, target = args.hub.rstrip("/"), args.target.rstrip("/")

    for slug, title, summary, body in PAGES:
        print(f"[sitemapredirect] {slug}")
        created = post(f"{target}/api/pages", json={
            "slug": slug, "title": title, "summary": summary, "body": body})
        if not created:
            continue
        reg = post(f"{hub}/submit", json={
            "url": created["url"], "bucket": "sitemapredirect",
            "title": title, "summary": summary})
        if reg:
            print(f"  registered -> {reg['redirect_url']} (in sitemap-redirects.xml)")

    print(f"\nseeded. SUBMIT {hub}/sitemap-redirects.xml in Search Console "
          "(ozymandias.space) so Google polls it.")


if __name__ == "__main__":
    main()
