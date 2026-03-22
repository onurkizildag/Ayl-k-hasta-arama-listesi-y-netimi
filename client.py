"""
Sağlık CRM İstemcisi
Tkinter GUI — UDP ağ keşfi + 5 sekme
DÜZELTMELER:
  - self.cfg kullanıldı (Tkinter'ın self.config() metoduyla çakışmıyordu)
  - Thread'den after() çağrısı thread-safe hale getirildi
  - Menü için tk.Tk.configure(self, menu=...) kullanıldı
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog, simpledialog
import json
import socket
import threading
import requests
import os
from typing import Optional, List, Dict, Any
from datetime import datetime

# ─── Config ──────────────────────────────────────────────────

CONFIG_DOSYASI = "config.json"
VARSAYILAN_CONFIG = {
    "sunucu_ip": "",
    "sunucu_port": 5000,
    "kullanici_adi": "",
    "udp_port": 5001,
}


def config_yukle() -> Dict:
    if os.path.exists(CONFIG_DOSYASI):
        try:
            with open(CONFIG_DOSYASI, encoding='utf-8') as f:
                cfg = json.load(f)
            for k, v in VARSAYILAN_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return VARSAYILAN_CONFIG.copy()


def config_kaydet(cfg: Dict):
    with open(CONFIG_DOSYASI, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ─── Sunucu İletişimi ─────────────────────────────────────────

class API:
    def __init__(self, ip: str, port: int = 5000):
        self.base = f"http://{ip}:{port}"
        self.timeout = 10

    def get(self, yol: str) -> Any:
        r = requests.get(f"{self.base}{yol}", timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("veri")

    def post(self, yol: str, veri: Dict) -> Any:
        r = requests.post(f"{self.base}{yol}", json=veri, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("veri")

    def put(self, yol: str, veri: Dict) -> Any:
        r = requests.put(f"{self.base}{yol}", json=veri, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("veri")

    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base}/ping", timeout=3)
            return r.status_code == 200
        except Exception:
            return False


# ─── UDP Keşif ───────────────────────────────────────────────

def udp_sunucu_bul(udp_port: int = 5001, zaman_asimi: float = 3.0) -> Optional[str]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', udp_port))
        sock.settimeout(zaman_asimi)
        veri, adres = sock.recvfrom(256)
        mesaj = veri.decode()
        if mesaj.startswith("SAGLIK_SUNUCU:"):
            port = mesaj.split(":")[1]
            return f"{adres[0]}:{port}"
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return None


# ─── İlk Bağlantı Penceresi ──────────────────────────────────

class BaglantiPenceresi(tk.Toplevel):
    """
    Bağlantı penceresi — thread KULLANMAZ.
    Ping ve UDP senkron çalışır, update() ile UI donmaz.
    Mainloop başlamadan önce güvenle çalışır.
    """
    def __init__(self, parent, cfg: Dict):
        super().__init__(parent)
        self.title("🏥 Sunucuya Bağlan")
        self.geometry("420x280")
        self.resizable(False, False)
        self.grab_set()
        self.cfg = cfg
        self.sonuc: Optional[str] = None

        tk.Label(self, text="🏥 Sağlık CRM",
                 font=("Arial", 16, "bold")).pack(pady=(20, 5))
        tk.Label(self, text="Sunucuya bağlanılıyor...",
                 font=("Arial", 10)).pack()

        self.durum_lbl = tk.Label(self, text="", fg="gray", font=("Arial", 9))
        self.durum_lbl.pack(pady=5)

        frame = tk.LabelFrame(self, text="Manuel Bağlantı", padx=10, pady=10)
        frame.pack(fill='x', padx=20, pady=10)

        tk.Label(frame, text="Sunucu IP:").grid(row=0, column=0, sticky='w')
        self.ip_entry = tk.Entry(frame, width=20)
        self.ip_entry.insert(0, cfg.get("sunucu_ip", ""))
        self.ip_entry.grid(row=0, column=1, padx=5)

        tk.Label(frame, text="Port:").grid(row=0, column=2, sticky='w')
        self.port_entry = tk.Entry(frame, width=7)
        self.port_entry.insert(0, str(cfg.get("sunucu_port", 5000)))
        self.port_entry.grid(row=0, column=3, padx=5)

        tk.Button(self, text="🔌 Bağlan", command=self._manuel_baglan,
                  bg="#4CAF50", fg="white",
                  font=("Arial", 10, "bold"), width=15).pack(pady=5)

        # Otomatik deneme — after() yerine update() + doğrudan çağrı
        # (mainloop henüz başlamadı, after() güvenli değil)
        if cfg.get("sunucu_ip"):
            self._kayitli_baglan()
        else:
            self._udp_ara()

    def _set_durum(self, metin: str, renk: str = "gray"):
        try:
            self.durum_lbl.config(text=metin, fg=renk)
            self.update()           # UI'yi hemen yenile (thread yok)
        except Exception:
            pass

    def _udp_ara(self):
        """UDP broadcast ile sunucu ara — senkron, UI donmaz (update())"""
        self._set_durum("UDP broadcast ile sunucu aranıyor (3 sn)...")
        udp_port = self.cfg.get("udp_port", 5001)
        adres = udp_sunucu_bul(udp_port, 3.0)   # max 3 sn bekler
        if adres:
            ip, port = adres.split(":")
            self.cfg["sunucu_ip"]   = ip
            self.cfg["sunucu_port"] = int(port)
            self.ip_entry.delete(0, 'end')
            self.ip_entry.insert(0, ip)
            self._kayitli_baglan()
        else:
            self._set_durum("Sunucu bulunamadı. IP'yi manuel girin.", "orange")

    def _kayitli_baglan(self):
        """Kayıtlı IP'ye ping at — senkron"""
        ip   = self.cfg.get("sunucu_ip", "")
        port = self.cfg.get("sunucu_port", 5000)
        if not ip:
            return
        self._set_durum(f"{ip}:{port} deneniyor...")
        ok = API(ip, port).ping()       # max 3 sn (API.ping timeout=3)
        if ok:
            self._set_durum(f"✅ Bağlandı: {ip}:{port}", "green")
            self.sonuc = f"{ip}:{port}"
            config_kaydet(self.cfg)
            self.update()
            self.after(600, self.destroy)
        else:
            self._set_durum(f"❌ {ip}:{port} yanıt vermedi", "red")

    def _manuel_baglan(self):
        ip = self.ip_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            messagebox.showerror("Hata", "Port sayı olmalı")
            return
        if not ip:
            messagebox.showerror("Hata", "IP adresi girin")
            return
        self.cfg["sunucu_ip"]   = ip
        self.cfg["sunucu_port"] = port
        self._kayitli_baglan()


