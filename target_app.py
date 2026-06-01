"""Target-domain app (e.g. coffeeclubguide.site).

Its ONLY job: host content pages at /<slug> so they have a real, crawlable
URL. The pages are the things we're trying to get indexed.

Deliberately has NO sitemap, NO feed, and the homepage does NOT link to the
test pages. The target domain must have *no discovery path of its own* — the
only way Google can reach a page is via the hub/feed on the OTHER domain
(ozymandias.space). That's what makes the 'control' bucket a real baseline:
a page nobody links to should stay unindexed.

Separate SQLite, hard-coded API key. POC only. Runs on port 5001 so it can
share a box with the hub app (port 5000).
"""
import os
import re
import sqlite3
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort, render_template_string

API_KEY = "poc-secret-key-change-me"
DB_PATH = os.path.join(os.path.dirname(__file__), "target.db")
# public URL of THIS app — must be the target domain in production
BASE_URL = os.environ.get("TARGET_BASE_URL", "http://localhost:5001").rstrip("/")

# paths that must not be claimed as page slugs
RESERVED = {"api", "favicon.ico", "robots.txt"}

app = Flask(__name__)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                slug       TEXT NOT NULL UNIQUE,
                title      TEXT,
                summary    TEXT,
                body       TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def require_key():
    if request.headers.get("X-API-Key") != API_KEY:
        abort(401, "bad or missing X-API-Key")


# --- API: create pages ------------------------------------------------------
@app.post("/api/pages")
def create_page():
    """Create a page. Body: {slug, title?, summary?, body?}.

    Returns the absolute URL, which you then register with the hub app
    (per bucket) to expose it to the indexing mechanisms.
    """
    require_key()
    data = request.get_json(force=True, silent=True) or {}
    slug = re.sub(r"[^a-z0-9-]", "", (data.get("slug") or "").strip().lower())
    if not slug or slug in RESERVED:
        abort(400, "valid slug required (a-z0-9- only, not reserved)")

    with db() as conn:
        if conn.execute("SELECT 1 FROM pages WHERE slug = ?", (slug,)).fetchone():
            abort(409, "slug already exists")
        conn.execute(
            "INSERT INTO pages (slug, title, summary, body, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (slug, data.get("title"), data.get("summary"),
             data.get("body"), utcnow()),
        )
    return jsonify({"ok": True, "slug": slug, "url": f"{BASE_URL}/{slug}"}), 201


@app.get("/api/pages")
def list_pages():
    require_key()
    with db() as conn:
        rows = conn.execute("SELECT * FROM pages ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


# --- crawlable page surface -------------------------------------------------
PAGE_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ p['title'] or p['slug'] }}</title>
<meta name="description" content="{{ p['summary'] or '' }}"></head><body>
<article>
<h1>{{ p['title'] or p['slug'] }}</h1>
<p>{{ p['body'] or p['summary'] or 'A page worth indexing.' }}</p>
</article>
</body></html>"""

# Homepage intentionally links to NOTHING — keeps test pages orphaned so the
# only discovery path is the external hub. Do not add a page list here.
HOME_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<title>Coffee Club Guide</title></head><body>
<h1>Coffee Club Guide</h1>
<p>Guides and notes for coffee enthusiasts.</p>
</body></html>"""


@app.get("/")
def home():
    return HOME_HTML


@app.get("/<slug>")
def page(slug):
    if slug in RESERVED:
        abort(404)
    with db() as conn:
        p = conn.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone()
    if not p:
        abort(404)
    return render_template_string(PAGE_HTML, p=p)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
