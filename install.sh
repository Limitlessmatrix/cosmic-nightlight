#!/bin/sh
# Install cosmic-nightlight for the current user: a `nightlight` command
# in ~/.local/bin and a systemd user service that starts with the desktop.
set -eu

REPO="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$BIN" "$UNIT_DIR"

cat > "$BIN/nightlight" <<EOF
#!/bin/sh
PYTHONPATH="$REPO" exec python3 -m nightlight "\$@"
EOF
chmod +x "$BIN/nightlight"

cat > "$UNIT_DIR/cosmic-nightlight.service" <<EOF
[Unit]
Description=Blue-light filter overlay for COSMIC
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Environment=PYTHONPATH=$REPO
ExecStart=/usr/bin/python3 -m nightlight run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat > "$APPS/cosmic-nightlight.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Night Light
Comment=Make the screen redder at night
Exec=$BIN/nightlight settings
Icon=weather-clear-night
Categories=Settings;
Keywords=blue light;redshift;warm;night;
EOF

systemctl --user daemon-reload
systemctl --user enable --now cosmic-nightlight.service
echo "Installed. Try: nightlight status"
