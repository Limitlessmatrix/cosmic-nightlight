#!/bin/sh
# Remove the service and command. Your config in ~/.config/cosmic-nightlight is kept.
set -eu
systemctl --user disable --now cosmic-nightlight.service 2>/dev/null || true
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/cosmic-nightlight.service" "$HOME/.local/bin/nightlight" \
  "${XDG_DATA_HOME:-$HOME/.local/share}/applications/cosmic-nightlight.desktop"
systemctl --user daemon-reload
echo "Uninstalled."
