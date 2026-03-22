"""
CRM Veritabanı - Aylık Hasta Arama Listesi Yönetimi
"""

import sqlite3
import json
import unicodedata
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

DB_PATH = "saglik_crm.db"

AYLAR = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık"
}

SONUC_TIPLERI = ["randevu", "ret", "tekrar_ara", "mesaj", "diger"]


# ─── Yardımcı ────────────────────────────────────────────────

def normalize_isim(isim: str) -> str:
    """Türkçe karakter normalizasyonu — eşleştirme için"""
    if not isim:
        return ""
    text = unicodedata.normalize('NFD', str(isim))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    replacements = {
        'İ': 'I', 'I': 'I', 'Ğ': 'G', 'Ü': 'U',
        'Ş': 'S', 'Ç': 'C', 'Ö': 'O'
    }
    for tr, en in replacements.items():
        text = text.replace(tr, en)
    return ' '.join(text.split())


def gecmis_ozet(gorusmeler: List[Dict]) -> str:
    """
    Geçmiş görüşmeleri kısa özet stringe çevirir
    Örnek: "Şub: ulaşılamadı | Mar: randevu 5326655656"
    """
    if not gorusmeler:
        return ""
    ozet_parcalar = []
    for g in gorusmeler:
        ay_kisa = AYLAR.get(g['ay'], '?')[:3]
        if g['ulasildi']:
            parca = f"{ay_kisa}: {g['sonuc'] or 'görüşüldü'}"
        else:
            parca = f"{ay_kisa}: ulaşılamadı"
        if g['telefon_kullanilan']:
            parca += f" {g['telefon_kullanilan']}"
        ozet_parcalar.append(parca)
    return " | ".join(ozet_parcalar)


# ─── Bağlantı ────────────────────────────────────────────────

def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # Çok kullanıcı için
    return conn


