#!/bin/sh
# Removes the ROG Control GPU helper and polkit policy. Run: sudo helper/uninstall.sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Root gerekli / run as root: sudo $0" >&2
    exit 1
fi
rm -f /usr/local/libexec/rog-control-gfx-helper /usr/share/polkit-1/actions/org.rogcontrol.gfx.policy
echo "Kaldırıldı / removed."
