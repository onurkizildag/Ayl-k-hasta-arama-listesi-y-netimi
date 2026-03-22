# 🏥 Sağlık CRM Sistemi

Aylık hasta arama listesi yönetimi. Metin / Excel / OCR ile hasta aktarımı,
telefon eşleştirme, görüşme kaydı ve geçmiş takibi.

---

## 📁 Dosya Yapısı

```
health_ai_system/
│
├── server.py          ← Sunucuda çalışır (Flask API + UDP broadcast)
├── db.py              ← Veritabanı şeması ve sorguları
├── importer.py        ← Metin / Excel / OCR veri aktarımı
├── phone_matcher.py   ← Telefon eşleştirme motoru
├── client.py          ← İstemci GUI (Tkinter, exe yapılır)
├── config.json        ← İstemci yapılandırması (otomatik oluşur)
│
├── saglik_crm.db      ← SQLite veritabanı (sunucuda oluşur)
│
│── LLM / AI (şimdilik bekleme)
├── main.py
├── pipeline.py
├── llm_client.py
├── vector_engine.py
└── prompt_templates.py
```

---

## 🖥️ Sunucu Kurulumu (Kendi Bilgisayarın)

### 1. Python Bağımlılıkları

```bash
pip install flask requests pandas openpyxl
```

### 2. Sunucuyu Başlat

```bash
python server.py
```

Ekranda şunu görürsün:

```
🏥 Sağlık CRM Sunucusu
🌐 Sunucu adresi : http://192.168.1.105:5000
📡 UDP broadcast : port 5001 (her 100s)
💾 Veritabanı    : C:\...\saglik_crm.db
İstemci bilgisayarda config.json'a şunu girin:
  "sunucu_ip": "192.168.1.105"
```

Sunucu **her zaman açık** kalmalı. İstemciler bağlandığında bu adres üzerinden çalışır.

---

## 💻 İstemci Kurulumu (Diğer Bilgisayarlar)

### Seçenek A: Python ile çalıştır

```bash
pip install requests
python client.py
```

### Seçenek B: .exe olarak çalıştır (Python gerektirmez)

**Sunucu bilgisayarında exe'yi derle:**

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name SaglikCRM client.py
```

Derleme tamamlanınca `dist/SaglikCRM.exe` oluşur.

`SaglikCRM.exe`yi istemci bilgisayara kopyala. Yan yana `config.json` da koy (yoksa ilk açılışta oluşur).

### İlk Açılış

Uygulama açılınca **"Sunucuya Bağlan"** penceresi çıkar:

1. UDP broadcast ile sunucuyu otomatik arar (3 saniye)
2. Bulamazsa IP kutusunu doldur: `192.168.1.105` → **Bağlan**
3. Bağlantı kaydedilir, bir daha sormaz

---

## 🔧 Ağ Ayarı (Tek Seferlik)

**Sunucu bilgisayarında** Windows Güvenlik Duvarı'nda iki port açılmalı:

```
Port 5000 — TCP  (REST API)
Port 5001 — UDP  (Broadcast keşif)
```

**Windows Güvenlik Duvarı → Gelişmiş Ayarlar → Gelen Kurallar → Yeni Kural**
→ Port → TCP → 5000 → İzin Ver → Ad: "Saglik CRM API"

Aynısını UDP 5001 için tekrarla.

---

## 📋 Kullanım

### Aylık Liste Oluşturma

1. **Listeler** sekmesi → **➕ Yeni Liste**
2. Ay ve yıl seç → Oluştur

### Veri Aktarma

**Veri Aktar** sekmesinde 3 yöntem:

**A) Metin yapıştır** (topla.py formatı):
```
Diyabet Taraması

Ahmet Yılmaz
12345678901 Yaş: 58

Hipertansiyon Taraması

Ahmet Yılmaz
12345678901 Yaş: 58

Ayşe Kaya
23456789012 Yaş: 45
```
→ Metni yapıştır → **Metni Parse Et** → önizle → **Listeye Aktar**

**B) Excel yükle**: Topla.py çıktısı formatında Excel.
Sütunlar: `İsim | TC | Yaş | Telefon | [tarama sütunları — VAR/boş]`

**C) OCR klasörü**: Ekran görüntülerinin bulunduğu klasörü seç.
Dosya adından kategori otomatik belirlenir: `diyabet_tarama_01.png` → diyabet tarama

### Telefon Eşleştirme

Veri aktarmadan önce:
1. **Telefon Excel'i Yükle** → `4102014.xls` formatındaki kaynak dosya
2. Sütun adlarını gir (Adı / Soyadı / Telefon)
3. Otomatik eşleştirir — bulamazsa fuzzy öneri sunar

### Arama Paneli

- Listeden bir ayı seç → Arama Paneli açılır
- Hastalar **öncelik puanına göre sıralı** (kaç taramada VAR sayısı ↓)
- **Çift tıkla** → Görüşme kaydı ekle
- **Sağ tıkla** → Hasta geçmişi, telefon düzenle
- Sütunlar: İsim | Telefon | [Tarama VAR/boş] | Puan | Durum | Geçmiş Özet
- Geçmiş sütunu: `Şub: ulaşılamadı | Mar: randevu 5321234567`

### Görüşme Kaydı

Hasta üzerine çift tıklayınca:
- Ulaşıldı / Ulaşılamadı
- Sonuç: randevu / ret / tekrar_ara / mesaj / diger
- Aranan telefon
- Kim aradı
- Serbest not

### Hasta Geçmişi

- **Hasta Geçmişi** sekmesi → Hasta ID gir → Tüm aylardaki kayıtlar

### Tarama Türü Ekleme

- **Ayarlar** sekmesi → Tarama Türleri → **➕ Ekle**
- Örnek: `kolesterol tarama`, `böbrek izlem`

---

## ⚙️ config.json (İstemci)

```json
{
  "sunucu_ip": "192.168.1.105",
  "sunucu_port": 5000,
  "kullanici_adi": "Hemşire Zeynep",
  "udp_port": 5001
}
```

---

## 🗄️ Veritabanı Tabloları

| Tablo | Açıklama |
|---|---|
| `tarama_turu` | Diyabet tarama, KVR izlem vb. (kullanıcı ekleyebilir) |
| `hasta` | Tüm hastalar (TC, normalize isim, telefon) |
| `aylik_liste` | Her ay için liste |
| `liste_hasta` | Hangi hasta hangi listede, öncelik puanı |
| `liste_hasta_tarama` | O aydaki tarama VAR/boş |
| `gorusme` | Görüşme kayıtları (tüm ayrıntılar) |

---

## 🔄 Güncelleme ve Yedek

**Veritabanı yedeği:**
```bash
copy saglik_crm.db saglik_crm_yedek_2025_01.db
```

**Sunucu güncelleme:**
```bash
git pull
python server.py
```

**Yeni exe derle (client güncellenince):**
```bash
pyinstaller --onefile --windowed --name SaglikCRM client.py
```
Eski exe'yi sil, yenisini istemcilere dağıt.

---

## 🛠️ Sorun Giderme

| Sorun | Çözüm |
|---|---|
| "Sunucuya bağlanılamadı" | server.py çalışıyor mu? IP doğru mu? Port 5000 açık mı? |
| "Import hatası: pandas" | `pip install pandas openpyxl` |
| OCR çalışmıyor | Ollama + glm-ocr modeli kurulu mu? |
| Telefon eşleşmiyor | Sütun adlarını kontrol et, fuzzy eşleşmeyi gözden geçir |
| exe açılmıyor | Antivirüs engelliyor olabilir — PyInstaller çıktısı beyaz listeye ekle |
