"""
Veri İçe Aktarma
topla.py + ocr_excel.py + Excel import mantığı tek modülde
"""

import re
import os
import glob
import base64
import unicodedata
from typing import List, Dict, Optional, Tuple
from pathlib import Path


# ─── İsim / Metin Normalizasyon ──────────────────────────────

def normalize_isim(isim: str) -> str:
    if not isim:
        return ""
    text = unicodedata.normalize('NFD', str(isim))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    for tr, en in {'İ': 'I', 'I': 'I', 'Ğ': 'G', 'Ü': 'U',
                   'Ş': 'S', 'Ç': 'C', 'Ö': 'O'}.items():
        text = text.replace(tr, en)
    return ' '.join(text.split())


def normalize_kategori(kat: str) -> str:
    """'Diyabet Taraması' → 'diyabet tarama'"""
    kat = kat.lower()
    # Unicode combining temizle
    kat = unicodedata.normalize('NFD', kat)
    kat = ''.join(c for c in kat if not unicodedata.combining(c))
    # Türkçe karakter
    for tr, en in {'i̇': 'i', 'ı': 'i', 'ğ': 'g', 'ü': 'u',
                   'ş': 's', 'ç': 'c', 'ö': 'o'}.items():
        kat = kat.replace(tr, en)
    # Ek kaldır
    kat = re.sub(r'taramasi|taramalar', 'tarama', kat)
    kat = re.sub(r'izlemi|izlemler', 'izlem', kat)
    return ' '.join(kat.split())


def isim_normalize_basliklari(isim: str) -> str:
    """AHMET YILMAZ → Ahmet Yılmaz"""
    return ' '.join(w.capitalize() for w in isim.split())


# ─── Hasta Kaydı Veri Yapısı ─────────────────────────────────

class HastaKaydi:
    def __init__(self, isim: str, tc: str = None,
                 yas: int = None, telefon: str = None,
                 taramalar: List[str] = None, kaynak: str = "metin"):
        self.isim = isim_normalize_basliklari(isim.strip())
        self.tc = tc
        self.yas = yas
        self.telefon = telefon
        self.taramalar = taramalar or []  # normalize edilmiş tarama adları
        self.kaynak = kaynak

    def __repr__(self):
        return (f"HastaKaydi(isim={self.isim!r}, tc={self.tc!r}, "
                f"yas={self.yas}, taramalar={self.taramalar})")


# ─── Metin Dosyası Parse (topla.py mantığı) ──────────────────

def _kisi_satirlari_parse(lines: List[str], idx: int
                           ) -> Tuple[Optional[str], Optional[str],
                                      Optional[str], int]:
    """
    İsim + TC/Yaş satırı ikilisini parse eder.
    Döner: (isim, tc, yas, sonraki_idx)
    """
    if idx >= len(lines):
        return None, None, None, idx

    isim_satiri = lines[idx].strip()
    isim_pattern = re.compile(
        r'^[A-ZÇĞİÖŞÜa-zçğıöşü]{2,}'
        r'(?:\s+[A-ZÇĞİÖŞÜa-zçğıöşü]{2,})+$'
    )
    if not isim_pattern.match(isim_satiri):
        return None, None, None, idx

    if idx + 1 >= len(lines):
        return None, None, None, idx

    bilgi_satiri = lines[idx + 1].strip()

    tc_match = re.search(r'(\d{11}|\d{2}\*{7}\d{2})', bilgi_satiri)
    if not tc_match:
        return None, None, None, idx
    tc = tc_match.group(1)

    yas_match = re.search(r'Ya[sş][:\s]*(\d{1,3})', bilgi_satiri, re.IGNORECASE)
    if not yas_match:
        return None, None, None, idx
    yas = yas_match.group(1)

    return isim_satiri, tc, yas, idx + 2


def parse_metin(metin: str) -> List[HastaKaydi]:
    """
    topla.py formatındaki metni parse eder.
    Kategori başlıkları → tarama türleri
    İsim + TC/Yaş satırı ikilisi → hasta
    """
    lines = [l.strip() for l in metin.splitlines() if l.strip()]

    kayitlar: List[HastaKaydi] = []
    mevcut_kategori: Optional[str] = None
    idx = 0

    while idx < len(lines):
        line = lines[idx]

        # Kategori satırı: "tarama" veya "izlem" içeriyor, rakam yok
        if re.search(r'tarama|izlem', line, re.IGNORECASE) and not re.search(r'\d', line):
            mevcut_kategori = normalize_kategori(line)
            idx += 1
            continue

        isim, tc, yas, sonraki = _kisi_satirlari_parse(lines, idx)
        if isim:
            # Aynı isim zaten var mı? (başka kategoriden)
            mevcut = next(
                (k for k in kayitlar
                 if normalize_isim(k.isim) == normalize_isim(isim)),
                None
            )
            if mevcut:
                if mevcut_kategori and mevcut_kategori not in mevcut.taramalar:
                    mevcut.taramalar.append(mevcut_kategori)
            else:
                taramalar = [mevcut_kategori] if mevcut_kategori else []
                kayitlar.append(HastaKaydi(
                    isim=isim, tc=tc,
                    yas=int(yas) if yas else None,
                    taramalar=taramalar,
                    kaynak="metin"
                ))
            idx = sonraki
        else:
            idx += 1

    return kayitlar


