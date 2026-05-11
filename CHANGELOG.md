# Changelog

## [0.5.0] - 2026-05-11

### Added
- **ElecFreaks KB mirror** — `elecfreaks-sync.sh` mirrors `wiki.elecfreaks.com/en/microbit/` to `/var/www/elecfreaks-kb/` via wget. Weekly systemd timer keeps it fresh.
- **Offline-first launcher** — `elecfreaks-kb-launcher` checks connectivity and opens the live wiki if reachable, falls back to the local nginx mirror transparently. Single desktop icon, no choice required from the kid.
- **Kid-proof desktop icon** — `.desktop` file placed on kid's Desktop, marked trusted (Nemo), then `chattr +i` so it cannot be deleted or moved.
- **nginx on :8080** — serves the local mirror; setup.sh installs and configures it as part of the KB step.
- **KB mirror step in setup.sh** — optional step 14 with Y/n prompt; initial sync runs in background. Status reported in the final verify summary.

---

## [0.4.0] - 2026-05-11

### Added
- **kid-lockdown.sh** — hides 28 admin/system app menu entries from the kid account via per-user `NoDisplay` overrides (no uninstalls; admin account is unaffected). Idempotent and accepts a username argument for reuse on sibling machines.
- **Age-based profiles** — lockdown accepts a `profile` argument (`restricted` / `tween` / `teen`). `restricted` is fully implemented (age ~6). `tween` and `teen` are scaffolded and fall back to `restricted` until implemented.
- **Silent auto-updates** — enables `mintupdate-automation-upgrade.timer` and `mintupdate-automation-autoremove.timer` so the OS patches daily without any GUI interaction.
- **Interactive lockdown in setup.sh** — after account creation, setup now asks whether to apply lockdown, which profile to use, and whether any additional accounts (siblings) should also be locked down.

---

## [0.3.0] - 2026-05-11

### Added
- **Weekly time limits** — each approved domain now supports a per-day and a per-week minute budget (enforced independently; whichever runs out first blocks access).
- **Countdown widget** — a small floating timer is injected into every HTML page on a timed domain, showing time remaining. Turns orange under 5 min, red under 1 min.
- **Weekly usage display** — review table shows today's and this week's usage alongside the limits.

### Changed
- DB migration runs automatically on startup — existing installs gain the `weekly_limit_minutes` column with no manual steps.

---

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
