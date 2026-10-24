<p align="center"><img src="assets/logo.png" width="200" alt="Alaz logosu"></p>

# Alaz

ASUS ROG dizüstü bilgisayarlar için Linux'ta çalışan, [G-Helper](https://github.com/seerge/g-helper)'dan esinlenmiş bir kontrol merkezi. `asusd` ve `supergfxd` üzerine kuruludur.

*Eski adı ROG Control.* Alaz, eski Türkçede "alev" demek. ASUS ile bağlantısı olmayan bağımsız bir projedir; ASUS ve ROG, ASUSTeK Computer Inc.'in ticari markalarıdır.

[![Tests](https://github.com/n3vrb/alaz/actions/workflows/tests.yml/badge.svg)](.github/workflows/tests.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

[English](README.md) | Türkçe

> **Durum: erken aşamada, yalnızca tek makinede test edildi.** Core Ultra 9 285H ve RTX 5070 Laptop'lu bir ASUS ROG Zephyrus (2025) üzerinde, Zorin OS 18 (GNOME, Wayland) ile geliştirildi ve doğrulandı. Diğer modellerde davranış farklı olabilir. Bkz. [Güvenlik ve sınırlamalar](#8-güvenlik-ve-sınırlamalar).
>
> **Arayüz İngilizce ve Türkçe olarak sunulur.** Dil sistem yerel ayarına göre seçilir (`tr` ile başlıyorsa Türkçe, aksi halde İngilizce); Ayarlar → Dil bölümünden değiştirilebilir (yeniden başlatınca uygulanır). Yeni çeviriler memnuniyetle karşılanır: bkz. `alaz/i18n.py` ve `alaz/i18n_en.py`.

<p align="center">
  <img src="docs/screenshots/tr/main-balanced.png" width="300" alt="Ana pencere, Dengeli mod">
  <img src="docs/screenshots/tr/main-turbo.png" width="300" alt="Ana pencere, Turbo mod">
</p>

## 1. Ekran görüntüleri

| | |
|---|---|
| ![Eco bekliyor](docs/screenshots/tr/main-eco-pending.png) Eco seçili, bir sonraki açılışta uygulanıyor (canlı geçiş kurulu değilken geçerli yedek yol) | ![Fanlar ve güç](docs/screenshots/tr/fans-power.png) Fan eğrisi editörü, güç limitleri, NVIDIA, EPP |
| ![Mini pencere](docs/screenshots/tr/mini.png) Mini pencere | ![Tepsi menüsü](docs/screenshots/tr/tray-menu.png) Tepsi menüsü |
| ![Klavye](docs/screenshots/tr/keyboard.png) Klavye parlaklığı ve rengi | ![Ayarlar](docs/screenshots/tr/settings.png) Ayarlar |

Ekran görüntüleri sahte verilerle üretilmiştir (`tools/screenshot_windows.py`); model adı ve sensör değerleri örnektir.

## 2. Özellikler

- **Performans modları:** Sessiz, Dengeli, Turbo (asusd termal politikaları) ve **Özel** (uygulama düzeyinde bir mod: Turbo politikası artı kendi limitlerin).
- **Özel güç limitleri:** PL1 (SPL, 15–120 W), PL2 (SPPT, 15–150 W) ve FPPT (15–170 W); varsayılanlar 60/90/110 W. Yalnızca Özel modda uygulanır.
- **Fan eğrisi editörü:** Her fan için (CPU, GPU, varsa MID), profil başına 8 sürüklenebilir nokta; varsayılana sıfırlama. Özel mod, Turbo'nun fan eğrilerini paylaşır.
- **NVIDIA Dynamic Boost ve sıcaklık hedefi** kaydırıcıları (asusd özellikleri).
- Profil başına **EPP** (enerji/performans tercihi).
- **Prize takılı / pil için otomatik profil:** Prizdeyken bir profil, pildeyken başka bir profil uygulanır.
- **GPU modları:**
  - **Eco ve Standart, yeniden başlatmadan canlı geçer** (yaklaşık 10–13 sn); `supergfxctl -m` ile değil, Alaz'ın kendi root yardımcısıyla ([nedeni](#4-bu-proje-neden-var-neler-öğrendik)). Bunun için isteğe bağlı yardımcının kurulması ve yeniden oturum açılması gerekir ([Kurulum](#6-kurulum)); aksi halde Alaz değişikliği bir sonraki açılışta uygulamaya geri döner.
  - **Optimize:** Prizdeyken Standart, pildeyken Eco; otomatik geçer (5 sn bekleme payıyla). dGPU'yu kullanan bir uygulama varsa o kapanana kadar bekler; hiçbir şeyi sonlandırmaz ve asla yeniden başlatmaz.
  - **Ultimate (MUX, dGPU doğrudan)** asusd üzerinden yazılır ve yeniden başlatma gerektirir. Kod hazır ama gerçek donanımda henüz denenmedi; risk uyarısı diyaloğuyla gelir.
  - dGPU'yu kullanan bir uygulama varken canlı geçiş reddedilir; Alaz kapanmasını beklemeyi, yeniden başlatınca uygulamayı ya da vazgeçmeyi sunar.
- Yalnızca **dahili panelin** yenileme hızı (harici monitöre dokunmaz) ve Otomatik seçeneği: prizde en yüksek hız, pilde 60 Hz.
- **Panel Overdrive** anahtarı.
- **Şarj limiti** (%20–%100).
- **Klavye** parlaklığı ve rengi (Aura sabit renk).
- **dGPU'yu uyandırmayan canlı sensörler:** CPU/GPU sıcaklığı ve yükü, fan devri, RAM, pil.
- RAPL `psys` sayacıyla **toplam sistem gücü** (prizde ve pilde watt).
- Anlık watt gösteren **tepsi simgesi**, profil ve GPU modu menüsü, kompakt **mini pencere**.
- Tek örnek çalışır; isteğe bağlı oturumda otomatik başlatma (tepside küçültülmüş) ve profil dışarıdan değişince (örneğin Fn tuşu) isteğe bağlı bildirim.

## 3. Gereksinimler

- [`asusctl`](https://asus-linux.org) tarafından desteklenen bir ASUS ROG / TUF dizüstü. `asusd` (test edilen: 6.0.12) ve `supergfxd` (test edilen: 5.2.7) kurulu ve çalışır durumda olmalı.
- PyQt6 (QtDBus dahil) ve `psutil` ile Python 3. Python 3.12 ve PyQt6 6.6 / Qt 6.4 ile geliştirildi; `pyproject.toml` Python 3.10+ ve PyQt6 6.4+ bildirir.
  Ubuntu tabanlı dağıtımlarda: `sudo apt install python3-pyqt6 python3-psutil`.
- Yenileme hızı kontrolü için GNOME (Wayland veya X11): Mutter'ın DisplayConfig D-Bus API'sini, X11'de `xrandr`'ı kullanır. Diğer ortamlar test edilmedi.
- İsteğe bağlı: GPU modu geçişi için `polkit`/`pkexec` ve aşağıdaki ayrıcalıklı yardımcı.

## 4. Bu proje neden var: neler öğrendik

Mevcut araçların çoğu GPU'yu `supergfxctl` ile canlı değiştirir. Bu donanımda bu, oturumu bozuyor; güvenilir bir Eco modu için (önce açılışta, sonra canlı) birbiriyle ilgisiz bir dizi sorunu bulmak gerekti. Aşağıdaki özetin her maddesi komutlar ve geri alma adımlarıyla **[docs/SYSTEM_SETUP.md](docs/SYSTEM_SETUP.md)** dosyasında anlatılıyor (İngilizce). Hepsi yalnızca yukarıdaki referans makinede doğrulandı.

- **`supergfxctl -m` GNOME'u bozar.** Oturum açıkken Eco'ya girerken gnome-shell ve Xwayland'i öldürdü, Eco'dan çıkarken Wayland gnome-shell'i dondurdu. Alaz onu hiç çağırmaz.
- **Canlı geçiş, kompozitör NVIDIA kartından uzak tutulunca çalışır.** Asıl nedenler: mutter'ın NVIDIA DRM kartını açması ve gnome-shell/Xwayland'in NVIDIA EGL'sini yüklemesi. İki udev kuralı (mutter NVIDIA kartını yok sayar; NVIDIA render düğümünde `uaccess` ACL yok) ve EGL'yi Mesa'ya yönlendiren bir oturum değişkeni bunu çözer; `/dev/nvidia*` erişilebilir kaldığı için GLX/EGL/Vulkan/CUDA offload çalışmaya devam eder. Geçiş sırasında yardımcı ayrıca Ubuntu'nun `71-nvidia.rules` dosyasını maskeler (yoksa udev sürücüyü bitmeyen bir döngüyle yükleyip boşaltıyor) ve işi bitince her durumda geri alır. Tasarım: [docs/LIVE_GPU_CONTRACT.md](docs/LIVE_GPU_CONTRACT.md) (İngilizce).
- **Eco'ya giriş:** `/etc/supergfxd.conf` içinde `"mode": "Integrated"` yap ve yeniden başlat.
- **Eco'dan çıkış (hile):** supergfxd Eco'dan kendiliğinden çıkmaz (`dgpu_disable=1` görünce modu yine Integrated'a zorlar). Çalışan sıra: supergfxd'yi durdur, `/sys/bus/pci/drivers_autoprobe` değerini `0` yap, yapılandırmada modu Hybrid yap, `dgpu_disable=0` yaz, **yeniden başlat**. Kart sürücüsüz geri gelir; masaüstü çalışırken yeni bir GPU belirmez.
- **Plymouth, Eco girişini şansa bağladı.** Açılış logosu, o an mevcut tek DRM aygıtı olan NVIDIA'yı (~4,5. saniye) açıyordu; supergfxd'nin `rmmod nvidia` komutu "module in use" ile başarısız oldu ve Eco yarım kaldı. Çekirdek satırından `splash` kaldırmak sorunu çözdü; bedeli yaklaşık 6,5 sn daha uzun açılış.
- **Ubuntu'nun `gpu-manager`'ı supergfxd ile yarışır.** İkisi de GPU durumunu yönetmek ister; bir açılış `nv_pci_remove` içinde kilitlenmeyle bitti. `gpu-manager.service` maskelenmeli.
- **`power-profiles-daemon` ve `asusd` çatışır:** ikisi de `platform_profile` yazar. power-profiles-daemon maskelenip profilleri asusd'ye bırakmak gerekir.
- **`nvidia-smi` yoklamak dGPU'yu uyanık tutar.** Uygulama onu yalnızca aygıt zaten aktifken ve `/dev/nvidiaN`'i gerçekten tutan bir süreç varken çağırır. Kompozitörler bu düğümü GPU'yu uyandırmadan sürekli açık tuttuğu için sayılmaz.
- **Windows ile çift önyükleme**, `dgpu_disable=1` bırakabilir (G-Helper'ın Eco'su). supergfxd `hotplug_type` değerini `Asus` yap; Linux bu durumla savaşmak yerine onu benimser.
- **Realtek kart okuyucu:** bu modelde ASPM, PCIe AER hata yağmuruna yol açıyor; bu yüzden `pcie_aspm=off` gerekli. Bu modelde kaldırma.
- **`GRUB_DEFAULT` sıra numarasıyla değil isimle** verilmeli; böylece menü değişince "UEFI Firmware Settings" satırına düşmez.

## 5. Teknoloji ve mimari

- **Python 3.12, PyQt6 (Qt 6.4).** GUI thread'i asla bloklanmaz: tüm D-Bus çağrıları QtDBus ile asenkrondur; `subprocess` ve yavaş G/Ç worker thread'lerde çalışır.
- **D-Bus API'leri:** asusd (`org.asuslinux.Daemon`: Platform, FanCurves, Aura) ve supergfxd (`org.supergfxctl.Daemon`, yalnızca okuma; `SetMode` ve `SetConfig` bilerek hiç çağrılmaz).
- **Sensörler:** `psutil` ile sysfs/hwmon, RAPL için `powercap`.
- **Ekran:** D-Bus üzerinden Mutter `org.gnome.Mutter.DisplayConfig`, X11'de `xrandr`.
- **Yetki:** polkit + `pkexec` yardımcısı, yalnızca GPU modu için (açılış modu yapılandırması, Eco çıkışı ve canlı Eco/Standart geçişi); bir udev kuralı yalnızca RAPL `psys` sayacını açar.

```
alaz/
├── app.py, __main__.py   giriş noktası, tek örnek, tepsi, bağlantılar
├── backend/              asusd.py, gfx.py, sensors.py, display.py, dbus_util.py, types.py
├── core/                 state.py (AppState: veri + sinyaller), controller.py (tek yazma yolu)
└── ui/                   theme.py, widgets/ (kutucuklar, fan grafiği, kartlar, kontroller), windows/
helper/
├── alaz-gfx-helper         root yardımcı (yalnızca standart kütüphane)
├── org.alaz.gfx.policy      polkit eylemi
├── 90-alaz-rapl.rules      udev kuralı (yalnızca RAPL psys)
├── 61-…/72-… .rules        canlı GPU geçişi için udev kuralları
└── install.sh / uninstall.sh      ayrıcalıklı kurulum, sudo ile çalışır
tests/                             pytest, ekransız (offscreen) Qt
tools/                             ekran görüntüsü ve widget galeri betikleri
```

Pencereler `AppState`'i okur ve `Controller`'ı çağırır; backend'lerle doğrudan konuşmaz. Her yazma işlemi meşgul/hata raporlamasıyla sarılıdır. Modül sözleşmeleri için [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) dosyasına bak (Türkçe).

## 6. Kurulum

### Uygulama (sudo gerekmez)

```bash
git clone https://github.com/n3vrb/alaz.git
cd alaz
./install.sh
```

Uygulamayı `~/.local/share/alaz` altına, başlatıcıyı `~/.local/bin/alaz` olarak, bir masaüstü girdisi ve bir simge ile birlikte kurar; Mesa'nın EGL vendor dosyası varsa canlı GPU geçişinin ihtiyaç duyduğu `~/.config/environment.d/90-alaz-egl-mesa.conf` dosyasını da koyar. `~/.local/bin` dizininin `PATH` içinde olduğundan emin ol.

### Oturum açılışında başlatma

```bash
./install.sh --autostart                  # systemd kullanıcı servisini kurar ve etkinleştirir
journalctl --user -u alaz -f       # günlükler
systemctl --user restart alaz      # yeniden başlat
systemctl --user disable --now alaz   # kapat (veya Ayarlar'daki anahtar)
```

Servis, oturum açılınca uygulamayı tepside küçültülmüş başlatır (tepsi hazır olana kadar en fazla 20 sn bekler). Hemen başlatmak için `--start` ekle.

### İlk çalıştırma

Uygulama menüsünden **Alaz**'ü aç ya da `alaz` komutunu çalıştır. Performans modları, fan eğrileri, güç limitleri, ekran ve klavye kontrolleri `asusd` çalışır çalışmaz kullanılabilir. GPU modu geçişi ve toplam güç göstergesi için aşağıdaki isteğe bağlı bölüm gerekir. **Canlı Eco/Standart geçişi için `sudo ./helper/install.sh` çalıştır, sonra oturumu kapatıp yeniden aç** (ortam değişkeni dosyası yalnızca oturum açılışında okunur).

### İsteğe bağlı ayrıcalıklı yardımcı (sudo gerekir)

```bash
sudo ./helper/install.sh
```

Şu dosyaları kurar:

| Dosya | Amaç |
|---|---|
| `/usr/local/libexec/alaz-gfx-helper` | `pkexec` ile çalışan root yardımcı |
| `/usr/share/polkit-1/actions/org.alaz.gfx.policy` | polkit eylemi (`auth_admin_keep`) |
| `/etc/udev/rules.d/90-alaz-rapl.rules` | RAPL `psys` sayacını okunabilir yapar |
| `/etc/udev/rules.d/61-alaz-mutter-ignore-nvidia.rules` | mutter NVIDIA DRM kartını yok sayar (yalnızca MUX Optimus iken) |
| `/etc/udev/rules.d/72-alaz-nvidia-render-noaccess.rules` | NVIDIA render düğümünde `uaccess` ACL yok (yalnızca MUX Optimus iken) |
| `/etc/udev/rules.d/70-alaz-peripherals.rules` | desteklenen çevre birimlerine erişim (Cihazlar penceresi) |

Polkit dosyası üç eylem tanımlar (`set-boot-mode`, `live-eco`, `live-hybrid`); canlı olanlar etkin yerel oturumda parola sormaz.

**Yardımcının yapabildikleri:** yalnızca `/etc/supergfxd.conf` içindeki `"mode"` anahtarını (Integrated veya Hybrid) yedek alarak ve atomik biçimde değiştirir; açılış yolu için test edilmiş Eco çıkış sırasını çalıştırır; canlı geçişi yapar (`live-eco` / `live-hybrid`: NVIDIA modüllerini boşalt ya da yükle, PCI aygıtını kaldır ya da yeniden tara, `dgpu_disable` yaz) ve dGPU'yu kullanan süreçleri yalnızca okuyarak listeleyen bir `holders` komutu sunar. Symlink olan yapılandırmayı reddeder, tüm girdiyi doğrular; MUX doğrudan dGPU'ya ayarlıyken ya da udev kuralı yokken canlı geçişi, bir süreç dGPU'yu tutuyorken de geçişi reddeder (hiçbir süreci sonlandırmaz).

**Yapmadıkları:** `supergfxctl`'yi asla çağırmaz, hiçbir süreci sonlandırmaz, yeniden başlatmaz (uygulama sana sorar, sonra logind üzerinden yeniden başlatır) ve yalnızca sabit sistem araçlarını mutlak yolla çalıştırır (`systemctl`, `modprobe`, `udevadm`); temiz ortam, kabuk yok.

**Güvenlik notları**

- Açılışta uygulanan GPU değişiklikleri yönetici kimlik doğrulaması ister (`auth_admin_keep`: yetki kısa bir süre hatırlanır). Canlı geçişler (`live-eco`, `live-hybrid`) etkin yerel oturum için parolasız izinlidir; çünkü yalnızca Eco ile Standart arasında geçiş yapabilirler ve uygulamalar GPU'yu kullanırken reddederler. Parola sorulmasını istersen polkit dosyasını sil ya da düzenle.
- udev kuralı, `psys` RAPL alanının `energy_uj` dosyasını herkes tarafından okunabilir yapar; paket, çekirdek ve DRAM alanlarına dokunulmaz. Herkesçe okunabilir RAPL enerji sayaçları yan kanal araştırmalarında (PLATYPUS) kullanılmıştır; burada maruziyet yalnızca platform sayacıyla sınırlıdır, ama bu seni rahatsız ediyorsa udev kuralını silebilirsin (sistem gücü göstergesi o zaman kullanılamaz).

### Kaldırma

```bash
./uninstall.sh                 # uygulama (ayarlar korunur)
sudo ./helper/uninstall.sh     # kurulduysa isteğe bağlı ayrıcalıklı kısım
```

## 7. Önerilen sistem ayarları

Bunlar GPU geçişini ve profilleri güvenilir kılar. Hepsi isteğe bağlıdır ve **açılışla ilgili her değişiklik kendi sorumluluğundadır**: yanlış bir GRUB ya da sürücü yükleme değişikliği siyah ekrana yol açabilir. Yanında bir canlı USB bulundur ve her adımdan önce **[docs/SYSTEM_SETUP.md](docs/SYSTEM_SETUP.md)** içindeki geri alma adımını oku.

1. NVIDIA çekirdek modülü ile kullanıcı alanı sürümlerini eşitle (güncellemeden sonra yeniden başlat).
2. `/etc/supergfxd.conf`: `"hotplug_type": "Asus"`, `"always_reboot": true`.
3. `sudo systemctl mask power-profiles-daemon`
4. `sudo systemctl mask gpu-manager.service` (Ubuntu tabanlı sistemler).
5. `GRUB_CMDLINE_LINUX_DEFAULT` içinden `splash`'ı kaldır (`quiet` kalsın), sonra `sudo update-grub`.
6. Çift önyükleme: `GRUB_DEFAULT` değerini girdi adıyla ver.
7. Modelin gerektiriyorsa `pcie_aspm=off` kalsın (referans makinede gerekiyordu).

Rehberin 7d bölümü canlı geçiş kurulumunu anlatır (neler kurulur, nasıl doğrulanır, yan etkiler, geri alma). Rehberde ayrıca **yapılmaması** gerekenler de var: canlı `supergfxctl -m`, NVIDIA otomatik yüklemesini kara listeye almak (dört siyah ekranlı açılış) ve supergfxd bekleme drop-in'i (her açılışa 20 sn ekler).

## 8. Güvenlik ve sınırlamalar

- **Yalnızca tek model test edildi.** Diğer her şey doğrulanmamıştır. Başka modellerden hata raporları çok değerlidir.
- **Canlı geçiş için yardımcının kurulması ve yeniden oturum açılması gerekir** ve yalnızca MUX Optimus (Standart/Eco) modundayken çalışır. Aksi halde Eco'dan çıkış hemen yeniden başlatmaya düşer (dGPU sürücüsüz olarak yeniden etkinleştirilir ve `drivers_autoprobe` o zamana kadar `0` kalır); uygulama bunu sorar.
- **dGPU'yu kullanan uygulamalar canlı geçişi engeller.** Hiçbir şey sonlandırılmaz: kapanmalarını bekleyebilir, yeniden başlatınca uygulatabilir ya da vazgeçebilirsin.
- **dGPU'ya bağlı portlar** (referans makinede bir HDMI ve bir DisplayPort) Eco'da harici ekran vermez; canlı geçiş udev kuralıyla Standart'ta da vermez.
- **Yalnızca EGL kullanan uygulamalar varsayılan olarak iGPU'da çalışır** (örneğin Wayland'de Blender görünüm penceresi). dGPU için `__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json` ile başlat; GNOME'un "Ayrık GPU ile başlat" seçeneği bunu ayarlamaz. CUDA/OptiX render etkilenmez.
- **Açık konular:** Ultimate (MUX) donanımda denenmedi; harici monitör bağlıyken canlı Eco geçişi henüz sınanmadı (bir denemede dahili panel kendiliğinden yeniden açıldı). Bkz. [docs/TODO.md](docs/TODO.md).
- **`splash`'ı kaldırmak** referans makinede açılışı yaklaşık 6,5 sn uzatır.
- **Özel mod, Turbo'nun fan eğrilerini paylaşır** (Performance politikasını kullanır). Özel'den çıkınca yalnızca politika yazılır; donanım yazılımının kendi limitlerine dönüp dönmediği doğrulanmadı.
- Referans makinede boşta tüketim pilde yaklaşık 15–16 W (ölçüldü; RAPL `psys` değeri 1–2 W daha yüksek gösteriyor). `pcie_aspm=off` muhtemelen bunun bir kısmına mal oluyor ama bu modelde gerekli (yukarıya bakın).
- Referans makinede `nvidia-powerd` kurulu değildi ve Dynamic Boost ona bağlı; oradaki kaydırıcının etkisi incelenmedi.
- Arayüz yalnızca İngilizce ve Türkçedir (Ayarlar → Dil; diğer diller katkı olarak memnuniyetle karşılanır).

## 9. Geliştirme

```bash
python3 -m venv .venv --system-site-packages   # ya da PyQt6 ve psutil'i kendi venv'ine kur
QT_QPA_PLATFORM=offscreen python3 -m pytest tests
QT_QPA_PLATFORM=offscreen python3 tools/screenshot_windows.py docs/screenshots/tr --lang tr   # pencereleri sahte durumla çiz
```

Test takımında 591 test var (backend'ler, core controller ve state, widget'lar, pencereler, root yardımcı) ve ekransız çalışır. **Testler gerçek sisteme asla yazmaz**; yazma yolları mock, sahte nesneler ve yeniden köklendirilmiş yardımcıyla (`ALAZ_HELPER_TESTROOT`, yalnızca root değilken geçerli) sınanır.

Katkı kuralları ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) kaynaklı): GUI thread'ini asla bloklama; `supergfxctl -m` ya da supergfxd `SetMode`/`SetConfig` çağırma (canlı geçiş yalnızca yardımcıdan geçer, bkz. [docs/LIVE_GPU_CONTRACT.md](docs/LIVE_GPU_CONTRACT.md)); izleme için dGPU'yu uyandırma; okunamayan değer `None` olur ve uydurma sayı yerine tire olarak görünür; `print` yerine `logging` kullan. Değişikliğinle birlikte test ekle ya da güncelle. Pull request'ler memnuniyetle karşılanır; özellikle: çeviriler, diğer ROG modelleri, Ultimate/MUX denemesi, diğer masaüstü ortamları.

### Nasıl yapıldı

Bu proje Anthropic'in Claude'u ile tasarlandı ve yönetildi: bir orkestratör model işi dalgalara böldü, her modülü yazılı sözleşmelerle Claude Sonnet alt ajanlarına devretti, çıktılarını ve testlerini gözden geçirdi. Proje sahibi her şeyi gerçek donanımda test etti ve ürün kararlarını verdi. Bu README'deki sistem bulguları tahminlerden değil, o gerçek donanım testlerinden geldi.

## 10. Teşekkürler

- [asusctl / asusd ve supergfxctl](https://asus-linux.org): asus-linux.org projesi; Alaz yalnızca onların servislerine bir ön yüzdür.
- Özellik setine ve görünüme ilham veren [G-Helper](https://github.com/seerge/g-helper) (seerge).
- Tipografi için tasarım referansı olarak IBM Plex Sans.

## Lisans

GPL-3.0. Bkz. [LICENSE](LICENSE).
