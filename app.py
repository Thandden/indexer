"""Minimal indexer POC.

Renders crawlable hub pages + sitemap + Atom/WebSub feed from a list of
submitted target URLs. A helper script POSTs URLs to /submit; Googlebot
crawls the hub pages and (hopefully) discovers the target URLs.

Two ways to supply targets:
  - /submit       : register an EXTERNAL url (target lives on another domain)
  - /new-target   : MINT a target page on THIS domain (served at /t/<slug>),
                    so a single-domain test needs no second site.

Single domain, single rolling hub, SQLite, hard-coded API key. POC only.
"""
import os
import re
import sqlite3
from datetime import datetime, timezone
from flask import (Flask, request, jsonify, abort, Response, redirect,
                   render_template_string)

# --- config (hard-coded for POC ease; do NOT ship this) ---------------------
API_KEY = "poc-secret-key-change-me"
DB_PATH = os.path.join(os.path.dirname(__file__), "indexer.db")
HUB_SIZE = 25          # links per hub page before sealing and rolling to a new one
FEED_ITEMS = 30        # most-recent URLs shown in the feed
WEBSUB_HUB = "https://pubsubhubbub.appspot.com/"
# BASE_URL is where THIS app is publicly reachable (your domain). Used to build
# absolute URLs in sitemap/feed. Override via env in production.
BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")

# A bucket is a combination of methods, canonical form: methods sorted and
# joined by '+', or 'control' for none. The app applies hub + websub +
# sitemapredirect. 'apiredirect' = seed.py pings the Indexing API at THIS app's
# /r/<id> redirector (which we own), 301-ing to the target.
# 'sitemapredirect' = the same /r/<id> redirector is listed in a polled
# sitemap (/sitemap-redirects.xml) with an honest set-once lastmod, so Google
# discovers it passively via sitemap re-reads (gated by domain crawl budget).
METHODS = {"hub", "websub", "apiredirect", "sitemapredirect"}


def bucket_methods(bucket):
    if bucket == "control":
        return set()
    return set(bucket.split("+"))


def valid_bucket(bucket):
    return bucket == "control" or bucket_methods(bucket) <= METHODS

app = Flask(__name__)