# ─── Ana Uygulama ─────────────────────────────────────────────

class SaglikCRM(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🏥 Sağlık CRM")
        self.geometry("1280x800")
        self.minsize(1000, 600)

        # self.cfg — Tkinter'ın self.config() metoduyla ÇAKIŞMAZ
        self.cfg: Dict = config_yukle()
        self.api: Optional[API] = None
        self.aktif_liste: Optional[Dict] = None
        self.tarama_turleri: List[Dict] = []
        self.sabit_veriler: Dict = {}

        self._baglan()

    def _baglan(self):
        pencere = BaglantiPenceresi(self, self.cfg)
        self.wait_window(pencere)

        if not pencere.sonuc:
            messagebox.showerror(
                "Bağlantı Hatası",
                "Sunucuya bağlanılamadı.\n"
                "Sunucunun çalıştığından ve IP'nin doğru olduğundan emin olun."
            )
            self.destroy()
            return

        self.api = API(self.cfg["sunucu_ip"], self.cfg["sunucu_port"])
        self._veri_yukle()
        self._arayuz_kur()

    def _veri_yukle(self):
        try:
            self.tarama_turleri = self.api.get("/tarama-turleri") or []
            self.sabit_veriler  = self.api.get("/sabit-veriler") or {}
        except Exception as e:
            messagebox.showwarning("Uyarı", f"Veri yüklenemedi: {e}")

    def _arayuz_kur(self):
        # Menü — tk.Tk.configure() kullan, self.configure() değil
        menubar = tk.Menu(self)
        tk.Tk.configure(self, menu=menubar)

        baglanti_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="🔌 Bağlantı", menu=baglanti_menu)
        baglanti_menu.add_command(label="Yeniden Bağlan",
                                   command=self._yeniden_baglan)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)

        self.sekme_listeler = ListelerSekmesi(self.notebook, self)
        self.sekme_import   = ImportSekmesi(self.notebook, self)
        self.sekme_arama    = AramaPaneliSekmesi(self.notebook, self)
        self.sekme_gecmis   = HastaGecmisSekmesi(self.notebook, self)
        self.sekme_ayarlar  = AyarlarSekmesi(self.notebook, self)

        self.notebook.add(self.sekme_listeler, text="📋 Listeler")
        self.notebook.add(self.sekme_import,   text="📥 Veri Aktar")
        self.notebook.add(self.sekme_arama,    text="📞 Arama Paneli")
        self.notebook.add(self.sekme_gecmis,   text="👤 Hasta Geçmişi")
        self.notebook.add(self.sekme_ayarlar,  text="⚙️ Ayarlar")

        self.notebook.bind("<<NotebookTabChanged>>", self._sekme_degisti)

        self.durum_cubugu = tk.Label(
            self,
            text=f"✅ Bağlı: {self.cfg['sunucu_ip']}:{self.cfg['sunucu_port']}",
            bd=1, relief='sunken', anchor='w', font=("Arial", 8)
        )
        self.durum_cubugu.pack(side='bottom', fill='x')

        self.sekme_listeler.yenile()

    def _sekme_degisti(self, event=None):
        try:
            secili = self.notebook.index(self.notebook.select())
        except Exception:
            return
        if secili == 2 and self.aktif_liste:
            self.sekme_arama.liste_yukle(self.aktif_liste)
        elif secili == 0:
            self.sekme_listeler.yenile()

    def _yeniden_baglan(self):
        self._baglan()

    def liste_sec(self, lst: Dict):
        self.aktif_liste = lst
        self.notebook.tab(2, text=f"📞 {lst['ay_ad']} {lst['yil']}")
        self.notebook.select(2)
        self.sekme_arama.liste_yukle(lst)

    def set_durum(self, metin: str):
        try:
            self.durum_cubugu.config(text=metin)
            self.update_idletasks()
        except Exception:
            pass


# ─── Sekme 1: Listeler ────────────────────────────────────────

class ListelerSekmesi(ttk.Frame):
    def __init__(self, parent, app: SaglikCRM):
        super().__init__(parent)
        self.app = app
        self._data: List[Dict] = []
        self._kur()

    def _kur(self):
        ust = tk.Frame(self)
        ust.pack(fill='x', padx=10, pady=10)
        tk.Label(ust, text="Aylık Listeler",
                 font=("Arial", 13, "bold")).pack(side='left')
        tk.Button(ust, text="➕ Yeni Liste", command=self._yeni_liste,
                  bg="#4CAF50", fg="white").pack(side='right')
        tk.Button(ust, text="🔄 Yenile",
                  command=self.yenile).pack(side='right', padx=5)

        cols = ('ay_yil', 'hasta_sayisi', 'aciklama')
        self.tree = ttk.Treeview(self, columns=cols, show='headings', height=20)
        self.tree.heading('ay_yil',       text='Ay / Yıl')
        self.tree.heading('hasta_sayisi', text='Hasta Sayısı')
        self.tree.heading('aciklama',     text='Açıklama')
        self.tree.column('ay_yil',       width=200)
        self.tree.column('hasta_sayisi', width=120, anchor='center')
        self.tree.column('aciklama',     width=500)

        sb = ttk.Scrollbar(self, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True,
                       padx=(10, 0), pady=5)
        sb.pack(side='right', fill='y', pady=5)
        self.tree.bind('<Double-1>', self._sec)
        tk.Label(self, text="Çift tıklayarak listeyi açın",
                 fg="gray", font=("Arial", 8)).pack(pady=2)

    def yenile(self):
        try:
            self._data = self.app.api.get("/listeler") or []
        except Exception as e:
            messagebox.showerror("Hata", str(e))
            return
        self.tree.delete(*self.tree.get_children())
        for lst in self._data:
            self.tree.insert('', 'end', iid=str(lst['id']), values=(
                f"{lst['ay_ad']} {lst['yil']}",
                lst['hasta_sayisi'],
                lst.get('aciklama', '')
            ))

    def _sec(self, event=None):
        item = self.tree.selection()
        if not item:
            return
        lst = next((l for l in self._data if l['id'] == int(item[0])), None)
        if lst:
            self.app.liste_sec(lst)

    def _yeni_liste(self):
        d = YeniListeDialog(self, self.app)
        self.wait_window(d)
        if d.olusturuldu:
            self.yenile()


