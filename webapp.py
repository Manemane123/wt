#!/usr/bin/env python3
"""Winning Team affiliate website - Flask app served alongside the Telegram bot.

- Reads products from the same inventory.db the bot writes to.
- Password-gated (session-based). The password rotates daily at midnight
  America/Chicago (Dallas). The current password is written to
  password.json by password_manager.py, which the bot's scheduler calls.
- Proxies Telegram media through /media/<file_id> so the bot token
  never appears in HTML.
"""

import os
import io
import json
import sqlite3
import urllib.request
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    send_file, abort, Response,
)

from password_manager import (
    get_current_password,
    get_password_url,
    SITE_URL,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "6422629080:AAESCucEB-w_64J4smXaKYHXs6kV-Lx1tVA")
CHANNEL_ID = "1192930889"
DM_LINK = "https://t.me/WT710"
DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")

CATEGORY_META = {
    "flower":       {"name": "Flower",       "emoji": "🌸"},
    "concentrate":  {"name": "Concentrate",  "emoji": "🧪"},
    "dispos":       {"name": "Dispos",       "emoji": "💨"},
    "edibles":      {"name": "Edibles",      "emoji": "🍪"},
    "psychedelic":  {"name": "Psychedelics", "emoji": "🌀"},
}

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "winning-team-change-me-please")


# ---------- helpers ------------------------------------------------------

def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


CAT_ALIASES = {
    "flowers": "flower", "bud": "flower",
    "concentrates": "concentrate", "wax": "concentrate",
    "dispo": "dispos", "disposables": "dispos", "carts": "dispos",
    "edible": "edibles",
    "psychedelics": "psychedelic", "psych": "psychedelic",
}


def _norm_cat(raw):
    """Normalize DB category values to CATEGORY_META keys."""
    key = (raw or "").strip().lower().replace(" ", "").replace("-", "")
    return CAT_ALIASES.get(key, key)


def _row_to_product(r):
    msg_id = r["msg_id"]
    channel_link = (
        f"https://t.me/c/{CHANNEL_ID}/{msg_id}" if msg_id else None
    )
    return {
        "id": r["id"],
        "name": r["name"],
        "description": r["description"] or "",
        "cat": _norm_cat(r["cat"]),
        "media_type": r["media_type"],
        "media_id": r["media_id"],
        "channel_link": channel_link,
    }


def _all_products_grouped():
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM products ORDER BY cat, name"
        ).fetchall()
    grouped = {}
    for r in rows:
        p = _row_to_product(r)
        meta = CATEGORY_META.get(p["cat"], {"name": p["cat"].title(), "emoji": "📦"})
        bucket = grouped.setdefault(p["cat"], {
            "name": meta["name"],
            "emoji": meta["emoji"],
            "products": [],
        })
        bucket["products"].append(p)
    return grouped


def _logo_exists():
    return os.path.exists(
        os.path.join(app.root_path, "static", "images", "logo.jpg")
    )


def _common_ctx():
    return {
        "current_password": get_current_password(),
        "password_url": get_password_url(),
        "dm_link": DM_LINK,
        "logo_exists": _logo_exists(),
        "current_time": datetime.now().strftime("%b %d, %Y %I:%M %p"),
        "bot_token": BOT_TOKEN,  # legacy; templates use /media/ now
    }


def _authed():
    return session.get("authed") is True and \
        session.get("password") == get_current_password()


# ---------- routes -------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def login():
    if _authed():
        return redirect(url_for("categories"))
    error = None
    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        current = get_current_password()
        # Accept with or without dashes.
        if pw.replace("-", "") == current.replace("-", ""):
            session["authed"] = True
            session["password"] = current
            return redirect(url_for("categories"))
        error = "Incorrect password. Passwords rotate daily."
    return render_template(
        "login.html",
        error=error,
        password_url=get_password_url(),
        logo_exists=_logo_exists(),
    )


@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


