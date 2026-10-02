Sen kıdemli bir masaüstü UI/UX tasarımcısısın ve aynı zamanda tasarımını Qt'ye aktarılabilir şekilde belgeleyen bir front-end geliştiricisin.

## Bağlam
ASUS ROG Zephyrus laptop için Linux'ta çalışan, G-Helper'ın yerini alacak "ROG Control" adlı bir kontrol uygulaması yazıyoruz. Uygulama **PyQt6 + özel QSS** ile yazılacak. Elimde bu uygulamanın ilk maketi var (ekte: `GHelper.dc.html` = ana pencere, `GHelperFans.dc.html` = "Fanlar & Güç" penceresi). Bu dosyalar özel bir canvas formatında (`{{...}}` şablon delikleri, `<sc-for>`, `<sc-if>`, `class Component extends DCLogic`) — onları sadece görsel/yerleşim referansı olarak oku, formatı kopyalama.

Yön zaten seçildi: **koyu, kompakt, tek sütunlu, G-Helper ruhunda ama özgün** bir tasarım. Senden bu tasarımı belirgin şekilde **daha iyi** hale getirmeni istiyorum — sıfırdan başka bir tarz değil, aynı yönün olgun ve cilalı versiyonu.

## Uygulamanın gerçek içeriği (bunları kullan, başka özellik/veri uydurma)
- Donanım: Intel Core Ultra 9 285H, NVIDIA GeForce RTX [MODEL] dGPU, Intel Arc iGPU, dahili panel 2560×1600 (60 Hz / 240 Hz), harici monitör de takılabiliyor (sadece dahili panel kontrol edilir).
- Canlı sensörler: CPU sıcaklık/kullanım, GPU sıcaklık/kullanım/güç (dGPU uykudayken "Uyku" göster, değer gösterme), 3 fan RPM (CPU / GPU / MID), RAM %, pil % ve durum (Şarj oluyor / Pilde / Dolu), şarj limiti.
- **Performans modu:** Sessiz / Dengeli / Turbo / Özel. "Özel" = kullanıcı tanımlı güç limitleri + fan eğrisi.
- **GPU modu:** Eco (dGPU kapalı) / Standart (Hybrid) / Ultimate (MUX, dGPU doğrudan) / Optimize (pilde Eco, prizde Standart). Eco ve Ultimate geçişi **yeniden başlatma gerektirir** → seçince onay + "Yeniden başlat / Sonra" akışı ve "bekleyen değişiklik" durumu olmalı.
- Dual-boot uyarısı: "Windows'tan kalan Eco ayarı algılandı" + "Düzelt" (kapatılabilir banner).
- **Ekran:** yenileme hızı 60 / 240 / Otomatik (pilde 60), Panel Overdrive anahtarı.
- **Pil:** şarj limiti (hızlı 60 / 80 / 100 + kaydırıcı 20–100), anlık durum.
- **Fanlar & Güç penceresi:** profil seçimi, CPU/GPU/MID fan sekmesi, 8 noktalı sürüklenebilir fan eğrisi (X: sıcaklık °C, Y: fan %), "Varsayılan" / "Uygula"; güç limitleri PL1 (SPL), PL2 (SPPT), FPPT (W); NVIDIA Dynamic Boost (5–25 W) ve sıcaklık hedefi (75–87 °C); EPP seçimi (performance / balance_performance / balance_power / power); otomatik geçiş (Prizde: [mod], Pilde: [mod]).
- Diğer: Klavye (parlaklık Kapalı/Düşük/Orta/Yüksek + statik renk), Ayarlar (oturum açılışında başlat, tray, bildirimler), Mini mod (her zaman üstte küçük pencere: sensörler + mod geçişi), sistem tepsisi menüsü.

