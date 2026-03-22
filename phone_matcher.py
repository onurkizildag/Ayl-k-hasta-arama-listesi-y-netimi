"""
Telefon Eşleştirme
telefon_ekle.py + telefon_eslestirme.py mantığı tek modülde.
Katmanlı eşleştirme: tam → soyisim → fuzzy → manuel
"""

import re
import unicodedata
from typing import List, Dict, Tuple, Optional


# ─── Normalizasyon ───────────────────────────────────────────

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


def soyisim_al(isim: str) -> str:
    parcalar = normalize_isim(isim).split()
    return parcalar[-1] if parcalar else ""


# ─── Telefon Doğrulama ───────────────────────────────────────

SAHTE_NUMARALAR = {
    '1234567890', '9876543210', '0123456789',
    '5555555555', '0000000000', '1111111111',
}


def telefon_gecerli_mi(telefon: str) -> bool:
    if not telefon:
        return False
    t = str(telefon).strip()
    # Sadece rakam
    t = re.sub(r'\D', '', t)
    if len(t) == 11 and t[0] == '0':
        t = t[1:]
    if len(t) != 10:
        return False
    if len(set(t)) <= 2:
        return False
    if t in SAHTE_NUMARALAR:
        return False
    return True


def telefon_temizle(telefon_str: str) -> List[str]:
    """
    Virgülle ayrılmış telefon listesini temizler.
    Geçerli 10 haneli formatı döner.
    """
    if not telefon_str:
        return []
    telefon_str = str(telefon_str).strip()
    parcalar = re.split(r'[,;/\s]+', telefon_str)
    gecerliler = []
    for t in parcalar:
        t = re.sub(r'\D', '', t)
        if len(t) == 11 and t[0] == '0':
            t = t[1:]
        if telefon_gecerli_mi(t) and t not in gecerliler:
            gecerliler.append(t)
    return gecerliler


def telefon_birlestir(mevcut: str, yeni: str) -> str:
    """İki telefon listesini birleştir, tekrarları temizle"""
    mevcut_liste = telefon_temizle(mevcut or "")
    yeni_liste = telefon_temizle(yeni or "")
    birlesik = list(dict.fromkeys(mevcut_liste + yeni_liste))
    return ', '.join(birlesik)


# ─── Benzerlik Skoru ─────────────────────────────────────────

def benzerlik_skoru(isim1: str, isim2: str) -> int:
    """
    İki isim arasında 0-100 benzerlik skoru hesaplar.
    Katmanlı: tam eşleşme → soyisim → karakter oranı
    """
    if not isim1 or not isim2:
        return 0

    n1 = normalize_isim(isim1)
    n2 = normalize_isim(isim2)

    if n1 == n2:
        return 100

    # Soyisim tam eşleşmesi
    s1 = soyisim_al(n1)
    s2 = soyisim_al(n2)
    if s1 and s2 and s1 == s2:
        # Soyisim aynı, ismin ilk harfleri?
        if n1[0] == n2[0]:
            return 88
        return 75

    # Karakter oranı (Levenshtein benzeri basit)
    ortak = sum(1 for c in n1 if c in n2 and c != ' ')
    oran = ortak / max(len(n1.replace(' ', '')),
                        len(n2.replace(' ', '')), 1)
    return int(oran * 60)


# ─── Eşleştirme Motoru ───────────────────────────────────────

