# ROG Control — Mimari ve modül sözleşmeleri

Yeni uygulama: `rog_control/` paketi, **PyQt6** (6.6, Qt 6.4), Python 3.12. Çalıştırma: `python3 -m rog_control`.
Eski `asus_helper/` sadece referanstır; içinden kod **import edilmez** (gerekirse mantık kopyalanır).

Tasarım kaynağı: `docs/design/V2Main.dc.html`, `V2Fans.dc.html`, `V2MiniTray.dc.html` (B v2). Arayüz metni Türkçe.

## Değişmez kurallar (hepsi zorunlu)

1. **GUI thread asla bloklanmaz.** Tüm D-Bus çağrıları **asenkron** (`QDBusConnection.asyncCall` + `QDBusPendingCallWatcher`) veya worker thread'de. `subprocess` sadece worker thread'de.
2. **`supergfxctl -m` / supergfxd `SetMode` / `SetConfig` ASLA çağrılmaz.** GPU modu değişikliği yalnızca `helper/rog-control-gfx-helper` (pkexec) ile ve **yeniden başlatma gerektiren** bir istek olarak yapılır. (Sebep: bu sistemde canlı GPU geçişi gnome-shell'i öldürüyor/donduruyor.)
3. **dGPU'yu gereksiz uyandırma.** `nvidia-smi` yalnızca `/sys/bus/pci/devices/0000:01:00.0/power/runtime_status == "active"` iken çağrılır (yol, supergfxd'nin bildirdiği/PCI'da bulunan NVIDIA aygıtından türetilir). Aksi halde GPU "Uyku".
4. **Testlerde gerçek sisteme yazma YOK.** Okuma serbest. Yazma yolları mock/fake ile test edilir.
5. Her modül `logging.getLogger(__name__)` kullanır; `print` yok.
6. Sistem değerleri uydurulmaz; okunamayan değer `None` olur ve UI "—" gösterir.

## Paket yapısı

```
rog_control/
├── __main__.py            # main()
├── app.py                 # QApplication, pencereler, tray kurulumu (Dalga 2)
├── core/
│   ├── state.py           # AppState (QObject, sinyaller) (Dalga 2)
│   └── controller.py      # UI → backend köprüsü, hata yönetimi (Dalga 2)
├── backend/
│   ├── dbus_util.py       # ortak async D-Bus yardımcıları        (Dalga 1-A)
│   ├── asusd.py           # AsusdClient                           (Dalga 1-A)
│   ├── gfx.py             # GfxClient (salt okuma + helper çağrısı)(Dalga 1-A)
│   ├── sensors.py         # SensorReader                          (Dalga 1-B)
│   └── display.py         # DisplayClient (dahili panel Hz)       (Dalga 1-B)
├── ui/
│   ├── theme.py           # token'lar + QSS                       (Dalga 1-C)
│   ├── widgets/…          # bileşenler                            (Dalga 1-C)
│   └── windows/…          # MainWindow, FansWindow, MiniWindow, Tray (Dalga 2)
helper/
├── rog-control-gfx-helper # root yardımcı (python3)               (Dalga 1-D)
├── org.rogcontrol.gfx.policy
└── install.sh / uninstall.sh
tests/                     # pytest; QT_QPA_PLATFORM=offscreen
```

## Ortak enum'lar (`rog_control/backend/types.py` — Dalga 1-A yazar, herkes import eder)

```python
class Profile(enum.IntEnum):      # asusd ThrottleThermalPolicy değerleri
    BALANCED = 0; PERFORMANCE = 1; QUIET = 2
# UI etiketleri: QUIET→"Sessiz", BALANCED→"Dengeli", PERFORMANCE→"Turbo"; "Özel" ayrı bir uygulama modu (Dalga 2)

class Epp(enum.IntEnum):          # asusd Throttle*Epp değerleri
    DEFAULT = 0; PERFORMANCE = 1; BALANCE_PERFORMANCE = 2; BALANCE_POWER = 3; POWER = 4

class GfxMode(enum.IntEnum):      # supergfxd Mode() değerleri
    HYBRID = 0; INTEGRATED = 1; NVIDIA_NO_MODESET = 2; VFIO = 3; ASUS_EGPU = 4; ASUS_MUX_DGPU = 5; NONE = 6
# UI: INTEGRATED→"Eco", HYBRID→"Standart", ASUS_MUX_DGPU→"Ultimate"

class GfxPower(enum.IntEnum):     # supergfxd Power()
    ACTIVE = 0; SUSPENDED = 1; OFF = 2; ASUS_DISABLED = 3; ASUS_MUX_DISCRETE = 4; UNKNOWN = 5

@dataclass(frozen=True)
class FanCurve:
    fan: str                       # "CPU" | "GPU" | "MID"
    temps: tuple[int, ...]         # 8 değer, °C (255 = son nokta "üstü")
    pwm: tuple[int, ...]           # 8 değer, 0–255
    enabled: bool
    def percent(self) -> tuple[int, ...]: ...   # round(p*100/255)
```
> Değerler kurulmadan önce gerçek daemon'dan doğrulanmalı (introspect + GetAll); uyuşmazlık varsa düzelt ve raporla.

## Gerçek D-Bus API (bu makinede doğrulandı, asusd 6.0.12 / supergfxd 5.2.7)

**asusd** — servis `org.asuslinux.Daemon`, sistem bus
- `/org/asuslinux` — `org.asuslinux.Platform` özellikleri (emits-change; çoğu writable):
  `ThrottleThermalPolicy u`, `ChargeControlEndThreshold y`, `PanelOd b`, `PptPl1Spl y`, `PptPl2Sppt y`, `PptFppt y`,
  `NvDynamicBoost y`, `NvTempTarget y`, `ThrottleQuietEpp u`, `ThrottleBalancedEpp u`, `ThrottlePerformanceEpp u`,
  `ThrottlePolicyLinkedEpp b`, `ThrottlePolicyOnAc u`, `ThrottlePolicyOnBattery u`, `ChangeThrottlePolicyOnAc b`,
  `ChangeThrottlePolicyOnBattery b`, `GpuMuxMode y` (salt okunur kabul et), `DgpuDisable b` (salt okunur), `BootSound b`.
  Metot: `SupportedProperties() -> as`.
  Not: `Ppt*` okunan değerler anlamsız olabilir (sysfs önbelleği, ör. 5); UI bunları sadece "Özel" modda yazar.
- `/org/asuslinux` — `org.asuslinux.FanCurves`:
  `FanCurveData(u profile) -> a(s(yyyyyyyy)(yyyyyyyy)b)` [fan, pwm, temp, enabled] — **sıra: pwm sonra temp**, gerçek çıktıyla doğrula
  `SetFanCurve(u profile, (s(yyyyyyyy)(yyyyyyyy)b))`, `SetCurvesToDefaults(u)`, `ResetProfileCurves(u)`,
  `SetFanCurvesEnabled(u, b)`, `SetProfileFanCurveEnabled(u, s fan, b)`
- Aura aygıtı: yolu **dinamik** (`/org/asuslinux/19b6_X_6`, her açılışta değişebilir) — `/org/asuslinux` altındaki
  çocuk nesneler arasında `org.asuslinux.Aura` arayüzü olanı Introspect ile bul.
  `Brightness u` (0=Kapalı…3=Yüksek, writable), `LedMode u`, `LedModeData (uu(yyy)(yyy)ss)` [mode, zone, colour1, colour2, speed, direction],
  `SupportedBasicModes au`, `SupportedBrightness au`.
- PropertiesChanged sinyalleri dinlenir → polling yok (sensörler hariç).

**supergfxd** — servis `org.supergfxctl.Daemon`, nesne `/org/supergfxctl/Gfx`, arayüz `org.supergfxctl.Daemon`
- Okuma: `Mode() u`, `Supported() au`, `Power() u`, `PendingMode() u`, `PendingUserAction() u`, `Vendor() s`, `Version() s`, `Config() (ubbbbtu)`
- Sinyaller: `NotifyGfx(u)`, `NotifyGfxStatus(u)`, `NotifyAction(u)`
- **YASAK:** `SetMode`, `SetConfig`.

**Firmware:** `/sys/devices/platform/asus-nb-wmi/dgpu_disable` (0/1), `gpu_mux_mode` (0=dGPU doğrudan, 1=Optimus).

## Backend sözleşmeleri (Dalga 1)

### `backend/asusd.py` — `class AsusdClient(QObject)`
```python
available: bool                                  # bağlantı/servis var mı
platformChanged = pyqtSignal(str, object)        # (property adı, yeni değer) — PropertiesChanged'den
auraChanged = pyqtSignal(str, object)
error = pyqtSignal(str, str)                     # (işlem adı, mesaj)

def refresh(self) -> None                        # async GetAll; her özellik için platformChanged yayar
def get_cached(self, name: str) -> object | None
def set_platform(self, name: str, value) -> None # async Set; doğru D-Bus tipiyle (y/u/b) — tip tablosu içeride
def fetch_fan_curves(self, profile: Profile, callback: Callable[[list[FanCurve]], None]) -> None
def set_fan_curve(self, profile: Profile, curve: FanCurve) -> None
def set_fan_curve_enabled(self, profile: Profile, fan: str, enabled: bool) -> None
def reset_fan_curves(self, profile: Profile) -> None
def set_kbd_brightness(self, level: int) -> None # 0..3
def set_aura_static(self, rgb: tuple[int, int, int]) -> None
```
### `backend/gfx.py` — `class GfxClient(QObject)`
```python
available: bool
modeChanged = pyqtSignal(int)       # GfxMode
powerChanged = pyqtSignal(int)      # GfxPower
def refresh(self) -> None           # async Mode/Power/Supported/Pending*
mode: GfxMode | None; power: GfxPower | None; supported: list[GfxMode]
def configured_boot_mode(self) -> GfxMode | None   # /etc/supergfxd.conf "mode" (okuma, herkes okuyabilir)
def dgpu_disabled(self) -> bool | None             # sysfs dgpu_disable
def request_boot_mode(self, mode: GfxMode, callback: Callable[[bool, str], None]) -> None
    # pkexec helper/rog-control-gfx-helper set-boot-mode <integrated|hybrid> (QProcess, async)
    # yeniden başlatma gerektirir; canlı hiçbir şey değiştirmez
def nvidia_pci_path(self) -> str | None            # "/sys/bus/pci/devices/0000:01:00.0" (lspci yerine sysfs taraması: vendor 0x10de, class 0x03xxxx)
```
### `backend/sensors.py` — `class SensorReader(QObject)`
```python
updated = pyqtSignal(object)        # SensorSnapshot
def start(self, interval_ms: int = 1000) -> None; def stop(self) -> None
@dataclass SensorSnapshot:
    cpu_temp: float|None; cpu_load: float|None; ram_pct: float|None
    gpu_state: str            # "sleep" | "active" | "off" | "unknown"
    gpu_temp: float|None; gpu_load: float|None; gpu_power_w: float|None
    fans_rpm: dict[str, int]  # {"cpu":…, "gpu":…, "mid":…} (psutil "asus" çipi: cpu_fan/gpu_fan/mid_fan)
    battery_pct: float|None; battery_status: str|None  # "Charging"/"Discharging"/"Full"/"Not charging"
    on_ac: bool|None; battery_power_w: float|None       # BAT1 current_now*voltage_now
```
Örnekleme bir worker thread'de (QThreadPool, tek thread) yapılır; nvidia-smi kuralı (3) zorunlu.

### `backend/display.py` — `class DisplayClient(QObject)`
```python
changed = pyqtSignal(object)   # DisplayState(connector, current_hz, rates: list[int])
def refresh(self) -> None; def set_refresh(self, hz: int) -> None
```
- Sadece **dahili panel** (`eDP-*`) — birincil monitör DEĞİL. Wayland: Mutter `org.gnome.Mutter.DisplayConfig` (session bus,
  GetCurrentState / ApplyMonitorsConfig method=1 temporary veya 2 persistent); X11: `xrandr`. Eski `asus_helper/display.py` referans.

### `ui/` (Dalga 1-C) — bileşenler V2 tasarımına sadık
`theme.py`: token'lar (V2'deki hex'ler: zemin #0E0F13, panel #16181E, kontrol #1E2129, kenar #2A2E38, ayırıcı #23262E,
metin #ECEEF3, ikincil #A3A9B6, üçüncül #8F96A3, ink #0B0C0F; mod renkleri Sessiz #34C08A, Dengeli #4C8DFF, Turbo #FF5A5F, Özel #F2A93B;
uyarı zemini #2A2112 / kenar #5C4517 / metin #F7DDA8), IBM Plex Sans (yoksa sistem sans), `qss(accent: str) -> str`.
Vurgu rengi aktif performans modunu izler → tüm bileşenler `set_accent(hex)` destekler.
Widget'lar (her biri bağımsız, backend import ETMEZ): `ModeTile`, `ModeTileRow` (seçili/bekleyen durumları, BEKLİYOR rozeti),
`Segmented`, `ToggleSwitch` (kendisine tıklayınca da sinyal!), `SectionHeader`, `SensorPanel`, `FanCurveChart` (QPainter,
8 nokta sürüklenebilir, X 20–100 °C, Y 0–100 %, anlık sıcaklık çizgisi, seçili nokta etiketi, ok tuşları), `PendingCard`, `Banner`, `ValueSlider`.

### `helper/` (Dalga 1-D)
`rog-control-gfx-helper set-boot-mode {integrated|hybrid}` (root, pkexec):
- `/etc/supergfxd.conf` JSON'unu okur, sadece `"mode"` alanını değiştirir (`Integrated`/`Hybrid`), atomik yazar (tmp + rename), yedek tutar.
- `hybrid` iken ve `dgpu_disable == 1` ise: test edilmiş Eco-çıkış prosedürü (PHASE0 son bölüm): config→Hybrid, `/usr/bin/systemctl stop supergfxd.service`, `drivers_autoprobe=0`, `dgpu_disable=0`, doğrula.
  Başarıda `{"ok":true,"boot_mode":"Hybrid","reboot_required":true,"eco_exit":true}`; yeniden başlatma HEMEN gerekir. Kodlar: 7 = supergfxd durdurulamadı (config geri alındı), 8 = sysfs yazma/doğrulama hatası (autoprobe geri alınır, config Hybrid kalır), 3 = ayrılmış/kullanılmıyor.
- Asla `supergfxctl -m` ya da reboot çağırmaz; tek alt süreç yukarıdaki systemctl stop (mutlak yol, temiz env, shell yok). Girdi doğrulaması sıkı; bilinmeyen argüman → çıkış 2.
`org.rogcontrol.gfx.policy`: `auth_admin_keep`. `install.sh`: helper'ı `/usr/local/libexec/`, policy'yi `/usr/share/polkit-1/actions/` altına kopyalar (çalıştırmak kullanıcıya kalır).

---

## Dalga 2 sözleşmesi — `core/` ↔ `ui/windows/`

Dalga 1'in gerçek API'leri kaynak koddadır (`rog_control/backend/*.py`, `rog_control/ui/widgets/*.py`); sözleşmeden
sapmalar orada belgelendi (ör. `AsusdClient(bus=None, parent=None)`, `availableChanged`, `Typed/Variant`). Okuyun.

### Uygulama modu kavramı
`PerfMode` (str): `"quiet" | "balanced" | "turbo" | "custom"` → UI: Sessiz / Dengeli / Turbo / Özel.
- quiet/balanced/turbo = asusd `ThrottleThermalPolicy` QUIET/BALANCED/PERFORMANCE.
- custom ("Özel") = uygulama modu: policy PERFORMANCE + kullanıcının PL1/PL2/FPPT değerleri (`PptPl1Spl/PptPl2Sppt/PptFppt`)
  + Performance profilinin fan eğrileri. Özel'den çıkınca sadece policy yazılır (firmware kendi limitlerine döner — doğrulanmadı,
  loglanır). Özel değerleri QSettings'te saklanır (varsayılan 60/90/110 W, aralık 15–170).
