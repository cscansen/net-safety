import sqlite3
from pathlib import Path
from datetime import date

DB_PATH = "/var/lib/kid-proxy/db.sqlite"

INITIAL_WHITELIST = [
    ("wiki.elecfreaks.com", None),   # None = no time limit
    ("shop.elecfreaks.com", None),
]

DEFAULT_LIMIT_MINUTES = 30


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS blocked_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                domain      TEXT NOT NULL,
                full_url    TEXT,
                attempted_at DATETIME DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS whitelist (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                domain               TEXT UNIQUE NOT NULL,
                daily_limit_minutes  INTEGER DEFAULT 30,
                weekly_limit_minutes INTEGER DEFAULT NULL,
                approved_by          TEXT,
                approved_at          DATETIME DEFAULT (datetime('now')),
                active               INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS session_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                domain           TEXT NOT NULL,
                session_date     TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                logged_at        DATETIME DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admins (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at   DATETIME DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS domain_descriptions (
                domain      TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                fetched_at  DATETIME DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_blocked_domain ON blocked_log(domain);
            CREATE INDEX IF NOT EXISTS idx_session_domain_date ON session_log(domain, session_date);
        """)
        # Migrate: add columns introduced after initial schema
        for col, defn in [
            ("weekly_limit_minutes", "INTEGER DEFAULT NULL"),
            ("approved_by",          "TEXT"),
            ("active",               "INTEGER NOT NULL DEFAULT 1"),
        ]:
            try:
                conn.execute(f"ALTER TABLE whitelist ADD COLUMN {col} {defn}")
            except Exception:
                pass

        for domain, limit in INITIAL_WHITELIST:
            conn.execute(
                "INSERT OR IGNORE INTO whitelist (domain, daily_limit_minutes) VALUES (?, ?)",
                (domain, limit),
            )


def get_whitelist():
    """Return {domain: (daily_limit_minutes, weekly_limit_minutes)} for active domains."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT domain, daily_limit_minutes, weekly_limit_minutes "
            "FROM whitelist WHERE active = 1"
        ).fetchall()
    return {r["domain"]: (r["daily_limit_minutes"], r["weekly_limit_minutes"]) for r in rows}


def log_blocked(domain, url):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO blocked_log (domain, full_url) VALUES (?, ?)",
            (domain, (url or "")[:500]),
        )


def log_session(domain, duration_seconds, session_date=None):
    if duration_seconds < 5:
        return
    if session_date is None:
        session_date = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO session_log (domain, session_date, duration_seconds) VALUES (?, ?, ?)",
            (domain, session_date, duration_seconds),
        )


def get_week_start():
    """Return ISO Monday of the current week as a date string."""
    from datetime import timedelta
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def get_today_db_seconds(domain):
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) as total FROM session_log "
            "WHERE domain = ? AND session_date = ?",
            (domain, today),
        ).fetchone()
    return row["total"] if row else 0


def get_this_week_db_seconds(domain):
    week_start = get_week_start()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) AS total FROM session_log "
            "WHERE domain = ? AND session_date >= ?",
            (domain, week_start),
        ).fetchone()
    return row["total"] if row else 0


def get_review_data():
    """All attempted domains with approval status, limits, and today's usage."""
    today = date.today().isoformat()
    with get_conn() as conn:
        week_start = get_week_start()
        return conn.execute("""
            SELECT
                bl.domain,
                COUNT(*)                                         AS attempt_count,
                MAX(bl.attempted_at)                             AS last_attempted,
                COALESCE(w.active, -1)                          AS status,
                w.daily_limit_minutes,
                w.weekly_limit_minutes,
                w.approved_by,
                w.approved_at,
                COALESCE(SUM(CASE WHEN sl.session_date = :today
                               THEN sl.duration_seconds END), 0) / 60.0  AS minutes_used_today,
                COALESCE(SUM(CASE WHEN sl.session_date >= :week_start
                               THEN sl.duration_seconds END), 0) / 60.0  AS minutes_used_week
            FROM blocked_log bl
            LEFT JOIN whitelist w ON w.domain = bl.domain
            LEFT JOIN session_log sl ON sl.domain = bl.domain
            GROUP BY bl.domain
            ORDER BY last_attempted DESC
        """, {"today": today, "week_start": week_start}).fetchall()


ADMIN_HASH_FILE = "/etc/kid-proxy/admin.hash"


def migrate_legacy_admin():
    """Import admin.hash into admins table as 'admin' if table is empty."""
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
        if count > 0:
            return
    import os
    if not os.path.exists(ADMIN_HASH_FILE):
        return
    try:
        pw_hash = open(ADMIN_HASH_FILE, "rb").read().strip().decode()
        with get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO admins (username, password_hash) VALUES ('admin', ?)",
                (pw_hash,),
            )
    except Exception:
        pass


