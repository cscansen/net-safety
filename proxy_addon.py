"""
Kid filtering proxy addon for mitmproxy.

Checks each request against the SQLite whitelist.  Blocked domains get a
friendly block page.  Approved domains with time limits are tracked and get
a "Time's Up" page when the budget is exhausted.  HTML responses for timed
domains get a floating countdown widget injected.
"""

import sys
import time
import threading

sys.path.insert(0, "/opt/kid-proxy")

import db
from mitmproxy import http

# ── constants ────────────────────────────────────────────────────────────────

ADMIN_URL = "http://localhost:9090"
ALWAYS_ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
CACHE_TTL = 5        # seconds between whitelist DB reads
IDLE_TIMEOUT = 60    # seconds of inactivity before session is considered ended
BYPASS_CACHE_TTL = 5

# ── state ────────────────────────────────────────────────────────────────────

# domain -> (daily_limit_minutes | None, weekly_limit_minutes | None)
_whitelist: dict[str, tuple[int | None, int | None]] = {}
_cache_ts: float = 0
_cache_lock = threading.Lock()

_bypass_cache: tuple[float, float | None] = (0, None)
_bypass_lock = threading.Lock()

# {domain: (session_start, last_seen)}
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
    _refresh_whitelist()
    for domain in _whitelist:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def _flush_session(domain: str):
    with _sessions_lock:
        if domain not in _sessions:
            return
        start, last = _sessions.pop(domain)
    db.log_session(domain, last - start)


def _record_activity(domain: str) -> tuple[float, float]:
    """
    Record activity and return (today_seconds_used, this_week_seconds_used).
    Both include the current in-memory session.
    """
    now = time.monotonic()
    with _sessions_lock:
        if domain in _sessions:
            start, last = _sessions[domain]
            if now - last > IDLE_TIMEOUT:
                _sessions[domain] = (now, now)
                db.log_session(domain, last - start)
            else:
                _sessions[domain] = (start, now)
        else:
            _sessions[domain] = (now, now)
        session_seconds = _sessions[domain][1] - _sessions[domain][0]

    today_db  = db.get_today_db_seconds(domain)
    week_db   = db.get_this_week_db_seconds(domain)
    return (today_db + session_seconds, week_db + session_seconds)


def _seconds_remaining(domain: str) -> int | None:
    """
    Return seconds remaining (min of daily and weekly), or None if no limits.
    Returns 0 if already over budget.
    """
    limits = _whitelist.get(domain)
    if limits is None:
        return None
    daily_limit, weekly_limit = limits
    if daily_limit is None and weekly_limit is None:
        return None

    today_used, week_used = _record_activity(domain)
    remaining = float("inf")
    if daily_limit is not None:
        remaining = min(remaining, daily_limit * 60 - today_used)
    if weekly_limit is not None:
        remaining = min(remaining, weekly_limit * 60 - week_used)
    return max(0, int(remaining))


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
    "Time's up!",
    "You've used up your time on this site. Ask a parent for more time.",
)


def _make_response(tmpl: str, domain: str, status: int = 403) -> http.Response:
    safe = domain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = tmpl.replace("__DOMAIN__", safe)
    return http.Response.make(status, body, {"Content-Type": "text/html; charset=utf-8"})


# ── countdown widget ─────────────────────────────────────────────────────────

_COUNTDOWN_WIDGET = """<style>
#_ns_timer{position:fixed;bottom:12px;right:12px;background:rgba(26,26,46,.85);
color:#fff;border-radius:12px;padding:8px 14px;font-family:system-ui,sans-serif;
font-size:13px;z-index:2147483647;backdrop-filter:blur(4px);pointer-events:none;
transition:background .5s;}
#_ns_timer.warn{background:rgba(230,81,0,.9);}
#_ns_timer.urgent{background:rgba(198,40,40,.9);}
</style>
<div id="_ns_timer"></div>
<script>(function(){
var s=__SECONDS__;
var el=document.getElementById('_ns_timer');
function fmt(n){if(n<=0)return"Time’s up!";
var h=Math.floor(n/3600),m=Math.floor((n%3600)/60),ss=n%60;
if(h>0)return h+'h '+m+'m left';
if(m>0)return m+'m '+(ss<10?'0':'')+ss+'s left';
return ss+'s left';}
function tick(){el.textContent=fmt(s);
el.className=s<=60?'urgent':s<=300?'warn':'';
if(s>0){s--;setTimeout(tick,1000);}}
tick();
})();</script>"""


def _inject_countdown(html: bytes, seconds: int) -> bytes:
    widget = _COUNTDOWN_WIDGET.replace("__SECONDS__", str(seconds)).encode()
    # Inject before </body>; fall back to appending
    tag = b"</body>"
    idx = html.lower().rfind(tag)
    if idx != -1:
        return html[:idx] + widget + html[idx:]
    return html + widget


# ── addon ─────────────────────────────────────────────────────────────────────

class KidFilter:
    def request(self, flow: http.HTTPFlow):
        host = flow.request.pretty_host

        if host in ALWAYS_ALLOWED_HOSTS:
            return

        if _check_bypass():
            return

        matched = _base_domain(host)
        if matched is None:
            db.log_blocked(host, flow.request.pretty_url)
            flow.response = _make_response(BLOCKED_TMPL, host)
            return

        daily_limit, weekly_limit = _whitelist.get(matched, (None, None))
        if daily_limit is not None or weekly_limit is not None:
            today_used, week_used = _record_activity(matched)
            if daily_limit is not None and today_used >= daily_limit * 60:
                flow.response = _make_response(TIMEOUT_TMPL, host)
                return
            if weekly_limit is not None and week_used >= weekly_limit * 60:
                flow.response = _make_response(TIMEOUT_TMPL, host)
                return

    def response(self, flow: http.HTTPFlow):
        if _check_bypass():
            return

        host = flow.request.pretty_host
        if host in ALWAYS_ALLOWED_HOSTS:
            return

        matched = _base_domain(host)
        if matched is None:
            return

        daily_limit, weekly_limit = _whitelist.get(matched, (None, None))
        if daily_limit is None and weekly_limit is None:
            return

        ct = flow.response.headers.get("content-type", "")
        if "text/html" not in ct:
            return

        remaining = _seconds_remaining(matched)
        if remaining is None or remaining <= 0:
            return

        try:
            flow.response.content = _inject_countdown(flow.response.content, remaining)
        except Exception:
            pass


addons = [KidFilter()]
