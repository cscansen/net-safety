# Changelog

## [0.7.2] - 2026-05-11

### Added
- **Per-domain clear button** — each row in the review table now has a small "× clear" button that wipes all history for that domain (blocked log, whitelist entry, and session log). Useful for resetting test state or removing noise entries without touching the rest of the list.

---

## [0.7.1] - 2026-05-11

### Fixed
- **Firefox cert warnings** — added `Certificates.Install` to the Firefox enterprise policy so the mitmproxy CA cert is explicitly trusted. `ImportEnterpriseRoots` alone doesn't reliably pick up the system trust store on Linux.
- **Review queue noise** — sub-resources (images, scripts, fonts, XHR) from blocked pages are silently dropped instead of flooding the approval queue. Sub-resources from already-approved pages that are themselves blocked still appear for review so the parent can approve what's needed to fix broken pages.

---

## [0.7.0] - 2026-05-11

### Changed
- **Dark mode** — all three pages (login, review, accounts) now switch to a dark colour scheme automatically when the OS/browser is in dark mode (`prefers-color-scheme: dark`). No toggle needed; works on phones, tablets, and desktop.
- **Font** — switched to Nunito (Google Fonts) with system-ui fallback. Rounded, friendly feel across all devices.

---

## [0.6.0] - 2026-05-11

### Added
- **LAN-accessible admin UI** — Flask now binds to `0.0.0.0:9090` instead of `127.0.0.1`. Parents can reach the review page from any device on the home network.
- **mDNS discovery** — `avahi-daemon` added to setup dependencies. No DNS required; devices find the admin UI at `http://<hostname>.local:9090` automatically (iOS, Android, macOS native; Windows via Bonjour).
- **UFW rules** — setup.sh opens port 9090 to all RFC1918 subnets (`192.168.0.0/16`, `172.16.0.0/12`) if UFW is present.

### Changed
- **review.html** — table wrapped in horizontal scroll container so it doesn't overflow on phone screens. Checkboxes and Apply button enlarged for touch targets on narrow viewports.

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
