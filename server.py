"""
Sağlık CRM Sunucusu
Flask REST API + UDP broadcast (ağda otomatik keşif)
"""

import json
import socket
import threading
import time
import os
from flask import Flask, request, jsonify
from db import (
    init_db, DB_PATH,
    tarama_turleri_listele, tarama_turu_ekle, tarama_turu_guncelle,
    liste_olustur, listeler, liste_getir, liste_hastalari, liste_istatistik,
    hasta_bul_veya_ekle, hasta_getir, hasta_guncelle,
    hasta_gorusmeleri, hasta_liste_gecmisi,
    listeye_hasta_ekle,
    gorusme_ekle,
    AYLAR, SONUC_TIPLERI
)

app = Flask(__name__)

HOST = "0.0.0.0"
HTTP_PORT = 5000
UDP_PORT  = 5001
UDP_INTERVAL = 100  # saniye


# ─── UDP Broadcast ────────────────────────────────────────────

def udp_broadcast():
    """
    Ağdaki istemcilere sunucunun varlığını duyurur.
    Her UDP_INTERVAL saniyede bir broadcast atar.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    mesaj = f"SAGLIK_SUNUCU:{HTTP_PORT}".encode()
    print(f"📡 UDP broadcast başladı (port {UDP_PORT}, her {UDP_INTERVAL}s)")
    while True:
        try:
            sock.sendto(mesaj, ('<broadcast>', UDP_PORT))
        except Exception as e:
            print(f"UDP hata: {e}")
        time.sleep(UDP_INTERVAL)


# ─── Yardımcı ────────────────────────────────────────────────

def ok(data=None, **kwargs):
    payload = {"durum": "ok"}
    if data is not None:
        payload["veri"] = data
    payload.update(kwargs)
    return jsonify(payload)


def hata(mesaj: str, kod: int = 400):
    return jsonify({"durum": "hata", "mesaj": mesaj}), kod


# ─── Sistem ──────────────────────────────────────────────────

@app.route("/ping")
def ping():
    return ok({"sunucu": "saglik_crm", "port": HTTP_PORT})


@app.route("/sabit-veriler")
def sabit_veriler():
    """İstemcinin başlangıçta çektiği sabit listeler"""
    return ok({
        "aylar": AYLAR,
        "sonuc_tipleri": SONUC_TIPLERI
    })


# ─── Tarama Türleri ──────────────────────────────────────────

@app.route("/tarama-turleri")
def tarama_turleri():
    return ok(tarama_turleri_listele())


@app.route("/tarama-turu", methods=["POST"])
def tarama_turu_ekle_ep():
    d = request.json or {}
    ad = (d.get("ad") or "").strip()
    if not ad:
        return hata("ad gerekli")
    new_id = tarama_turu_ekle(ad)
    return ok({"id": new_id, "ad": ad})


@app.route("/tarama-turu/<int:tid>", methods=["PUT"])
def tarama_turu_guncelle_ep(tid):
    d = request.json or {}
    tarama_turu_guncelle(
        tid,
        ad=d.get("ad"),
        aktif=d.get("aktif"),
        sira=d.get("sira")
    )
    return ok()


# ─── Aylık Listeler ───────────────────────────────────────────

@app.route("/listeler")
def listeler_ep():
    return ok(listeler())


@app.route("/liste", methods=["POST"])
def liste_olustur_ep():
    d = request.json or {}
    try:
        ay  = int(d["ay"])
        yil = int(d["yil"])
    except (KeyError, ValueError):
        return hata("ay ve yil gerekli")
    liste_id = liste_olustur(ay, yil, d.get("aciklama", ""))
    return ok({"liste_id": liste_id})


@app.route("/liste/<int:liste_id>")
def liste_bilgi_ep(liste_id):
    liste = liste_getir(liste_id)
    if not liste:
        return hata("liste bulunamadı", 404)
    return ok(liste)


@app.route("/liste/<int:liste_id>/hastalar")
def liste_hastalari_ep(liste_id):
    hastalar = liste_hastalari(liste_id)
    return ok(hastalar)


@app.route("/liste/<int:liste_id>/istatistik")
def istatistik_ep(liste_id):
    return ok(liste_istatistik(liste_id))


# ─── Toplu Hasta Ekleme (importer'dan gelir) ─────────────────

@app.route("/liste/<int:liste_id>/hasta/toplu", methods=["POST"])
def toplu_hasta_ekle_ep(liste_id):
    """
    Body: {
      "hastalar": [
        {
          "isim": "...",
          "tc": "...",        # opsiyonel
          "yas": 45,          # opsiyonel
          "telefon": "...",   # opsiyonel
          "kaynak": "metin",
          "tarama_turu_idler": [1, 3]
        }, ...
      ]
    }
    """
    d = request.json or {}
    hastalar = d.get("hastalar", [])
    if not hastalar:
        return hata("hastalar listesi boş")

    eklenen = 0
    guncellenen = 0
    hatalar = []

    for h in hastalar:
        try:
            isim = (h.get("isim") or "").strip()
            if not isim:
                continue
            hasta_id = hasta_bul_veya_ekle(
                isim=isim,
                tc=h.get("tc"),
                yas=h.get("yas"),
                telefon=h.get("telefon"),
                kaynak=h.get("kaynak", "metin")
            )
            tt_idler = h.get("tarama_turu_idler", [])
            listeye_hasta_ekle(liste_id, hasta_id, tt_idler)
            eklenen += 1
        except Exception as e:
            hatalar.append({"isim": h.get("isim"), "hata": str(e)})

    return ok({
        "eklenen": eklenen,
        "hatalar": hatalar
    })


# ─── Hasta ───────────────────────────────────────────────────

@app.route("/hasta/<int:hasta_id>")
def hasta_getir_ep(hasta_id):
    h = hasta_getir(hasta_id)
    if not h:
        return hata("hasta bulunamadı", 404)
    return ok(h)


@app.route("/hasta/<int:hasta_id>", methods=["PUT"])
def hasta_guncelle_ep(hasta_id):
    d = request.json or {}
    hasta_guncelle(
        hasta_id,
        telefon=d.get("telefon"),
        tc=d.get("tc"),
        yas=d.get("yas")
    )
    return ok()


@app.route("/hasta/<int:hasta_id>/gecmis")
def hasta_gecmis_ep(hasta_id):
    gorusmeler = hasta_gorusmeleri(hasta_id)
    listeler_gecmis = hasta_liste_gecmisi(hasta_id)
    return ok({
        "gorusmeler": gorusmeler,
        "listeler": listeler_gecmis
    })


# ─── Görüşme ─────────────────────────────────────────────────

@app.route("/gorusme", methods=["POST"])
def gorusme_ekle_ep():
    """
    Body: {
      "liste_id": 1,
      "hasta_id": 5,
      "ulasildi": true,
      "sonuc": "randevu",
      "arayan": "Hemşire Zeynep",
      "telefon_kullanilan": "5321234567",
      "not_metni": "15 Ocak 10:00 randevu"
    }
    """
    d = request.json or {}
    try:
        liste_id = int(d["liste_id"])
        hasta_id = int(d["hasta_id"])
        ulasildi = bool(d.get("ulasildi", False))
    except (KeyError, ValueError):
        return hata("liste_id ve hasta_id gerekli")

    gorusme_id = gorusme_ekle(
        liste_id=liste_id,
        hasta_id=hasta_id,
        ulasildi=ulasildi,
        sonuc=d.get("sonuc"),
        arayan=d.get("arayan"),
        telefon_kullanilan=d.get("telefon_kullanilan"),
        not_metni=d.get("not_metni")
    )
    return ok({"gorusme_id": gorusme_id})


@app.route("/gorusme/<int:liste_id>/<int:hasta_id>")
def gorusmeler_ep(liste_id, hasta_id):
    from db import get_connection
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM gorusme
        WHERE liste_id=? AND hasta_id=?
        ORDER BY tarih_saat DESC
    """, (liste_id, hasta_id)).fetchall()
    conn.close()
    return ok([dict(r) for r in rows])


# ─── Başlatıcı ───────────────────────────────────────────────

def sunucu_ip():
    """Yerel ağ IP adresini bul"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    # Veritabanı başlat
    init_db()

    # UDP broadcast thread
    t = threading.Thread(target=udp_broadcast, daemon=True)
    t.start()

    ip = sunucu_ip()
    print("\n" + "=" * 50)
    print("🏥 Sağlık CRM Sunucusu")
    print("=" * 50)
    print(f"🌐 Sunucu adresi : http://{ip}:{HTTP_PORT}")
    print(f"📡 UDP broadcast : port {UDP_PORT} (her {UDP_INTERVAL}s)")
    print(f"💾 Veritabanı    : {os.path.abspath(DB_PATH)}")
    print("=" * 50)
    print("İstemci bilgisayarda config.json'a şunu girin:")
    print(f'  "sunucu_ip": "{ip}"')
    print("=" * 50 + "\n")

    app.run(host=HOST, port=HTTP_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
