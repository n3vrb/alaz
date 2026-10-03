#!/bin/sh
# ROG Control user installer (no sudo). Installs into ~/.local.
#   ./install.sh [--prefix DIR] [--uninstall [--purge]]
# --prefix DIR  use DIR as $HOME (for testing)
set -eu

here=$(cd "$(dirname "$0")" && pwd)
prefix=""
uninstall=0
purge=0
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) [ $# -ge 2 ] || { echo "--prefix needs a directory" >&2; exit 2; }; prefix=$2; shift 2 ;;
        --prefix=*) prefix=${1#--prefix=}; shift ;;
        --uninstall) uninstall=1; shift ;;
        --purge) purge=1; shift ;;
        -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
icon_file="$data_home/icons/hicolor/scalable/apps/rog-control.svg"
autostart_file="$config_home/autostart/rog-control.desktop"

refresh_caches() {
    if [ -z "$prefix" ]; then
        command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data_home/applications" >/dev/null 2>&1 || true
        command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
    fi
}

if [ "$uninstall" -eq 1 ]; then
    rm -rf "$app_dir"
    rm -f "$bin_file" "$desktop_file" "$icon_file" "$autostart_file"
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
mkdir -p "$data_home" "$HOME/.local/bin" "$data_home/applications" "$(dirname "$icon_file")"
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

cp "$here/assets/icon.svg" "$icon_file"

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

echo "Installed ROG Control:"
echo "  $bin_file"
echo "  $app_dir"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add $HOME/.local/bin to your PATH" ;; esac
echo
echo "Optional (needs root): GPU mode switching helper, polkit policy and the RAPL psys"
echo "udev rule (total system power readout). Run:"
echo "  sudo $app_dir/helper/install.sh"
