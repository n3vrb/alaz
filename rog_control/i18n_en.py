"""English catalogue: Turkish source text (the key used in the code) -> English UI copy.

Placeholders ({name}, {value}, ...) must match the Turkish source exactly.
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ---- mode names
    "Sessiz": "Silent",
    "Dengeli": "Balanced",
    "Turbo": "Turbo",
    "Özel": "Custom",
    "Eco": "Eco",
    "Standart": "Standard",
    "Ultimate": "Ultimate",
    "Optimize": "Optimize",
    "Firmware": "Firmware",

    # ---- common
    "Uygula": "Apply",
    "Varsayılan": "Default",
    "Otomatik": "Auto",
    "(otomatik)": "(auto)",
    "Kapat": "Close",
    "Küçült": "Minimize",
    "Ana pencereye dön": "Back to main window",
    "Tam pencereye dön": "Back to full window",
    "Uyarıyı kapat": "Dismiss warning",
    "Düzelt": "Fix",
    "İptal": "Cancel",
    "Vazgeç": "Cancel",
    "Devam": "Continue",
    "Sonra": "Later",
    "Tamam": "OK",
    "Yeniden başlat": "Restart",
    "Pilde": "On battery",
    "Prizde": "Plugged in",
    "Veri yok": "No data",

    # ---- power text
    "Sistem {w} W": "System {w} W",
    "Şarj +{w} W": "Charging +{w} W",
    "Güç: {value}": "Power: {value}",

    # ---- battery status
    "Şarj oluyor": "Charging",
    "Boşalıyor": "Discharging",
    "Dolu": "Full",
    "Şarj olmuyor": "Not charging",
    "Şarj durdu": "Not charging",
    "Pil {value}": "Battery {value}",
    "Pil {pct} %": "Battery {pct} %",

    # ---- sensor panel
    "FANLAR": "FANS",
    "{value} % yük": "{value} % load",
    "Uyku": "Asleep",
    "Kapalı": "Off",
    "dGPU kapalı": "dGPU off",
    "dGPU devre dışı": "dGPU disabled",
    "BEKLİYOR": "PENDING",

    # ---- main window
    "Performans": "Performance",
    "GPU modu": "GPU mode",
    "Ekran": "Display",
    "Şarj limiti": "Charge limit",
    "Yenileme hızı": "Refresh rate",
    "Diğer yenileme hızları": "Other refresh rates",
    "Panel Overdrive": "Panel Overdrive",
    "Daha hızlı piksel tepkisi": "Faster pixel response",
    "Dahili panel · {value}": "Built-in panel · {value}",
    "Otomatik: prizde {ac} · pilde {bat}": "Auto: {ac} plugged in · {bat} on battery",
    "Etkin: {name}": "Active: {name}",
    "Fanlar & Güç": "Fans & Power",
    "Klavye": "Keyboard",
    "Ayarlar": "Settings",
    "Mini moda geç": "Switch to mini mode",
    "Henüz desteklenmiyor": "Not supported yet",
    "Windows'tan kalan Eco ayarı": "Eco setting left over from Windows",
    "dGPU firmware'de kapalı kalmış (dgpu_disable=1); bir sonraki GPU modu seçimi bunu düzeltir":
        "The dGPU was left disabled in firmware (dgpu_disable=1); choosing a GPU mode next will fix it",
    "Düşük fan devri, sessiz çalışma ve uzun pil ömrü.": "Low fan speed, quiet operation and long battery life.",
    "Günlük kullanım: performans ile ses arasında denge.": "Everyday use: a balance of performance and noise.",
    "En yüksek güç limitleri ve agresif fan eğrisi.": "Highest power limits and an aggressive fan curve.",
    "Kendi güç limitlerin ve fan eğrin — Fanlar & Güç’ten düzenle.":
        "Your own power limits and fan curve — edit them under Fans & Power.",
    "dGPU tamamen kapalı. En uzun pil ömrü; harici ekran çıkışları çalışmaz.":
        "dGPU fully off. Longest battery life; no external display output.",
    "iGPU çizer, dGPU gerektiğinde uyanır.": "iGPU renders; dGPU wakes when needed.",
    "MUX: ekran doğrudan dGPU’ya bağlı. En yüksek oyun performansı.":
        "MUX: display wired straight to the dGPU. Best gaming performance.",
    "Şu an dGPU uykuda.": "dGPU is asleep now.",
    "Yeniden başlatma gerekli": "Restart required",
    "dGPU yeniden etkinleştirildi. Standart mod için bilgisayarı şimdi yeniden başlat.":
        "The dGPU has been re-enabled. Restart now to finish switching to Standard.",
    "{name} yeniden başlatınca etkin olacak": "{name} takes effect after restart",
    "Açık işlerini kaydet.": "Save your open work.",
    "Açık işlerini kaydet. Harici monitör bu modda çalışmaz.":
        "Save your open work. External monitors don't work in this mode.",
    "Açık işlerini kaydet. Geçiş açılışta uygulanır.": "Save your open work. The switch happens at boot.",

    # ---- dialogs
    "Eco modundan çık": "Leave Eco mode",
    "dGPU şimdi yeniden etkinleştirilecek ve bilgisayarı hemen ardından yeniden başlatman GEREKİYOR. "
    "Yeniden başlatana kadar yeni bir USB/Thunderbolt aygıtı takma. Açık işlerini kaydetmeye hazır mısın?":
        "The dGPU will be re-enabled now and you MUST restart right afterwards. Don't plug in any new "
        "USB/Thunderbolt devices until you restart. Ready to save your open work?",
    "GPU modu: {name}": "GPU mode: {name}",
    "{name} moduna geçiş yeniden başlatınca uygulanır; şu an hiçbir şey değişmez. "
    "İstediğin zaman yeniden başlatmadan önce iptal edebilirsin.":
        "Switching to {name} takes effect after a restart; nothing changes right now. "
        "You can cancel at any time before restarting.",
    "Bilgisayar şimdi yeniden başlatılacak. Açık işlerini kaydettiğinden emin ol.":
        "Your computer will restart now. Make sure you've saved your open work.",
    "dGPU yeniden etkinleştirildi. Standart modun çalışması için bilgisayarı şimdi yeniden "
    "başlatman gerekiyor. Açık işlerini kaydettiğinden emin ol.":
        "The dGPU has been re-enabled. You need to restart now for Standard mode to work. "
        "Make sure you've saved your open work.",

    # ---- fans window
    "ROG Control — Fanlar & Güç": "ROG Control — Fans & Power",
    "Düzenlenen profil": "Profile being edited",
    "Fan eğrisi": "Fan curve",
    "CPU güç limitleri": "CPU power limits",
    "Sürekli güç": "Sustained power",
    "Kısa süreli": "Short boost",
    "Anlık tepe": "Instant peak",
    "Özel modu etkinleştir": "Enable Custom mode",
    "Özel’e geç": "Switch to Custom",
    "Sıcaklık hedefi": "Temp. target",
    "Enerji tercihi (EPP)": "Energy preference (EPP)",
    "Denge +": "Balance +",
    "Denge −": "Balance −",
    "Tasarruf": "Power saver",
    "Prize takılınca": "When plugged in",
    "Nokta {i}/{n} seçili · sürükle veya ok tuşlarıyla ayarla": "Point {i}/{n} selected · drag or use the arrow keys",
    "Eğri okunuyor…": "Reading curve…",
    "Değerler bırakınca uygulanır.": "Values apply when you release the slider.",
    "Özel mod etkin değil: değerler kaydedilir, Özel seçilince uygulanır.":
        "Custom mode isn't active: values are saved and applied when you select Custom.",
    "{mode} modunda limitleri firmware yönetir. Kendi limitlerin için {custom} profili seç.":
        "In {mode} mode the firmware manages the limits. Select the {custom} profile to set your own.",
    "{mode} profili için": "For the {mode} profile",
    "Sıcaklık °C": "Temperature °C",
    "Fan %": "Fan %",
    "Şu an {t}°": "Now {t}°",

    # ---- keyboard window
    "ROG Control — Klavye": "ROG Control — Keyboard",
    "Parlaklık": "Brightness",
    "Renk": "Colour",
    "Renk (hex)": "Colour (hex)",
    "Düşük": "Low",
    "Orta": "Medium",
    "Yüksek": "High",

    # ---- settings window
    "ROG Control — Ayarlar": "ROG Control — Settings",
    "Oturum açılışında başlat": "Start at login",
    "Giriş yapınca tepside küçültülmüş açılır": "Starts minimised in the tray when you log in",
    "Kapatınca tepsiye küçült": "Minimise to tray on close",
    "Pencereyi kapatmak uygulamayı çalışır halde bırakır": "Closing the window keeps the app running",
    "Profil değişince bildirim göster": "Notify on profile change",
    "Fn tuşu gibi dış değişikliklerde": "For external changes such as the Fn key",
    "Tepside watt göster": "Show watts in the tray",
    "Tepsi simgesinde toplam güç (W) yazar": "Shows total power draw (W) on the tray icon",
    "Toplam güç: RAPL psys": "Total power: RAPL psys",
    "Toplam güç ölçümü için izin gerekli. Terminalde çalıştırın:":
        "Measuring total power needs permission. Run in a terminal:",
    "Otomatik başlatma ayarlanamadı: {err}": "Couldn't set up autostart: {err}",
    "Otomatik başlatma ayarlanamadı (systemctl --user başarısız).":
        "Couldn't set up autostart (systemctl --user failed).",

    # ---- tray
    "PERFORMANS": "PERFORMANCE",
    "GPU MODU": "GPU MODE",
    "Eco   (yeniden başlatma)": "Eco   (needs restart)",
    "Pencereyi aç": "Open window",
    "Mini mod": "Mini mode",
    "Klavye ışığı": "Keyboard light",
    "Klavye ışığı aç/kapat": "Toggle keyboard light",
    "Çıkış": "Quit",
    "Profil: {mode}": "Profile: {mode}",
    "ROG Control — Mini": "ROG Control — Mini",

    # ---- controller messages
    "İşlem başarısız oldu ({key}).": "Operation failed ({key}).",
    "asusd işlemi başarısız ({op}): {msg}": "asusd operation failed ({op}): {msg}",
    "Yenileme hızı değiştirilemedi: {msg}": "Couldn't change the refresh rate: {msg}",
    "Bilinmeyen mod: {mode}": "Unknown mode: {mode}",
    "Bu GPU modu henüz desteklenmiyor.": "This GPU mode isn't supported yet.",
    "Bekleyen değişiklik iptal edilemedi: etkin GPU modu bilinmiyor veya desteklenmiyor.":
        "Couldn't cancel the pending change: the active GPU mode is unknown or unsupported.",
    "Bekleyen GPU değişikliği iptal edildi.": "Pending GPU change cancelled.",
    "dGPU yeniden etkinleştirildi. Standart mod için bilgisayarı ŞİMDİ yeniden başlatman gerekiyor.":
        "The dGPU has been re-enabled. Restart NOW to finish switching to Standard.",
    "{name} yeniden başlatınca etkin olacak.": "{name} will take effect after restart.",
    "Yetkilendirme iptal edildi; hiçbir şey değiştirilmedi.": "Authentication cancelled; nothing was changed.",
    "GPU yardımcısı çalıştırılamadı: yetki verilmedi ya da kurulu değil (kurulum: sudo helper/install.sh).":
        "The GPU helper couldn't run: permission wasn't granted or it isn't installed "
        "(install with: sudo helper/install.sh).",
    "supergfxd durdurulamadı; Eco'dan çıkış başlatılmadı ve yapılandırma geri alındı. Hiçbir şey değişmedi.":
        "Couldn't stop supergfxd; leaving Eco wasn't started and the configuration was rolled back. "
        "Nothing was changed.",
    "Eco'dan çıkış tamamlanamadı: dGPU açılamadı. Yapılandırma Standart olarak kaldı; "
    "yeniden başlatırsan bilgisayar güvenle Eco'da açılır.":
        "Leaving Eco didn't complete: the dGPU couldn't be enabled. The configuration stayed on Standard; "
        "if you restart, the computer boots safely into Eco.",
    "Ultimate (dGPU doğrudan) MUX modunda Eco kullanılamaz. Önce Ultimate modundan çıkılmalı.":
        "Eco isn't available in Ultimate (direct dGPU) MUX mode. Leave Ultimate mode first.",
    "GPU modu değiştirilemedi: {msg}": "Couldn't change the GPU mode: {msg}",
    "Yeniden başlatılamadı: {err}": "Couldn't restart: {err}",
    "Geçersiz EPP değeri: {epp}": "Invalid EPP value: {epp}",
    "Geçersiz otomatik profil seçimi.": "Invalid auto-profile selection.",
    "Fan eğrileri okunamadı.": "Couldn't read the fan curves.",
    "Fan eğrisi tam olarak 8 nokta içermelidir.": "A fan curve must have exactly 8 points.",
    "Fan eğrisi noktaları geçersiz.": "The fan curve points are invalid.",
    "Fan eğrisinde sıcaklıklar artan sırada olmalıdır.": "Fan curve temperatures must be in ascending order.",
    "Fan eğrisi değerleri aralık dışında.": "Fan curve values are out of range.",
}
