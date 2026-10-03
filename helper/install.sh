#!/bin/sh
# Installs the ROG Control GPU helper, polkit policy and the RAPL psys udev rule. Run: sudo helper/install.sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Root gerekli / run as root: sudo $0" >&2
    exit 1
fi
here=$(cd "$(dirname "$0")" && pwd)
install -d -m 0755 -o root -g root /usr/local/libexec
install -m 0755 -o root -g root "$here/rog-control-gfx-helper" /usr/local/libexec/rog-control-gfx-helper
install -m 0644 -o root -g root "$here/org.rogcontrol.gfx.policy" /usr/share/polkit-1/actions/org.rogcontrol.gfx.policy
install -d -m 0755 -o root -g root /etc/udev/rules.d
install -m 0644 -o root -g root "$here/90-rog-control-rapl.rules" /etc/udev/rules.d/90-rog-control-rapl.rules
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=powercap --action=change || true
    udevadm settle --timeout=5 || true
fi
echo "Kuruldu / installed."