# ─── Excel Parse ─────────────────────────────────────────────

def parse_excel(dosya_yolu: str) -> List[HastaKaydi]:
    """
    Excel dosyasından hasta listesi çıkarır.
    Desteklenen formatlar:
      A) İsim | TC | Yaş | Telefon | [tarama sütunları...]
      B) İsim sütunu + tarama türleri sütunlar halinde (topla.py çıktısı)
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas gerekli: pip install pandas openpyxl")

    try:
        df = pd.read_excel(dosya_yolu, dtype=str)
    except Exception as e:
        raise ValueError(f"Excel okunamadı: {e}")

    df.columns = [str(c).strip() for c in df.columns]
    kayitlar: List[HastaKaydi] = []

    # Sütun isimlerini normalize et
    col_map = {normalize_isim(c): c for c in df.columns}

    # İsim sütunu bul
    isim_col = None
    for aday in ['ISIM', 'ADI SOYADI', 'AD SOYAD', 'NAME', 'AD']:
        if aday in col_map:
            isim_col = col_map[aday]
            break
    if not isim_col:
        # İlk sütun
        isim_col = df.columns[0]

    # TC, Yaş, Telefon sütunları
    tc_col = col_map.get('TC') or col_map.get('TC NO') or col_map.get('KIMLIK')
    yas_col = col_map.get('YAS') or col_map.get('YASI')
    tel_col = col_map.get('TELEFON') or col_map.get('TEL') or col_map.get('CEPNUMARASI')

    # Tarama sütunları: İsim/TC/Yaş/Tel dışındaki sütunlar
    bilinen = {isim_col, tc_col, yas_col, tel_col} - {None}
    tarama_cols = [c for c in df.columns if c not in bilinen]

    for _, row in df.iterrows():
        isim = str(row.get(isim_col, '') or '').strip()
        if not isim or isim.lower() in ('nan', 'none', ''):
            continue

        tc = str(row.get(tc_col, '') or '').strip() if tc_col else None
        if tc in ('nan', 'none', ''):
            tc = None

        yas = None
        if yas_col:
            try:
                yas = int(float(str(row[yas_col])))
            except Exception:
                pass

        telefon = str(row.get(tel_col, '') or '').strip() if tel_col else None
        if telefon in ('nan', 'none', ''):
            telefon = None

        # Tarama VAR/boş
        taramalar = []
        for col in tarama_cols:
            val = str(row.get(col, '') or '').strip().upper()
            if val in ('VAR', '1', 'X', 'EVET'):
                taramalar.append(normalize_kategori(col))

        kayitlar.append(HastaKaydi(
            isim=isim, tc=tc, yas=yas,
            telefon=telefon, taramalar=taramalar,
            kaynak="excel"
        ))

    return kayitlar


# ─── OCR (Ekran Görüntüsü) ───────────────────────────────────

CATEGORY_KEYWORDS = {
    'diyabet': 'diyabet',
    'tansiyon': 'hipertansiyon',
    'hipertansiyon': 'hipertansiyon',
    'kvr': 'kvr',
    'kardiyo': 'kvr',
    'obezite': 'obezite',
}
SUBCAT_KEYWORDS = {
    'tarama': 'tarama',
    'izlem': 'izlem',
}


def _kategori_dosyadan(dosyaadi: str) -> Optional[str]:
    """Dosya adından kategori çıkarır"""
    ad = dosyaadi.lower()
    ana = None
    for anahtar, deger in CATEGORY_KEYWORDS.items():
        if anahtar in ad:
            ana = deger
            break
    if not ana:
        return None
    alt = 'tarama'
    for anahtar, deger in SUBCAT_KEYWORDS.items():
        if anahtar in ad:
            alt = deger
            break
    return f"{ana} {alt}"


def _ocr_satir_parse(satir: str
                      ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """OCR satırından isim, tc, yas, deger çıkar"""
    satir = satir.strip()
    if not satir:
        return None, None, None, None

    tc_m = re.search(r'\b(\d{11}|\d{2}\*{7}\d{2})\b', satir)
    tc = tc_m.group(1) if tc_m else None

    yas_m = re.search(r'(?:Yaş|Yas|Age)[:\s]*(\d{1,3})', satir, re.IGNORECASE)
    yas = yas_m.group(1) if yas_m else None

    isim_m = re.search(
        r'\b([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü]+'
        r'\s+[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü]+'
        r'(?:\s+[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü]+)?)\b',
        satir
    )
    isim = isim_m.group(1) if isim_m else None

    deger_m = re.search(
        r'\b(VAR|YOK)\b|\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b',
        satir, re.IGNORECASE
    )
    deger = deger_m.group(0) if deger_m else None

    return isim, tc, yas, deger


def _glm_ocr_cagir(goruntu_yolu: str,
                    ollama_url: str = "http://localhost:11434/api/generate",
                    model: str = "glm-ocr") -> Optional[str]:
    """Ollama GLM-OCR ile görüntüden metin çıkar"""
    try:
        import requests
        with open(goruntu_yolu, "rb") as f:
            goruntu_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "model": model,
            "prompt": ("Bu görüntüdeki tüm yazıları olduğu gibi düz metin olarak çıkar. "
                       "Yorum ekleme, sadece gördüğün metni yaz."),
            "images": [goruntu_b64],
            "stream": False
        }
        r = requests.post(ollama_url, json=payload, timeout=120)
        r.raise_for_status()
        return r.json().get("response", "")
    except Exception as e:
        print(f"  OCR hata ({goruntu_yolu}): {e}")
        return None


def parse_ocr_klasor(klasor: str,
                      ollama_url: str = "http://localhost:11434/api/generate",
                      model: str = "glm-ocr") -> List[HastaKaydi]:
    """
    Klasördeki tüm görüntü dosyalarını OCR ile işler.
    Dosya adından kategori belirler.
    """
    uzantilar = ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.PNG", "*.JPEG"]
    dosyalar = set()
    for uz in uzantilar:
        for f in glob.glob(os.path.join(klasor, uz)):
            dosyalar.add(f)

    kayitlar: List[HastaKaydi] = []

    for dosya in sorted(dosyalar):
        dosyaadi = os.path.basename(dosya)
        kategori = _kategori_dosyadan(dosyaadi)
        if not kategori:
            print(f"  Atlanıyor (kategori yok): {dosyaadi}")
            continue

        print(f"  İşleniyor [{kategori}]: {dosyaadi}")
        ocr_metin = _glm_ocr_cagir(dosya, ollama_url, model)
        if not ocr_metin:
            continue

        for satir in ocr_metin.splitlines():
            isim, tc, yas, _ = _ocr_satir_parse(satir)
            if not isim:
                continue

            # Normalize isim ile mevcut kayıt var mı?
            mevcut = next(
                (k for k in kayitlar
                 if normalize_isim(k.isim) == normalize_isim(isim)),
                None
            )
            if mevcut:
                if kategori not in mevcut.taramalar:
                    mevcut.taramalar.append(kategori)
            else:
                kayitlar.append(HastaKaydi(
                    isim=isim,
                    tc=tc,
                    yas=int(yas) if yas else None,
                    taramalar=[kategori],
                    kaynak="ocr"
                ))

    return kayitlar


# ─── Tarama Türü ID Eşleştirme ───────────────────────────────

def tarama_idler_eslestir(tarama_adlari: List[str],
                           sunucu_turleri: List[Dict]) -> List[int]:
    """
    Tarama adlarını sunucudan gelen ID'lerle eşleştirir.
    Tam eşleşme + bulanık eşleşme.
    """
    id_listesi = []
    tur_map = {normalize_isim(t['ad']): t['id'] for t in sunucu_turleri}

    for ad in tarama_adlari:
        anahtar = normalize_isim(ad)
        if anahtar in tur_map:
            id_listesi.append(tur_map[anahtar])
        else:
            # Kısmi eşleşme
            for tur_anahtar, tur_id in tur_map.items():
                if anahtar in tur_anahtar or tur_anahtar in anahtar:
                    id_listesi.append(tur_id)
                    break

    return list(set(id_listesi))


# ─── Demo / Test ─────────────────────────────────────────────

if __name__ == "__main__":
    ornek_metin = """
Diyabet Taraması

Ahmet Yılmaz
12345678901 Yaş: 58

Ayşe Kaya
23456789012 Yaş: 45

Hipertansiyon Taraması

Ayşe Kaya
23456789012 Yaş: 45

Mehmet Demir
34567890123 Yaş: 62
"""
    print("Metin parse test:")
    kayitlar = parse_metin(ornek_metin)
    for k in kayitlar:
        print(f"  {k}")

    print(f"\nToplam: {len(kayitlar)} hasta")
    print("Ayşe Kaya taramaları:",
          next(k.taramalar for k in kayitlar if 'Ayşe' in k.isim))
