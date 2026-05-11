#!/usr/bin/env bash
# kid-lockdown.sh — hide admin/system apps from kid account, enable silent auto-updates
# Usage: sudo ./kid-lockdown.sh [username]
# Default username: ohmankids

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root (sudo)"; exit 1; }

KID_USER="${1:-ohmankids}"
KID_HOME=$(getent passwd "$KID_USER" | cut -d: -f6)
[[ -n "$KID_HOME" ]] || { echo "User '$KID_USER' not found"; exit 1; }

LOCAL_APPS="$KID_HOME/.local/share/applications"
mkdir -p "$LOCAL_APPS"

# Apps to hide — overrides /usr/share/applications/ per-user, no uninstall needed
HIDE=(
    # Package / app management
    mintinstall
    mintinstall-fp-handler
    mintinstall-kde
    mintupdate
    mintupdate-kde
    mintdrivers
    mintsources
    mint-meta-codecs

    # System tools
    timeshift-gtk
    mintstick
    mintstick-format
    mintstick-format-kde
    mintstick-kde
    mintbackup
    mintsysadm
    mintreport
    mintreport-tray

    # Settings / locale / welcome
    mintlocale
    mintlocale-im
    mintwelcome
    cinnamon-settings-users
    cinnamon-settings-user

    # Disk tools
    org.gnome.DiskUtility
    gnome-disk-image-mounter
    gnome-disk-image-writer

    # Network editor + terminal
    nm-connection-editor
    org.gnome.Terminal
    org.gnome.Terminal.Preferences
)

echo "Hiding ${#HIDE[@]} entries for $KID_USER..."
for app in "${HIDE[@]}"; do
    target="$LOCAL_APPS/${app}.desktop"
    if [[ ! -f "$target" ]]; then
        printf '[Desktop Entry]\nNoDisplay=true\n' > "$target"
        echo "  hidden: $app"
    else
        echo "  already hidden: $app"
    fi
done
chown -R "$KID_USER:$KID_USER" "$LOCAL_APPS"

# Enable mintupdate automatic upgrades — daily systemd timer, no GUI interaction needed
echo ""
echo "Configuring automatic updates..."
SENTINEL="/var/lib/linuxmint/mintupdate-automatic-upgrades-enabled"
if [[ ! -f "$SENTINEL" ]]; then
    touch "$SENTINEL"
    echo "  created upgrade sentinel"
else
    echo "  upgrade sentinel already present"
fi
systemctl enable --now mintupdate-automation-upgrade.timer
echo "  mintupdate-automation-upgrade.timer: enabled"

# Auto-remove orphaned packages after upgrades
AUTOREMOVE_SENTINEL="/var/lib/linuxmint/mintupdate-automatic-removals-enabled"
if [[ ! -f "$AUTOREMOVE_SENTINEL" ]]; then
    touch "$AUTOREMOVE_SENTINEL"
    echo "  created autoremove sentinel"
else
    echo "  autoremove sentinel already present"
fi
systemctl enable --now mintupdate-automation-autoremove.timer
echo "  mintupdate-automation-autoremove.timer: enabled"

echo ""
echo "Done. Lockdown applied for '$KID_USER'."
