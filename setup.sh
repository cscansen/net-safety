#!/usr/bin/env bash
# setup.sh — deploy kid parental control proxy
# Run as: sudo bash setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fatal() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && fatal "Run with sudo: sudo bash setup.sh"

# ── 1. kid account ───────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Kid account setup"
echo "══════════════════════════════════════════"
read -rp "  Kid's username [buddy]: " KID_USER
KID_USER="${KID_USER:-buddy}"
KID_USER="${KID_USER,,}"   # force lowercase

if id "$KID_USER" &>/dev/null; then
  warn "User '$KID_USER' already exists."
  read -rp "  Lock down this existing account? [y/N]: " CONFIRM
  [[ "${CONFIRM,,}" == "y" ]] || fatal "Aborted."
  # Warn if the account has sudo
  if groups "$KID_USER" | grep -qw sudo; then
    warn "WARNING: '$KID_USER' is in the sudo group — this account should not have sudo."
    read -rp "  Remove from sudo group? [Y/n]: " RM_SUDO
    [[ "${RM_SUDO,,}" != "n" ]] && gpasswd -d "$KID_USER" sudo && info "Removed from sudo."
  fi
else
  info "Creating standard user '$KID_USER'..."
  adduser --disabled-password --gecos "" "$KID_USER"
  read -rsp "  Set password for '$KID_USER' (Enter for passwordless): " KP1; echo
  if [ -z "$KP1" ]; then
    passwd -d "$KID_USER"
    info "User '$KID_USER' created with no password."
  else
    read -rsp "  Confirm password: " KP2; echo
    while [[ "$KP1" != "$KP2" ]]; do
      warn "Passwords don't match, try again."
      read -rsp "  Set password for '$KID_USER': " KP1; echo
      read -rsp "  Confirm password:              " KP2; echo
    done
    echo "$KID_USER:$KP1" | chpasswd
    info "User '$KID_USER' created."
  fi

  # Offer auto-login via LightDM
  read -rp "  Enable auto-login as '$KID_USER' at boot? [Y/n]: " AUTO_LOGIN
  if [[ "${AUTO_LOGIN,,}" != "n" ]]; then
    LIGHTDM_CONF=/etc/lightdm/lightdm.conf
    if [ -f "$LIGHTDM_CONF" ]; then
      # Update existing autologin lines if present, else append
      grep -q "^autologin-user=" "$LIGHTDM_CONF" \
        && sed -i "s/^autologin-user=.*/autologin-user=$KID_USER/" "$LIGHTDM_CONF" \
        || sed -i "/^\[Seat:\*\]/a autologin-user=$KID_USER\nautologin-user-timeout=0" "$LIGHTDM_CONF"
    else
      mkdir -p /etc/lightdm
      printf '[Seat:*]\nautologin-user=%s\nautologin-user-timeout=0\n' "$KID_USER" > "$LIGHTDM_CONF"
    fi
    info "Auto-login enabled for '$KID_USER'."
  fi
fi

# Persist username for Timekpr and future reference
mkdir -p /etc/kid-proxy
echo "$KID_USER" > /etc/kid-proxy/kid-user
info "Kid username '$KID_USER' saved to /etc/kid-proxy/kid-user"

# ── 2. dependencies ──────────────────────────────────────────────────────────
info "Installing system dependencies..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv libnss3-tools openssl git rsync

info "Creating Python venv and installing packages..."
python3 -m venv /opt/kid-proxy/venv
/opt/kid-proxy/venv/bin/pip install --quiet mitmproxy flask bcrypt

# ── 3. system user ───────────────────────────────────────────────────────────
if ! id kidproxy &>/dev/null; then
  info "Creating kidproxy system user..."
  useradd --system --no-create-home --shell /usr/sbin/nologin kidproxy
else
  info "kidproxy user already exists, skipping."
fi

# ── 4. directories ───────────────────────────────────────────────────────────
info "Creating directories..."
mkdir -p /opt/kid-proxy/templates
mkdir -p /var/lib/kid-proxy

# ── 5. copy files ────────────────────────────────────────────────────────────
info "Copying proxy files..."
cp "$SCRIPT_DIR/db.py"          /opt/kid-proxy/
cp "$SCRIPT_DIR/proxy_addon.py" /opt/kid-proxy/
cp "$SCRIPT_DIR/admin_app.py"   /opt/kid-proxy/
cp "$SCRIPT_DIR/templates/"*    /opt/kid-proxy/templates/

chown -R kidproxy:kidproxy /opt/kid-proxy /var/lib/kid-proxy
chmod 750 /opt/kid-proxy /var/lib/kid-proxy

# ── 6. initialise database ───────────────────────────────────────────────────
info "Initialising SQLite database..."
sudo -u kidproxy /opt/kid-proxy/venv/bin/python -c "import sys; sys.path.insert(0,'/opt/kid-proxy'); import db; db.init_db()"

