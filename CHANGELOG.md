# Changelog

## [0.2.0] - 2026-05-11

### Added
- **Multi-admin accounts** — named username + password replaces single shared password. Manage accounts at `/accounts` (add, change password, delete). Cannot delete the last account or your own.
- **Audit trail** — every domain approval records who approved it and when. Visible as an "Approved By" column in the review table.
- **Domain filter tabs** — Outstanding / Approved / Denied tabs with live counts on the review page.
- **Denied state** — revoking a domain soft-deletes it (history preserved, re-approvable) rather than wiping it entirely.
- **Bypass mode** — password-gated bypass from the admin UI (1h / 4h / 8h / Indefinite). Proxy passes all traffic when active; auto-expires.

### Changed
- Login page now requires username + password.
- Existing single-password installs auto-migrate to a named `admin` account on first login.

---

## [0.1.0] - 2026-05-11

### Added
- **mitmproxy addon** — intercepts all HTTP/HTTPS traffic, enforces domain allowlist with per-domain daily time budgets.
- **Flask admin UI** (`localhost:9090`) — password-protected, review blocked requests, approve/deny domains, set time limits.
- **SQLite backend** — shared between proxy and admin app; survives restarts.
- **Firefox enterprise policy** — locks proxy to `127.0.0.1:3128`, disables dev tools and private browsing, imports CA cert.
- **Fail-closed design** — if the proxy dies, Firefox cannot reach the internet.
- **setup.sh** — interactive one-shot deploy: creates kid account (passwordless + auto-login supported), installs all services, generates mitmproxy CA cert, sets up admin account.
- **Auto-update** — `kid-update.timer` pulls from GitHub weekly (also on boot if a week was missed) and redeploys without intervention.
- **Kid account setup** — prompts for username (lowercased), creates standard account with no sudo, optionally passwordless with LightDM auto-login.
