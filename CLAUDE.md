# CLAUDE.md — ROG Control

Read this first. Then `docs/TODO.md` (what to do next), `docs/ARCHITECTURE.md` (module contracts),
`docs/SYSTEM_SETUP.md` (system-level findings) and, for deep history, `docs/PHASE0_SYSTEM_FIX.md` (Turkish dev log).

## What this is
ROG Control: a G-Helper-inspired PyQt6 control app for ASUS ROG laptops on Linux, built on the
`asusd` (asusctl 6.0.12) and `supergfxd` (5.2.7) D-Bus APIs. Public repo: github.com/n3vrb/rog-control (GPL-3.0).
Reference machine: ROG Zephyrus 2025, Intel Core Ultra 9 285H, RTX 5070 Laptop, Zorin OS 18 (GNOME 46, Wayland).
The owner is Turkish; talk to them in Turkish. UI is Turkish + English (`rog_control/i18n.py`).

## Layout
- `rog_control/backend/` — asusd.py, gfx.py (supergfxd, read-only + helper call), sensors.py, display.py, dbus_util.py, types.py
- `rog_control/core/` — state.py (AppState: data + signals), controller.py (THE only write path)
- `rog_control/ui/` — theme.py, widgets/, windows/ (main, fans, keyboard, settings, mini, tray, dialogs, _fake.py for offscreen renders)
- `helper/` — root GPU helper (pkexec), polkit policy, RAPL psys udev rule, install/uninstall (sudo)
- `packaging/rog-control.service` — systemd user service (autostart); `install.sh` / `uninstall.sh` — user install (no sudo)
- `tests/` — pytest, offscreen Qt; `tools/` — screenshot_windows.py, widget_gallery.py

## Commands
- Tests: `.venv/bin/python -m pytest tests -q` (venv has system site-packages + pytest-qt). Run the WHOLE suite, ideally a few times (one flaky offscreen paint segfault was seen once).
- Render windows with fake state: `QT_QPA_PLATFORM=offscreen .venv/bin/python tools/screenshot_windows.py <outdir>` — LOOK at the PNGs after UI changes.
- Installed copy runs from `~/.local/share/rog-control` via the user service: after changing code the owner runs `./install.sh && systemctl --user restart rog-control`. Logs: `journalctl --user -u rog-control -f`.
- Git identity is configured to `n3vrb <178571977+n3vrb@users.noreply.github.com>`; never commit with another email. Push only when the owner asks.

## Hard rules (each one was learned the hard way on real hardware)
1. NEVER switch the GPU live: no `supergfxctl -m`, no supergfxd `SetMode`/`SetConfig`. Live Eco entry killed gnome-shell; live Eco exit froze it. GPU mode = boot config via the helper + reboot.
2. Eco exit = stop supergfxd → `drivers_autoprobe=0` → config Hybrid → `dgpu_disable=0` → reboot (implemented in the helper; tested).
3. Do NOT blacklist NVIDIA autoload / change driver load order (caused 4 black-screen boots). Any boot-order change can race GDM: tell the owner the risk + rollback BEFORE they do it, and prefer one-boot tests via GRUB `e`.
4. Do NOT remove `pcie_aspm=off` (Realtek card reader floods PCIe AER errors without it). `splash` was removed on purpose (Plymouth grabbed the NVIDIA DRM device and broke Eco entry).
5. gpu-manager is masked and power-profiles-daemon is masked on the owner's machine — don't re-enable.
6. GUI thread never blocks (async QtDBus, workers for subprocess/I-O). Never wake the dGPU for monitoring (nvidia-smi only when runtime_status=active AND a non-compositor process holds /dev/nvidia*).
7. Tests never write to the real system (fakes/mocks/test roots). Never run the helper as root or install scripts yourself — give the owner the exact commands.
8. Don't invent values: unknown → None → "—".
9. D-Bus quirk: the first typed call in a fresh process fails to marshal; `dbus_util._warm_up` sends a sacrificial call to the bus daemon. Covered by `tests/backend/test_dbus_first_call_quirk.py` — keep it passing.

## Working style the owner asked for
Orchestrator mode: plan, split work into packages with clear file ownership, delegate implementation to Sonnet sub-agents, then REVIEW their output yourself (run tests, read critical code — especially anything running as root —, look at screenshots, reproduce claims). Sub-agents have repeatedly shipped plausible-but-wrong fixes that only careful review caught. Ask before using Opus sub-agents. Commit per verified package.
