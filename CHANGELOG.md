# Changelog

## [0.8.7] - 2026-05-16

### Added
- **Parent URL on block page** — the block and time's-up pages now show `http://<hostname>:9090` below the Parent Review button so parents on another device know where to go without guessing.
- **Admin hostname in header** — the mDNS address is displayed in the top-right of the admin review page as a persistent reminder for bookmarking or sharing with co-parents.

### Changed
- **Hostname is now configurable** — `setup.sh` writes `ADMIN_HOSTNAME=$(hostname).local` to `/etc/kid-proxy/env` at install time. Both services read it on startup, so the correct address appears on any machine without hardcoding.

### Fixed
- Removed stale comment in `update.sh` referencing a deploy key that was removed when the repo switched to HTTPS in v0.4.

---

## [0.8.6] - 2026-05-16

### Added
- **Admin-seeded domain display** — always-allowed domains (ElecFreaks, microbit.org, MakeCode) now appear in the Approved tab with an "Administratively allowed" badge. Previously they were invisible in the UI since they never pass through the review queue. The Allow checkbox is replaced with a lock icon and the row is read-only — time limit inputs and the clear button are disabled.
- **MakeCode allowlist** — `makecode.com` (main editor) and `pxt.azureedge.net` (MakeCode CDN/static assets) added to the default approved list with no time limit. `microbit.org` already covered `makecode.microbit.org`. Existing installs get both entries automatically on next restart.
- **Filter tab empty state** — switching to Outstanding, Approved, or Denied when no rows match now shows a friendly message instead of column headers over an empty table.

---

## [0.8.5] - 2026-05-16

### Added
- **MakeCode allowlist** — `microbit.org` (covers `makecode.microbit.org` and all subdomains) added to the default approved list with no time limit. Existing installs get it automatically via the update script's DB upsert on next pull.

---

## [0.8.4] - 2026-05-13

### Fixed
- **Midnight rollover** — daily time budgets now reset correctly at midnight without requiring a proxy restart. Session tracking stores the session date; if a domain is still active when the day changes, the previous day's time is flushed to the DB with the correct date and a fresh session begins for the new day.

---

## [0.8.3] - 2026-05-13

### Fixed
- **Session persistence across restarts** — proxy now flushes all in-memory session time to the DB on shutdown via the mitmproxy `done` hook. Previously, any time the kid had spent on a timed site since the last idle timeout was silently discarded on proxy restart, resetting the daily counter.

---

## [0.8.2] - 2026-05-13

### Added
- **Timed Out tab** — new orange tab in the admin review page lists every domain that has hit its daily limit. Shows time used vs. limit for each.
- **Quick extend buttons** — +15 min and +30 min buttons per domain on the Timed Out tab. Each press adds to the daily limit so the kid can continue immediately without going through the full review flow.

---

## [0.8.1] - 2026-05-13

### Changed
- **Navigation-only blocking** — only top-level page navigations (`Sec-Fetch-Mode: navigate`) are blocked and queued for review. Sub-resources (scripts, images, XHR, CDN calls, etc.) pass through silently — they are never blocked and never appear in the review queue. This means the review queue shows only sites the kid actually tried to visit.
- **Response streaming** — non-HTML responses (video, audio, images, JS, etc.) are now streamed through mitmproxy without buffering. Fixes video playback on YouTube and other media sites that previously timed out while mitmproxy tried to buffer the full response body.

---

## [0.8.0] - 2026-05-11

### Added
- **Chromium support** — `chromium-browser` added to setup dependencies. Proxy CA cert is now installed into the kid user's Chromium NSS database via `certutil` so Chromium trusts mitmproxy-intercepted HTTPS the same as Firefox.
- **Chromium enterprise policy** — `/etc/chromium/policies/managed/kid-proxy.json` locks Chromium's proxy to `127.0.0.1:3128` with the same fail-closed guarantee as the Firefox enterprise policy.

### Changed
- **kid-lockdown.sh moved** — app-hiding and Google Docs/Sheets launcher setup are now managed by the standalone `kid-lockdown` repo. `setup.sh` no longer calls `kid-lockdown.sh` directly; the summary now prints the command to run it separately.

---

## [0.7.3] - 2026-05-11

### Added
- **Wildcard domain bundling** — all subdomains are now collapsed to their registered domain (eTLD+1) before being stored in the review queue. `www.google.com`, `maps.google.com`, and `google.com` appear as a single `google.com` entry. Approving it covers the whole domain as before — only the display noise is gone. Uses `tldextract` with its bundled Public Suffix List (no network required at runtime).
- **AI site descriptions** — outstanding domains in the review table show a 3-sentence overview fetched from the DuckDuckGo Instant Answer API (free, no key required, Wikipedia-backed). Results are cached in the DB. The page never blocks on the lookup — if no description is available the element is silently removed.

---

## [0.7.2] - 2026-05-11

### Added
- **Per-domain clear button** — each row in the review table now has a small "× clear" button that wipes all history for that domain (blocked log, whitelist entry, and session log). Useful for removing noise entries without touching the rest of the list.
- **Clear Database button** (admin account only) — wipes all blocked log, whitelist approvals, and session history in one shot, then re-seeds the default ElecFreaks entries. Shows a confirmation warning before proceeding. Only visible when signed in as the `admin` account.

### Fixed
- Per-row clear buttons were nested inside the main apply `<form>`, which is invalid HTML and caused unpredictable browser behaviour. All mini-forms are now rendered outside the main form and linked via the HTML5 `form=` attribute.

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