# --- db ---------------------------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS urls (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT NOT NULL UNIQUE,
                slug         TEXT UNIQUE,         -- set when target is hosted on THIS domain (/t/<slug>)
                title        TEXT,
                summary      TEXT,
                body         TEXT,               -- page content for locally-hosted targets
                bucket       TEXT NOT NULL DEFAULT 'both',
                hub_id       INTEGER,            -- NULL for control/websub-only (not linked)
                submitted_at TEXT NOT NULL,
                crawled_at   TEXT,               -- filled by checker.py
                indexed_at   TEXT,               -- filled by checker.py
                state        TEXT                -- last coverageState from URL Inspection
            )
            """
        )


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def next_hub_id(conn):
    """Current open hub, or a new one once the latest is full (cap-and-roll)."""
    row = conn.execute(
        "SELECT hub_id, COUNT(*) AS n FROM urls WHERE hub_id IS NOT NULL "
        "GROUP BY hub_id ORDER BY hub_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return 1
    return row["hub_id"] if row["n"] < HUB_SIZE else row["hub_id"] + 1


# --- auth -------------------------------------------------------------------
def require_key():
    if request.headers.get("X-API-Key") != API_KEY:
        abort(401, "bad or missing X-API-Key")


# --- API --------------------------------------------------------------------
@app.post("/submit")
def submit():
    """Register a target URL. Body: {url, title?, summary?, bucket?}.

    bucket is a '+'-joined combo of methods (or 'control'). This app applies
    the 'hub' and 'websub' methods; 'api' is fired by seed.py but recorded here
    so the checker tracks it. Examples:
      control            -> recorded only, never linked/fed (baseline)
      hub                -> hub link only
      websub             -> feed only
      hub+websub+api     -> linked, fed, and API-pinged
    """
    require_key()
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        abort(400, "url must be absolute http(s)")
    bucket = (data.get("bucket") or "control").strip().lower()
    if not valid_bucket(bucket):
        abort(400, f"bucket methods must be subset of {sorted(METHODS)} or 'control'")
    methods = bucket_methods(bucket)

    with db() as conn:
        if conn.execute("SELECT 1 FROM urls WHERE url = ?", (url,)).fetchone():
            abort(409, "url already submitted")
        # only 'hub' method gets a durable hub link
        hub_id = next_hub_id(conn) if "hub" in methods else None
        cur = conn.execute(
            "INSERT INTO urls (url, title, summary, bucket, hub_id, submitted_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (url, data.get("title"), data.get("summary"), bucket, hub_id, utcnow()),
        )
        row_id = cur.lastrowid
    redirect_url = f"{BASE_URL}/r/{row_id}"
    return jsonify({"ok": True, "id": row_id, "url": url, "bucket": bucket,
                    "hub_id": hub_id, "redirect_url": redirect_url}), 201


@app.post("/new-target")
def new_target():
    """Mint a target page hosted on THIS domain, served at /t/<slug>.

    Body: {slug, title?, summary?, body?, bucket?}. Lets a single-domain test
    run without a second site: the app both hosts the target AND links/feeds it.
    The stored url is BASE_URL/t/<slug>, so it flows through hubs/feed/checker
    exactly like an external url.
    """
    require_key()
    data = request.get_json(force=True, silent=True) or {}
    slug = re.sub(r"[^a-z0-9-]", "", (data.get("slug") or "").strip().lower())
    if not slug:
        abort(400, "slug required (a-z0-9- only)")
    bucket = (data.get("bucket") or "control").strip().lower()
    if not valid_bucket(bucket):
        abort(400, f"bucket methods must be subset of {sorted(METHODS)} or 'control'")
    url = f"{BASE_URL}/t/{slug}"

    with db() as conn:
        if conn.execute("SELECT 1 FROM urls WHERE slug = ? OR url = ?",
                        (slug, url)).fetchone():
            abort(409, "slug/url already exists")
        hub_id = next_hub_id(conn) if "hub" in bucket_methods(bucket) else None
        conn.execute(
            "INSERT INTO urls (url, slug, title, summary, body, bucket, hub_id, "
            "submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (url, slug, data.get("title"), data.get("summary"),
             data.get("body"), bucket, hub_id, utcnow()),
        )
    return jsonify({"ok": True, "url": url, "slug": slug,
                    "bucket": bucket, "hub_id": hub_id}), 201


@app.get("/urls")
def list_urls():
    """Inspect current state (used by checker.py and for eyeballing)."""
    require_key()
    with db() as conn:
        rows = conn.execute("SELECT * FROM urls ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


# --- crawlable surfaces -----------------------------------------------------
INDEX_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<title>Notes & Links</title></head><body>
<h1>Notes & Links</h1>
<p>A small collection of pages worth a look.</p>
<ul>
{% for h in hubs %}<li><a href="{{ base }}/hub/{{ h }}">Collection {{ h }}</a></li>
{% endfor %}</ul></body></html>"""

HUB_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<title>Collection {{ hub_id }}</title></head><body>
<h1>Collection {{ hub_id }}</h1>
{% for r in rows %}
<article>
  <h2><a href="{{ r['url'] }}">{{ r['title'] or r['url'] }}</a></h2>
  <p>{{ r['summary'] or 'A useful resource worth reading.' }}</p>
</article>
{% endfor %}
</body></html>"""

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{{ base }}/</loc></url>
{% for h in hubs %}<url><loc>{{ base }}/hub/{{ h }}</loc></url>
{% endfor %}</urlset>"""