# ── 7. admin account ─────────────────────────────────────────────────────────
echo ""
read -rp "  Admin username [admin]: " ADMIN_USER
ADMIN_USER="${ADMIN_USER:-admin}"
while true; do
  read -rsp "  Set password for '$ADMIN_USER': " PW1; echo
  [[ -n "$PW1" ]] && break
  warn "Admin password cannot be empty."
done
read -rsp "  Confirm password: " PW2; echo
while [[ "$PW1" != "$PW2" ]]; do
  warn "Passwords don't match, try again."
  read -rsp "  Set password for '$ADMIN_USER': " PW1; echo
  read -rsp "  Confirm password:               " PW2; echo
done

/opt/kid-proxy/venv/bin/python -c "
import sys; sys.path.insert(0,'/opt/kid-proxy')
import db, bcrypt
db.init_db()
h = bcrypt.hashpw(sys.argv[2].encode(), bcrypt.gensalt()).decode()
db.add_admin(sys.argv[1], h)
" "$ADMIN_USER" "$PW1"
info "Admin account '$ADMIN_USER' created."

# ── 8. flask secret ──────────────────────────────────────────────────────────
FLASK_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
cat > /etc/kid-proxy/env <<EOF
FLASK_SECRET=${FLASK_SECRET}
EOF

chmod 600 /etc/kid-proxy/admin.hash /etc/kid-proxy/env
chown -R kidproxy:kidproxy /etc/kid-proxy

# ── 9. generate mitmproxy CA cert ────────────────────────────────────────────
info "Generating mitmproxy CA certificate..."
# Start briefly on an unused port just to trigger cert generation, then stop
sudo -u kidproxy /opt/kid-proxy/venv/bin/mitmdump --set confdir=/etc/kid-proxy --listen-port 13128 &
MITM_PID=$!
sleep 4
kill "$MITM_PID" 2>/dev/null || true
wait "$MITM_PID" 2>/dev/null || true

CA_CERT=/etc/kid-proxy/mitmproxy-ca-cert.pem
[[ -f "$CA_CERT" ]] || fatal "CA cert not generated at $CA_CERT — check mitmproxy logs."

# ── 10. install CA cert into system trust store ──────────────────────────────
info "Installing CA cert into system trust store..."
cp "$CA_CERT" /usr/local/share/ca-certificates/kid-proxy-ca.crt
update-ca-certificates

# ── 10. Firefox enterprise policy ────────────────────────────────────────────
info "Installing Firefox policy..."
mkdir -p /etc/firefox/policies
cp "$SCRIPT_DIR/policies.json" /etc/firefox/policies/policies.json

# ── 11. systemd services ─────────────────────────────────────────────────────
info "Installing and enabling systemd services..."
cp "$SCRIPT_DIR/kid-proxy.service"  /etc/systemd/system/
cp "$SCRIPT_DIR/kid-admin.service"  /etc/systemd/system/
cp "$SCRIPT_DIR/kid-update.service" /etc/systemd/system/
cp "$SCRIPT_DIR/kid-update.timer"   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now kid-proxy kid-admin

# ── 12. clone repo for auto-update ──────────────────────────────────────────
REPO_DIR=/opt/net-safety-src
REPO_URL="https://github.com/cscansen/net-safety.git"

info "Cloning net-safety repo to $REPO_DIR..."
if [ -d "$REPO_DIR/.git" ]; then
  info "Repo already cloned, skipping."
else
  git clone "$REPO_URL" "$REPO_DIR"
fi

# Install update script and enable timer
cp "$SCRIPT_DIR/update.sh" /usr/local/bin/kid-proxy-update
chmod +x /usr/local/bin/kid-proxy-update
systemctl enable --now kid-update.timer
info "Auto-update timer enabled (pulls every 15 min)."

# ── 13. kid account lockdown ────────────────────────────────────────────────
echo ""
read -rp "  Apply lockdown to '$KID_USER'? [Y/n]: " DO_LOCKDOWN
if [[ "${DO_LOCKDOWN,,}" != "n" ]]; then
  echo "  Profiles: restricted (age ~6, default) | tween (age ~9, planned) | teen (age ~13, planned)"
  read -rp "  Profile [restricted]: " LOCKDOWN_PROFILE
  LOCKDOWN_PROFILE="${LOCKDOWN_PROFILE:-restricted}"
  bash "$SCRIPT_DIR/kid-lockdown.sh" "$KID_USER" "$LOCKDOWN_PROFILE"
fi

# Lock down any additional accounts (e.g. siblings sharing the same machine)
while true; do
  echo ""
  read -rp "  Lock down an additional account? [y/N]: " MORE_LOCKDOWN
  [[ "${MORE_LOCKDOWN,,}" == "y" ]] || break
  read -rp "    Username: " EXTRA_USER
  if ! id "$EXTRA_USER" &>/dev/null; then
    warn "User '$EXTRA_USER' not found — skipping."
    continue
  fi
  read -rp "    Profile [restricted]: " EXTRA_PROFILE
  EXTRA_PROFILE="${EXTRA_PROFILE:-restricted}"
  bash "$SCRIPT_DIR/kid-lockdown.sh" "$EXTRA_USER" "$EXTRA_PROFILE"
