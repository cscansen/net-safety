"""
Kid filtering proxy addon for mitmproxy.

Checks each request against the SQLite whitelist.  Blocked domains get a
friendly block page.  Approved domains with a daily time limit are tracked via
an in-memory activity-window approach and get a "Time's Up" page when the
budget is exhausted.
"""

import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, "/opt/kid-proxy")

import db
from mitmproxy import http

# ── constants ────────────────────────────────────────────────────────────────

ADMIN_URL = "http://localhost:9090"
ALWAYS_ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
CACHE_TTL = 5          # seconds between whitelist DB reads
IDLE_TIMEOUT = 60      # seconds of inactivity before a session is considered ended

# ── state ────────────────────────────────────────────────────────────────────

_whitelist: dict[str, int | None] = {}   # domain -> daily_limit_minutes
_cache_ts: float = 0
_cache_lock = threading.Lock()

# bypass cache: (monotonic cache_ts, wall-clock bypass_until or None or inf)
_bypass_cache: tuple[float, float | None] = (0, None)
_bypass_lock = threading.Lock()
BYPASS_CACHE_TTL = 5

# {domain: (session_start, last_seen)}  — only for currently active sessions
_sessions: dict[str, tuple[float, float]] = {}
_sessions_lock = threading.Lock()

# ── helpers ──────────────────────────────────────────────────────────────────

def _check_bypass() -> bool:
    global _bypass_cache
    mono_now = time.monotonic()
    with _bypass_lock:
        cache_ts, bypass_until = _bypass_cache
        if mono_now - cache_ts > BYPASS_CACHE_TTL:
            bypass_until = db.get_bypass_until()
            _bypass_cache = (mono_now, bypass_until)
    if bypass_until is None:
        return False
    if bypass_until == float("inf"):
        return True
    return time.time() < bypass_until


def _refresh_whitelist():
    global _whitelist, _cache_ts
    with _cache_lock:
        if time.monotonic() - _cache_ts > CACHE_TTL:
            _whitelist = db.get_whitelist()
            _cache_ts = time.monotonic()


def _base_domain(host: str) -> str | None:
    """Return the matching whitelist domain for host, or None."""
    _refresh_whitelist()
    for domain in _whitelist:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def _flush_session(domain: str, now: float):
    """Close an active session and write duration to DB."""
    with _sessions_lock:
        if domain not in _sessions:
            return
        start, last = _sessions.pop(domain)
    db.log_session(domain, last - start)


def _record_activity(domain: str) -> float:
    """
    Mark activity for domain.  Returns total seconds used today
    (DB + current session) so the caller can check against the limit.
    """
    now = time.monotonic()
    with _sessions_lock:
        if domain in _sessions:
            start, last = _sessions[domain]
            if now - last > IDLE_TIMEOUT:
                # Session lapsed; close it and start a new one
                _sessions[domain] = (now, now)
                db.log_session(domain, last - start)
            else:
                _sessions[domain] = (start, now)
        else:
            _sessions[domain] = (now, now)
        session_seconds = _sessions[domain][1] - _sessions[domain][0]

    db_seconds = db.get_today_db_seconds(domain)
    return db_seconds + session_seconds


# ── block pages ──────────────────────────────────────────────────────────────

def _page(title: str, icon: str, heading: str, body: str, button: bool = True) -> str:
    btn = f'<a class="btn" href="{ADMIN_URL}">🔒 Parent Review</a>' if button else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:#f0f4ff;min-height:100vh;display:flex;
        align-items:center;justify-content:center;padding:16px}}
  .card{{background:#fff;border-radius:20px;padding:40px 32px;max-width:420px;
         width:100%;text-align:center;box-shadow:0 4px 32px rgba(0,0,0,.08)}}
  .icon{{font-size:64px;margin-bottom:16px}}
  h2{{font-size:22px;color:#1a1a2e;margin-bottom:10px}}
  p{{color:#555;margin-bottom:24px;line-height:1.5}}
  .domain{{display:inline-block;background:#f5f5f7;border-radius:8px;
           padding:6px 14px;font-family:monospace;font-size:14px;
           margin-bottom:20px;color:#333}}
  .btn{{display:inline-block;background:#1a73e8;color:#fff;text-decoration:none;
        padding:12px 28px;border-radius:10px;font-size:15px;font-weight:600}}
  .btn:hover{{background:#155db2}}
</style>
</head>
<body>
<div class="card">
  <div class="icon">{icon}</div>
  <h2>{heading}</h2>
  <div class="domain">__DOMAIN__</div>
  <p>{body}</p>
  {btn}
</div>
</body>
</html>"""


BLOCKED_TMPL = _page(
    "Site Blocked", "🚫",
    "This site is blocked",
    "Ask a parent if you need to visit this site.",
)

TIMEOUT_TMPL = _page(
    "Time's Up!", "⏰",
    "Time's up for today!",
    "You've used up your time on this site. Ask a parent for more time.",
)


def _make_response(tmpl: str, domain: str, status: int = 403) -> http.Response:
    safe = domain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = tmpl.replace("__DOMAIN__", safe)
    return http.Response.make(status, body, {"Content-Type": "text/html; charset=utf-8"})


# ── addon ────────────────────────────────────────────────────────────────────

class KidFilter:
    def request(self, flow: http.HTTPFlow):
        host = flow.request.pretty_host

        if host in ALWAYS_ALLOWED_HOSTS:
            return

        if _check_bypass():
            return

        matched = _base_domain(host)

        if matched is None:
            # Not whitelisted — block and log
            db.log_blocked(host, flow.request.pretty_url)
            flow.response = _make_response(BLOCKED_TMPL, host)
            return

        limit = _whitelist.get(matched)
        if limit is not None:
            used_seconds = _record_activity(matched)
            if used_seconds >= limit * 60:
                flow.response = _make_response(TIMEOUT_TMPL, host)
                return
            # Activity already recorded inside _record_activity
        # else: no limit, just pass through (no session tracking needed)


addons = [KidFilter()]
