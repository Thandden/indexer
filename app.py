"""Minimal indexer POC.

Renders crawlable hub pages + sitemap + Atom/WebSub feed from a list of
submitted target URLs. A helper script POSTs URLs to /submit; Googlebot
crawls the hub pages and (hopefully) discovers the target URLs.

Single domain, single rolling hub, SQLite, hard-coded API key. POC only.
"""
import os
import sqlite3
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort, Response, render_template_string

# --- config (hard-coded for POC ease; do NOT ship this) ---------------------
API_KEY = "poc-secret-key-change-me"
DB_PATH = os.path.join(os.path.dirname(__file__), "indexer.db")
HUB_SIZE = 25          # links per hub page before sealing and rolling to a new one
FEED_ITEMS = 30        # most-recent URLs shown in the feed
WEBSUB_HUB = "https://pubsubhubbub.appspot.com/"
# BASE_URL is where THIS app is publicly reachable (your domain). Used to build
# absolute URLs in sitemap/feed. Override via env in production.
BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")

# valid experiment buckets — decide which mechanisms a URL is exposed to
BUCKETS = {"control", "websub", "hub", "both"}

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
                title        TEXT,
                summary      TEXT,
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

    bucket controls exposure so the same app runs the A-D experiment:
      control = recorded only, never linked or pinged (baseline)
      websub  = appears in feed only (WebSub nudge, no durable link)
      hub     = linked from a hub page only (durable, no ping)
      both    = linked AND in feed (the real T+0 combo)
    """
    require_key()
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        abort(400, "url must be absolute http(s)")
    bucket = (data.get("bucket") or "both").strip().lower()
    if bucket not in BUCKETS:
        abort(400, f"bucket must be one of {sorted(BUCKETS)}")

    with db() as conn:
        if conn.execute("SELECT 1 FROM urls WHERE url = ?", (url,)).fetchone():
            abort(409, "url already submitted")
        # only bucket gets a durable hub link
        hub_id = next_hub_id(conn) if bucket in ("hub", "both") else None
        conn.execute(
            "INSERT INTO urls (url, title, summary, bucket, hub_id, submitted_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (url, data.get("title"), data.get("summary"), bucket, hub_id, utcnow()),
        )
    return jsonify({"ok": True, "url": url, "bucket": bucket, "hub_id": hub_id}), 201


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


@app.get("/sitemap.xml")
def sitemap():
    with db() as conn:
        xml = render_template_string(SITEMAP_XML, base=BASE_URL, hubs=hub_ids(conn))
    return Response(xml, mimetype="application/xml")


@app.get("/feed.xml")
def feed():
    # feed carries 'websub' and 'both' buckets (the URLs meant to get a ping)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM urls WHERE bucket IN ('websub', 'both') "
            "ORDER BY id DESC LIMIT ?", (FEED_ITEMS,)
        ).fetchall()
    xml = render_template_string(
        FEED_XML, base=BASE_URL, websub=WEBSUB_HUB, updated=utcnow(), rows=rows
    )
    return Response(xml, mimetype="application/atom+xml")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