# Redirect sitemap: lists /r/<id> for sitemapredirect-method URLs. Each <loc>
# is a redirect we own; lastmod = the row's creation time, set ONCE and never
# re-dated (honest — a redirect never changes). The sitemap file's own change
# (a new <url> appended) is what Google notices on re-read.
SITEMAP_REDIRECTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{% for r in rows %}<url><loc>{{ base }}/r/{{ r['id'] }}</loc><lastmod>{{ r['submitted_at'] }}</lastmod></url>
{% endfor %}</urlset>"""

FEED_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Notes &amp; Links</title>
<link rel="self" href="{{ base }}/feed.xml"/>
<link rel="hub" href="{{ websub }}"/>
<id>{{ base }}/feed.xml</id>
<updated>{{ updated }}</updated>
{% for r in rows %}<entry>
<title>{{ r['title'] or r['url'] }}</title>
<link href="{{ r['url'] }}"/>
<id>{{ r['url'] }}</id>
<updated>{{ r['submitted_at'] }}</updated>
<summary>{{ r['summary'] or 'A useful resource worth reading.' }}</summary>
</entry>
{% endfor %}</feed>"""


def hub_ids(conn):
    return [r["hub_id"] for r in conn.execute(
        "SELECT DISTINCT hub_id FROM urls WHERE hub_id IS NOT NULL ORDER BY hub_id"
    ).fetchall()]


@app.get("/")
def index():
    with db() as conn:
        return render_template_string(INDEX_HTML, base=BASE_URL, hubs=hub_ids(conn))


@app.get("/hub/<int:hub_id>")
def hub(hub_id):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM urls WHERE hub_id = ? ORDER BY id", (hub_id,)
        ).fetchall()
    if not rows:
        abort(404)
    return render_template_string(HUB_HTML, hub_id=hub_id, rows=rows)


TARGET_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<title>{{ r['title'] or r['slug'] }}</title>
<meta name="description" content="{{ r['summary'] or '' }}"></head><body>
<article>
<h1>{{ r['title'] or r['slug'] }}</h1>
<p>{{ r['body'] or r['summary'] or 'A page worth indexing.' }}</p>
</article>
</body></html>"""


@app.get("/t/<slug>")
def target(slug):
    """Serve a target page hosted on this domain (minted via /new-target)."""
    with db() as conn:
        r = conn.execute("SELECT * FROM urls WHERE slug = ?", (slug,)).fetchone()
    if not r:
        abort(404)
    return render_template_string(TARGET_HTML, r=r)


@app.get("/r/<int:row_id>")
def redirector(row_id):
    """301 to the target URL. We own this domain, so the Indexing API may be
    pinged here; the redirect carries the crawl to a target we don't own."""
    with db() as conn:
        r = conn.execute("SELECT url FROM urls WHERE id = ?", (row_id,)).fetchone()
    if not r:
        abort(404)
    return redirect(r["url"], code=301)


@app.get("/sitemap.xml")
def sitemap():
    with db() as conn:
        xml = render_template_string(SITEMAP_XML, base=BASE_URL, hubs=hub_ids(conn))
    return Response(xml, mimetype="application/xml")


@app.get("/sitemap-redirects.xml")
def sitemap_redirects():
    """Polled sitemap of /r/<id> redirects for the sitemapredirect method."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, submitted_at FROM urls "
            "WHERE bucket = 'sitemapredirect' OR bucket LIKE '%sitemapredirect%' "
            "ORDER BY id"
        ).fetchall()
    xml = render_template_string(SITEMAP_REDIRECTS_XML, base=BASE_URL, rows=rows)
    return Response(xml, mimetype="application/xml")


@app.get("/feed.xml")
def feed():
    # feed carries any bucket whose methods include 'websub'
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM urls WHERE bucket = 'websub' OR bucket LIKE '%websub%' "
            "ORDER BY id DESC LIMIT ?", (FEED_ITEMS,)
        ).fetchall()
    xml = render_template_string(
        FEED_XML, base=BASE_URL, websub=WEBSUB_HUB, updated=utcnow(), rows=rows
    )
    return Response(xml, mimetype="application/atom+xml")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
