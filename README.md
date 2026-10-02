# ASUS Helper

A G-Helper-style PyQt5 desktop UI for ASUS ROG laptops on Linux. Wraps the
existing `asusctl` and `supergfxctl` daemons — no root-owned code is added.

## Features

- **Performance profiles** — Silent / Balanced / Turbo (mapped to asusctl's Quiet / Balanced / Performance).
- **GPU mode** — Eco / Hybrid / Ultimate (mapped to supergfxctl's Integrated / Hybrid / AsusMuxDgpu). Only modes your firmware exposes are shown.
- **Battery charge limit** — 20–100% slider.
- **Fan curves** — interactive 8-point editor per fan (CPU / GPU / MID) per profile, drag points on a chart.
- **Keyboard aura** — brightness segmented control + static colour picker, with multi-device selection when more than one Aura device is present.
- **Live monitoring** — an always-on sensor bar (and tray tooltip) showing CPU/GPU temperature, CPU/GPU usage, RAM, fan RPM, GPU power and battery %.
- **Display & panel** — refresh-rate switching and Panel Overdrive toggle (Flicker-free Dimming appears only if your firmware exposes it).
- **Mini mode** — a compact, always-on-top window with the sensor bar plus quick profile/GPU toggles.
- **Notifications** — a tray notification when the performance profile changes (e.g. via the Fn hotkey); toggle in the tray menu.
- **System tray** — minimise to tray, quick profile / GPU mode switching from the tray menu.

## Monitoring & extras — scope

These features read **only unprivileged sources**, so behaviour depends on your hardware:

- **Sensors** come from `psutil` (CPU temp/usage, RAM, battery, fan RPM) and `nvidia-smi` (GPU usage/temp/power/memory). On non-NVIDIA GPUs, usage falls back to `/sys/class/drm/card*/device/gpu_busy_percent`.
- **Power** shows **GPU watts** (nvidia-smi). CPU/package watts via RAPL is root-only on most kernels, so it is shown only when readable and otherwise omitted.
- **Flicker-free Dimming** is auto-detected: the toggle appears only when a real sysfs interface exists. asusctl does not expose it on most laptops.
- **Refresh rate** uses the GNOME/Mutter D-Bus API on Wayland (`org.gnome.Mutter.DisplayConfig`) and `xrandr` on X11.

## Requirements

- Linux with `asusd` and (optionally) `supergfxd` installed and running.
- Python 3.10+.
- For monitoring: `python3-psutil`, optionally `nvidia-smi` (NVIDIA driver) and `python3-gi` (for Wayland refresh-rate switching). All optional — the app degrades gracefully when any are missing.

On Ubuntu / Zorin / Debian:

```bash
sudo apt install python3-pyqt5 python3-pyqtgraph python3-numpy python3-psutil python3-gi
```

Or via a venv:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Running

From the project root:

```bash
python3 -m asus_helper
```

## Installing a desktop launcher

```bash
cp asus_helper.desktop ~/.local/share/applications/
cp assets/icon.svg ~/.local/share/icons/asus-helper.svg
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
```

You may need to edit `Exec=` in the `.desktop` file to point at an absolute
path if the project is not on `PYTHONPATH`.

## Privileges

Privileged actions (profile, GPU mode, charge limit, fan curves, aura) are
sent through the `asusd` / `supergfxd` D-Bus services, which authorise via
polkit. The desktop polkit agent will prompt you the first time per session.
The app does *not* invoke `pkexec` directly.

## Layout

```
asus_helper/
├── app.py              # QApplication, MainWindow, system tray
├── backend.py          # all asusctl / supergfxctl invocations
├── theme.py            # dark QSS + palette
├── widgets/            # Card, SegmentedControl
└── tabs/               # main_tab, fans_tab, aura_tab
```
