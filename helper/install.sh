#!/bin/sh
# Installs the Alaz GPU helper, polkit policy, the RAPL psys udev rule and the peripherals udev rule. Run: sudo helper/install.sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Root gerekli / run as root: sudo $0" >&2
    exit 1
fi
here=$(cd "$(dirname "$0")" && pwd)
# Remove the files of the former name (ROG Control) if present.
rm -f /usr/local/libexec/rog-control-gfx-helper \
      /usr/share/polkit-1/actions/org.rogcontrol.gfx.policy \
      /etc/udev/rules.d/90-rog-control-rapl.rules
install -d -m 0755 -o root -g root /usr/local/libexec
install -m 0755 -o root -g root "$here/alaz-gfx-helper" /usr/local/libexec/alaz-gfx-helper
install -m 0644 -o root -g root "$here/org.alaz.gfx.policy" /usr/share/polkit-1/actions/org.alaz.gfx.policy
install -d -m 0755 -o root -g root /etc/udev/rules.d
install -m 0644 -o root -g root "$here/90-alaz-rapl.rules" /etc/udev/rules.d/90-alaz-rapl.rules
install -m 0644 -o root -g root "$here/70-alaz-peripherals.rules" /etc/udev/rules.d/70-alaz-peripherals.rules
# Live GPU switching preconditions (MUX=1 only). Rules only take effect for devices (re)added later:
# deliberately NO "udevadm trigger" on drm, so a running session is not disturbed.
install -m 0644 -o root -g root "$here/61-alaz-mutter-ignore-nvidia.rules" /etc/udev/rules.d/61-alaz-mutter-ignore-nvidia.rules
install -m 0644 -o root -g root "$here/72-alaz-nvidia-render-noaccess.rules" /etc/udev/rules.d/72-alaz-nvidia-render-noaccess.rules
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=powercap --action=change || true
    udevadm trigger --subsystem-match=hidraw --action=change || true
    udevadm settle --timeout=5 || true
fi
echo "Kuruldu / installed."
echo "Canlı GPU geçişi için çıkış yapıp tekrar giriş yapın (ve ./install.sh çalıştırın) / for live GPU switching log out and in again (and run ./install.sh)."