class YeniListeDialog(tk.Toplevel):
    def __init__(self, parent, app: SaglikCRM):
        super().__init__(parent)
        self.app = app
        self.olusturuldu = False
        self.title("Yeni Aylık Liste")
        self.geometry("350x200")
        self.grab_set()
        self.resizable(False, False)

        aylar = app.sabit_veriler.get('aylar', {})
        simdi = datetime.now()

        tk.Label(self, text="Ay:").grid(row=0, column=0, padx=15, pady=10, sticky='w')
        self.ay_combo = ttk.Combobox(
            self, state='readonly', width=18,
            values=[f"{k} - {v}"
                    for k, v in sorted(aylar.items(), key=lambda x: int(x[0]))]
        )
        idx = simdi.month - 1
        if 0 <= idx < len(self.ay_combo['values']):
            self.ay_combo.current(idx)
        self.ay_combo.grid(row=0, column=1, padx=5, pady=10)

        tk.Label(self, text="Yıl:").grid(row=1, column=0, padx=15, sticky='w')
        self.yil_entry = tk.Entry(self, width=8)
        self.yil_entry.insert(0, str(simdi.year))
        self.yil_entry.grid(row=1, column=1, sticky='w', padx=5)

        tk.Label(self, text="Açıklama:").grid(row=2, column=0, padx=15, sticky='w')
        self.aciklama_entry = tk.Entry(self, width=25)
        self.aciklama_entry.grid(row=2, column=1, padx=5)

        tk.Button(self, text="✅ Oluştur", command=self._olustur,
                  bg="#4CAF50", fg="white").grid(
            row=3, column=0, columnspan=2, pady=15)

    def _olustur(self):
        try:
            ay  = int(self.ay_combo.get().split(" - ")[0])
            yil = int(self.yil_entry.get().strip())
        except ValueError:
            messagebox.showerror("Hata", "Ay ve yıl geçerli sayı olmalı")
            return
        try:
            self.app.api.post("/liste", {
                "ay": ay, "yil": yil,
                "aciklama": self.aciklama_entry.get().strip()
            })
            self.olusturuldu = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("Hata", str(e))


# ─── Sekme 2: Veri Aktar ─────────────────────────────────────

