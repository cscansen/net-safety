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
  while true; do
    read -rsp "  Set password for '$KID_USER': " KP1; echo
    read -rsp "  Confirm password:              " KP2; echo
    [[ "$KP1" == "$KP2" ]] && break
    warn "Passwords don't match, try again."
  done
  echo "$KID_USER:$KP1" | chpasswd
  info "User '$KID_USER' created."
fi

# Persist username for Timekpr and future reference
mkdir -p /etc/kid-proxy
echo "$KID_USER" > /etc/kid-proxy/kid-user
info "Kid username '$KID_USER' saved to /etc/kid-proxy/kid-user"

# ── 2. dependencies ──────────────────────────────────────────────────────────
info "Installing system dependencies..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv libnss3-tools openssl git rsync

info "Installing Python packages..."
pip3 install --quiet mitmproxy flask bcrypt

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
sudo -u kidproxy python3 -c "import sys; sys.path.insert(0,'/opt/kid-proxy'); import db; db.init_db()"

# ── 7. admin password ────────────────────────────────────────────────────────
echo ""
while true; do
  read -rsp "  Set admin password: " PW1; echo
  read -rsp "  Confirm password:   " PW2; echo
  [[ "$PW1" == "$PW2" ]] && break
  warn "Passwords don't match, try again."
done

python3 -c "
import bcrypt, sys
h = bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode()
print(h)
" "$PW1" > /etc/kid-proxy/admin.hash

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
sudo -u kidproxy mitmdump --set confdir=/etc/kid-proxy --listen-port 13128 &
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

# ── 12. auto-update deploy key ───────────────────────────────────────────────
info "Setting up auto-update deploy key..."
DEPLOY_KEY=/etc/kid-proxy/deploy_key
if [ ! -f "$DEPLOY_KEY" ]; then
  ssh-keygen -t ed25519 -f "$DEPLOY_KEY" -N "" -C "net-safety-deploy@$(hostname)" -q
fi
chmod 600 "$DEPLOY_KEY"
chmod 644 "${DEPLOY_KEY}.pub"

echo ""
echo "══════════════════════════════════════════"
echo "  Add this deploy key to the net-safety GitHub repo"
echo "  (Settings → Deploy keys → Add key — read-only)"
echo ""
cat "${DEPLOY_KEY}.pub"
echo "══════════════════════════════════════════"
echo ""
read -rp "  Press Enter once the deploy key has been added to GitHub..."

# ── 13. clone repo for auto-update ──────────────────────────────────────────
REPO_DIR=/opt/net-safety-src
REPO_URL="git@github.com:cscansen/net-safety.git"
GIT_SSH="ssh -i $DEPLOY_KEY -o StrictHostKeyChecking=no"

info "Cloning net-safety repo to $REPO_DIR..."
if [ -d "$REPO_DIR/.git" ]; then
  info "Repo already cloned, skipping."
else
  GIT_SSH_COMMAND="$GIT_SSH" git clone "$REPO_URL" "$REPO_DIR"
fi

# Install update script and enable timer
cp "$SCRIPT_DIR/update.sh" /usr/local/bin/kid-proxy-update
chmod +x /usr/local/bin/kid-proxy-update
systemctl enable --now kid-update.timer
info "Auto-update timer enabled (pulls every 15 min)."

# ── 14. verify ───────────────────────────────────────────────────────────────
echo ""
info "Waiting for services to start..."
sleep 5

PROXY_OK=false; ADMIN_OK=false; TIMER_OK=false
systemctl is-active --quiet kid-proxy  && PROXY_OK=true
systemctl is-active --quiet kid-admin  && ADMIN_OK=true
systemctl is-active --quiet kid-update.timer && TIMER_OK=true

echo ""
echo "══════════════════════════════════════════"
echo "  Setup complete"
echo "══════════════════════════════════════════"
$PROXY_OK && echo -e "  Proxy  : ${GREEN}running${NC} (localhost:3128)" \
           || echo -e "  Proxy  : ${RED}NOT running${NC} — check: journalctl -u kid-proxy"
$ADMIN_OK && echo -e "  Admin  : ${GREEN}running${NC} (localhost:9090)" \
           || echo -e "  Admin  : ${RED}NOT running${NC} — check: journalctl -u kid-admin"
$TIMER_OK && echo -e "  Updates: ${GREEN}active${NC} (every 15 min from GitHub)" \
           || echo -e "  Updates: ${RED}not active${NC} — check: systemctl status kid-update.timer"
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
