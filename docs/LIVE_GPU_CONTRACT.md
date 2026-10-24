# Live GPU switching: shared contract (P1–P4)

Status: implemented 2026-10-24 (helper `live-eco`/`live-hybrid`, controller, UI) and tested by the owner on
the reference machine (Zephyrus 2025, RTX 5070, GNOME 46 Wayland). The shell prototypes it was ported from
were removed; `tools/gpu_probe.sh` remains as a read-only diagnostic (who holds the dGPU).
Note: pkexec picks the FIRST action whose exec.path and (if set) exec.argv1 match, so every action for the
helper carries an exec.argv1 (see helper/org.alaz.gfx.policy).

## Why live switching is safe now (and only under these preconditions)
1. `/etc/udev/rules.d/61-alaz-mutter-ignore-nvidia.rules`: mutter ignores the NVIDIA DRM card (MUX=1 only),
   so gnome-shell never opens it and a card appearing/disappearing does not touch the compositor.
2. `/etc/udev/rules.d/72-alaz-nvidia-render-noaccess.rules`: no `uaccess` ACL on the NVIDIA renderD node
   (MUX=1 only), so Chromium/Electron apps do not keep it open. `/dev/nvidia*` stay accessible, so
   offload (GLX/EGL/Vulkan/CUDA) still works.
3. `~/.config/environment.d/90-alaz-egl-mesa.conf`: `__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json`
   so Xwayland/gnome-shell do not load NVIDIA EGL (needs re-login).
4. During a switch, udev must not load/unload nvidia: mask Ubuntu's `71-nvidia.rules`
   (`/run/udev/rules.d/71-nvidia.rules -> /dev/null`) + runtime blacklist
   `/run/modprobe.d/alaz-live-nvidia.conf` (`blacklist nvidia|nvidia_drm|nvidia_modeset|nvidia_uvm`), then
   `udevadm control --reload`. ALWAYS undone at the end (also on failure). Without this, udev's
   71-nvidia add/remove RUN rules + 80-drivers modalias autoload form an endless load/unload loop.
5. Nothing is ever killed. If any process holds the dGPU, the switch is refused ("busy").
`supergfxctl -m` / supergfxd `SetMode` stay FORBIDDEN.

## P1 — helper CLI (`helper/alaz-gfx-helper`, root via pkexec)
Existing commands stay unchanged (`set-boot-mode {integrated|hybrid}`, `status`).
New commands:

```
alaz-gfx-helper live-eco       # Hybrid -> Eco now (dGPU off), boot config -> Integrated
alaz-gfx-helper live-hybrid    # Eco -> Hybrid now (driver bound), boot config -> Hybrid
alaz-gfx-helper holders        # list dGPU holders (JSON), changes nothing; root not required
```

Output: the LAST line of stdout is always one JSON object (human-readable log lines may precede it on
stderr). Exit codes:

| code | meaning | JSON |
|---|---|---|
| 0 | done, or already in the target state (`"changed": false`) | `{"ok": true, "mode": "Integrated"/"Hybrid", "changed": bool}` |
| 2 | usage | — |
| 4 | MUX is dGPU-direct (Ultimate): live switching unsupported | `{"ok": false, "error": "mux"}` |
| 5 | not root | — |
| 6 | config error (existing meaning) | — |
| 7 | could not stop supergfxd, nothing changed | `{"ok": false, "error": "supergfxd"}` |
| 9 | busy: processes hold the dGPU, NOTHING changed | `{"ok": false, "error": "busy", "holders": [H...]}` |
| 10 | failed midway; boot config already = target; a reboot completes it safely | `{"ok": false, "error": "failed", "step": "<name>", "reboot_required": true}` |
| 11 | precondition missing (mutter-ignore rule absent), nothing changed | `{"ok": false, "error": "precondition", "missing": ["..."]}` |
| 12 | aborted before any persistent change (e.g. `modprobe -r` failed); services restored, nothing changed | `{"ok": false, "error": "aborted", "step": "<name>"}` |

Holder object `H`: `{"pid": int, "comm": str, "user": str, "exe": str|null, "nodes": ["/dev/nvidia0", "/dev/dri/renderD129", ...]}`.
nvidia-persistenced is never a holder (the helper stops it itself). `holders` output:
`{"ok": true, "dgpu_present": bool, "holders": [H...]}`.

`status` gains: `"holders"` (list as above, [] when the card is absent), `"live_ready"` (bool: MUX=1 and
rule 61 present). Existing keys unchanged.

Procedures = the reference scripts, in Python, stdlib only, absolute paths, minimal env, no shell:
- live-eco: checks (root, dgpu_disable=0, MUX=1, rule 61) -> holders check -> mask udev -> stop supergfxd
  -> stop nvidia-persistenced -> holders re-check (restore services and exit 9 if any) -> `modprobe -r`
  nvidia_drm, nvidia_modeset, nvidia_uvm, nvidia (failure -> nothing persistent changed yet: modprobe
  back the modules already removed (forward order), restart persistenced + supergfxd, unmask, exit 12) -> config ->
  Integrated (reuse the existing atomic config writer) -> PCI remove audio fn then GPU -> dgpu_disable=1
  (verify) -> unmask udev -> `systemctl reset-failed supergfxd` + start supergfxd.