class ImportSekmesi(ttk.Frame):
    def __init__(self, parent, app: SaglikCRM):
        super().__init__(parent)
        self.app = app
        self.import_kayitlar = []
        self.telefon_sozlugu: Dict[str, str] = {}
        self._listeler_data: List[Dict] = []
        self._kur()

    def _kur(self):
        ust = tk.Frame(self)
        ust.pack(fill='x', padx=10, pady=5)
        tk.Label(ust, text="Aktarılacak Liste:",
                 font=("Arial", 10, "bold")).pack(side='left')
        self.liste_combo = ttk.Combobox(ust, state='readonly', width=30)
        self.liste_combo.pack(side='left', padx=10)
        tk.Button(ust, text="🔄", command=self._listeler_yukle,
                  width=3).pack(side='left')

        kaynak = tk.LabelFrame(self, text="1. Veri Kaynağı", padx=10, pady=5)
        kaynak.pack(fill='x', padx=10, pady=5)
        btn_f = tk.Frame(kaynak)
        btn_f.pack(fill='x')
        tk.Button(btn_f, text="📂 Excel Yükle",
                  command=self._excel_yukle).pack(side='left', padx=3)
        tk.Button(btn_f, text="📷 OCR Klasörü",
                  command=self._ocr_yukle).pack(side='left', padx=3)
        tk.Button(btn_f, text="✅ Metni Parse Et",
                  command=self._metin_parse,
                  bg="#2196F3", fg="white").pack(side='right', padx=3)
        tk.Label(kaynak, text="Metni buraya yapıştırın:").pack(anchor='w')
        self.metin_alan = scrolledtext.ScrolledText(
            kaynak, height=8, font=("Consolas", 9))
        self.metin_alan.pack(fill='x')

        tel_f = tk.LabelFrame(self, text="2. Telefon Eşleştirme (opsiyonel)",
                               padx=10, pady=5)
        tel_f.pack(fill='x', padx=10, pady=5)
        tb = tk.Frame(tel_f)
        tb.pack(fill='x')
        tk.Button(tb, text="📂 Telefon Excel'i Yükle",
                  command=self._telefon_yukle).pack(side='left', padx=3)
        self.tel_durum = tk.Label(tb, text="", fg="gray")
        self.tel_durum.pack(side='left', padx=10)

        oniz = tk.LabelFrame(self, text="3. Önizleme", padx=5, pady=5)
        oniz.pack(fill='both', expand=True, padx=10, pady=5)
        cols = ('isim', 'tc', 'yas', 'telefon', 'taramalar', 'puan')
        self.oniz_tree = ttk.Treeview(oniz, columns=cols, show='headings', height=8)
        for col, baslik, gen in [
            ('isim',      'İsim',      200),
            ('tc',        'TC',        120),
            ('yas',       'Yaş',        50),
            ('telefon',   'Telefon',   150),
            ('taramalar', 'Taramalar', 300),
            ('puan',      'Puan',       50),
        ]:
            self.oniz_tree.heading(col, text=baslik)
            self.oniz_tree.column(col, width=gen,
                                   anchor='center' if gen <= 60 else 'w')
        sb = ttk.Scrollbar(oniz, command=self.oniz_tree.yview)
        self.oniz_tree.configure(yscrollcommand=sb.set)
        self.oniz_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        alt = tk.Frame(self)
        alt.pack(fill='x', padx=10, pady=5)
        self.import_durum = tk.Label(alt, text="", fg="gray")
        self.import_durum.pack(side='left')
        tk.Button(alt, text="📤 Listeye Aktar", command=self._listeyeaktar,
                  bg="#4CAF50", fg="white",
                  font=("Arial", 10, "bold")).pack(side='right')

        self._listeler_yukle()

    def _listeler_yukle(self):
        try:
            self._listeler_data = self.app.api.get("/listeler") or []
            self.liste_combo['values'] = [
                f"{l['ay_ad']} {l['yil']} (ID:{l['id']})"
                for l in self._listeler_data
            ]
            if self.liste_combo['values']:
                self.liste_combo.current(0)
        except Exception:
            pass

    def _metin_parse(self):
        from importer import parse_metin
        metin = self.metin_alan.get(1.0, 'end')
        if not metin.strip():
            messagebox.showwarning("Uyarı", "Metin boş!")
            return
        self._goster(parse_metin(metin))

    def _excel_yukle(self):
        from importer import parse_excel
        dosya = filedialog.askopenfilename(
            filetypes=[("Excel", "*.xlsx *.xls"), ("Tümü", "*.*")])
        if not dosya:
            return
        try:
            self._goster(parse_excel(dosya))
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _ocr_yukle(self):
        from importer import parse_ocr_klasor
        klasor = filedialog.askdirectory(title="Görüntü Klasörü Seç")
        if not klasor:
            return
        self.app.set_durum("OCR işleniyor...")

        def isle():
            try:
                kayitlar = parse_ocr_klasor(klasor)
                self.after(0, lambda: self._goster(kayitlar))
                self.after(0, lambda: self.app.set_durum(
                    f"✅ OCR: {len(kayitlar)} hasta"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("OCR Hatası", str(e)))

        threading.Thread(target=isle, daemon=True).start()

    def _goster(self, kayitlar):
        from importer import tarama_idler_eslestir
        from phone_matcher import normalize_isim
        self.import_kayitlar = kayitlar
        self.oniz_tree.delete(*self.oniz_tree.get_children())
        for k in kayitlar:
            if self.telefon_sozlugu and not k.telefon:
                k.telefon = self.telefon_sozlugu.get(normalize_isim(k.isim), "")
            tt = tarama_idler_eslestir(k.taramalar, self.app.tarama_turleri)
            self.oniz_tree.insert('', 'end', values=(
                k.isim, k.tc or '', k.yas or '',
                k.telefon or '', ', '.join(k.taramalar), len(tt)
            ))
        self.import_durum.config(
            text=f"{len(kayitlar)} hasta yüklendi", fg="blue")

    def _telefon_yukle(self):
        from phone_matcher import TelefonEslestirici
        dosya = filedialog.askopenfilename(
            title="Telefon Excel'i Seç",
            filetypes=[("Excel", "*.xlsx *.xls"), ("Tümü", "*.*")])
        if not dosya:
            return
        ic = simpledialog.askstring("Sütun", "Adı sütunu:",    initialvalue="Adı")
        sc = simpledialog.askstring("Sütun", "Soyadı sütunu:", initialvalue="Soyadı")
        tc = simpledialog.askstring("Sütun", "Telefon sütunu:", initialvalue="Telefon")
        if not all([ic, sc, tc]):
            return
        try:
            e = TelefonEslestirici(kaynak_dosya=dosya,
                                    isim_sutunu=ic, soyisim_sutunu=sc,
                                    telefon_sutunu=tc)
            self.telefon_sozlugu = e.telefon_sozlugu
            self.tel_durum.config(
                text=f"✅ {len(self.telefon_sozlugu)} kişi", fg="green")
            if self.import_kayitlar:
                self._goster(self.import_kayitlar)
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _listeyeaktar(self):
        from importer import tarama_idler_eslestir
        if not self.import_kayitlar:
            messagebox.showwarning("Uyarı", "Önce veri yükleyin!")
            return
        secili = self.liste_combo.get()
        if not secili:
            messagebox.showwarning("Uyarı", "Liste seçin!")
            return
        try:
            liste_id = int(secili.split("ID:")[1].rstrip(")"))
        except Exception:
            messagebox.showerror("Hata", "Liste ID alınamadı")
            return

        payload = [{
            "isim": k.isim, "tc": k.tc, "yas": k.yas,
            "telefon": k.telefon, "kaynak": k.kaynak,
            "tarama_turu_idler": tarama_idler_eslestir(
                k.taramalar, self.app.tarama_turleri)
        } for k in self.import_kayitlar]

        self.app.set_durum(f"{len(payload)} hasta aktarılıyor...")

        def gonder():
            try:
                sonuc   = self.app.api.post(
                    f"/liste/{liste_id}/hasta/toplu", {"hastalar": payload})
                eklenen = (sonuc or {}).get("eklenen", 0)
                self.after(0, lambda: self.import_durum.config(
                    text=f"✅ {eklenen} hasta aktarıldı", fg="green"))
                self.after(0, lambda: self.app.set_durum(
                    f"✅ {eklenen} hasta aktarıldı"))
            except Exception as ex:
                self.after(0, lambda: messagebox.showerror(
                    "Aktarma Hatası", str(ex)))

        threading.Thread(target=gonder, daemon=True).start()


# ─── Sekme 3: Arama Paneli ───────────────────────────────────

class AramaPaneliSekmesi(ttk.Frame):
    def __init__(self, parent, app: SaglikCRM):
        super().__init__(parent)
        self.app = app
        self.aktif_liste: Optional[Dict] = None
        self.hastalar: List[Dict] = []
        self.tarama_kolonlari: List[str] = []
        self.tree: Optional[ttk.Treeview] = None
        self.tablo_kolonlari: List[str] = []
        self._kur()

    def _kur(self):
        ust = tk.Frame(self)
        ust.pack(fill='x', padx=10, pady=5)
        self.liste_bilgi = tk.Label(
            ust, text="← Listeler sekmesinden liste seçin",
            font=("Arial", 11, "bold"), fg="gray")
        self.liste_bilgi.pack(side='left')
        tk.Button(ust, text="🔄", command=self._yenile, width=3).pack(side='right')

        filtre = tk.Frame(self)
        filtre.pack(fill='x', padx=10, pady=2)
        tk.Label(filtre, text="Ara:").pack(side='left')
        self.filtre_ara = tk.Entry(filtre, width=20)
        self.filtre_ara.pack(side='left', padx=5)
        self.filtre_ara.bind('<KeyRelease>', lambda e: self._filtrele())

        self.filtre_durum = ttk.Combobox(
            filtre, state='readonly', width=18,
            values=["Tümü", "Aranmadı", "Ulaşılamadı", "Ulaşıldı"])
        self.filtre_durum.set("Tümü")
        self.filtre_durum.pack(side='left', padx=5)
        self.filtre_durum.bind('<<ComboboxSelected>>', lambda e: self._filtrele())

        self.filtre_tarama = ttk.Combobox(filtre, state='readonly', width=25)
        self.filtre_tarama.pack(side='left', padx=5)
        self.filtre_tarama.bind('<<ComboboxSelected>>', lambda e: self._filtrele())

        self.tablo_frame = tk.Frame(self)
        self.tablo_frame.pack(fill='both', expand=True, padx=10, pady=5)
        self._tablo_kur([])

        self.istat_label = tk.Label(self, text="", fg="gray", font=("Arial", 8))
        self.istat_label.pack(side='bottom', anchor='w', padx=10, pady=2)

    def _tablo_kur(self, tarama_turleri: List[str]):
        for w in self.tablo_frame.winfo_children():
            w.destroy()

        self.tablo_kolonlari = ['isim', 'telefon'] + tarama_turleri + \
                                ['puan', 'durum', 'gecmis']

        self.tree = ttk.Treeview(self.tablo_frame,
                                  columns=self.tablo_kolonlari,
                                  show='headings', height=20)
        self.tree.heading('isim',    text='İsim')
        self.tree.heading('telefon', text='Telefon')
        self.tree.column('isim',    width=180, minwidth=120)
        self.tree.column('telefon', width=130, minwidth=100)

        for t in tarama_turleri:
            kisa = t.replace(' tarama', ' T').replace(' izlem', ' İ')
            self.tree.heading(t, text=kisa)
            self.tree.column(t, width=80, anchor='center', minwidth=60)

        self.tree.heading('puan',   text='Puan')
        self.tree.heading('durum',  text='Durum')
        self.tree.heading('gecmis', text='Geçmiş')
        self.tree.column('puan',   width=50,  anchor='center')
        self.tree.column('durum',  width=120)
        self.tree.column('gecmis', width=350)

        sb_y = ttk.Scrollbar(self.tablo_frame, command=self.tree.yview)
        sb_x = ttk.Scrollbar(self.tablo_frame, orient='horizontal',
                               command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb_y.pack(side='right', fill='y')
        sb_x.pack(side='bottom', fill='x')

        self.tree.tag_configure('aranmadi',    background='#fff9c4')
        self.tree.tag_configure('ulasilamadi', background='#ffccbc')
        self.tree.tag_configure('ulasildi',    background='#c8e6c9')
        self.tree.tag_configure('yuksek',      font=("Arial", 9, "bold"))

        self.tree.bind('<Double-1>', self._gorusme_ekle)
        self.tree.bind('<Button-3>', self._sag_tikla)

    def liste_yukle(self, lst: Dict):
        self.aktif_liste = lst
        self.liste_bilgi.config(
            text=f"{lst['ay_ad']} {lst['yil']}", fg="black")
        self._yenile()

    def _yenile(self):
        if not self.aktif_liste:
            return
        self.app.set_durum("Yükleniyor...")

        def yukle():
            try:
                hastalar = self.app.api.get(
                    f"/liste/{self.aktif_liste['id']}/hastalar") or []
                self.after(0, lambda: self._guncelle(hastalar))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Hata", str(e)))

        threading.Thread(target=yukle, daemon=True).start()

    def _guncelle(self, hastalar: List[Dict]):
        self.hastalar = hastalar
        tarama_adlari: set = set()
        for h in hastalar:
            tarama_adlari.update(h.get('taramalar', {}).keys())
        tarama_sirali = [t['ad'] for t in self.app.tarama_turleri
                          if t['ad'] in tarama_adlari]

        self._tablo_kur(tarama_sirali)
        self.tarama_kolonlari = tarama_sirali

        self.filtre_tarama['values'] = ['Tüm Taramalar'] + tarama_sirali
        self.filtre_tarama.set('Tüm Taramalar')
        self._filtrele()

        try:
            istat = self.app.api.get(
                f"/liste/{self.aktif_liste['id']}/istatistik") or {}
            self.istat_label.config(text=(
                f"Toplam: {istat.get('toplam',0)}  |  "
                f"Aranmış: {istat.get('aranmis',0)}  |  "
                f"Ulaşılan: {istat.get('ulasilmis',0)}  |  "
                f"Randevu: {istat.get('randevu',0)}  |  "
                f"Bekleyen: {istat.get('aranmamis',0)}"
            ))
        except Exception:
            pass
        self.app.set_durum(f"✅ {len(hastalar)} hasta")

    def _filtrele(self):
        if self.tree is None:
            return
        arama    = self.filtre_ara.get().strip().lower()
        d_filtre = self.filtre_durum.get()
        t_filtre = self.filtre_tarama.get()
        self.tree.delete(*self.tree.get_children())

        for h in self.hastalar:
            if arama:
                if (arama not in h['isim'].lower() and
                        arama not in (h.get('telefon') or '')):
                    continue
            d = h.get('arama_durumu', 'aranmadı')
            if d_filtre == "Aranmadı"    and d != 'aranmadı':    continue
            if d_filtre == "Ulaşılamadı" and d != 'ulaşılamadı': continue
            if d_filtre == "Ulaşıldı"    and d in ('aranmadı', 'ulaşılamadı'): continue
            if t_filtre and t_filtre != 'Tüm Taramalar':
                if h.get('taramalar', {}).get(t_filtre) != 'VAR':
                    continue

            row = [h['isim'], h.get('telefon') or '']
            for t in self.tarama_kolonlari:
                row.append('✓' if h.get('taramalar', {}).get(t) == 'VAR' else '')
            row += [h.get('oncelik_puani', 0), d, h.get('gecmis_ozet', '')]

            tags = []
            if d == 'aranmadı':         tags.append('aranmadi')
            elif d == 'ulaşılamadı':    tags.append('ulasilamadi')
            else:                       tags.append('ulasildi')
            if h.get('oncelik_puani', 0) >= 3:
                tags.append('yuksek')

            self.tree.insert('', 'end', iid=str(h['hasta_id']),
                              values=row, tags=tuple(tags))

    def _gorusme_ekle(self, event=None):
        item = self.tree.selection()
        if not item:
            return
        hasta = next((h for h in self.hastalar
                      if h['hasta_id'] == int(item[0])), None)
        if not hasta:
            return
        d = GorusmeDialog(self, self.app, hasta, self.aktif_liste)
        self.wait_window(d)
        if d.kaydedildi:
            self._yenile()

    def _sag_tikla(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)
        hasta = next((h for h in self.hastalar
                      if h['hasta_id'] == int(item)), None)
        if not hasta:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="📞 Görüşme Ekle",  command=self._gorusme_ekle)
        menu.add_command(label="👤 Hasta Geçmişi",
                          command=lambda: self._gecmise_git(hasta))
        menu.add_separator()
        menu.add_command(label="✏️ Telefon Düzenle",
                          command=lambda: self._telefon_duzenle(hasta))
        menu.post(event.x_root, event.y_root)

    def _gecmise_git(self, hasta: Dict):
        self.app.sekme_gecmis.hasta_yukle(hasta['hasta_id'], hasta['isim'])
        self.app.notebook.select(3)

    def _telefon_duzenle(self, hasta: Dict):
        yeni = simpledialog.askstring(
            "Telefon Düzenle", f"{hasta['isim']} — yeni telefon:",
            initialvalue=hasta.get('telefon') or '')
        if yeni is not None:
            try:
                self.app.api.put(f"/hasta/{hasta['hasta_id']}",
                                  {"telefon": yeni.strip()})
                self._yenile()
            except Exception as e:
                messagebox.showerror("Hata", str(e))


# ─── Görüşme Dialog ──────────────────────────────────────────

class GorusmeDialog(tk.Toplevel):
    def __init__(self, parent, app: SaglikCRM, hasta: Dict, liste: Dict):
        super().__init__(parent)
        self.app = app
        self.hasta = hasta
        self.liste = liste
        self.kaydedildi = False
        self.title(f"📞 Görüşme — {hasta['isim']}")
        self.geometry("480x430")
        self.grab_set()
        self.resizable(False, False)

        tk.Label(self, text=hasta['isim'],
                 font=("Arial", 12, "bold")).pack(pady=(15, 3))
        tk.Label(self, text=f"Telefon: {hasta.get('telefon') or 'Yok'}",
                 fg="gray").pack()

        form = tk.Frame(self, padx=20)
        form.pack(fill='x', pady=8)

        self.ulasildi_var = tk.BooleanVar(value=True)
        ul_f = tk.Frame(form)
        ul_f.grid(row=0, column=0, columnspan=2, sticky='w', pady=5)
        tk.Radiobutton(ul_f, text="✅ Ulaşıldı",
                        variable=self.ulasildi_var, value=True).pack(side='left')
        tk.Radiobutton(ul_f, text="❌ Ulaşılamadı",
                        variable=self.ulasildi_var, value=False).pack(
            side='left', padx=15)

        tk.Label(form, text="Sonuç:").grid(row=1, column=0, sticky='w', pady=5)
        sonuclar = app.sabit_veriler.get(
            'sonuc_tipleri', ['randevu', 'ret', 'tekrar_ara', 'mesaj', 'diger'])
        self.sonuc_combo = ttk.Combobox(
            form, state='readonly', values=sonuclar, width=20)
        self.sonuc_combo.set('randevu')
        self.sonuc_combo.grid(row=1, column=1, sticky='w', pady=5)

        tk.Label(form, text="Aranan Tel:").grid(row=2, column=0, sticky='w')
        self.tel_entry = tk.Entry(form, width=18)
        self.tel_entry.insert(0, hasta.get('telefon') or '')
        self.tel_entry.grid(row=2, column=1, sticky='w', pady=5)

        tk.Label(form, text="Arayan:").grid(row=3, column=0, sticky='w')
        self.arayan_entry = tk.Entry(form, width=25)
        self.arayan_entry.insert(0, app.cfg.get('kullanici_adi', ''))
        self.arayan_entry.grid(row=3, column=1, sticky='w', pady=5)

        tk.Label(form, text="Not:").grid(row=4, column=0, sticky='nw', pady=5)
        self.not_alan = scrolledtext.ScrolledText(
            form, height=5, width=35, font=("Arial", 9))
        self.not_alan.grid(row=4, column=1, pady=5)

        gorusmeler = hasta.get('gorusmeler', [])
        if gorusmeler:
            son = gorusmeler[0]
            tk.Label(self,
                      text=f"Son: {(son.get('tarih_saat') or '')[:16]}  "
                           f"{son.get('sonuc', '')}",
                      fg="blue", font=("Arial", 8)).pack()

        tk.Button(self, text="💾 Kaydet", command=self._kaydet,
                  bg="#4CAF50", fg="white",
                  font=("Arial", 10, "bold"), width=15).pack(pady=12)

    def _kaydet(self):
        try:
            self.app.api.post("/gorusme", {
                "liste_id":           self.liste['id'],
                "hasta_id":           self.hasta['hasta_id'],
                "ulasildi":           self.ulasildi_var.get(),
                "sonuc":              self.sonuc_combo.get(),
                "arayan":             self.arayan_entry.get().strip(),
                "telefon_kullanilan": self.tel_entry.get().strip(),
                "not_metni":          self.not_alan.get(1.0, 'end').strip()
            })
            self.kaydedildi = True
            self.destroy()
        except Exception as e:
            messagebox.showerror("Kaydetme Hatası", str(e))


# ─── Sekme 4: Hasta Geçmişi ──────────────────────────────────

class HastaGecmisSekmesi(ttk.Frame):
    def __init__(self, parent, app: SaglikCRM):
        super().__init__(parent)
        self.app = app
        self._kur()

    def _kur(self):
        ust = tk.Frame(self)
        ust.pack(fill='x', padx=10, pady=10)
        tk.Label(ust, text="Hasta ID:").pack(side='left')
        self.id_entry = tk.Entry(ust, width=8)
        self.id_entry.pack(side='left', padx=5)
        tk.Button(ust, text="🔍 Getir", command=self._getir).pack(side='left')
        self.isim_lbl = tk.Label(ust, text="",
                                  font=("Arial", 12, "bold"), fg="#1565C0")
        self.isim_lbl.pack(side='left', padx=20)

        lst_f = tk.LabelFrame(self, text="Aylık Listeler", padx=5, pady=5)
        lst_f.pack(fill='x', padx=10, pady=5)
        cols_l = ('ay_yil', 'taramalar', 'puan')
        self.liste_tree = ttk.Treeview(lst_f, columns=cols_l,
                                        show='headings', height=5)
        self.liste_tree.heading('ay_yil',    text='Ay / Yıl')
        self.liste_tree.heading('taramalar', text='Taramalar (VAR)')
        self.liste_tree.heading('puan',      text='Puan')
        self.liste_tree.column('ay_yil',    width=150)
        self.liste_tree.column('taramalar', width=500)
        self.liste_tree.column('puan',      width=60, anchor='center')
        self.liste_tree.pack(fill='x')

        gor_f = tk.LabelFrame(self, text="Görüşme Kayıtları", padx=5, pady=5)
        gor_f.pack(fill='both', expand=True, padx=10, pady=5)
        cols_g = ('tarih', 'ay_yil', 'ulasildi', 'sonuc', 'arayan', 'tel', 'not')
        self.gor_tree = ttk.Treeview(gor_f, columns=cols_g,
                                      show='headings', height=12)
        for col, baslik, gen in [
            ('tarih',    'Tarih',    140),
            ('ay_yil',   'Liste',    120),
            ('ulasildi', '✓/✗',       60),
            ('sonuc',    'Sonuç',    100),
            ('arayan',   'Arayan',   130),
            ('tel',      'Telefon',  120),
            ('not',      'Not',      300),
        ]:
            self.gor_tree.heading(col, text=baslik)
            self.gor_tree.column(col, width=gen,
                                  anchor='center' if gen <= 70 else 'w')

        sb = ttk.Scrollbar(gor_f, command=self.gor_tree.yview)
        self.gor_tree.configure(yscrollcommand=sb.set)
        self.gor_tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.gor_tree.tag_configure('ulasildi',    background='#c8e6c9')
        self.gor_tree.tag_configure('ulasilamadi', background='#ffccbc')

    def hasta_yukle(self, hasta_id: int, isim: str = ""):
        self.id_entry.delete(0, 'end')
        self.id_entry.insert(0, str(hasta_id))
        self.isim_lbl.config(text=isim)
        self._getir()

    def _getir(self):
        try:
            hasta_id = int(self.id_entry.get().strip())
        except ValueError:
            messagebox.showerror("Hata", "Geçerli hasta ID girin")
            return
        try:
            veri  = self.app.api.get(f"/hasta/{hasta_id}/gecmis") or {}
            hasta = self.app.api.get(f"/hasta/{hasta_id}") or {}
        except Exception as e:
            messagebox.showerror("Hata", str(e))
            return

        self.isim_lbl.config(text=hasta.get('isim', ''))

        self.liste_tree.delete(*self.liste_tree.get_children())
        for l in veri.get('listeler', []):
            var_t = [ad for ad, v in l['taramalar'].items() if v == 'VAR']
            self.liste_tree.insert('', 'end', values=(
                f"{l['ay_ad']} {l['yil']}",
                ', '.join(var_t), l['oncelik_puani']
            ))

        self.gor_tree.delete(*self.gor_tree.get_children())
        for g in veri.get('gorusmeler', []):
            etiket = 'ulasildi' if g['ulasildi'] else 'ulasilamadi'
            self.gor_tree.insert('', 'end', tags=(etiket,), values=(
                (g.get('tarih_saat') or '')[:16],
                f"{g.get('ay_ad', '')} {g.get('yil', '')}",
                '✅' if g['ulasildi'] else '❌',
                g.get('sonuc') or '',
                g.get('arayan') or '',
                g.get('telefon_kullanilan') or '',
                (g.get('not_metni') or '')[:80]
            ))


# ─── Sekme 5: Ayarlar ────────────────────────────────────────

class AyarlarSekmesi(ttk.Frame):
    def __init__(self, parent, app: SaglikCRM):
        super().__init__(parent)
        self.app = app
        self._turler_data: List[Dict] = []
        self._kur()

    def _kur(self):
        kul_f = tk.LabelFrame(self, text="Kullanıcı", padx=15, pady=10)
        kul_f.pack(fill='x', padx=15, pady=10)
        tk.Label(kul_f,
                 text="Adınız (görüşme kayıtlarında görünür):").pack(anchor='w')
        self.kul_entry = tk.Entry(kul_f, width=30)
        self.kul_entry.insert(0, self.app.cfg.get('kullanici_adi', ''))
        self.kul_entry.pack(anchor='w', pady=5)
        tk.Button(kul_f, text="💾 Kaydet",
                  command=self._kullanici_kaydet).pack(anchor='w')

        sun_f = tk.LabelFrame(self, text="Sunucu Bağlantısı",
                               padx=15, pady=10)
        sun_f.pack(fill='x', padx=15, pady=5)
        tk.Label(sun_f, text="IP:").grid(row=0, column=0, sticky='w')
        self.ip_entry = tk.Entry(sun_f, width=18)
        self.ip_entry.insert(0, self.app.cfg.get('sunucu_ip', ''))
        self.ip_entry.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(sun_f, text="Port:").grid(row=0, column=2, sticky='w')
        self.port_entry = tk.Entry(sun_f, width=7)
        self.port_entry.insert(0, str(self.app.cfg.get('sunucu_port', 5000)))
        self.port_entry.grid(row=0, column=3)
        tk.Button(sun_f, text="🔌 Bağlantıyı Test Et",
                  command=self._test_baglan).grid(
            row=1, column=0, columnspan=4, pady=5)

        tt_f = tk.LabelFrame(self, text="Tarama Türleri", padx=15, pady=10)
        tt_f.pack(fill='both', expand=True, padx=15, pady=10)
        btn_f = tk.Frame(tt_f)
        btn_f.pack(fill='x')
        tk.Button(btn_f, text="➕ Ekle",
                  command=self._tur_ekle).pack(side='left')
        tk.Button(btn_f, text="✏️ Düzenle",
                  command=self._tur_duzenle).pack(side='left', padx=5)
        tk.Button(btn_f, text="🔄 Yenile",
                  command=self._turler_yukle).pack(side='left')

        cols = ('sira', 'ad', 'aktif')
        self.tur_tree = ttk.Treeview(tt_f, columns=cols,
                                      show='headings', height=10)
        self.tur_tree.heading('sira',  text='Sıra')
        self.tur_tree.heading('ad',    text='Tarama Adı')
        self.tur_tree.heading('aktif', text='Aktif')
        self.tur_tree.column('sira',  width=50,  anchor='center')
        self.tur_tree.column('ad',    width=250)
        self.tur_tree.column('aktif', width=70,  anchor='center')
        self.tur_tree.pack(fill='both', expand=True, pady=5)
        self._turler_yukle()

    def _kullanici_kaydet(self):
        self.app.cfg['kullanici_adi'] = self.kul_entry.get().strip()
        config_kaydet(self.app.cfg)
        messagebox.showinfo("✅", "Kaydedildi")

    def _test_baglan(self):
        ip = self.ip_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            messagebox.showerror("Hata", "Port sayı olmalı")
            return
        if API(ip, port).ping():
            self.app.cfg['sunucu_ip']   = ip
            self.app.cfg['sunucu_port'] = port
            config_kaydet(self.app.cfg)
            self.app.api = API(ip, port)
            messagebox.showinfo("✅", f"Bağlandı: {ip}:{port}")
        else:
            messagebox.showerror("❌", "Bağlanamadı")

    def _turler_yukle(self):
        try:
            turler = self.app.api.get("/tarama-turleri") or []
            self.app.tarama_turleri = turler
        except Exception as e:
            messagebox.showerror("Hata", str(e))
            return
        self._turler_data = turler
        self.tur_tree.delete(*self.tur_tree.get_children())
        for t in turler:
            self.tur_tree.insert('', 'end', iid=str(t['id']), values=(
                t['sira'], t['ad'], '✅' if t['aktif'] else '❌'))

    def _tur_ekle(self):
        ad = simpledialog.askstring(
            "Yeni Tarama Türü",
            "Tarama adı (ör: kolesterol tarama):")
        if ad and ad.strip():
            try:
                self.app.api.post("/tarama-turu", {"ad": ad.strip()})
                self._turler_yukle()
            except Exception as e:
                messagebox.showerror("Hata", str(e))

    def _tur_duzenle(self):
        item = self.tur_tree.selection()
        if not item:
            messagebox.showwarning("Uyarı", "Bir tür seçin")
            return
        tur_id = int(item[0])
        tur = next((t for t in self._turler_data if t['id'] == tur_id), None)
        if not tur:
            return

        d = tk.Toplevel(self)
        d.title("Türü Düzenle")
        d.geometry("320x200")
        d.grab_set()

        tk.Label(d, text="Ad:").grid(row=0, column=0, padx=10, pady=10, sticky='w')
        ad_e = tk.Entry(d, width=25)
        ad_e.insert(0, tur['ad'])
        ad_e.grid(row=0, column=1, padx=5)

        tk.Label(d, text="Sıra:").grid(row=1, column=0, padx=10, sticky='w')
        sira_e = tk.Entry(d, width=8)
        sira_e.insert(0, str(tur['sira']))
        sira_e.grid(row=1, column=1, sticky='w', padx=5)

        aktif_var = tk.BooleanVar(value=bool(tur['aktif']))
        tk.Checkbutton(d, text="Aktif",
                        variable=aktif_var).grid(
            row=2, column=0, columnspan=2, pady=5)

        def kaydet():
            try:
                self.app.api.put(f"/tarama-turu/{tur_id}", {
                    "ad":    ad_e.get().strip(),
                    "sira":  int(sira_e.get()),
                    "aktif": 1 if aktif_var.get() else 0
                })
                d.destroy()
                self._turler_yukle()
            except Exception as e:
                messagebox.showerror("Hata", str(e))

        tk.Button(d, text="💾 Kaydet", command=kaydet,
                  bg="#4CAF50", fg="white").grid(
            row=3, column=0, columnspan=2, pady=15)


# ─── Başlatıcı ───────────────────────────────────────────────

def main():
    app = SaglikCRM()
    app.mainloop()


if __name__ == "__main__":
    main()
