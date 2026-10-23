# ASUS peripherals — protocol spec (verified on the reference machine, 2026-10-22)

Scope: ROG Harpe Ace Mini (via ROG OMNI RECEIVER), ROG Pelta headset (2.4 GHz dongle), ROG Strix XG27UCDMG
monitor (DDC/CI). Monitor Aura RGB (0b05:1bfe) is **not** implemented (protocol unpublished; deferred by the owner).

"VERIFIED" = read back from the owner's real device and cross-checked against the OSD / what the owner sees.
"SOURCE" = documented in a source that ran on real hardware, not yet exercised here. Anything else is not used.
Rule: unknown → None → "—". Never send command bytes that are not listed here.

## Access
`/dev/hidraw*` are `root 0600`. The app needs a udev rule (installed by `helper/install.sh`, sudo):
`helper/70-alaz-peripherals.rules` — uaccess on the control interface only (mouse iface 2, headset iface 3). VERIFIED:
only those two nodes get the ACL. Note: all `ATTRS{}` keys of one udev rule must match the same parent device, so the
rule tags the device by VID/PID first (`ENV{ALAZ_PERIPH}`) and checks `bInterfaceNumber` in a second rule.
DDC (`/dev/i2c-*`) already works for the user via ddcutil's own rule. If a hidraw node can't be opened → device
shown as "no permission" with a hint, never a crash.

## Device discovery (sysfs only, no root)
For each `/sys/class/hidraw/hidrawN/device/uevent`: `HID_ID=0003:0000VVVV:0000PPPP`. A device has several hidraw
nodes; pick the one whose `report_descriptor` declares the control report ID (byte sequence `85 <id>`):
- Mouse: VID 0b05 PID 1ace (Omni receiver), node with report ID **0x03** on usage page 0xFF01 (`06 01 ff` … `85 03`). Here: interface 2 = hidraw3.
- Headset: VID 0b05 PID 1b84 (dongle; 1b82 = USB-C cable, same protocol, SOURCE only), node with report ID **0xCC** (`85 cc`). Here: interface 3 = hidraw13.
Re-scan on hotplug (devices come and go; the dongle stays when the headset is off).

## Common transport
Write exactly 64 bytes: `[report_id] + command bytes`, zero-padded. Read 64-byte input reports.
Before each request drain pending input. A matching reply has `r[0]==report_id` and echoes the request's
command bytes (`r[1:3]`, for mouse `12 04 xx` / `12 03 xx` / `12 12 02` also `r[3]`). Ignore non-matching reports
(the mouse emits async `12 01` button reports). Timeout 500 ms (mouse) / 1000 ms (headset), 2 retries.
Writes: the device echoes every write (VERIFIED on both: `03 51 28 …`, `03 50 03 …`, `cc 51 10 …`, `cc 51 28 …`) —
wait for the echo of the first 2 command bytes before the next write; no retry on a lost echo.
Error reply: `r[1:3] == ff aa` (VERIFIED on headset when the headset is off; SOURCE on mouse: mouse asleep/off) → treat
the device as "asleep/disconnected", values None. All I/O in a worker thread, one in-flight request per device.
Data offsets below are indices in the full 64-byte reply `r` (r[0] = report id).

