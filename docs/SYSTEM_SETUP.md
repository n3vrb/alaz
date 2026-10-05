# System setup and troubleshooting guide

This guide documents the system-level changes that made Alaz reliable on the
machine it was developed on, and the dead ends we hit on the way. It is a record of what
worked **on one machine**, not a universal recipe.

> **Reference machine:** ASUS ROG Zephyrus (2025), Intel Core Ultra 9 285H, NVIDIA RTX 5070
> Laptop GPU (proprietary driver 580.x), Zorin OS 18 (Ubuntu 24.04 based), GNOME on Wayland,
> asusd 6.0.12, supergfxd 5.2.7, dual boot with Windows. Everything below was verified only
> there. On other models, treat each step as a hypothesis and test it.

> **Warning.** Several steps touch the boot chain (GRUB, initramfs, driver loading, the
> dGPU power state). A wrong change can give you a black screen at boot. Every step below
> has a rollback; read it **before** you apply the step, and keep a way to boot into
> recovery (a live USB, or the GRUB menu). You apply these at your own risk.

None of these steps is required to run the app. The app works without them, but GPU mode
switching and profile handling are only reliable once they are in place.

Placeholders used below: `<disk-partition>` is your EFI/Windows partition as shown by GRUB;
`~` is your home directory.

---

## 0. Background in one paragraph

On this hardware, switching the GPU while the desktop is running (`supergfxctl -m ...`)
either kills or freezes GNOME on Wayland, in both directions. The only safe way to change
GPU mode is at boot. Everything in this guide serves that: make the boot deterministic,
remove other programs that fight over the GPU or the power profile, and use known-good
manual procedures for entering and leaving Eco mode.

---

## 1. Driver sanity

**Why.** The loaded kernel module and the user-space libraries must be the same version.
After an upgrade they can differ until you reboot. Stale metapackages and DKMS leftovers
also make debugging confusing.

**Check**

```bash
cat /proc/driver/nvidia/version     # kernel module version
nvidia-smi                          # user space; must run without errors
dpkg -l | grep -i nvidia            # look for leftover packages (state "rc" = config only)
```

**Fix.** Reboot after a driver upgrade so module and user space match. Remove packages you
no longer need, for example an old driver metapackage (`sudo apt remove <old-metapackage>`)
or config-only leftovers (`sudo apt purge <package-in-rc-state>`). On the reference machine
the stale ones were an old `nvidia-driver-570-open` metapackage and a leftover
`nvidia-dkms-580`.

**Rollback.** Reinstall the removed package with `apt install`.

---

## 2. supergfxd configuration

**Why.** With the default `hotplug_type: None`, supergfxd after a Windows (G-Helper) Eco
session "re-enabled" a dGPU that the firmware had switched off. In the meantime the NVIDIA
module probed the half-removed card and logged "GPU has fallen off the bus".
`hotplug_type: Asus` makes Eco use the firmware switch (`dgpu_disable`), so the card
disappears from the PCI bus completely and the NVIDIA module never sees it. If it boots with
`dgpu_disable=1` it adopts Integrated mode, which matches a Windows-side Eco.
`always_reboot` makes mode changes apply at reboot instead of trying to stop the display
manager live.

**Apply.** Back up, then edit `/etc/supergfxd.conf` (JSON) so it contains:

```json
"hotplug_type": "Asus",
"always_reboot": true
```

```bash
sudo cp /etc/supergfxd.conf /etc/supergfxd.conf.bak
sudo nano /etc/supergfxd.conf
sudo systemctl restart supergfxd
```

**Verify**

```bash
grep -E 'hotplug_type|always_reboot|"mode"' /etc/supergfxd.conf
systemctl is-active supergfxd
```

**Roll back.** `sudo cp /etc/supergfxd.conf.bak /etc/supergfxd.conf && sudo systemctl restart supergfxd`

---

## 3. Mask the services that fight over the GPU and the power profile

### 3a. power-profiles-daemon

**Why.** `power-profiles-daemon` and `asusd` both write the kernel's `platform_profile`.
Whichever wrote last won, so profiles changed behind your back. Alaz talks to asusd,
so give asusd sole ownership.

```bash
sudo systemctl mask power-profiles-daemon
```

Side effect: GNOME's built-in power mode selector disappears. Alaz's tray menu and
mini window replace it.

**Verify:** `systemctl is-enabled power-profiles-daemon` prints `masked`.
**Roll back:** `sudo systemctl unmask power-profiles-daemon && sudo systemctl start power-profiles-daemon`

### 3b. gpu-manager (Ubuntu) and GDM PrimeOff

**Why.** At boot, Ubuntu's `gpu-manager.service` loaded the NVIDIA driver right after
supergfxd took control of the GPU. When supergfxd then tried to remove the card for Eco,
the kernel got stuck in an endless loop inside `nv_pci_remove`: an unkillable process, a
second gpu-manager waiting on a lock, and a forced power-off. supergfxd and gpu-manager
both want to own GPU state, so only one of them should run.

```bash
sudo systemctl mask gpu-manager.service
# GDM's PrimeOff hook (only if the file exists on your system):
sudo mv /etc/gdm3/PrimeOff/Default /etc/gdm3/PrimeOff/Default.disabled
```

