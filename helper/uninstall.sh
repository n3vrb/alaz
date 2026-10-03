#!/bin/sh
# Removes the ROG Control GPU helper, polkit policy and the RAPL psys udev rule. Run: sudo helper/uninstall.sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Root gerekli / run as root: sudo $0" >&2
    exit 1
fi
rm -f /usr/local/libexec/rog-control-gfx-helper /usr/share/polkit-1/actions/org.rogcontrol.gfx.policy
rm -f /etc/udev/rules.d/90-rog-control-rapl.rules
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
fi
# restore the stock root-only mode on the psys counter only
for d in /sys/class/powercap/intel-rapl:*; do
    [ -r "$d/name" ] || continue
    if [ "$(cat "$d/name")" = "psys" ] && [ -e "$d/energy_uj" ]; then
        chmod 0400 "$d/energy_uj" || true
    fi
done
echo "Kaldırıldı / removed."
