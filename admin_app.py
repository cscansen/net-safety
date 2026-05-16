"""
Kid proxy admin web interface.
Binds to 0.0.0.0:9090 — reachable from any LAN device via http://<hostname>.local:9090
(mDNS via avahi-daemon). Accessible from the kid's browser via Firefox proxy passthrough.
"""

import json
import os
import re
import sys
import time as _time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import bcrypt
from flask import Flask, redirect, render_template, request, session, url_for

sys.path.insert(0, "/opt/kid-proxy")
import db

app = Flask(__name__, template_folder="/opt/kid-proxy/templates")
app.secret_key = os.environ["FLASK_SECRET"]
ADMIN_HOSTNAME = os.environ.get("ADMIN_HOSTNAME", "localhost")
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)


def _require_auth():
    if not session.get("admin_username"):
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


def _hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    if not session.get("admin_username"):
        return redirect(url_for("login"))
    return redirect(url_for("review"))


@app.route("/login", methods=["GET", "POST"])
def login():
    # Run migration once on first login attempt
    db.migrate_legacy_admin()
    error = False
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username and db.check_admin_password(username, password):
            session.permanent = True
            session["admin_username"] = username
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
        status = r["status"]  # 1=approved, 0=denied, -1=outstanding
        domains.append({
            "domain":              r["domain"],
            "attempts":            r["attempt_count"],
            "last_seen":           _fmt_age(r["last_attempted"]),
            "approved":            status == 1,
            "denied":              status == 0,
            "daily_limit":         r["daily_limit_minutes"],
            "weekly_limit":        r["weekly_limit_minutes"],
            "used_today":          round(r["minutes_used_today"], 1),
            "used_week":           round(r["minutes_used_week"], 1),
            "approved_by":         r["approved_by"] or "—",
            "approved_at":         _fmt_age(r["approved_at"]),
            "is_admin":            False,
        })

    for r in db.get_admin_only_domains():
        domains.append({
            "domain":    r["domain"],
            "attempts":  0,
            "last_seen": "—",
            "approved":  True,
            "denied":    False,
            "daily_limit":  r["daily_limit_minutes"],
            "weekly_limit": r["weekly_limit_minutes"],
            "used_today":   round(r["minutes_used_today"], 1),
            "used_week":    round(r["minutes_used_week"], 1),
            "approved_by":  "—",
            "approved_at":  "—",
            "is_admin":     True,
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

    timed = [d for d in domains
             if d["approved"] and d["daily_limit"] is not None
             and d["used_today"] >= d["daily_limit"]]

    return render_template("review.html", domains=domains, timed=timed,
                           bypass_active=bypass_active,
                           bypass_remaining=bypass_remaining,
                           current_user=session["admin_username"],
                           admin_hostname=ADMIN_HOSTNAME)


@app.post("/apply")
def apply():
    redir = _require_auth()
    if redir:
        return redir

    approved: dict[str, int | None] = {}
    form = request.form

    for key in form:
        if not key.startswith("allow_"):
            continue
        domain = key[len("allow_"):]
        def _parse_limit(val, default=db.DEFAULT_LIMIT_MINUTES):
            try:
                return max(1, int(val.strip())) if val.strip() else None
            except (ValueError, TypeError):
                return default
        daily  = _parse_limit(form.get(f"daily_{domain}",  ""))
        weekly = _parse_limit(form.get(f"weekly_{domain}", ""), default=None)
        approved[domain] = (daily, weekly)

    db.apply_parent_review(approved, approved_by=session["admin_username"])
    return redirect(url_for("review"))


@app.post("/extend")
def extend():
    redir = _require_auth()
    if redir:
        return redir
    domain = request.form.get("domain", "").strip()
    try:
        minutes = int(request.form.get("minutes", 0))
    except (ValueError, TypeError):
        minutes = 0
    if domain and minutes in (15, 30):
        db.extend_daily_limit(domain, minutes)
    return redirect(url_for("review"))


@app.post("/delete")
def delete_domain():
    redir = _require_auth()
    if redir:
        return redir
    domain = request.form.get("domain", "").strip()
    if domain:
        db.delete_domain(domain)
    return redirect(url_for("review"))


@app.get("/describe/<domain>")
def describe(domain):
    redir = _require_auth()
    if redir:
        return {"description": ""}

    cached = db.get_cached_description(domain)
    if cached is not None:
        return {"description": cached}

    description = ""
    try:
        q = urllib.parse.quote(domain)
        url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "net-safety/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        text = data.get("AbstractText") or data.get("Abstract") or ""
        if text:
            sentences = re.split(r"(?<=[.!?])\s+", text.strip())
            description = " ".join(sentences[:3])
    except Exception:
        pass

    db.cache_description(domain, description)
    return {"description": description}


@app.post("/clear-all")
def clear_all():
    redir = _require_auth()
    if redir:
        return redir
    if session.get("admin_username") != "admin":
        return redirect(url_for("review"))
    db.clear_all()
    return redirect(url_for("review"))


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


# ── account management ────────────────────────────────────────────────────────

@app.get("/accounts")
def accounts():
    redir = _require_auth()
    if redir:
        return redir
    admins = [dict(r) for r in db.list_admins()]
    return render_template("accounts.html",
                           admins=admins,
                           current_user=session["admin_username"])


@app.post("/accounts/add")
def accounts_add():
    redir = _require_auth()
    if redir:
        return redir
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    error = None
    if not username:
        error = "Username is required."
    elif not password:
        error = "Password is required."
    else:
        try:
            db.add_admin(username, _hash_password(password))
        except Exception:
            error = f"Username '{username}' already exists."
    if error:
        admins = [dict(r) for r in db.list_admins()]
        return render_template("accounts.html", admins=admins,
                               current_user=session["admin_username"],
                               add_error=error)
    return redirect(url_for("accounts"))


@app.post("/accounts/change-password")
def accounts_change_password():
    redir = _require_auth()
    if redir:
        return redir
    username = request.form.get("username", "").strip()
    current_pw = request.form.get("current_password", "")
    new_pw = request.form.get("new_password", "")
    error = None
    if not db.check_admin_password(username, current_pw):
        error = "Current password is incorrect."
    elif len(new_pw) < 1:
        error = "New password cannot be empty."
    else:
        db.update_admin_password(username, _hash_password(new_pw))
    admins = [dict(r) for r in db.list_admins()]
    return render_template("accounts.html", admins=admins,
                           current_user=session["admin_username"],
                           pw_error=error,
                           pw_changed=(error is None),
                           pw_username=username)


@app.post("/accounts/delete")
def accounts_delete():
    redir = _require_auth()
    if redir:
        return redir
    username = request.form.get("username", "").strip()
    error = None
    if username == session["admin_username"]:
        error = "You cannot delete your own account."
    elif db.admin_count() <= 1:
        error = "Cannot delete the last admin account."
    else:
        db.delete_admin(username)
    if error:
        admins = [dict(r) for r in db.list_admins()]
        return render_template("accounts.html", admins=admins,
                               current_user=session["admin_username"],
                               del_error=error)
    return redirect(url_for("accounts"))


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    db.migrate_legacy_admin()
    app.run(host="0.0.0.0", port=9090, debug=False)