- live-hybrid: checks (root, dgpu_disable=1, MUX=1, rule 61) -> mask udev -> existing tested Eco-exit
  (config Hybrid, stop supergfxd, autoprobe=0, dgpu_disable=0) -> wait for 0000:01:00.0 (rescan after 5 s,
  give up after 15 s) -> `udevadm settle` -> autoprobe=1 -> modprobe nvidia, nvidia_modeset, nvidia_drm,
  nvidia_uvm, each followed by settle and an lsmod-style check (`/sys/module/<m>` exists) -> verify driver
  bound and a drm card exists -> `ub-device-create` (if present) -> `power/control=auto` -> bind audio fn
  via drivers_probe -> unmask udev -> reset-failed + start nvidia-persistenced and supergfxd.
- The PCI address must not be hard-coded: find the NVIDIA VGA/3D function (vendor 0x10de, class 0x03xxxx)
  and its sibling functions; when absent (Eco), derive from the remembered slot or rescan.
Timing on the reference machine: live-eco ~10 s, live-hybrid ~13 s (dgpu_disable=0 alone takes ~8 s).

## P2 — install / polkit
- New polkit action `org.alaz.gfx.live-switch`, `exec.path` = helper, `exec.argv1` = `live-eco` and a
  second action (or the same id is not allowed twice — use two ids: `org.alaz.gfx.live-eco`,
  `org.alaz.gfx.live-hybrid`), defaults `allow_active=yes`, `allow_inactive=auth_admin`,
  `allow_any=auth_admin`. Existing `org.alaz.gfx.set-boot-mode` unchanged. pkexec 124 supports
  `org.freedesktop.policykit.exec.argv1`.
- `helper/install.sh` installs rules 61 and 72 (MUX-conditional, exact text below), reloads udev,
  `uninstall.sh` removes them.
- User `install.sh` installs `~/.config/environment.d/90-alaz-egl-mesa.conf` (and `uninstall.sh` removes it);
  print that a re-login is needed.

```
# 61-alaz-mutter-ignore-nvidia.rules
SUBSYSTEM=="drm", KERNEL=="card[0-9]*", DRIVERS=="nvidia", PROGRAM=="/usr/bin/cat /sys/devices/platform/asus-nb-wmi/gpu_mux_mode", RESULT=="1", TAG+="mutter-device-ignore"
# 72-alaz-nvidia-render-noaccess.rules
SUBSYSTEM=="drm", KERNEL=="renderD*", DRIVERS=="nvidia", PROGRAM=="/usr/bin/cat /sys/devices/platform/asus-nb-wmi/gpu_mux_mode", RESULT=="1", TAG-="uaccess"
```

## P3 — backend + controller API (consumed by P4)
`GfxClient` (alaz/backend/gfx.py) gains `request_live(target: GfxMode, callback(result: LiveResult))`,
`LiveResult` = dataclass(ok: bool, code: int|None, error: str|None, holders: list[Holder], reboot_required: bool, message: str),
`Holder` = dataclass(pid, comm, user, exe, nodes). Also `query_holders(callback(list[Holder]))` (no pkexec).

`GfxView` (alaz/core/state.py) — new fields (P3 owns state.py):
```
selected: str | None = None     # user's choice: "eco" | "standard" | "optimize" | "ultimate"
switching: bool = False         # a live switch is running
waiting: str | None = None      # target mode queued until holders exit ("eco"/"standard")
holders: list = field(default_factory=list)   # [Holder] last seen blocking the switch
live_ready: bool = False        # helper status live_ready
optimize: bool = False          # Optimize is active
```
`active` keeps meaning the CURRENT hardware mode ("eco"/"standard"/"ultimate").

Controller (alaz/core/controller.py) — public API for the UI:
- `request_gpu_mode(mode)` with mode in eco/standard/optimize/ultimate.
  eco/standard: live switch if `live_ready`, else the old boot path. Selecting eco/standard turns Optimize off.
  optimize: turns Optimize on (persisted setting `gpu/optimize`) and immediately applies the mode for the
  current power source. ultimate: emits `gpuUltimateConfirm()`; the UI calls `confirm_ultimate(True/False)`.
- `resolve_busy(choice)` with choice in "wait" | "reboot" | "cancel" (answer to `gpuBusy`).
- `cancel_gpu_pending()` existing; also cancels a "waiting" target.
- Signals: `gpuBusy(list)` (holders; UI shows the dialog), `gpuSwitchFailed(str, bool)` (message,
  reboot_required), `gpuUltimateConfirm()`, existing `gpuRebootRequired`.
- Optimize: on AC->battery go eco, battery->AC go standard, 5 s debounce, at app start apply once.
  If busy: do NOT ask; set `waiting`, poll `query_holders` every 5 s, switch when empty, toast
  "<app> dGPU kullanıyor; kapanınca Eco'ya geçilecek". Never reboot automatically.
- Ultimate: write asusd `GpuMuxMode` = 0 (enter) / 1 (leave), then reboot prompt (existing dialog).
  While MUX=0: eco and optimize disabled. Leaving Ultimate to standard = MUX 1 + reboot.
- Elapsed time for a switch is 10–15 s: `switching=True` during it, all GPU tiles disabled.

## P4 — UI
Main window GPU row: all four tiles enabled per the rules above, "Geçiliyor…" state, busy dialog
(list app names, buttons "Kapatınca geç" / "Yeniden başlatınca uygula" / "Vazgeç"), Ultimate confirm
dialog with the risk text (black internal panel if the NVIDIA driver fails; recovery: TTY or Windows
G-Helper), failure toast with optional "Yeniden başlat". Tray menu GPU entries. Turkish + English (i18n).
Build against `alaz/ui/windows/_fake.py` (fake controller/state implementing the API above).
