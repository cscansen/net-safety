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
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                domain              TEXT UNIQUE NOT NULL,
                daily_limit_minutes INTEGER DEFAULT 30,
                approved_by         TEXT,
                approved_at         DATETIME DEFAULT (datetime('now'))
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

            CREATE INDEX IF NOT EXISTS idx_blocked_domain ON blocked_log(domain);
            CREATE INDEX IF NOT EXISTS idx_session_domain_date ON session_log(domain, session_date);
        """)
        for domain, limit in INITIAL_WHITELIST:
            conn.execute(
                "INSERT OR IGNORE INTO whitelist (domain, daily_limit_minutes) VALUES (?, ?)",
                (domain, limit),
            )


def get_whitelist():
    """Return {domain: daily_limit_minutes} for all approved domains."""
    with get_conn() as conn:
        rows = conn.execute("SELECT domain, daily_limit_minutes FROM whitelist").fetchall()
    return {r["domain"]: r["daily_limit_minutes"] for r in rows}


def log_blocked(domain, url):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO blocked_log (domain, full_url) VALUES (?, ?)",
            (domain, (url or "")[:500]),
        )


def log_session(domain, duration_seconds):
    if duration_seconds < 5:
        return
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO session_log (domain, session_date, duration_seconds) VALUES (?, ?, ?)",
            (domain, today, duration_seconds),
        )


def get_today_db_seconds(domain):
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) as total FROM session_log "
            "WHERE domain = ? AND session_date = ?",
            (domain, today),
        ).fetchone()
    return row["total"] if row else 0


def get_review_data():
    """All attempted domains with approval status, limits, and today's usage."""
    today = date.today().isoformat()
    with get_conn() as conn:
        return conn.execute("""
            SELECT
                bl.domain,
                COUNT(*)                                   AS attempt_count,
                MAX(bl.attempted_at)                       AS last_attempted,
                w.domain IS NOT NULL                       AS is_approved,
                w.daily_limit_minutes,
                w.approved_by,
                w.approved_at,
                COALESCE(SUM(sl.duration_seconds), 0) / 60.0 AS minutes_used_today
            FROM blocked_log bl
            LEFT JOIN whitelist w ON w.domain = bl.domain
            LEFT JOIN session_log sl
                   ON sl.domain = bl.domain AND sl.session_date = ?
            GROUP BY bl.domain
            ORDER BY last_attempted DESC
        """, (today,)).fetchall()


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
        # Remove revoked domains (only ones that have been attempted)
        for domain in attempted - set(approved_domains_limits):
            conn.execute("DELETE FROM whitelist WHERE domain = ?", (domain,))
        # Upsert approved domains
        for domain, limit in approved_domains_limits.items():
            conn.execute("""
                INSERT INTO whitelist (domain, daily_limit_minutes, approved_by, approved_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(domain) DO UPDATE SET
                    daily_limit_minutes = excluded.daily_limit_minutes,
                    approved_by         = excluded.approved_by,
                    approved_at         = excluded.approved_at
            """, (domain, limit, approved_by))