def _categories_list():
    """Return a list of category dicts for categories.html.

    categories.html iterates a LIST and reads cat.key / cat.name /
    cat.emoji / cat.count, so a dict keyed by cat slug must not be passed
    here (that yields plain strings and breaks the links + counts).
    """
    grouped = _all_products_grouped()
    items = []
    seen = set()
    for key, meta in CATEGORY_META.items():
        bucket = grouped.get(key)
        seen.add(key)
        items.append({
            "key": key,
            "name": meta["name"],
            "emoji": meta["emoji"],
            "count": len(bucket["products"]) if bucket else 0,
        })
    # any category present in the DB that isn't in CATEGORY_META
    for key, bucket in grouped.items():
        if key in seen:
            continue
        items.append({
            "key": key,
            "name": bucket["name"],
            "emoji": bucket["emoji"],
            "count": len(bucket["products"]),
        })
    return items


@app.route("/categories")
def categories():
    if not _authed():
        return redirect(url_for("login"))
    return render_template(
        "categories.html",
        categories=_categories_list(),
        **_common_ctx(),
    )


@app.route("/category/<cat_key>")
def category(cat_key):
    if not _authed():
        return redirect(url_for("login"))
    grouped = _all_products_grouped()
    cat = grouped.get(cat_key)
    if not cat:
        meta = CATEGORY_META.get(cat_key, {"name": cat_key.title(), "emoji": "📦"})
        cat = {"name": meta["name"], "emoji": meta["emoji"], "products": []}
    return render_template(
        "category.html",
        category=cat,
        cat_key=cat_key,
        **_common_ctx(),
    )


@app.route("/product/<cat_key>/<int:product_id>")
def product_detail(cat_key, product_id):
    if not _authed():
        return redirect(url_for("login"))
    with _conn() as c:
        r = c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not r:
        abort(404)
    p = _row_to_product(r)
    meta = CATEGORY_META.get(p["cat"], {"name": p["cat"].title(), "emoji": "📦"})
    return render_template(
        "product_detail.html",
        product=p,
        category={"name": meta["name"], "emoji": meta["emoji"]},
        cat_key=cat_key,
        **_common_ctx(),
    )


# ---------- feed for the index page (kept for compatibility) -------------

@app.route("/home")
def index():
    if not _authed():
        return redirect(url_for("login"))
    return render_template(
        "index.html",
        categories=_all_products_grouped(),
        **_common_ctx(),
    )


# ---------- Telegram media proxy ----------------------------------------

_media_cache = {}  # file_id -> (bytes, content_type)
_MAX_CACHE_BYTES = 8 * 1024 * 1024

_EXT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
}


def _ctype_for(file_path, fallback):
    ext = os.path.splitext(file_path or "")[1].lower()
    if ext in _EXT_TYPES:
        return _EXT_TYPES[ext]
    if not fallback or fallback == "application/octet-stream":
        return "video/mp4" if ext else "application/octet-stream"
    return fallback


def _telegram_get_file(file_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    if not data.get("ok"):
        print(f"[media] getFile not ok: {data}")
        return None
    return data["result"].get("file_path")


def _telegram_download(file_path):
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    req = urllib.request.Request(url, headers={"User-Agent": "winning-team-site"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


@app.route("/media/<path:file_id>")
def media(file_id):
    """Proxy Telegram media (photo / video / animated GIF).

    Telegram stores animations (GIFs) as MP4 files, so the browser must load
    them in a <video> element, not <img>. The correct Content-Type is derived
    from the Telegram file path extension so both work.
    """
    if not _authed():
        abort(403)

    cached = _media_cache.get(file_id)
    if cached:
        blob, ctype = cached
        resp = Response(blob, mimetype=ctype)
        resp.headers["Cache-Control"] = "private, max-age=86400"
        resp.headers["Accept-Ranges"] = "none"
        return resp

    try:
        path = _telegram_get_file(file_id)
        if not path:
            abort(404)
        blob, raw_ctype = _telegram_download(path)
        ctype = _ctype_for(path, raw_ctype)
        if len(blob) <= _MAX_CACHE_BYTES:
            if sum(len(v[0]) for v in _media_cache.values()) > 128 * 1024 * 1024:
                _media_cache.clear()
            _media_cache[file_id] = (blob, ctype)
        resp = Response(blob, mimetype=ctype)
        resp.headers["Cache-Control"] = "private, max-age=86400"
        resp.headers["Content-Length"] = str(len(blob))
        return resp
    except Exception as e:
        print(f"[media] error for {file_id}: {e}")
        abort(404)


@app.route("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