## İyileştirmeni istediğim konular
1. **Görsel hiyerarşi ve okunabilirlik:** bir bakışta "şu an hangi moddayım, sıcaklık/fan ne durumda" anlaşılmalı. Bölüm başlıkları, canlı değerler ve seçimler arasında net ayrım.
2. **Durum dili:** seçili / üzerine gelinmiş / basılı / devre dışı / uygulanıyor (yükleniyor) / bekleyen (reboot gerekli) / hata durumlarının her biri için tutarlı görsel. Özellikle GPU geçişinin "bekleyen" hali.
3. **Renk sistemi:** mod renkleri (Sessiz yeşil, Dengeli mavi, Turbo kırmızı, Özel amber) korunsun ama doygunluk/parlaklıkları birbirine uyumlu olsun; dolu kutucuk üzerindeki metin ≥ 4.5:1 kontrast; renk körlüğünde de ayırt edilebilir olsun (ikon + etiket, sadece renk değil).
4. **Yoğunluk ve ritim:** 8 px ızgara, tutarlı boşluklar; pencere 480 px genişlikte ve 1080p ekranda kaydırmadan sığmalı (ana pencere ~ 480×900'ü geçmesin).
5. **Mikro etkileşimler:** mod değişiminde kısa geçiş, canlı değerlerin güncellenmesi, fan eğrisinde nokta sürükleme ipuçları. Sadece Qt ile yapılabilecek şeyler (QPropertyAnimation, renk/opaklık/geometri animasyonu) — blur, backdrop-filter, karmaşık CSS efektleri yok.
6. **Fan eğrisi grafiği:** daha okunur eksenler, mevcut sıcaklığı gösteren dikey çizgi, aktif noktanın değer etiketi, eğri altında hafif dolgu.
7. **Mini mod ve tray menüsü** için de birer tasarım ekle.

## Kısıtlar
- Her şey PyQt6 widget'larıyla yapılabilir olmalı: QPushButton, QLabel, QSlider, QFrame, QComboBox, özel çizim (QPainter) ile grafik ve anahtar. CSS'te QSS'nin desteklemediği şeyleri (grid gap hileleri, filter, box-shadow, pseudo-element) tasarımın temeline koyma.
- Yazı tipi: IBM Plex Sans (yoksa sistem sans-serif). Inter/Roboto/Arial kullanma. Sayılar tabular.
- İkonlar: tek renk, çizgi (stroke) stilinde SVG. Emoji yok.
- Arayüz metni Türkçe; teknik terimler (Eco, Turbo, PL1, EPP, RPM, Hz) olduğu gibi.
- Sahte veri uydurma; bilinmeyen değerleri [köşeli parantez] ile yer tutucu bırak.

## Teslim etmen gerekenler
1. **`rog-control-mockup.html`** — tek dosya, dış bağımlılık yok (Google Fonts linki hariç), tarayıcıda açılınca çalışan tıklanabilir maket. Ana pencere, Fanlar & Güç penceresi, Mini mod ve tray menüsü yan yana; "bekleyen GPU geçişi" ve "dual-boot uyarısı" durumları gösterilsin. Düz HTML + CSS + az miktarda vanilla JS.
2. **`DESIGN_SPEC.md`** — geliştiricinin PyQt6'da birebir uygulayacağı tasarım dokümanı:
   - Renk token'ları (isim → hex), mod renkleri ve her biri için metin rengi + kontrast oranı
   - Tipografi ölçeği (boyut / ağırlık / satır yüksekliği, kullanım yeri)
   - Boşluk ve köşe yarıçapı ölçekleri
   - Her bileşenin anatomisi, ölçüleri ve tüm durumları (mod kutucuğu, segmentli seçici, anahtar, kaydırıcı, bölüm başlığı, banner, bekleyen-değişiklik rozeti, fan grafiği, tray menüsü)
   - Animasyon süreleri ve easing
   - Pencere boyutları (ana, Fanlar & Güç, Mini)
3. **`theme.qss`** — yukarıdaki token'larla yazılmış, bileşenleri `objectName` / dinamik property (`[selected="true"]`, `[mode="turbo"]`, `[state="pending"]`) ile hedefleyen başlangıç QSS dosyası.

Önce kısa bir tasarım gerekçesi yaz (en fazla 10 madde: neyi neden değiştirdin), sonra üç dosyayı tam halleriyle ver.