def list_admins():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, username, created_at FROM admins ORDER BY id"
        ).fetchall()


def add_admin(username, pw_hash):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (username, pw_hash),
        )


def update_admin_password(username, pw_hash):
    with get_conn() as conn:
        conn.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (pw_hash, username),
        )


def delete_admin(username):
    with get_conn() as conn:
        conn.execute("DELETE FROM admins WHERE username = ?", (username,))


def admin_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]


def check_admin_password(username, password):
    import bcrypt
    with get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM admins WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return False
    return bcrypt.checkpw(password.encode(), row["password_hash"].encode())


def get_bypass_until():
    """Return expiry as Unix float, float('inf') for indefinite, or None if not set."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'bypass_until'"
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    if row["value"] == "indefinite":
        return float("inf")
    try:
        return float(row["value"])
    except (ValueError, TypeError):
        return None


def set_bypass(until_ts):
    """Set bypass expiry. Pass float Unix timestamp, float('inf') for indefinite, or None to clear."""
    with get_conn() as conn:
        if until_ts is None:
            conn.execute("DELETE FROM settings WHERE key = 'bypass_until'")
        elif until_ts == float("inf"):
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('bypass_until', 'indefinite')"
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('bypass_until', ?)",
                (str(until_ts),),
            )


def delete_domain(domain):
    """Wipe all history for a domain: blocked log, whitelist entry, session log, and description cache."""
    with get_conn() as conn:
        conn.execute("DELETE FROM blocked_log          WHERE domain = ?", (domain,))
        conn.execute("DELETE FROM whitelist            WHERE domain = ?", (domain,))
        conn.execute("DELETE FROM session_log          WHERE domain = ?", (domain,))
        conn.execute("DELETE FROM domain_descriptions  WHERE domain = ?", (domain,))


def get_cached_description(domain: str) -> str | None:
    """Return cached description string, or None if not yet fetched."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT description FROM domain_descriptions WHERE domain = ?", (domain,)
        ).fetchone()
    return row["description"] if row is not None else None


def cache_description(domain: str, description: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO domain_descriptions (domain, description) VALUES (?, ?)",
            (domain, description),
        )


def extend_daily_limit(domain: str, minutes: int):
    """Add minutes to a domain's daily limit (creates one if none was set)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE whitelist SET daily_limit_minutes = COALESCE(daily_limit_minutes, 0) + ? WHERE domain = ?",
            (minutes, domain),
        )


def clear_all():
    """Wipe all blocked log, session history, whitelist, and description cache, then re-seed defaults."""
    with get_conn() as conn:
        conn.execute("DELETE FROM blocked_log")
        conn.execute("DELETE FROM session_log")
        conn.execute("DELETE FROM whitelist")
        conn.execute("DELETE FROM domain_descriptions")
        for domain, limit in INITIAL_WHITELIST:
            conn.execute(
                "INSERT OR IGNORE INTO whitelist (domain, daily_limit_minutes) VALUES (?, ?)",
                (domain, limit),
            )


def apply_parent_review(approved_domains_limits, approved_by=None):
    """
    approved_domains_limits: {domain: limit_minutes | None}
    Domains in blocked_log not present here get removed from whitelist.
    Initial whitelist entries (never blocked) are never touched.
    """
    with get_conn() as conn:
        attempted = {
            r["domain"]
            for r in conn.execute("SELECT DISTINCT domain FROM blocked_log")
        }
        # Soft-delete revoked domains (only ones that have been attempted)
        for domain in attempted - set(approved_domains_limits):
            conn.execute(
                "UPDATE whitelist SET active = 0 WHERE domain = ? AND active = 1",
                (domain,),
            )
        # Upsert approved domains (reactivates previously denied ones)
        for domain, limits in approved_domains_limits.items():
            daily, weekly = limits if isinstance(limits, tuple) else (limits, None)
            conn.execute("""
                INSERT INTO whitelist
                    (domain, daily_limit_minutes, weekly_limit_minutes, approved_by, approved_at, active)
                VALUES (?, ?, ?, ?, datetime('now'), 1)
                ON CONFLICT(domain) DO UPDATE SET
                    daily_limit_minutes  = excluded.daily_limit_minutes,
                    weekly_limit_minutes = excluded.weekly_limit_minutes,
                    approved_by          = excluded.approved_by,
                    approved_at          = excluded.approved_at,
                    active               = 1
            """, (domain, daily, weekly, approved_by))
