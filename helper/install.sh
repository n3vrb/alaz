#!/bin/sh
# Installs the ROG Control GPU helper and polkit policy. Run: sudo helper/install.sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Root gerekli / run as root: sudo $0" >&2
    exit 1
fi
here=$(cd "$(dirname "$0")" && pwd)
install -d -m 0755 -o root -g root /usr/local/libexec
install -m 0755 -o root -g root "$here/rog-control-gfx-helper" /usr/local/libexec/rog-control-gfx-helper
install -m 0644 -o root -g root "$here/org.rogcontrol.gfx.policy" /usr/share/polkit-1/actions/org.rogcontrol.gfx.policy
echo "Kuruldu / installed."
