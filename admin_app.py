"""
Kid proxy admin web interface.
Runs on localhost:9090. Accessible from the kid's browser via Firefox proxy passthrough.
"""

import os
import sys
import time as _time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import bcrypt
from flask import Flask, redirect, render_template, request, session, url_for

sys.path.insert(0, "/opt/kid-proxy")
import db

app = Flask(__name__, template_folder="/opt/kid-proxy/templates")
app.secret_key = os.environ["FLASK_SECRET"]
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)

ADMIN_HASH_FILE = "/etc/kid-proxy/admin.hash"


def _check_password(pw: str) -> bool:
    try:
        stored = Path(ADMIN_HASH_FILE).read_bytes().strip()
        return bcrypt.checkpw(pw.encode(), stored)
    except Exception:
        return False


def _require_auth():
    if not session.get("authenticated"):
        return redirect(url_for("login"))


def _fmt_age(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return ts


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    return redirect(url_for("review"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = False
    if request.method == "POST":
        if _check_password(request.form.get("password", "")):
            session.permanent = True
            session["authenticated"] = True
            return redirect(url_for("review"))
        error = True
    return render_template("login.html", error=error)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/review")
def review():
    redir = _require_auth()
    if redir:
        return redir

    rows = db.get_review_data()
    domains = []
    for r in rows:
        domains.append({
            "domain":        r["domain"],
            "attempts":      r["attempt_count"],
            "last_seen":     _fmt_age(r["last_attempted"]),
            "approved":      bool(r["is_approved"]),
            "limit_minutes": r["daily_limit_minutes"],
            "used_minutes":  round(r["minutes_used_today"], 1),
        })

    bypass_until = db.get_bypass_until()
    now = _time.time()
    if bypass_until is None or (bypass_until != float("inf") and bypass_until <= now):
        bypass_active = False
        bypass_remaining = None
    elif bypass_until == float("inf"):
        bypass_active = True
        bypass_remaining = None
    else:
        bypass_active = True
        bypass_remaining = int(bypass_until - now)

    return render_template("review.html", domains=domains,
                           bypass_active=bypass_active,
                           bypass_remaining=bypass_remaining)


@app.post("/bypass")
def bypass():
    redir = _require_auth()
    if redir:
        return redir
    action = request.form.get("action", "off")
    if action == "off":
        db.set_bypass(None)
    elif action == "indefinite":
        db.set_bypass(float("inf"))
    else:
        try:
            hours = float(action)
            db.set_bypass(_time.time() + hours * 3600)
        except ValueError:
            db.set_bypass(None)
    return redirect(url_for("review"))


@app.post("/apply")
def apply():
    redir = _require_auth()
    if redir:
        return redir

    # Build {domain: limit_minutes | None} for every checked domain
    approved: dict[str, int | None] = {}
    form = request.form

    for key in form:
        if not key.startswith("allow_"):
            continue
        domain = key[len("allow_"):]
        raw_limit = form.get(f"limit_{domain}", "").strip()
        try:
            limit = max(1, int(raw_limit))
        except (ValueError, TypeError):
            limit = db.DEFAULT_LIMIT_MINUTES
        approved[domain] = limit

    db.apply_parent_review(approved)
    return redirect(url_for("review"))


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    app.run(host="127.0.0.1", port=9090, debug=False)