class TelefonEslestirici:
    """
    Kaynak Excel'deki telefonları hasta listesiyle eşleştirir.
    """

    def __init__(self, kaynak_df=None, kaynak_dosya: str = None,
                 isim_sutunu: str = "Adı", soyisim_sutunu: str = "Soyadı",
                 telefon_sutunu: str = "Telefon"):
        """
        kaynak_df:     pandas DataFrame (zaten yüklenmiş)
        kaynak_dosya:  Excel dosya yolu (biri verilmeli)
        """
        self.telefon_sozlugu: Dict[str, str] = {}  # normalize_isim → telefon
        self._ham_veri: List[Dict] = []

        if kaynak_df is not None:
            self._df_yukle(kaynak_df, isim_sutunu, soyisim_sutunu, telefon_sutunu)
        elif kaynak_dosya:
            self._dosya_yukle(kaynak_dosya, isim_sutunu, soyisim_sutunu, telefon_sutunu)

    def _df_yukle(self, df, isim_col, soyisim_col, tel_col):
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas gerekli")

        for _, row in df.iterrows():
            adi = str(row.get(isim_col, '') or '').strip()
            soyadi = str(row.get(soyisim_col, '') or '').strip()
            if not adi:
                continue
            isim = f"{adi} {soyadi}".strip()
            key = normalize_isim(isim)
            tel_ham = str(row.get(tel_col, '') or '')
            telefonlar = telefon_temizle(tel_ham)
            if telefonlar:
                if key in self.telefon_sozlugu:
                    mevcut = telefon_temizle(self.telefon_sozlugu[key])
                    birlesik = list(dict.fromkeys(mevcut + telefonlar))
                    self.telefon_sozlugu[key] = ', '.join(birlesik)
                else:
                    self.telefon_sozlugu[key] = ', '.join(telefonlar)
                self._ham_veri.append({
                    'isim': isim, 'key': key,
                    'telefon': self.telefon_sozlugu[key]
                })

    def _dosya_yukle(self, dosya_yolu, isim_col, soyisim_col, tel_col):
        try:
            import pandas as pd
            df = pd.read_excel(dosya_yolu, dtype=str)
            self._df_yukle(df, isim_col, soyisim_col, tel_col)
            print(f"✅ Kaynak yüklendi: {len(self.telefon_sozlugu)} kişi")
        except Exception as e:
            raise ValueError(f"Kaynak dosya okunamadı: {e}")

    def eslestir(self, hasta_listesi: List[Dict],
                  esik: int = 60
                  ) -> Tuple[List[Dict], List[Dict]]:
        """
        Hasta listesini telefon sözlüğüyle eşleştirir.

        Döner:
          eslesen:   [{'hasta': ..., 'telefon': ..., 'skor': ..., 'tip': ...}]
          eslesmeyenler: [{'hasta': ..., 'oneri': ..., 'oneri_telefon': ..., 'skor': ...}]
        """
        eslesen = []
        eslesmeyenler = []

        for hasta in hasta_listesi:
            isim = hasta.get('isim', '')
            key = normalize_isim(isim)

            # 1. Tam eşleşme
            if key in self.telefon_sozlugu:
                eslesen.append({
                    'hasta': hasta,
                    'telefon': self.telefon_sozlugu[key],
                    'skor': 100,
                    'tip': 'tam'
                })
                continue

            # 2. TC ile eşleşme (varsa)
            tc = hasta.get('tc', '')
            if tc:
                tc_esles = next(
                    (v for k, v in self._ham_veri_dict_by_tc().items()
                     if k == tc),
                    None
                )
                if tc_esles:
                    eslesen.append({
                        'hasta': hasta,
                        'telefon': tc_esles,
                        'skor': 99,
                        'tip': 'tc'
                    })
                    continue

            # 3. Fuzzy eşleşme
            en_iyi = None
            en_iyi_skor = 0
            for kaynak_key, telefon in self.telefon_sozlugu.items():
                skor = benzerlik_skoru(key, kaynak_key)
                if skor > en_iyi_skor:
                    en_iyi_skor = skor
                    en_iyi = (kaynak_key, telefon)

            if en_iyi and en_iyi_skor >= esik:
                eslesen.append({
                    'hasta': hasta,
                    'telefon': en_iyi[1],
                    'skor': en_iyi_skor,
                    'tip': 'fuzzy'
                })
            else:
                eslesmeyenler.append({
                    'hasta': hasta,
                    'oneri': en_iyi[0] if en_iyi else None,
                    'oneri_telefon': en_iyi[1] if en_iyi else None,
                    'skor': en_iyi_skor if en_iyi else 0
                })

        return eslesen, eslesmeyenler

    def _ham_veri_dict_by_tc(self) -> Dict[str, str]:
        """TC → telefon sözlüğü (yavaş, sadece fallback için)"""
        return {}  # TC kaynak Excel'de olmayabilir, placeholder


# ─── Tekli Eşleştirme Yardımcısı ─────────────────────────────

def telefon_ata(hasta_listesi: List[Dict],
                kaynak_telefon_sozlugu: Dict[str, str],
                esik: int = 60) -> Tuple[List[Dict], List[Dict]]:
    """
    Basit wrapper: normalize_isim → telefon sözlüğü ile eşleştir.
    DB'deki hastalar için kullanılır.
    """
    eslesen = []
    eslesmeyenler = []

    for hasta in hasta_listesi:
        key = normalize_isim(hasta.get('isim', ''))
        if key in kaynak_telefon_sozlugu:
            hasta['telefon'] = kaynak_telefon_sozlugu[key]
            eslesen.append({'hasta': hasta, 'skor': 100, 'tip': 'tam'})
        else:
            en_iyi = max(
                kaynak_telefon_sozlugu.keys(),
                key=lambda k: benzerlik_skoru(key, k),
                default=None
            )
            if en_iyi:
                skor = benzerlik_skoru(key, en_iyi)
                if skor >= esik:
                    hasta['telefon'] = kaynak_telefon_sozlugu[en_iyi]
                    eslesen.append({'hasta': hasta, 'skor': skor, 'tip': 'fuzzy'})
                else:
                    eslesmeyenler.append({
                        'hasta': hasta,
                        'oneri': en_iyi,
                        'oneri_telefon': kaynak_telefon_sozlugu[en_iyi],
                        'skor': skor
                    })
            else:
                eslesmeyenler.append({'hasta': hasta, 'oneri': None,
                                       'oneri_telefon': None, 'skor': 0})

    return eslesen, eslesmeyenler


# ─── Demo ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Telefon doğrulama testleri:")
    testler = [
        ("5321234567", True),
        ("05321234567", True),
        ("532123456", False),
        ("5555555555", False),
        ("abc", False),
    ]
    for t, beklenen in testler:
        sonuc = telefon_gecerli_mi(t)
        durum = "✅" if sonuc == beklenen else "❌"
        print(f"  {durum} {t!r} → {sonuc}")

    print("\nBenzerlik skoru testleri:")
    esler = [
        ("Ahmet Yılmaz", "AHMET YILMAZ", 100),
        ("Ahmet Yılmaz", "Ahmet Yilmaz", 100),
        ("Ayşe Kaya", "Ayse Kaya", 100),
        ("Mehmet Demir", "Mehmet Demır", 75),
        ("Ali Veli", "Hasan Hüseyin", 0),
    ]
    for i1, i2, beklenen in esler:
        skor = benzerlik_skoru(i1, i2)
        print(f"  {i1!r} ↔ {i2!r} → {skor} (beklenen≈{beklenen})")
