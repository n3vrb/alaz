# Aşama 0 — Sistem düzeltmesi (Eco modu + sürücü + güç profili çakışması)

> Bu adımlar `sudo` gerektirir; kullanıcı kendisi çalıştırır. Her adımdan sonra
> çıktı orkestratöre gösterilir, bir sonraki adıma ancak o zaman geçilir.

## Teşhis özeti (2026-10-02, loglardan)

- 16 Eylül: `supergfxctl -m Integrated` → supergfxd `display-manager`'ı durdurdu,
  X11 oturumundaki süreçler (Xorg, gnome-shell, tarayıcılar) NVIDIA sürücüsünü
  tuttuğu için takıldı; 28 sn sonra kapanış geldi. Mod **kaydedilmedi**.
- Sonraki açılışta: `dgpu_disable=1` (yarım geçiş veya Windows G-Helper Eco'su),
  ama supergfxd `hotplug_type: None` → "re-enable dgpu" yaptı; arada NVIDIA
  modülü kapalı kartı yoklayıp **"GPU has fallen off the bus"** hatası verdi.
- Sürücü: çalışan çekirdek modülü 580.159, DKMS ve kullanıcı alanı 580.178
  (sadece yeniden başlatma bekliyor). `nvidia-driver-570-open` artık gereksiz
  bir metapaket. `nvidia-dkms-580` sadece "rc" (yapılandırma artığı).
- `power-profiles-daemon` ve `asusd` ikisi de `platform_profile` yazıyor.

## Adım 1 — Sürücüyü hizala
1. Yeniden başlat.
2. Doğrula: `cat /proc/driver/nvidia/version` → 580.178 olmalı; `nvidia-smi` hatasız.
3. Artıkları temizle:
   ```bash
   sudo apt remove nvidia-driver-570-open
   sudo apt purge nvidia-dkms-580
   ```

## Adım 2 — supergfxd'yi ASUS yöntemine geçir (Windows G-Helper ile uyumlu)
`/etc/supergfxd.conf` içinde:
```json
"hotplug_type": "Asus",
"always_reboot": true
```
- `Asus` → Eco = firmware `dgpu_disable` (kart PCI hattından tamamen kalkar;
  NVIDIA modülü onu hiç görmez → "fallen off the bus" olmaz). Açılışta
  `dgpu_disable=1` görürse modu Integrated'a **uydurur** (Windows'tan gelen Eco).
- `always_reboot` → canlı logout/display-manager durdurma yok; geçiş yeniden
  başlatmada uygulanır (X11'de takılan kısım tamamen atlanır).
```bash
sudo systemctl restart supergfxd
```

## Adım 3 — Kontrollü Eco testi (pildeyken, harici monitör takılı değilken)
1. `supergfxctl -m Integrated` → `supergfxctl -p` "reboot" demeli.
2. Yeniden başlat. Kontrol:
   - `supergfxctl -g` → Integrated
   - `cat /sys/devices/platform/asus-nb-wmi/dgpu_disable` → 1
   - `lspci | grep -i nvidia` → boş
   - `journalctl -b -k | grep -i nvrm` → "fallen off the bus" OLMAMALI
3. Geri dönüş: `supergfxctl -m Hybrid` + yeniden başlat.
4. **Kurtarma (gerekirse):** Windows'ta G-Helper → Standart, ya da Linux'ta
   `echo 0 | sudo tee /sys/devices/platform/asus-nb-wmi/dgpu_disable` + reboot.

> Not: Eco modunda harici DP/HDMI çıkışı dGPU'ya bağlıysa çalışmaz (beklenen).

## Adım 4 — Güç profili çakışması
Seçenek A (önerilen): profil yönetimini asusd + yeni uygulamaya bırak:
```bash
sudo systemctl mask power-profiles-daemon
```
(GNOME menüsündeki güç modu seçici kaybolur; yeni uygulamanın tray menüsü onun yerini alır.)
Seçenek B: ppd kalsın, uygulama ppd'yi tek kaynak olarak kullansın (daha az özellik).

## Adım 5 — Küçük temizlik
- Çekirdek satırındaki tanınmayan `nvidia.NVreg_EnableBacklightHandler=0` kaldırılabilir (zararsız).

## Sonuçlar (2026-10-02 akşam)

- Adım 1–2 uygulandı: sürücü 580.178 hizalı (RTX 5070 Laptop), 570/dkms-580 artıkları silindi,
  supergfxd `hotplug_type: Asus` + `always_reboot: true`, power-profiles-daemon masked.
- **UYARI — canlı geçiş yasak:** `supergfxctl -m Integrated` oturum açıkken çalıştırıldığında
  `always_reboot`'a rağmen supergfxd canlı geçiş yaptı: gnome-shell ve Xwayland'i ÖLDÜRDÜ
  (oturum çöktü), sonra rmmod hatası yüzünden Hybrid'e geri döndü ve modprobe/Vulkan ICD
  dosyalarını Integrated halinde bıraktı (`systemctl restart supergfxd` düzeltti).
- **Çalışan yöntem — açılışta geçiş:** `/etc/supergfxd.conf` içinde `"mode"` değiştir + reboot.
  supergfxd `Before=display-manager.service` olduğundan geçişi GDM'den önce, kimse kartı
  tutmazken yapar. Eco testi: mode Integrated, status off, dgpu_disable=1, lspci'de NVIDIA yok.
  DÜZELTME: ilk Eco açılışında aslında "fallen off the bus" hataları VARDI (0.7 sn, initramfs'teki
  nvidia modülü kapalı kartı yokluyordu). Çözüm: /etc/modprobe.d/rog-control-nvidia-noauto.conf
  (blacklist nvidia*), initramfs-tools/modules içindeki geçersiz `framebuffer-nvidia` satırı
  yorumlandı, `update-initramfs -u -k all`. Sonrasında Eco açılışı TEMİZ ("No NVIDIA GPU found"
  dışında satır yok); Hybrid'de sürücüyü supergfxd adıyla yüklüyor (3.6 sn) — çalışıyor.
- **Canlı Eco→Hybrid de yasak:** `supergfxctl -m Hybrid` canlıda kartı geri getirdi ve sürücü
  yüklendi, ama Wayland gnome-shell yeni GPU'yu hotplug ederken kilitlendi ("Failed to hotplug
  secondary gpu", EGL hataları) → güç düğmesiyle kapatma gerekti. Sonuç: bu sistemde GPU iki
  yönde de canlı eklenip çıkarılamaz.
- Açılışta Eco'dan çıkış da kendiliğinden olmaz: supergfxd `asus_boot_safety_check`,
  dgpu_disable=1 görünce modu Integrated'a zorlar.
- Uygulama tasarımı (polkit yardımcısı, `supergfxctl -m` ASLA canlı çağrılmaz):
  - Eco'ya giriş: config "mode"=Integrated → yeniden başlat. (test edildi, temiz)
  - Eco'dan çıkış: `systemctl stop supergfxd` → config "mode"=Hybrid → dgpu_disable=0 yaz
    (noauto blacklist sayesinde sürücü yüklenmez, gnome-shell'in yakalayacağı DRM aygıtı oluşmaz)
    → yeniden başlat. (HENÜZ TEST EDİLMEDİ)
- Açık konu: Eco'da boşta ~22 W tüketim yüksek. Şüpheliler: `pcie_aspm=off` çekirdek
  parametresi, 240 Hz panel. Güç optimizasyonunda incelenecek.
- Sıradaki test: yukarıdaki Eco'dan çıkış prosedürü.
