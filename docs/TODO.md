# TODO — Alaz

Ordered roughly by priority. Each item: why, where, how to verify. Update this file when you finish or
discover something. Status as of 2026-10-03. Read `CLAUDE.md` first (hard rules!).

## Rename follow-ups
- [x] New Alaz logo — done: Turkic tamga-style emblem chosen by the owner, traced to an exact vector polygon (`tools/alaz_logo_shape.py`), all sizes rendered by `tools/make_logo.py` (re-run it after editing the shape).
- [ ] Owner: rename the GitHub repo (`gh repo rename alaz -R n3vrb/rog-control`, then `git remote set-url origin https://github.com/n3vrb/alaz.git`).

## 0. Finish if not done (check `git log` / `git status` first)
- [x] **English UI (i18n)** — done (commit 00871fe). — a sub-agent was implementing `alaz/i18n.py` (Turkish strings as keys, EN catalogue, `ui/language` setting auto|en|tr, Settings → Language), English screenshots in `docs/screenshots/` and Turkish in `docs/screenshots/tr/`, README updates. Verify: whole suite passes; the "no Turkish text in English mode" test exists; look at EN screenshots.
- [x] **App identity + new logo** — done: setDesktopFileName, bundled icons in `alaz/ui/icons/`, installer installs hicolor PNGs. Owner must reinstall + restart the service to see it. — window shows as "python3" with no icon on GNOME/Wayland.
  - Logo source files are ready in `assets/`: `assets/logo.png` (full logo + wordmark, for README), `assets/alaz.png` (512 px app icon), `assets/icons/alaz-{16..512}.png`. The old `assets/icon.svg` is obsolete.
  - Code: in `alaz/app.py` call `QGuiApplication.setDesktopFileName("alaz")` (Wayland app_id = desktop file name, so GNOME picks up the name + icon), `setApplicationDisplayName("Alaz")`, set the window icon from the PNG sizes (QIcon with all sizes); use it in the title bar (`ui/windows/_base.py`) and as the tray fallback icon (`ui/windows/tray.py`) instead of the old SVG.
  - `install.sh`: install PNGs to `~/.local/share/icons/hicolor/<s>x<s>/apps/alaz.png` (drop the scalable SVG), keep `Icon=alaz`, add `StartupWMClass=alaz` to the desktop entry; uninstall removes them.
  - README.md / README.tr.md: show `assets/logo.png` at the top.
  - Verify: tests; after the owner reinstalls + restarts the service, the dock/alt-tab shows "Alaz" with the logo.
- [x] **CONTRIBUTING.md + issue templates** — done. (`.github/ISSUE_TEMPLATE/bug_report.yml`) asking for: model, CPU (Intel/AMD), distro/kernel, `asusctl -s`, `supergfxctl -s/-g`, `journalctl --user -u alaz -b`. A friend with an AMD ROG laptop may open PRs.
- [x] checkout@v5 bumped. Push only when the owner asks; bump `actions/checkout@v4` → `@v5` in `.github/workflows/tests.yml` (Node 20 deprecation warning).

## 1. CPU limiting (deferred by the owner — ask before starting)
**Finding (2026-10-03, verified):** on the reference Intel model, asusd `PptPl1Spl/PptPl2Sppt` ARE written
(`/sys/devices/platform/asus-nb-wmi/ppt_pl1_spl` reads 60) but the firmware does NOT enforce them: under a
28 s all-core load psys stayed at 135 W (PL1=60/PL2=90 set). `PptFppt` doesn't exist on this model
(asusd: "ppt_fppt No such device") → the UI must hide FPPT when `SupportedProperties` lacks it and not
emit an error toast. So "Özel" (Custom) mode is currently ineffective on this model — README should say so
until fixed.
- [ ] **RAPL test (Intel)** — owner must run as root (one-off, resets on reboot):
  `for f in /sys/class/powercap/intel-rapl-mmio:0/constraint_{0,1}_power_limit_uw /sys/class/powercap/intel-rapl:0/constraint_{0,1}_power_limit_uw; do echo 45000000 | sudo tee $f; done`
  then run an all-core load and sample psys (`/sys/class/powercap/intel-rapl:1/energy_uj` delta) + avg MHz
  (`/proc/cpuinfo`). Baseline: MMIO 95/95 W in Performance, 70/70 W in Balanced; MSR 200/110 W.
  If the cap holds (~45 W package, psys lower) → implement direct RAPL limits.
- [ ] **"CPU sınırlama" section** (works on Intel AND AMD): "Boost'u kapat" (`/sys/devices/system/cpu/cpufreq/boost` on AMD / `intel_pstate/no_turbo` on Intel) + max frequency slider (`scaling_max_freq`) + Intel RAPL PL1/PL2 (if the test passes). Needs root: new helper subcommand(s) with strict validation, new polkit action with `allow_active=yes` (no password per slider move, like power-profiles), re-apply on app start and after profile changes (firmware resets limits). Make "Özel" mode use RAPL on Intel when asusd PPT is ineffective.
- [ ] **AMD**: on ASUS AMD models asusd PPT (incl. `ppt_apu_sppt`, `ppt_platform_sppt`) is expected to work — needs a tester (the owner's friend: AMD ROG, thermal shutdowns under load; quick workaround for him: `echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost`). Optionally ryzenadj later.

## 2. GPU modes
- [ ] **Ultimate (MUX)**: asusd `GpuMuxMode` (y, writable; 1 = Optimus, 0 = dGPU direct) applies at reboot (no live effect). Risk: if the NVIDIA driver fails in Ultimate the internal panel is black (no iGPU fallback) → recovery = Windows G-Helper or TTY. Plan a controlled 2-reboot test with the owner, rollback ready. Helper already refuses Eco while MUX=0.
- [ ] **Optimize**: on unplug, offer "switch to Eco and reboot?" notification (and reverse on AC). No automatic reboots.

## 3. Boot / power
- [ ] **Bring back the boot logo safely**: removing `splash` costs ~6.5 s in initramfs (cause unknown). Idea: keep `splash` but make Plymouth not use the NVIDIA DRM device (e.g. early-load i915 in initramfs so it's first, or plymouth device selection). Boot-order change → one-boot tests via GRUB `e`, rollback ready, owner's consent.
- [ ] **"Fallen off the bus" cosmetic warnings** on Eco boots (initramfs nvidia probes the powered-off card). Must not change driver load order (see hard rule 3).
- [ ] Idle power ~15–16 W on battery (psys reads 1–2 W higher; could subtract a calibrated offset). `pcie_aspm=off` must stay. Explore per-device runtime PM, refresh Auto (60 Hz on battery) defaults.
- [ ] `nvidia-powerd` not installed → Dynamic Boost probably ineffective; investigate.

## 4. Polish
- [ ] IBM Plex Sans font (OFL) bundled under `assets/fonts/` (falls back to Inter today; some texts wrap).
- [ ] Hide/disable controls for unsupported asusd properties using `SupportedProperties()` (FPPT here).
- [ ] Custom mode has no separate fan curves (shares Performance/Turbo) — consider app-stored curves.
- [ ] `docs/ARCHITECTURE.md` is Turkish — translate to English for contributors.