The PrimeOff rename was done together with the mask on the reference machine; the mask is
what addresses the observed deadlock.

**Verify:** `systemctl is-enabled gpu-manager.service` prints `masked`.
**Roll back:**

```bash
sudo systemctl unmask gpu-manager.service
sudo mv /etc/gdm3/PrimeOff/Default.disabled /etc/gdm3/PrimeOff/Default
```

---

## 4. Remove `splash` from the kernel command line

**Why (the real root cause of flaky Eco entry).** `nvidia-drm` creates its DRM device at
about 2.4 s into boot; the Intel iGPU's device only appears at about 6.4 s. Plymouth (the boot
logo) starts at about 4.5 s and opens the only DRM device available at that moment: the
NVIDIA one. When supergfxd then runs `rmmod nvidia` for Eco, it fails with "Module nvidia is
in use", and Eco ends half-done (card partly detached, `dgpu_disable=0`). Plymouth quits when
GDM starts. Which driver was ready first decided the outcome, so earlier "successful" Eco
boots were luck, and the `nv_pci_remove` hang above was very likely the same root cause.

**Apply.** In `/etc/default/grub`, remove only the word `splash` and keep `quiet`:

```bash
sudo cp /etc/default/grub /etc/default/grub.bak
sudo nano /etc/default/grub
#   GRUB_CMDLINE_LINUX_DEFAULT="quiet"      <- was: "quiet splash ..."
sudo update-grub
```

**Verify.** After reboot, `cat /proc/cmdline` has no `splash`. Then a boot with
`"mode": "Integrated"` ends with `supergfxctl -g` printing `Integrated`, no "fallen off the
bus" in `journalctl -b -k | grep -i nvrm`, and no hang.

**Cost.** The initramfs stage took about 6.5 s longer on the reference machine (switching to
the root file system went from about 4 s to about 10.8 s). The cause is not understood. A possible
future alternative is to keep `splash` and stop Plymouth from using the NVIDIA device.

**Roll back.** `sudo cp /etc/default/grub.bak /etc/default/grub && sudo update-grub`, reboot.

---

## 5. `pcie_aspm=off`: model-specific, probably leave it alone

On the reference machine the Realtek RTS525A card reader (`rtsx_pci` is blacklisted)
produces a flood of PCIe AER errors when ASPM is enabled (seen from a live USB). The
`pcie_aspm=off` kernel parameter prevents that, so it stays there.

This has a cost: with ASPM off, PCIe links cannot enter low-power states. Measured idle
draw on the reference machine is about 15-16 W on battery with the dGPU asleep (an earlier
22-24 W reading was taken with an external monitor and background load). If your laptop does not have this card reader problem, you may test without it.
If your command line already contains it, do not remove it blindly: check the kernel log for
AER errors first (`journalctl -k | grep -i aer`).

---

## 6. GRUB_DEFAULT by name (dual boot)

**Why.** If `GRUB_DEFAULT` is a menu index and the menu changes, the index can land on
"UEFI Firmware Settings", which reboots into the BIOS instead of your system.

**Apply.** Set the default by entry title and regenerate:

```bash
sudo cp /etc/default/grub /etc/default/grub.bak-alaz
grep -E "^(menuentry|submenu)" /boot/grub/grub.cfg | cut -d"'" -f2   # list exact titles
sudo nano /etc/default/grub
#   GRUB_DEFAULT="Windows Boot Manager (on <disk-partition>)"
sudo update-grub
```

(`GRUB_DEFAULT=saved` with `GRUB_SAVEDEFAULT=true` is another approach; it was not tested
here.)

**Roll back.** `sudo cp /etc/default/grub.bak-alaz /etc/default/grub && sudo update-grub`

---

## 7. Eco mode: manual procedures

Prerequisites: sections 2, 3b and 4 applied. Run these on battery with no external monitor
attached (an external DP/HDMI port wired to the dGPU does not work in Eco, which is
expected). Alaz's GPU Mode tiles do exactly these things through a small root
helper; the manual versions are for when you want to do it by hand or the app is not
installed.

### 7a. Enter Eco (applies at boot)

```bash
sudo cp /etc/supergfxd.conf /etc/supergfxd.conf.bak
sudo nano /etc/supergfxd.conf        # set  "mode": "Integrated"
sudo reboot
```

**Verify after reboot**

```bash
supergfxctl -g                                  # Integrated
cat /sys/devices/platform/asus-nb-wmi/dgpu_disable    # 1
lspci | grep -i nvidia                          # empty
journalctl -b -k | grep -i nvrm                 # no "fallen off the bus" beyond the cosmetic note below
```

Cosmetic: in the very first second of boot, the NVIDIA module in the initramfs can probe the
card before it is switched off and log a "fallen off the bus" warning. Eco still works. It
is not a fix target; the one tried (see section 9) was worse than the warning.

### 7b. Leave Eco (the tested procedure)

The key is to bring the card back with **no driver bound**, so no new GPU appears and the
compositor is not disturbed. The order matters.

