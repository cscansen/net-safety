# net-safety

Kid-safe web proxy and parental control system for Linux. Designed for a household where a young child has their own desktop — filtering runs transparently in the background, and parents manage it from any device on the home network.

**Current version:** 0.8.0

---

## How it works

```
Browser → mitmproxy (127.0.0.1:3128) → internet
               ↓
         allowlist check
               ↓
         time budget check
               ↓
         block page / pass through
```

- **Proxy** intercepts all HTTP and HTTPS traffic via mitmproxy. The browser's proxy is locked by enterprise policy — the kid cannot bypass or disable it.
- **Admin UI** is a Flask web app accessible from any phone or device on your home network. Review blocked sites, approve or deny them, set daily/weekly time limits.
- **Fail-closed** — if the proxy service dies, the browser gets no internet. There's no fallback to direct connection.

---

## Features

- Domain allowlist with one-click approve/deny
- Per-domain daily and weekly time budgets
- Live countdown timer injected into pages on timed domains
- Bypass mode (1h / 4h / 8h / indefinite) for supervised sessions
- Multi-admin accounts with audit trail (who approved what and when)
- AI-generated site descriptions (DuckDuckGo/Wikipedia, cached, non-blocking)
- Subdomain bundling — `www.google.com` and `maps.google.com` both queue as `google.com`
- LAN-accessible admin UI with mDNS (`http://<hostname>.local:9090`)
- Dark mode (follows OS preference)
- Weekly auto-update from GitHub, daily OS auto-updates
- Covers Firefox and Chromium via enterprise policy

---

## Requirements

- Linux with `systemd` (tested on Linux Mint 22)
- Python 3.10+
- `sudo` / root access for setup
- Ports: `3128` (proxy, localhost only), `9090` (admin UI, LAN)

---

## Install

```bash
sudo bash setup.sh
```

The script is interactive and handles everything:

1. Creates the kid's standard user account (no sudo, optional passwordless + auto-login)
2. Installs mitmproxy, Flask, and dependencies into a virtualenv at `/opt/kid-proxy/`
3. Generates a mitmproxy CA cert and installs it into Firefox and Chromium trust stores
4. Deploys Firefox and Chromium enterprise policies to lock the proxy setting
5. Creates the `admin` account for the parent UI
6. Starts and enables all systemd services
7. Sets up the weekly auto-update timer

After setup, open `http://<hostname>.local:9090` from any device on your network.

---

## Update

Updates run automatically every week via `kid-update.timer`. To update manually:

```bash
sudo git -C /opt/net-safety-src pull
sudo cp /opt/net-safety-src/*.py /opt/kid-proxy/
sudo cp -r /opt/net-safety-src/templates/* /opt/kid-proxy/templates/
sudo systemctl restart kid-proxy kid-admin
```

---

## File reference

| File | Purpose |
|------|---------|
| `setup.sh` | Full one-shot deploy |
| `update.sh` | Called by the auto-update timer |
| `proxy_addon.py` | mitmproxy addon — filtering, time tracking, countdown injection |
| `admin_app.py` | Flask admin UI |
| `db.py` | SQLite helpers shared by proxy and admin |
| `requirements.txt` | Python deps |
| `policies.json` | Firefox enterprise policy |
| `kid-proxy.service` | mitmproxy systemd unit |
| `kid-admin.service` | Flask admin systemd unit |
| `kid-update.service` / `.timer` | Weekly GitHub auto-update |

---

## Paths on the deployed machine

| Path | Contents |
|------|---------|
| `/opt/kid-proxy/` | Deployed app files and virtualenv |
| `/opt/net-safety-src/` | Git clone (auto-update source) |
| `/var/lib/kid-proxy/db.sqlite` | Database |
| `/etc/kid-proxy/` | CA cert and Flask secret |
| `/etc/firefox/policies/policies.json` | Firefox enterprise policy |
| `/etc/chromium/policies/managed/kid-proxy.json` | Chromium enterprise policy |
| `/var/log/kid-proxy-update.log` | Auto-update log |

---

## Companion: kid-lockdown

[`kid-lockdown`](https://github.com/cscansen/kid-lockdown) hides system/admin apps from the kid's account and adds age-appropriate launchers. Run separately after setup:

```bash
sudo bash kid-lockdown.sh restricted <username>
```
