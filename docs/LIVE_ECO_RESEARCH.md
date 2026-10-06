# Live Eco (no reboot) — research, 2026-10-06

Question from the owner: Windows (G-Helper) switches Eco ↔ Standard live; can Linux do it too?
This file records what the source code says, what the earlier failures on the reference machine
mean in that light, and a staged test plan. **Nothing here is implemented in the app.** Hard rule 1
(`CLAUDE.md`) stays in force until the owner has run the tests below and they pass.

Confidence tags: **[src]** = read in source code, **[obs]** = observed on the reference machine
(`docs/PHASE0_SYSTEM_FIX.md`), **[anec]** = forum/issue anecdote, **[inf]** = inference.

## 1. Why Windows can

- G-Helper Eco (`app/Gpu/GPUModeControl.cs`, `HardwareControl.cs`) [src]: kills a few known
  launchers (and, if the `kill_gpu_apps` option is on, every process NVAPI reports on the dGPU),
  drops its NVAPI handles, stops `NvContainerLocalSystem` / `NVDisplay.ContainerLocalSystem`,
  then writes ACPI `GPUEco` (DEVID `0x00090020`, the same WMI call Linux exposes as
  `dgpu_disable`). Standard: write 0, wait ~5.5 s, restart the NV services, retry NVAPI init,
  force eco=0 again if the GPU did not come back. Ultimate: eco=0 first, then MUX
  (`0x00090016`) = 0, then `shutdown /r` — **even Windows reboots for the MUX**.
- On Windows the dGPU is a render-only WDDM adapter; DWM composes on the iGPU. When the card
  disappears, dxgkrnl handles it as a PnP surprise removal (`DxgkDdiNotifySurpriseRemoval`) and
  apps get "device lost" and recover [inf, consistent with the code above].

## 2. Why it broke on Linux

- `supergfxctl -m Integrated` with `always_reboot: true` [src, `supergfxctl` 5.2.7 `actions.rs`]:
  `always_reboot` only skips *wait for logout / stop display manager / start display manager*.
  The destructive steps still run inside the live session: stop persistenced/powerd →
  **`KillNvidia` = `lsof /dev/nvidia0` + `kill -9` on every holder** (gnome-shell and Xwayland are
  holders) → `rmmod nvidia_drm nvidia_modeset nvidia_uvm nvidia` → unbind + PCI remove →
  `dgpu_disable=1`. That is exactly the observed session crash [obs].
- mutter (GNOME 46, also 47–49 and main) [src, `meta-backend-native.c`, `meta-backend.c`]:
  a hot-added DRM card is adopted as a secondary GPU (`add_drm_device`), but there is **no
  remove path** — a GPU mutter has adopted is held until gnome-shell exits. A udev "remove"
  only re-probes KMS. Newer GNOME does not change this.
- NVIDIA 580 [src, open-gpu-kernel-modules `nv-pci.c`]: `nv_pci_remove` waits in a loop while any
  process holds `/dev/nvidia0`. Unbinding/removing the card while gnome-shell holds it hangs
  forever — the `nv_pci_remove` endless loop seen on 2026-10-02 [obs].
- Eco exit: when the card comes back with autoprobe on, the driver binds, a new DRM card
  appears, mutter tries to hot-add it and gnome-shell froze [obs; matches an upstream report
  "Failed to hotplug secondary gpu … ENODEV" [anec]].
- asus-wmi `dgpu_disable` [src, kernel `asus-wmi.c`]: just a firmware call; it does not unbind
  anything. If a driver is still bound, the card "falls off the bus" under it. Refused while the
  MUX is in dGPU mode. Newer kernels also expose it via `asus-armoury` firmware attributes.

**The real difference from Windows:** GNOME's compositor (and possibly Xwayland through
libglvnd/EGL) opens the NVIDIA device at login and never lets go, and the NVIDIA kernel driver
cannot be removed while anyone holds it. Windows' compositor never depended on the dGPU.

## 3. The only route that fits GNOME: never let the session touch the dGPU

mutter supports a udev tag, `mutter-device-ignore` [src, since mutter 41; checked both at startup
and for hot-added cards]. Upstream only uses it for `vkms`. A rule tagging the NVIDIA card:

```
# /etc/udev/rules.d/61-mutter-ignore-nvidia.rules   (candidate — NOT tested)
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", SUBSYSTEMS=="pci", ATTRS{vendor}=="0x10de", TAG+="mutter-device-ignore"
```

Trade-offs:
- mutter never uses the dGPU for displays → **HDMI/DP ports wired to the dGPU stop working, also
  in Standard mode.** (Which ports are wired where must be checked: Stage 0.)
- Render offload (games via `prime-run`/Vulkan) should still work through dmabuf copy [inf].
- Affects the GDM greeter too. Does not change driver load order (rule 3 still: one-boot test).
- **Unknown:** whether gnome-shell / Xwayland still open `/dev/nvidia*` *without* mutter adopting
  the card (e.g. glvnd loading `libEGL_nvidia` and enumerating devices). If they do, live Eco
  entry is impossible without a session-wide `__EGL_VENDOR_LIBRARY_FILENAMES` override, which
  costs EGL offload. Stage 0 answers this.

Candidate procedures (all untested; the owner runs root commands; `01:00.0` is an example address):