## Mouse — ROG Harpe Ace Mini, report ID 0x03 (64 bytes)
Reads (all VERIFIED: values matched the owner's mouse — DPI 800, colour-cycle lighting):
| request | reply fields |
|---|---|
| `03 12 07` | battery % = r[5] (VERIFIED 67); sleep code = r[6]; low-battery warn % = r[7] (20); charging = r[10] > 0 |
| `03 12 12 02` | serial ASCII r[5:17] (VERIFIED "S7MPKR039858") |
| `03 12 00` | active profile = r[11] (0-based, 0); active DPI stage = r[12] (1-based, VERIFIED 2 → 800 DPI) |
| `03 12 04 00` | polling code = r[13] & 7 (3); debounce code = r[15] (2); angle snapping = r[17]==1 (0); angle tuning = int16 LE r[19:21] |
| `03 12 04 02` | 4 DPI stages: stage i X = u16 LE at r[5+4i], Y at r[7+4i]; dpi = raw*50 + 50 (VERIFIED 400/800/1600/3200) |
| `03 12 04 03` | DPI stage colour i = RGB r[5+3i : 8+3i] |
| `03 12 03 00` | LED (zone byte ignored; reports the zone 0x00 copy, see LED write): mode = r[5]; brightness 0–100 = r[6] (50); RGB = r[7:10]; direction r[11]; random r[12]; speed r[13] (VERIFIED mode 2 = colour cycle) |
| `03 12 06` | lift-off: SOURCE says r[8] (0=low,1=high); reply here `01 01 ff 00 …` → offset NOT verified → show read-only "—" until verified |
(`03 12 03 01` returns the same reply with r[3]=00 — an earlier "timeout" was the probe's matcher expecting r[3]=01.)

Tables: polling code 0=125, 1=250, 2=500, 3=1000 Hz (Mini supports only these). Debounce code n → (n+1)*4 ms for
n=1..7 (8…32 ms); code 0 ambiguous (4 ms or off) → label "4 ms". Sleep code 0=1 min, 1=2, 2=3, 3=5, 4=10, 0xFF=never.
LED modes supported by the Mini: 0 static, 1 breathing, 2 colour cycle, 4 reactive, 6 battery state, 0xF0 off.
DPI range 100–42000, step 50; 4 stages.

Writes (LED + save VERIFIED; the rest SOURCE = G-Helper `AsusMouse.cs`/`HarpeAceMini.cs`; each followed by save `03 50 03` once per batch):
| what | bytes |
|---|---|
| DPI stage i (0–3), X=Y | `03 51 31 <i> 00 <lo> <hi> <R> <G> <B>` (raw=(dpi-50)/50 LE; RGB = that stage's current colour, read first) |
| active DPI stage | `03 51 31 09 00 <stage 1-based>` |
| polling | `03 51 31 04 00 <code>` |
| debounce | `03 51 31 05 00 <code>` |
| angle snapping | `03 51 31 06 00 <0/1>` |
| sleep + low-battery | `03 51 37 00 00 <sleep code> 00 <low %>` (send both, keep the other at its read value) |
| LED | `03 51 28 <zone> 00 <mode> <bright 0-100> <R> <G> <B> <dir> <random> <speed>` — VERIFIED visually by the owner: only zone **0x01** changes the physical LED (as G-Helper does). The LED read `12 03` ignores its zone byte and reports zone **0x00**, a separate stored copy the LED never shows → write 0x01 then 0x00 so reads match the LED. Save is not needed for the LED to change. |
| save | `03 50 03` |
NOT used (avoid): lift-off write `51 35 …` (also resets surface calibration), button remap `51 21`, DPI-count `51 31 0A`,
profile switch `50 02`, anything on report IDs 1/2 (receiver/keyboard channels), the LampArray interface (hidraw5;
VERIFIED it reports 1 lamp, kind=mouse, 33 ms min interval — kept for a possible live-sync later).

## Headset — ROG Pelta, report ID 0xCC (64 bytes)
Source: OthrineTM/pelta-control (GPL-3.0, protocol facts only). Body = `[group, cmd, 0, 0, data…]`; data in reply at r[5:].
Reads (VERIFIED with the headset on; with it off the dongle answers `12 00 00 01` → r[5]=0 and everything else `ff aa`):
| request | reply |
|---|---|
| `cc 12 00 00 01` | headset connected = r[5]==1 |
| `cc 12 00 00 00` | firmware (r[5:13], VERIFIED 4.0.5.0 / 4.0.5.0) |
| `cc 12 07` | sleep min = r[5] (5); battery % = r[6] (VERIFIED 87; 0xFE or >100 → None); low-batt % = r[7]; voice = r[8] |
| `cc 12 08` | charging = r[5]==1 |
| `cc 12 03` | lighting: effect = r[5], brightness 0–100 = r[6], RGB = r[7:10] (VERIFIED 1 static, 50, #EAB215) |
| `cc 12 13` | software-LED (Aura Sync) mode = r[5] (VERIFIED 1) |
Writes (VERIFIED: static blue written, read back, restored; the only writes we send):
- software-LED mode off: `cc 51 10 00 00 00` — SOURCE says it must precede hardware effects. It is echoed, but `12 13`
  still reads 1 afterwards, so that field's meaning is unclear; we send it before every lighting write (harmless).
- lighting: `cc 51 28 00 00 <effect> <brightness 0-100> <R> <G> <B>`; effects 1 static, 2 breathing, 3 strobing, 4 colour cycle;
  brightness 0 = lights off. No save command (takes effect immediately).
NOT used: everything else (noise reduction, sidetone, power settings, `51 30` direct colour) — owner only wants RGB.
The dongle is the firmware-update target: never probe unknown group/cmd bytes.

## Monitor — XG27UCDMG via DDC/CI (ddcutil)
Bus: `ddcutil detect --brief` → the display whose `Monitor:` contains `XG27UCDMG` (here `/dev/i2c-13`, card1-DP-1).
Run `ddcutil --bus N --brief getvcp <code>`; output `VCP <code> C <cur> <max>` (continuous) / `SNC x<val>` /
`CNC x<mh> x<ml> x<sh> x<sl>` (value = sh<<8|sl). ~50 ms between commands; worker thread; 8 s timeout per call.
Mapping SOURCE = KharalDipendra/Asus-Displaywidget-Linux (sibling XG27ACDMS); VERIFIED = matched the owner's OSD.
| code | feature | values | status |
|---|---|---|---|
| 10 | brightness 0–100 | continuous (30) | VERIFIED |
| 12 | contrast 0–100 | continuous (80) | VERIFIED |
| 14 | colour temp | 03 4000K, 04 5000K, 05 6500K, 06 7500K, 07 8200K, 08 9300K, 09 10000K, 0B User (current 0B) | SOURCE+MCCS |
| DC | GameVisual | 01 Cinema, 02 Scenery, 04 User, 05 Racing, 06 RTS/RPG, 07 FPS, 08 MOBA, 09 Night Vision, 0A sRGB Cal | 02=Scenery VERIFIED; rest SOURCE |
| E5 | Shadow Boost | 00 off, 01–03 level 1–3, 04 dynamic | SOURCE |
| E6 | blue-light filter | 00 off, 01–04 level | SOURCE (254 reply = locked in this mode → disable control) |
| E2 | HDR mode | read-only display; 0 = SDR. NEVER write | SOURCE |
| F9 | OLED Screen Move | 00 off, 01 light, 02 middle, 03 strong | 02=Middle VERIFIED |
| F8 | pixel-cleaning reminder | 00 off, 02/04/08 hours | SOURCE (current 08) |
| 60 | input source | 0F DisplayPort, 11 HDMI-1, 12 HDMI-2, 1A USB-C | 1A=USB-C VERIFIED; switching away blanks this laptop's picture → confirm dialog |
Risky, only behind an explicit confirm dialog (never automatic, never on startup/restore): input switch (60), pixel
cleaning start (FD bit 0x0010, read-modify-write; ~6 min dark screen) — v2. Never send: 04/05/08 factory resets,
EC, D6 (power), E2 writes, FC/FD except the documented RMW, any code not in this table.
Pending verification (read-only diff while the owner changes the OSD): FD bits (VRR 0x0001, uniform brightness 0x0040, …),
GamePlus E3/E4/EA, EE, KVM F3.
