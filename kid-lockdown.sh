#!/usr/bin/env bash
# kid-lockdown.sh — hide admin/system apps from kid account, enable silent auto-updates
# Usage: sudo ./kid-lockdown.sh [username] [profile]
# Profiles: restricted (default) | tween | teen
# Default username: ohmankids

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root (sudo)"; exit 1; }

KID_USER="${1:-ohmankids}"
PROFILE="${2:-restricted}"

KID_HOME=$(getent passwd "$KID_USER" | cut -d: -f6)
[[ -n "$KID_HOME" ]] || { echo "User '$KID_USER' not found"; exit 1; }

# ── Profile definitions ───────────────────────────────────────────────────────
# Always hidden regardless of profile — these are never appropriate for a kid account
HIDE_ALWAYS=(
    mintinstall mintinstall-fp-handler mintinstall-kde
    mintdrivers mintsources mint-meta-codecs
    timeshift-gtk
    mintstick mintstick-format mintstick-format-kde mintstick-kde
    mintbackup mintsysadm mintreport mintreport-tray
    mintlocale mintlocale-im mintwelcome
    cinnamon-settings-users cinnamon-settings-user
    org.gnome.DiskUtility gnome-disk-image-mounter gnome-disk-image-writer
    nm-connection-editor
)

case "$PROFILE" in
    restricted)
        # Age ~6: no terminal, no update viewer, maximum lockdown
        HIDE_PROFILE=(
            mintupdate mintupdate-kde
            org.gnome.Terminal org.gnome.Terminal.Preferences
        )
        ;;
    tween)
        # Age ~9-11: terminal + update viewer visible (planned — not yet implemented)
        # TODO: unlock scratch/coding IDEs, allow display/sound settings
        echo "  [warn] profile 'tween' not yet implemented — applying 'restricted'"
        HIDE_PROFILE=(
            mintupdate mintupdate-kde
            org.gnome.Terminal org.gnome.Terminal.Preferences
        )
        ;;
    teen)
        # Age ~13+: most admin tools still hidden, productivity unlocked (planned)
        # TODO: unlock terminal, nm-connection-editor, mintupdate; keep install/source tools hidden
        echo "  [warn] profile 'teen' not yet implemented — applying 'restricted'"
        HIDE_PROFILE=(
            mintupdate mintupdate-kde
            org.gnome.Terminal org.gnome.Terminal.Preferences
        )
        ;;
    *)
        echo "Unknown profile '$PROFILE'. Valid profiles: restricted, tween, teen"
        exit 1
        ;;
esac

HIDE=("${HIDE_ALWAYS[@]}" "${HIDE_PROFILE[@]}")

# ── Apply overrides ───────────────────────────────────────────────────────────
LOCAL_APPS="$KID_HOME/.local/share/applications"
mkdir -p "$LOCAL_APPS"

echo "Applying profile '$PROFILE' for '$KID_USER' (${#HIDE[@]} entries)..."
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

# ── Auto-updates (system-wide, run once) ─────────────────────────────────────
echo ""
echo "Configuring automatic updates..."

SENTINEL="/var/lib/linuxmint/mintupdate-automatic-upgrades-enabled"
[[ -f "$SENTINEL" ]] || { touch "$SENTINEL"; echo "  created upgrade sentinel"; }
systemctl enable --now mintupdate-automation-upgrade.timer
echo "  mintupdate-automation-upgrade.timer: enabled"

AUTOREMOVE_SENTINEL="/var/lib/linuxmint/mintupdate-automatic-removals-enabled"
[[ -f "$AUTOREMOVE_SENTINEL" ]] || { touch "$AUTOREMOVE_SENTINEL"; echo "  created autoremove sentinel"; }
systemctl enable --now mintupdate-automation-autoremove.timer
echo "  mintupdate-automation-autoremove.timer: enabled"

echo ""
echo "Done. Profile '$PROFILE' applied for '$KID_USER'."