```bash
sudo systemctl stop supergfxd
echo 0 | sudo tee /sys/bus/pci/drivers_autoprobe          # new PCI devices get no driver (resets to 1 on reboot)
sudo nano /etc/supergfxd.conf                              # set  "mode": "Hybrid"
echo 0 | sudo tee /sys/devices/platform/asus-nb-wmi/dgpu_disable   # takes 5-10 s
sudo reboot                                                # immediately
```

The card returns, driverless, and the desktop is unaffected. After the reboot supergfxd sees
Hybrid with `dgpu_disable=0` and boots normally (NVIDIA bound, Vulkan ICD back).

Do not skip the reboot: `drivers_autoprobe` stays `0` until then, so a newly appearing PCI
device would not get a driver.

Why this is needed: if you only edit the config, supergfxd's boot safety check sees
`dgpu_disable=1` and forces Integrated again, so you stay in Eco forever.

### 7c. Recovery if you end up in a bad state

- From Linux: `echo 0 | sudo tee /sys/devices/platform/asus-nb-wmi/dgpu_disable`, then reboot.
- From Windows: G-Helper, set the GPU mode to Standard.

---

## 8. Verification checklist

| Check | Command | Expected |
|---|---|---|
| Driver aligned | `cat /proc/driver/nvidia/version` | same version as `nvidia-smi` |
| asusd running | `systemctl is-active asusd` | `active` |
| supergfxd config | `grep -E 'hotplug_type|always_reboot' /etc/supergfxd.conf` | `Asus`, `true` |
| ppd masked | `systemctl is-enabled power-profiles-daemon` | `masked` |
| gpu-manager masked | `systemctl is-enabled gpu-manager.service` | `masked` |
| No splash | `cat /proc/cmdline` | no `splash` |
| dGPU asleep when idle | `cat /sys/bus/pci/devices/<nvidia-pci-id>/power/runtime_status` | `suspended` |

Find the NVIDIA PCI id with `lspci | grep -i nvidia` (for example `01:00.0`; the sysfs name
carries a `0000:` prefix).

---

## 9. Things that did not work, and the "never do this" list

1. **Live switching with `supergfxctl -m ...`.** Entering Eco live killed gnome-shell and
   Xwayland (session crash). Leaving Eco live froze Wayland gnome-shell while it hot-plugged
   the new GPU. Both directions are unsafe on this machine. Alaz never calls it.

2. **Blacklisting automatic NVIDIA loading** (a `modprobe.d` file such as
   `alaz-nvidia-noauto.conf`). It removed the "fallen off the bus" warnings in Eco, but
   in Hybrid the driver was then loaded later (about 3.6 s, by supergfxd). Because supergfxd
   is `Type=dbus`, GDM does not wait for it, so GDM's Xorg crashed with "Failed to create
   pixmap": four boots in a row with a black screen. The file was deleted and the initramfs
   regenerated (`sudo update-initramfs -u`); the driver loads at about 0.7 s again.
   Lesson: any change to boot ordering can race GDM. Understand the risk and prepare the
   rollback first.

3. **An `ExecStartPost` wait drop-in for supergfxd** (`timeout 20 supergfxctl -g`) to make
   GDM wait. `supergfxctl` gets no answer during early boot, so this added exactly 20 s to
   every boot. Removed. (Plymouth was the real culprit, see section 4.)

4. **Leaving Eco by editing the config alone**, or by writing `dgpu_disable=0` with the driver
   auto-loading. The driver binds the card as soon as it appears, a new GPU shows up, and
   gnome-shell can lock up on the hot-plug. Use the procedure in 7b.

---

## 10. Other things worth knowing

- **Polling `nvidia-smi` wakes the GPU.** Every run resets the runtime-suspend timer, so a
  monitor that polls it keeps the dGPU awake forever. Alaz only calls `nvidia-smi`
  when the PCI device's `runtime_status` is `active` and a real process holds `/dev/nvidiaN`
  open. Compositors (gnome-shell, Xwayland) keep that device node open permanently without
  keeping the GPU awake, so they are not counted. Check status for your own scripts with
  `runtime_status` in sysfs, not with `nvidia-smi`.

- **Windows dual boot.** Windows G-Helper's Eco leaves `dgpu_disable=1`. Linux then boots with
  the card gone. With `hotplug_type: Asus` (section 2) supergfxd adopts that as Integrated
  instead of fighting it. Alaz shows a banner when it sees this mismatch.

- **Total system power.** The RAPL `psys` counter gives whole-platform power, but it is
  root-only by default. Alaz ships a udev rule that makes only that one counter
  world-readable (see the README for the security note). On the reference machine it read
  about 1-2 W above the real draw measured on battery.

- **Dynamic Boost.** `nvidia-powerd` was not installed on the reference machine, and NVIDIA
  Dynamic Boost depends on it. The sliders write the asusd properties, but the effect without
  `nvidia-powerd` was not investigated.

- **Harmless cleanups** that were done on the reference machine: removing the unrecognised
  `nvidia.NVreg_EnableBacklightHandler=0` kernel parameter and commenting out an invalid
  `framebuffer-nvidia` line in `/etc/initramfs-tools/modules`. Neither affects behaviour.
