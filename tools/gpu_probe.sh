#!/bin/sh
# Read-only snapshot of who touches the NVIDIA dGPU (live-switch research, step A).
# Run with sudo to see processes of other users (gdm, root daemons). Changes nothing.
# Usage: sudo sh tools/gpu_probe.sh > gpu_probe_$(date +%s).txt 2>&1

echo "== date / boot"; date; uptime; cat /proc/cmdline
echo "== supergfxd"; supergfxctl -g 2>&1; supergfxctl -S 2>&1
grep -E '"mode"|hotplug_type|always_reboot' /etc/supergfxd.conf
echo "dgpu_disable=$(cat /sys/devices/platform/asus-nb-wmi/dgpu_disable 2>&1)"
echo "gpu_mux_mode=$(cat /sys/devices/platform/asus-nb-wmi/gpu_mux_mode 2>&1)"

echo "== PCI (NVIDIA)"
for d in /sys/bus/pci/devices/*; do
    [ "$(cat "$d/vendor")" = 0x10de ] || continue
    drv=$(basename "$(readlink "$d/driver" 2>/dev/null)" 2>/dev/null)
    echo "$(basename "$d") class=$(cat "$d/class") driver=${drv:-none} runtime=$(cat "$d/power/runtime_status" 2>/dev/null) control=$(cat "$d/power/control" 2>/dev/null)"
done

echo "== modules"; lsmod | grep -E '^(nvidia|i915|xe) ' ; lsmod | grep -E '^nvidia'

echo "== DRM cards"
for c in /sys/class/drm/card[0-9] /sys/class/drm/renderD*; do
    [ -e "$c" ] || continue
    drv=$(basename "$(readlink "$c/device/driver")")
    echo "$(basename "$c") -> $(basename "$(readlink -f "$c/device")") driver=$drv tags=$(udevadm info -q property "$c" 2>/dev/null | grep -E '^(TAGS|CURRENT_TAGS)=' | tr '\n' ' ')"
done
echo "-- connectors"
for c in /sys/class/drm/card*-*; do echo "$(basename "$c") $(cat "$c/status") enabled=$(cat "$c/enabled" 2>/dev/null)"; done

echo "== holders of /dev/nvidia*"
for p in /proc/[0-9]*; do
    l=$(ls -l "$p/fd" 2>/dev/null | grep -o '/dev/nvidia[a-z0-9-]*' | sort -u | tr '\n' ' ')
    [ -n "$l" ] && echo "pid=$(basename "$p") user=$(stat -c %U "$p") comm=$(cat "$p/comm") -> $l"
done

echo "== holders of NVIDIA DRM nodes"
for c in /sys/class/drm/card[0-9] /sys/class/drm/renderD*; do
    [ "$(basename "$(readlink "$c/device/driver")")" = nvidia ] || continue
    n=/dev/dri/$(basename "$c")
    for p in /proc/[0-9]*; do
        ls -l "$p/fd" 2>/dev/null | grep -q " $n\$" && echo "$n pid=$(basename "$p") user=$(stat -c %U "$p") comm=$(cat "$p/comm")"
    done
done

echo "== processes with NVIDIA libs mapped"
for p in /proc/[0-9]*; do
    grep -qE 'libnvidia|libEGL_nvidia|libGLX_nvidia' "$p/maps" 2>/dev/null && echo "pid=$(basename "$p") user=$(stat -c %U "$p") comm=$(cat "$p/comm")"
done

echo "== gnome-shell env (GPU related)"
for p in $(pgrep -x gnome-shell) $(pgrep -x Xwayland); do
    echo "pid=$p comm=$(cat /proc/$p/comm)"
    tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -E '^(__EGL|__GLX|__NV|MUTTER|DRI_PRIME|VK_)' || echo "  (none)"
done

echo "== services"; systemctl is-active nvidia-persistenced supergfxd gdm 2>&1
echo "== mutter/kernel log (this boot, GPU lines)"
journalctl -b --no-pager -o short-monotonic 2>/dev/null | grep -iE 'mutter|gnome-shell.*(gpu|drm|kms)|nvidia|nvrm|fallen off' | tail -60
