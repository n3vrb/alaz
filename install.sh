#!/bin/sh
# ROG Control user installer (no sudo). Installs into ~/.local.
#   ./install.sh [--prefix DIR] [--autostart] [--start] [--uninstall [--purge]]
# --prefix DIR  use DIR as $HOME (for testing; systemctl is skipped)
# --autostart   enable rog-control.service (start at every login)
# --start       also start the service now
set -eu

here=$(cd "$(dirname "$0")" && pwd)
prefix=""
uninstall=0
purge=0
autostart=0
start=0
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) [ $# -ge 2 ] || { echo "--prefix needs a directory" >&2; exit 2; }; prefix=$2; shift 2 ;;
        --prefix=*) prefix=${1#--prefix=}; shift ;;
        --uninstall) uninstall=1; shift ;;
        --purge) purge=1; shift ;;
        --autostart) autostart=1; shift ;;
        --start) start=1; shift ;;
        -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ -n "$prefix" ]; then
    mkdir -p "$prefix"
    HOME=$(cd "$prefix" && pwd)
    export HOME
    data_home="$HOME/.local/share"
    config_home="$HOME/.config"
else
    data_home=${XDG_DATA_HOME:-$HOME/.local/share}
    config_home=${XDG_CONFIG_HOME:-$HOME/.config}
fi
app_dir="$data_home/rog-control"
bin_file="$HOME/.local/bin/rog-control"
desktop_file="$data_home/applications/rog-control.desktop"
icon_file="$data_home/icons/hicolor/scalable/apps/rog-control.svg"  # legacy, removed
icon_sizes="16 24 32 48 64 128 256 512"
autostart_file="$config_home/autostart/rog-control.desktop"
unit_dir="$config_home/systemd/user"
unit_file="$unit_dir/rog-control.service"

# systemctl is skipped in --prefix test mode or when ROG_CONTROL_NO_SYSTEMCTL=1.
use_systemctl=1
{ [ -n "$prefix" ] || [ "${ROG_CONTROL_NO_SYSTEMCTL:-0}" = 1 ] || ! command -v systemctl >/dev/null 2>&1; } && use_systemctl=0
sctl() { if [ "$use_systemctl" -eq 1 ]; then systemctl --user "$@"; else return 0; fi; }

refresh_caches() {
    if [ -z "$prefix" ]; then
        command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data_home/applications" >/dev/null 2>&1 || true
        command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
    fi
}

if [ "$uninstall" -eq 1 ]; then
    sctl disable --now rog-control.service >/dev/null 2>&1 || true
    rm -f "$unit_file"
    sctl daemon-reload >/dev/null 2>&1 || true
    rm -rf "$app_dir"
    rm -f "$bin_file" "$desktop_file" "$icon_file" "$autostart_file"
    for s in $icon_sizes; do rm -f "$data_home/icons/hicolor/${s}x${s}/apps/rog-control.png"; done
    refresh_caches
    if [ "$purge" -eq 1 ]; then
        rm -rf "$config_home/rog-control"
        echo "Removed ROG Control and its settings."
    else
        echo "Removed ROG Control. Settings kept in $config_home/rog-control (use --purge to delete)."
    fi
    echo "The privileged helper (if installed) is removed with: sudo ./helper/uninstall.sh"
    exit 0
fi

# --- checks ----------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import PyQt6.QtWidgets, psutil' >/dev/null 2>&1; then
    echo "Missing Python dependencies (PyQt6 and/or psutil). Install them with:" >&2
    echo "  sudo apt install python3-pyqt6 python3-psutil python3-gi" >&2
    exit 1
fi
python3 -c 'import gi' >/dev/null 2>&1 || echo "note: python3-gi not found; Wayland display control will be unavailable (sudo apt install python3-gi)"
if command -v systemctl >/dev/null 2>&1; then
    for svc in asusd supergfxd; do
        systemctl is-active --quiet "$svc" 2>/dev/null || echo "warning: $svc.service is not active; the related features will be unavailable"
    done
fi

# --- install ---------------------------------------------------------------
mkdir -p "$data_home" "$HOME/.local/bin" "$data_home/applications"
tmp="$app_dir.new.$$"
rm -rf "$tmp"
mkdir -p "$tmp"
cp -R "$here/rog_control" "$tmp/rog_control"
mkdir -p "$tmp/helper"
for f in "$here"/helper/*; do [ -f "$f" ] && cp "$f" "$tmp/helper/"; done
find "$tmp" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$app_dir.old"
[ -e "$app_dir" ] && mv "$app_dir" "$app_dir.old"
mv "$tmp" "$app_dir"
rm -rf "$app_dir.old"

cat > "$bin_file.tmp" <<EOF
#!/bin/sh
PYTHONPATH="$app_dir\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m rog_control "\$@"
EOF
chmod 0755 "$bin_file.tmp"
mv "$bin_file.tmp" "$bin_file"

rm -f "$icon_file"
for s in $icon_sizes; do
    mkdir -p "$data_home/icons/hicolor/${s}x${s}/apps"
    cp "$here/assets/icons/rog-control-$s.png" "$data_home/icons/hicolor/${s}x${s}/apps/rog-control.png"
done

cat > "$desktop_file" <<'EOF'
[Desktop Entry]
Type=Application
Name=ROG Control
Comment=Control app for ASUS ROG laptops
Comment[tr]=ASUS ROG dizüstü bilgisayarlar için kontrol uygulaması
Exec=rog-control
Icon=rog-control
Terminal=false
Categories=Settings;HardwareSettings;System;
StartupWMClass=rog-control
EOF
refresh_caches

mkdir -p "$unit_dir"
cp "$here/packaging/rog-control.service" "$unit_file"
sctl daemon-reload || echo "warning: systemctl --user daemon-reload failed"
if [ "$autostart" -eq 1 ]; then
    if [ -f "$autostart_file" ]; then
        rm -f "$autostart_file"
        echo "Removed old autostart entry $autostart_file (replaced by the systemd service)."
    fi
    if [ "$use_systemctl" -eq 0 ]; then
        echo "(systemctl skipped: would enable rog-control.service)"
    elif sctl enable rog-control.service; then
        echo "Enabled rog-control.service (starts at every login)."
    else
        echo "warning: could not enable rog-control.service" >&2
    fi
fi
if [ "$start" -eq 1 ]; then
    sctl start rog-control.service || echo "warning: could not start rog-control.service" >&2
fi

echo "Installed ROG Control:"
echo "  $bin_file"
echo "  $app_dir"
echo "  $unit_file"
[ "$autostart" -eq 1 ] || echo "Start at login: ./install.sh --autostart  (or the toggle in Settings)"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add $HOME/.local/bin to your PATH" ;; esac
echo
echo "Optional (needs root): GPU mode switching helper, polkit policy and the RAPL psys"
echo "udev rule (total system power readout). Run:"
echo "  sudo $app_dir/helper/install.sh"