# ─── Şema ────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH):
    conn = get_connection(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS tarama_turu (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ad        TEXT NOT NULL UNIQUE,
            aktif     INTEGER DEFAULT 1,
            sira      INTEGER DEFAULT 0,
            olusturma TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS hasta (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            isim            TEXT NOT NULL,
            isim_normalize  TEXT NOT NULL,
            tc              TEXT,
            yas             INTEGER,
            telefon         TEXT,
            kaynak          TEXT,
            olusturma       TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_hasta_normalize ON hasta(isim_normalize)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hasta_tc ON hasta(tc)")

    c.execute("""
        CREATE TABLE IF NOT EXISTS aylik_liste (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ay        INTEGER NOT NULL,
            yil       INTEGER NOT NULL,
            aciklama  TEXT,
            olusturma TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ay, yil)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS liste_hasta (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            liste_id       INTEGER NOT NULL,
            hasta_id       INTEGER NOT NULL,
            oncelik_puani  INTEGER DEFAULT 0,
            ekleme         TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (liste_id) REFERENCES aylik_liste(id),
            FOREIGN KEY (hasta_id) REFERENCES hasta(id),
            UNIQUE(liste_id, hasta_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS liste_hasta_tarama (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            liste_hasta_id  INTEGER NOT NULL,
            tarama_turu_id  INTEGER NOT NULL,
            deger           TEXT DEFAULT 'VAR',
            FOREIGN KEY (liste_hasta_id) REFERENCES liste_hasta(id),
            FOREIGN KEY (tarama_turu_id) REFERENCES tarama_turu(id),
            UNIQUE(liste_hasta_id, tarama_turu_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS gorusme (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            liste_id          INTEGER NOT NULL,
            hasta_id          INTEGER NOT NULL,
            tarih_saat        TEXT DEFAULT CURRENT_TIMESTAMP,
            ulasildi          INTEGER DEFAULT 0,
            sonuc             TEXT,
            arayan            TEXT,
            telefon_kullanilan TEXT,
            not_metni         TEXT,
            FOREIGN KEY (liste_id) REFERENCES aylik_liste(id),
            FOREIGN KEY (hasta_id) REFERENCES hasta(id)
        )
    """)

    # Varsayılan tarama türleri
    varsayilan = [
        ("diyabet tarama", 1),
        ("hipertansiyon tarama", 2),
        ("kvr tarama", 3),
        ("obezite tarama", 4),
        ("diyabet izlem", 5),
        ("hipertansiyon izlem", 6),
        ("kvr izlem", 7),
        ("obezite izlem", 8),
    ]
    for ad, sira in varsayilan:
        c.execute(
            "INSERT OR IGNORE INTO tarama_turu (ad, sira) VALUES (?, ?)",
            (ad, sira)
        )

    conn.commit()
    conn.close()
    print("✅ Veritabanı şeması hazır")


# ─── Tarama Türleri ──────────────────────────────────────────

def tarama_turleri_listele(db_path=DB_PATH) -> List[Dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM tarama_turu ORDER BY sira, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def tarama_turu_ekle(ad: str, db_path=DB_PATH) -> int:
    conn = get_connection(db_path)
    c = conn.cursor()
    maks = c.execute("SELECT COALESCE(MAX(sira),0) FROM tarama_turu").fetchone()[0]
    c.execute(
        "INSERT INTO tarama_turu (ad, sira) VALUES (?, ?)",
        (ad.strip().lower(), maks + 1)
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def tarama_turu_guncelle(tid: int, ad: str = None, aktif: int = None,
                          sira: int = None, db_path=DB_PATH):
    conn = get_connection(db_path)
    if ad is not None:
        conn.execute("UPDATE tarama_turu SET ad=? WHERE id=?", (ad, tid))
    if aktif is not None:
        conn.execute("UPDATE tarama_turu SET aktif=? WHERE id=?", (aktif, tid))
    if sira is not None:
        conn.execute("UPDATE tarama_turu SET sira=? WHERE id=?", (sira, tid))
    conn.commit()
    conn.close()


# ─── Aylık Liste ─────────────────────────────────────────────

def liste_olustur(ay: int, yil: int, aciklama: str = "", db_path=DB_PATH) -> int:
    conn = get_connection(db_path)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO aylik_liste (ay, yil, aciklama) VALUES (?, ?, ?)",
            (ay, yil, aciklama)
        )
        new_id = c.lastrowid
        conn.commit()
        return new_id
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT id FROM aylik_liste WHERE ay=? AND yil=?", (ay, yil)
        ).fetchone()
        return row['id']
    finally:
        conn.close()


def listeler(db_path=DB_PATH) -> List[Dict]:
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT l.*, COUNT(lh.id) as hasta_sayisi
        FROM aylik_liste l
        LEFT JOIN liste_hasta lh ON lh.liste_id = l.id
        GROUP BY l.id
        ORDER BY l.yil DESC, l.ay DESC
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['ay_ad'] = AYLAR.get(d['ay'], '')
        result.append(d)
    return result


def liste_getir(liste_id: int, db_path=DB_PATH) -> Optional[Dict]:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM aylik_liste WHERE id=?", (liste_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d['ay_ad'] = AYLAR.get(d['ay'], '')
    return d


# ─── Hasta ───────────────────────────────────────────────────

def hasta_bul_veya_ekle(isim: str, tc: str = None, yas: int = None,
                         telefon: str = None, kaynak: str = "manuel",
                         db_path=DB_PATH) -> int:
    """
    TC varsa TC ile, yoksa normalize isimle arar.
    Bulursa günceller, bulamazsa ekler. Hasta id döner.
    """
    conn = get_connection(db_path)
    c = conn.cursor()
    isim_norm = normalize_isim(isim)
    hasta_id = None

    # TC ile ara
    if tc:
        row = c.execute("SELECT id FROM hasta WHERE tc=?", (tc,)).fetchone()
        if row:
            hasta_id = row['id']

    # İsim ile ara
    if not hasta_id:
        row = c.execute(
            "SELECT id FROM hasta WHERE isim_normalize=?", (isim_norm,)
        ).fetchone()
        if row:
            hasta_id = row['id']

    if hasta_id:
        # Güncelle — boş alanları doldur
        if tc:
            c.execute("UPDATE hasta SET tc=? WHERE id=? AND (tc IS NULL OR tc='')",
                      (tc, hasta_id))
        if telefon:
            c.execute("UPDATE hasta SET telefon=? WHERE id=?", (telefon, hasta_id))
        if yas:
            c.execute("UPDATE hasta SET yas=? WHERE id=? AND (yas IS NULL OR yas=0)",
                      (yas, hasta_id))
    else:
        c.execute("""
            INSERT INTO hasta (isim, isim_normalize, tc, yas, telefon, kaynak)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (isim, isim_norm, tc, yas, telefon, kaynak))
        hasta_id = c.lastrowid

    conn.commit()
    conn.close()
    return hasta_id


def hasta_getir(hasta_id: int, db_path=DB_PATH) -> Optional[Dict]:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM hasta WHERE id=?", (hasta_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def hasta_guncelle(hasta_id: int, telefon: str = None, tc: str = None,
                   yas: int = None, db_path=DB_PATH):
    conn = get_connection(db_path)
    if telefon is not None:
        conn.execute("UPDATE hasta SET telefon=? WHERE id=?", (telefon, hasta_id))
    if tc is not None:
        conn.execute("UPDATE hasta SET tc=? WHERE id=?", (tc, hasta_id))
    if yas is not None:
        conn.execute("UPDATE hasta SET yas=? WHERE id=?", (yas, hasta_id))
    conn.commit()
    conn.close()


# ─── Liste Hasta Ekleme ───────────────────────────────────────

def listeye_hasta_ekle(liste_id: int, hasta_id: int,
                        tarama_turu_idler: List[int],
                        db_path=DB_PATH) -> int:
    """
    Hastayı listeye ekler, tarama türlerini işler,
    öncelik puanını (VAR sayısı) hesaplar.
    """
    conn = get_connection(db_path)
    c = conn.cursor()

    # liste_hasta kaydı
    try:
        c.execute("""
            INSERT INTO liste_hasta (liste_id, hasta_id, oncelik_puani)
            VALUES (?, ?, ?)
        """, (liste_id, hasta_id, len(tarama_turu_idler)))
        lh_id = c.lastrowid
    except sqlite3.IntegrityError:
        row = c.execute("""
            SELECT id FROM liste_hasta
            WHERE liste_id=? AND hasta_id=?
        """, (liste_id, hasta_id)).fetchone()
        lh_id = row['id']

    # Taramaları ekle / güncelle
    for tt_id in tarama_turu_idler:
        c.execute("""
            INSERT OR IGNORE INTO liste_hasta_tarama
            (liste_hasta_id, tarama_turu_id, deger)
            VALUES (?, ?, 'VAR')
        """, (lh_id, tt_id))

    # Öncelik puanını yeniden hesapla
    var_sayisi = c.execute("""
        SELECT COUNT(*) FROM liste_hasta_tarama
        WHERE liste_hasta_id=? AND deger='VAR'
    """, (lh_id,)).fetchone()[0]

    c.execute(
        "UPDATE liste_hasta SET oncelik_puani=? WHERE id=?",
        (var_sayisi, lh_id)
    )

    conn.commit()
    conn.close()
    return lh_id


# ─── Liste Görünümü ───────────────────────────────────────────

def liste_hastalari(liste_id: int, db_path=DB_PATH) -> List[Dict]:
    """
    Bir ayın hastalarını tarama VAR/boş sütunlarıyla,
    öncelik puanına göre sıralı döner.
    Her hastada geçmiş görüşme özeti de vardır.
    """
    conn = get_connection(db_path)

    # Aktif tarama türleri
    turler = conn.execute(
        "SELECT id, ad FROM tarama_turu WHERE aktif=1 ORDER BY sira, id"
    ).fetchall()

    # Hastalar
    rows = conn.execute("""
        SELECT
            h.id         as hasta_id,
            h.isim,
            h.tc,
            h.yas,
            h.telefon,
            lh.id        as liste_hasta_id,
            lh.oncelik_puani
        FROM liste_hasta lh
        JOIN hasta h ON h.id = lh.hasta_id
        WHERE lh.liste_id = ?
        ORDER BY lh.oncelik_puani DESC, h.isim
    """, (liste_id,)).fetchall()

    # Tarama VAR/boş
    result = []
    for row in rows:
        d = dict(row)
        lh_id = d['liste_hasta_id']

        # Bu hastaın bu listedeki taramaları
        taramalar = conn.execute("""
            SELECT tarama_turu_id, deger
            FROM liste_hasta_tarama
            WHERE liste_hasta_id=?
        """, (lh_id,)).fetchall()
        tarama_map = {t['tarama_turu_id']: t['deger'] for t in taramalar}

        d['taramalar'] = {
            tur['ad']: tarama_map.get(tur['id'], '')
            for tur in turler
        }

        # Bu aydaki görüşmeler
        gorusmeler_bu_ay = conn.execute("""
            SELECT * FROM gorusme
            WHERE liste_id=? AND hasta_id=?
            ORDER BY tarih_saat DESC
        """, (liste_id, d['hasta_id'])).fetchall()
        d['gorusmeler'] = [dict(g) for g in gorusmeler_bu_ay]
        d['arama_durumu'] = _arama_durumu(d['gorusmeler'])

        # Geçmiş özet (diğer aylar)
        gecmis = conn.execute("""
            SELECT
                g.ulasildi, g.sonuc, g.telefon_kullanilan,
                al.ay, al.yil
            FROM gorusme g
            JOIN aylik_liste al ON al.id = g.liste_id
            WHERE g.hasta_id=? AND g.liste_id != ?
            ORDER BY al.yil DESC, al.ay DESC, g.tarih_saat DESC
        """, (d['hasta_id'], liste_id)).fetchall()

        # Her ay için sadece son görüşme
        gecmis_aylar = {}
        for g in gecmis:
            key = (g['yil'], g['ay'])
            if key not in gecmis_aylar:
                gecmis_aylar[key] = dict(g)

        gecmis_liste = sorted(
            gecmis_aylar.values(),
            key=lambda x: (x['yil'], x['ay'])
        )
        d['gecmis_ozet'] = gecmis_ozet(gecmis_liste)

        result.append(d)

    conn.close()
    return result


def _arama_durumu(gorusmeler: List[Dict]) -> str:
    """Son görüşme durumunu döner"""
    if not gorusmeler:
        return "aranmadı"
    son = gorusmeler[0]
    if son['ulasildi']:
        return son['sonuc'] or "ulaşıldı"
    return "ulaşılamadı"


# ─── Görüşme Kaydı ───────────────────────────────────────────

def gorusme_ekle(liste_id: int, hasta_id: int, ulasildi: bool,
                  sonuc: str = None, arayan: str = None,
                  telefon_kullanilan: str = None,
                  not_metni: str = None,
                  db_path=DB_PATH) -> int:
    conn = get_connection(db_path)
    c = conn.cursor()
    c.execute("""
        INSERT INTO gorusme
        (liste_id, hasta_id, tarih_saat, ulasildi, sonuc,
         arayan, telefon_kullanilan, not_metni)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        liste_id, hasta_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        1 if ulasildi else 0,
        sonuc, arayan, telefon_kullanilan, not_metni
    ))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def hasta_gorusmeleri(hasta_id: int, db_path=DB_PATH) -> List[Dict]:
    """Bir hastanın tüm geçmiş görüşmeleri (tüm aylar)"""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT
            g.*,
            al.ay, al.yil
        FROM gorusme g
        JOIN aylik_liste al ON al.id = g.liste_id
        WHERE g.hasta_id = ?
        ORDER BY g.tarih_saat DESC
    """, (hasta_id,)).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['ay_ad'] = AYLAR.get(d['ay'], '')
        result.append(d)
    return result


def hasta_liste_gecmisi(hasta_id: int, db_path=DB_PATH) -> List[Dict]:
    """Bir hastanın hangi aylarda hangi taramalarla listeye girdiği"""
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT
            al.ay, al.yil, lh.oncelik_puani, lh.id as lh_id
        FROM liste_hasta lh
        JOIN aylik_liste al ON al.id = lh.liste_id
        WHERE lh.hasta_id = ?
        ORDER BY al.yil DESC, al.ay DESC
    """, (hasta_id,)).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d['ay_ad'] = AYLAR.get(d['ay'], '')

        # O aydaki taramalar
        taramalar = conn.execute("""
            SELECT tt.ad, lht.deger
            FROM liste_hasta_tarama lht
            JOIN tarama_turu tt ON tt.id = lht.tarama_turu_id
            WHERE lht.liste_hasta_id = ?
        """, (d['lh_id'],)).fetchall()
        d['taramalar'] = {t['ad']: t['deger'] for t in taramalar}
        result.append(d)

    conn.close()
    return result


# ─── İstatistik ──────────────────────────────────────────────

def liste_istatistik(liste_id: int, db_path=DB_PATH) -> Dict:
    conn = get_connection(db_path)

    toplam = conn.execute(
        "SELECT COUNT(*) FROM liste_hasta WHERE liste_id=?", (liste_id,)
    ).fetchone()[0]

    aranmis_hastalar = conn.execute("""
        SELECT COUNT(DISTINCT hasta_id)
        FROM gorusme WHERE liste_id=?
    """, (liste_id,)).fetchone()[0]

    ulasilmis = conn.execute("""
        SELECT COUNT(DISTINCT hasta_id)
        FROM gorusme WHERE liste_id=? AND ulasildi=1
    """, (liste_id,)).fetchone()[0]

    randevu = conn.execute("""
        SELECT COUNT(DISTINCT hasta_id)
        FROM gorusme WHERE liste_id=? AND sonuc='randevu'
    """, (liste_id,)).fetchone()[0]

    tarama_dagilimi = conn.execute("""
        SELECT tt.ad, COUNT(*) as sayi
        FROM liste_hasta_tarama lht
        JOIN tarama_turu tt ON tt.id = lht.tarama_turu_id
        JOIN liste_hasta lh ON lh.id = lht.liste_hasta_id
        WHERE lh.liste_id=? AND lht.deger='VAR'
        GROUP BY tt.ad
        ORDER BY sayi DESC
    """, (liste_id,)).fetchall()

    conn.close()
    return {
        'toplam': toplam,
        'aranmis': aranmis_hastalar,
        'ulasilmis': ulasilmis,
        'randevu': randevu,
        'aranmamis': toplam - aranmis_hastalar,
        'tarama_dagilimi': [dict(r) for r in tarama_dagilimi]
    }


# ─── Demo Verisi ─────────────────────────────────────────────

def demo_veri_ekle(db_path=DB_PATH):
    """Geliştirme/test için örnek veri"""
    # Ocak 2025 listesi
    liste_id = liste_olustur(1, 2025, "Ocak 2025 Tarama Listesi", db_path)

    turler = {t['ad']: t['id'] for t in tarama_turleri_listele(db_path)}

    ornekler = [
        ("Ahmet Yılmaz", "12345678901", 58, "5321234567",
         ["diyabet tarama", "hipertansiyon tarama", "kvr tarama"]),
        ("Ayşe Kaya", "23456789012", 45, "5332345678",
         ["hipertansiyon tarama", "obezite tarama"]),
        ("Mehmet Demir", "34567890123", 62, "5343456789",
         ["diyabet tarama", "kvr tarama"]),
        ("Fatma Şahin", "45678901234", 39, "5354567890",
         ["obezite tarama"]),
        ("Ali Özdemir", "56789012345", 28, "5365678901",
         ["diyabet izlem"]),
    ]

    for isim, tc, yas, tel, taramalar in ornekler:
        hid = hasta_bul_veya_ekle(isim, tc, yas, tel, "demo", db_path)
        tt_idler = [turler[t] for t in taramalar if t in turler]
        listeye_hasta_ekle(liste_id, hid, tt_idler, db_path)

    # Örnek görüşme kaydı
    gorusme_ekle(
        liste_id=liste_id,
        hasta_id=1,
        ulasildi=True,
        sonuc="randevu",
        arayan="Hemşire Zeynep",
        telefon_kullanilan="5321234567",
        not_metni="15 Ocak saat 10:00 randevu verildi.",
        db_path=db_path
    )

    print("✅ Demo verisi eklendi")


if __name__ == "__main__":
    init_db()
    demo_veri_ekle()
    print("\nListe hastaları:")
    for h in liste_hastalari(1):
        print(f"  {h['isim']} | Puan:{h['oncelik_puani']} | {h['taramalar']} | {h['arama_durumu']}")
    print("\nİstatistik:")
    print(liste_istatistik(1))