done

# ── 14. ElecFreaks KB mirror ─────────────────────────────────────────────────
echo ""
read -rp "  Set up ElecFreaks KB mirror (offline fallback)? [Y/n]: " DO_KB
if [[ "${DO_KB,,}" != "n" ]]; then
  info "Installing nginx..."
  apt-get install -y nginx wget curl

  info "Configuring nginx on :8080..."
  cp "$SCRIPT_DIR/elecfreaks-nginx.conf" /etc/nginx/sites-available/elecfreaks-kb
  ln -sf /etc/nginx/sites-available/elecfreaks-kb /etc/nginx/sites-enabled/elecfreaks-kb
  # Disable the default nginx site so :80 isn't claimed
  rm -f /etc/nginx/sites-enabled/default
  nginx -t && systemctl enable --now nginx

  info "Installing launcher and sync script..."
  cp "$SCRIPT_DIR/elecfreaks-kb-launcher" /usr/local/bin/elecfreaks-kb-launcher
  cp "$SCRIPT_DIR/elecfreaks-sync.sh"     /usr/local/bin/elecfreaks-sync
  chmod +x /usr/local/bin/elecfreaks-kb-launcher /usr/local/bin/elecfreaks-sync

  info "Installing ElecFreaks desktop icon for '$KID_USER'..."
  KID_DESKTOP="/home/$KID_USER/Desktop"
  mkdir -p "$KID_DESKTOP"
  chown "$KID_USER:$KID_USER" "$KID_DESKTOP"
  ICON_PATH="$KID_DESKTOP/elecfreaks-kb.desktop"
  cp "$SCRIPT_DIR/elecfreaks-kb.desktop" "$ICON_PATH"
  chmod +x "$ICON_PATH"
  chown root:root "$ICON_PATH"
  # Trust the launcher in Nemo so it opens directly without the safety dialog
  sudo -u "$KID_USER" gio set "$ICON_PATH" metadata::trusted true 2>/dev/null || true
  # Immutable — kid cannot delete or move it
  chattr +i "$ICON_PATH"
  info "Icon installed (immutable): $ICON_PATH"

  info "Enabling weekly sync timer..."
  cp "$SCRIPT_DIR/elecfreaks-sync.service" /etc/systemd/system/
  cp "$SCRIPT_DIR/elecfreaks-sync.timer"   /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now elecfreaks-sync.timer

  info "Starting initial mirror in background (this takes a while)..."
  nohup /usr/local/bin/elecfreaks-sync >> /var/log/elecfreaks-sync.log 2>&1 &
  info "Mirror running in background. Check progress: tail -f /var/log/elecfreaks-sync.log"
fi

# ── 15. verify ───────────────────────────────────────────────────────────────
echo ""
info "Waiting for services to start..."
sleep 5

PROXY_OK=false; ADMIN_OK=false; TIMER_OK=false; NGINX_OK=false
systemctl is-active --quiet kid-proxy       && PROXY_OK=true
systemctl is-active --quiet kid-admin       && ADMIN_OK=true
systemctl is-active --quiet kid-update.timer && TIMER_OK=true
systemctl is-active --quiet nginx           && NGINX_OK=true

echo ""
echo "══════════════════════════════════════════"
echo "  Setup complete"
echo "══════════════════════════════════════════"
$PROXY_OK && echo -e "  Proxy  : ${GREEN}running${NC} (localhost:3128)" \
           || echo -e "  Proxy  : ${RED}NOT running${NC} — check: journalctl -u kid-proxy"
$ADMIN_OK && echo -e "  Admin  : ${GREEN}running${NC} (localhost:9090)" \
           || echo -e "  Admin  : ${RED}NOT running${NC} — check: journalctl -u kid-admin"
$TIMER_OK && echo -e "  Updates: ${GREEN}active${NC} (weekly from GitHub)" \
           || echo -e "  Updates: ${RED}not active${NC} — check: systemctl status kid-update.timer"
$NGINX_OK && echo -e "  KB     : ${GREEN}running${NC} (localhost:8080, mirror syncing in background)" \
           || echo -e "  KB     : ${YELLOW}not running${NC} (skipped or check: systemctl status nginx)"
echo ""
echo "  Firefox will trust the proxy CA via ImportEnterpriseRoots."
echo "  Restart Firefox after first login to pick up the new policy."
echo ""
echo "  Kid account       : $KID_USER"
echo "  Parent Review URL : http://localhost:9090"
echo "  Proxy             : 127.0.0.1:3128 (locked in Firefox policy)"
echo ""
echo "  Next: configure Timekpr for '$KID_USER'"
echo "    timekpra --setallowedweekdays $KID_USER 1,2,3,4,5,6,7"
echo "    timekpra --settimelimits $KID_USER 120,120,120,120,120,180,180"
echo ""
warn "If proxy service fails, Firefox cannot reach the internet (fail-closed)."
echo "══════════════════════════════════════════"