- Dışarıdan (Fn tuşu) policy değişirse: aktif mod policy'den türetilir (custom bilgisi kaybolur → balanced/quiet/turbo).

### `core/state.py` — `class AppState(QObject)` (salt veri + sinyaller, backend import ETMEZ)
```python
perfModeChanged = pyqtSignal(str)                 # PerfMode
accentChanged = pyqtSignal(str)                   # hex, perfMode'dan türetilir
sensorsChanged = pyqtSignal(object)               # backend.sensors.SensorSnapshot
gfxChanged = pyqtSignal(object)                   # GfxView (aşağıda)
displayChanged = pyqtSignal(object)               # DisplayView
batteryLimitChanged = pyqtSignal(int)
platformChanged = pyqtSignal(str, object)         # ham asusd özellik değişimi (EPP, NV, OnAc/OnBattery …)
fanCurvesChanged = pyqtSignal(str, object)        # (perfMode, list[FanCurve])
auraChanged = pyqtSignal(object)                  # AuraView(brightness:int|None, color:(r,g,b)|None)
busyChanged = pyqtSignal(str, bool)               # (işlem anahtarı, meşgul mü) — UI butonları kilitlemek için
message = pyqtSignal(str, str)                    # (seviye "info"|"warn"|"error", Türkçe metin) — toast/banner
# + aynı adlı okunabilir özellikler: perf_mode, accent, sensors, gfx, display, battery_limit, platform(dict), aura
@dataclass GfxView: active: str|None ("eco"|"standard"|"ultimate"), boot: str|None (config'deki), pending: str|None,
                    power: str ("sleep"|"active"|"off"|"unknown"), dgpu_disabled: bool|None, mux_direct: bool|None,
                    can_eco_exit: bool  # şimdilik False
@dataclass DisplayView: connector: str|None, current_hz: int|None, rates: list[int], auto: bool
```
### `core/controller.py` — `class Controller(QObject)` (tek yazma yolu; UI yalnızca bunu çağırır)
```python
def __init__(self, state: AppState, asusd, gfx, sensors, display, settings: QSettings)
def start(self)                                   # refresh'leri başlat, sinyalleri bağla, sensörü 1 sn başlat
def set_perf_mode(self, mode: str)
def set_custom_limits(self, pl1: int, pl2: int, fppt: int)   # custom aktifse hemen yazar
def request_gpu_mode(self, mode: str)             # "eco"|"standard" — helper (pkexec) ile BOOT modu; sonuç → state.gfx.pending + message
def cancel_gpu_pending(self)                      # boot config'i aktif moda geri yazar (helper)
def reboot_now(self)                              # logind org.freedesktop.login1.Manager.Reboot(false) — UI onay diyaloğundan SONRA çağırır
def set_refresh(self, hz: int | None)             # None = Otomatik (prizde en yüksek, pilde 60; on_ac değişince uygular)
def set_panel_od(self, on: bool)
def set_battery_limit(self, pct: int)             # 20..100
def load_fan_curves(self, mode: str)              # → state.fanCurvesChanged
def apply_fan_curve(self, mode: str, fan: str, points: list[tuple[int,int]])  # % → pwm, enabled=True
def reset_fan_curves(self, mode: str)
def set_epp(self, mode: str, epp: int)            # Throttle{Quiet,Balanced,Performance}Epp (custom → Performance)
def set_nv_boost(self, w: int); def set_nv_temp_target(self, c: int)
def set_auto_profile(self, on_ac: str, on_battery: str)   # ThrottlePolicyOnAc/OnBattery + Change*=true
def set_kbd_brightness(self, level: int); def set_kbd_color(self, rgb: tuple[int,int,int])
```
Kurallar: her yazma `busyChanged(key, True/False)` ile sarılır; hata → `message("error", Türkçe açıklama)`; hiçbir çağrı bloklamaz;
GPU için sadece `gfx.request_boot_mode` (helper) — Eco çıkışı başarılırsa `gpuRebootRequired` sinyali (UI hemen yeniden başlatma sorar), kod 7/8 → Türkçe hata;
`ultimate` ve `optimize` şimdilik desteklenmez (UI devre dışı + tooltip).

### `ui/windows/` (Dalga 2-F)
`MainWindow` (V2Main), `FansWindow` (V2Fans), `KeyboardWindow` (parlaklık Segmented + 16 renk swatch + uygula),
`SettingsWindow` (oturumda başlat → `~/.config/autostart/rog-control.desktop`, tepside küçült, bildirimler),
`MiniWindow` + `Tray` (V2MiniTray). Pencereler YALNIZCA `AppState` okur/dinler ve `Controller` çağırır.
`app.py`: QApplication, `theme.apply`, backend nesneleri, state, controller, pencereler, tray; tek örnek (QLocalServer ile ikinci
başlatma mevcut pencereyi öne getirir); `--minimized`. `__main__.py`: `main()`.