**Enter Eco live** — only if Stage 0/1 show **no holder** of `/dev/nvidia*` besides helpers:
1. `sudo fuser -v /dev/nvidia* /dev/dri/card*` — any gnome-shell/Xwayland/app holder → STOP.
   Never kill them; never unbind with a holder (hang).
2. `sudo systemctl stop nvidia-persistenced nvidia-powerd supergfxd` (whichever exist).
3. `sudo modprobe -r nvidia_drm nvidia_modeset nvidia_uvm nvidia` — failure here is harmless
   ("in use") → `sudo modprobe nvidia_drm` and stop.
4. `echo 1 | sudo tee /sys/bus/pci/devices/0000:01:00.{1,0}/remove`
5. `echo 1 | sudo tee /sys/devices/platform/asus-nb-wmi/dgpu_disable`
6. Config `"mode": "Integrated"` so the next boot agrees; `sudo systemctl start supergfxd`.

**Leave Eco live** — the first half is already tested [obs]:
1. `sudo systemctl stop supergfxd`; `echo 0 | sudo tee /sys/bus/pci/drivers_autoprobe`
2. `echo 0 | sudo tee /sys/devices/platform/asus-nb-wmi/dgpu_disable` (5–10 s); card returns driverless.
3. New, untested: with the udev rule active, `sudo modprobe nvidia_drm` and bind the card
   (`echo 0000:01:00.0 | sudo tee /sys/bus/pci/drivers/nvidia/bind`). Expect mutter to log
   "Ignoring DRM device" and the desktop to stay unaffected.
4. `echo 1 | sudo tee /sys/bus/pci/drivers_autoprobe`; config Hybrid; start supergfxd.
   Fallback if anything misbehaves: leave the card driverless and reboot (= today's behaviour).

## 4. Staged test plan (owner)

**Stage 0 — read-only, zero risk** (in Standard mode, logged in, no game running):

```bash
gnome-shell --version; cat /sys/module/nvidia/version; uname -r
for c in /sys/class/drm/card[0-9]; do echo "$c vendor=$(cat $c/device/vendor) $(basename $(readlink -f $c/device))"; done
ls /sys/class/drm/ | grep -E 'card[0-9]-'          # which connectors (HDMI/DP/eDP) belong to which card
for p in $(pgrep -x gnome-shell) $(pgrep -x Xwayland); do
  echo "== $p $(cat /proc/$p/comm)"
  ls -l /proc/$p/fd 2>/dev/null | grep -E 'nvidia|/dev/dri' | awk '{print $NF}' | sort | uniq -c
  grep -oE '[^ /]*nvidia[^ ]*' /proc/$p/maps | sort -u
done
sudo fuser -v /dev/nvidia* /dev/dri/* 2>&1
ls /sys/class/firmware-attributes/ 2>/dev/null
journalctl -b --user -o cat | grep -iE 'Ignoring DRM|secondary gpu|hotplug' | tail
```

Paste the output. It tells us (a) whether gnome-shell/Xwayland hold the NVIDIA nodes and why
(fd vs. loaded library), (b) which external ports hang off the dGPU, (c) the exact driver.

**Stage 1 — udev rule only** (one boot; rollback: delete the file,
`sudo udevadm control --reload`, reboot). Check `udevadm info /dev/dri/cardN | grep TAGS`,
"Ignoring DRM device" in the user journal, re-run Stage 0, test a Vulkan game with offload.

**Stage 2 — live Eco exit** (lower risk; TTY open with `journalctl -kf`). **Stage 3 — live Eco
entry**, only if Stage 0/1 showed zero holders; hard-reboot recovery in mind.

Only after Stage 2/3 pass repeatedly would the app get a "live" path (in the root helper, with a
`fuser` gate that refuses when anything holds the device), and hard rule 1 be revised.

## 5. Verdict

- **Leave Eco live:** probably feasible, at the cost of dGPU-wired external ports (udev rule).
- **Enter Eco live:** feasible only if the session does not hold `/dev/nvidia*` once mutter
  ignores the card — unknown until Stage 0/1. If it does, not feasible on GNOME without a
  logout (or a session-wide EGL override with offload costs).
- KDE Plasma (kwin) and wlroots compositors do have GPU hot-unplug support [src]; the NVIDIA
  holder limit applies there too.

## Sources
- G-Helper: https://github.com/seerge/g-helper (`app/Gpu/GPUModeControl.cs`, `app/AsusACPI.cs`, `app/HardwareControl.cs`, `app/Program.cs`)
- supergfxctl 5.2.7: https://gitlab.com/asus-linux/supergfxctl (`src/actions.rs`, `src/special_asus.rs`, `src/config.rs`)
- mutter gnome-46: https://github.com/GNOME/mutter/blob/gnome-46/src/backends/native/meta-backend-native.c, `data/61-mutter.rules`, `src/backends/native/meta-udev.c`
- NVIDIA open kernel modules 580: https://github.com/NVIDIA/open-gpu-kernel-modules (`kernel-open/nvidia/nv-pci.c`, `nvidia-drm/nvidia-drm-drv.c`)
- Kernel: `drivers/platform/x86/asus-wmi.c`, `drivers/platform/x86/asus-armoury.c`
- kwin GPU hotplug: https://github.com/KDE/kwin/blob/master/src/backends/drm/drm_backend.cpp
