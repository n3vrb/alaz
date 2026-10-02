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

## Sonuçlar (2026-10-02 akşam) — son durum

### Kalıcı olarak uygulanan değişiklikler (çalışıyor)
- Sürücü 580.178 hizalı (RTX 5070 Laptop); `nvidia-driver-570-open` silindi, `nvidia-dkms-580` purge.
- `/etc/supergfxd.conf`: `hotplug_type: "Asus"`, `always_reboot: true` (yedek: `.bak`).
- `power-profiles-daemon` masked (asusd ile çakışıyordu).
- **`gpu-manager.service` masked** ve `/etc/gdm3/PrimeOff/Default` → `Default.disabled`.
  Sebep: açılışta gpu-manager NVIDIA sürücüsünü supergfxd'nin kontrolünden hemen sonra yükledi;
  supergfxd kartı kaldırırken `nv_pci_remove` sonsuz döngüye girdi (öldürülemeyen süreç,
  ikinci gpu-manager kilit bekledi) → zorla kapatma gerekti.
- `/etc/initramfs-tools/modules` içindeki geçersiz `framebuffer-nvidia` satırı yorumlandı (zararsız).

### Denenip GERİ ALINAN değişiklik
- `/etc/modprobe.d/rog-control-nvidia-noauto.conf` (nvidia otomatik yükleme kara listesi):
  Eco açılışındaki "fallen off the bus" uyarılarını giderdi AMA Hybrid'de sürücü 3.6 sn'de
  (supergfxd) yükleniyor, supergfxd `Type=dbus` olduğu için GDM beklemeden başlıyor → GDM Xorg
  "Failed to create pixmap" ile çöktü, 4 açılış siyah ekran. Dosya silindi + initramfs yenilendi;
  sürücü yine 0.7 sn'de yükleniyor, Hybrid açılış normal.
- Ders: açılış sırasını değiştiren her değişiklik GDM ile yarış yaratabilir; önce riski söyle,
  geri dönüş yolunu hazırla.

### GPU geçiş bulguları
- `supergfxctl -m` CANLI kullanılamaz, iki yönde de:
  - Eco'ya canlı giriş: gnome-shell + Xwayland öldürüldü (oturum çöktü).
  - Eco'dan canlı çıkış: Wayland gnome-shell yeni GPU'yu hotplug ederken kilitlendi.
- Eco'ya giriş — açılışta: config `"mode": "Integrated"` + reboot → ÇALIŞIYOR (dgpu_disable=1,
  kart PCI'dan kalkar). Kozmetik: açılışın ilk saniyesinde initramfs'teki nvidia modülü kapalı
  kartı yoklayıp "fallen off the bus" uyarısı basar; Eco yine çalışır. (Ayrı, güvenli bir çözüm
  sonra aranacak — açılış sırasını bozmadan.)
- Açılışta Eco'dan çıkış kendiliğinden olmaz: supergfxd `asus_boot_safety_check`, dgpu_disable=1
  görünce modu Integrated'a zorlar.
- Eco'dan çıkış prosedürü (stop supergfxd → config Hybrid → dgpu_disable=0 → reboot):
  kara liste varken canlı kısmı sorunsuzdu, ama sonraki açılış kara liste yüzünden siyah ekran
  verdi. Kara liste OLMADAN bu prosedür: dgpu_disable=0 yazınca sürücü otomatik yüklenir →
  gnome-shell hotplug kilitlenmesi riski. Çözüm adayı: yalnız o an için geçici bir modprobe
  kara listesi (initramfs'e GİRMEYEN) yaz → dgpu_disable=0 → geçici dosyayı sil → reboot.
  HENÜZ TEST EDİLMEDİ.

### Açık konular
- Eco'da boşta ~22–24 W tüketim yüksek (dGPU kapalıyken). Şüpheliler: `pcie_aspm=off` çekirdek
  parametresi, 240 Hz panel, parlaklık. Güç optimizasyonunda.
- `nvidia-powerd` kurulu değil (Dynamic Boost buna bağlı) — güç profillerinde bakılacak.
