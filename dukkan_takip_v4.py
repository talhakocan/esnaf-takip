"""
Elektronik ve Bilgisayar Dükkânı Takip Programı - v4
Mesleki Çözümleme Dersi Projesi

v3'ten v4'e Yenilikler:
  - Ürünlere "Barkod / Ürün Kodu" özelliği eklendi ve arama sistemi barkodu kapsayacak şekilde genişletildi.
  - Arayüz (UI) modernleştirildi: ttk.Style ile okunabilirlik artırıldı, satır yükseklikleri ayarlandı.
  - Tüm Treeview tablolarına dikey kaydırma çubuğu (Scrollbar) entegre edildi (Veri arttığında donmayı önler).
  - Veritabanı güncelleme mimarisi sayesinde eski veriler kaybolmadan yeni sütunlar (barkod) eklenebiliyor.
"""

import csv
import hashlib
import os
import shutil
import sqlite3
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

DB_ADI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dukkan.db")
DISA_AKTARMA_KLASORU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disa_aktarilanlar")

DURUMLAR = ["Beklemede", "Tamir Ediliyor", "Tamamlandı", "Teslim Edildi"]

# ======================================================================
# 1) VERİTABANI KATMANI
# ======================================================================

def baglan():
    return sqlite3.connect(DB_ADI)

def sayiya_cevir(metin):
    try:
        if not metin:
            return None
        return float(str(metin).strip().replace(",", "."))
    except ValueError:
        return None

def _sutunlari_tamamla(db, tablo, sutunlar):
    mevcut = {satir[1] for satir in db.execute(f"PRAGMA table_info({tablo})")}
    for ad, tanim in sutunlar.items():
        if ad not in mevcut:
            db.execute(f"ALTER TABLE {tablo} ADD COLUMN {ad} {tanim}")

def tablolari_olustur():
    with baglan() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS urun (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ad          TEXT NOT NULL,
                birim_fiyat REAL NOT NULL,
                stok        REAL NOT NULL,
                kritik_stok REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS musteri (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ad      TEXT NOT NULL,
                telefon TEXT
            );
            CREATE TABLE IF NOT EXISTS satis (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih       TEXT NOT NULL,
                musteri_id  INTEGER REFERENCES musteri(id),
                urun_id     INTEGER NOT NULL REFERENCES urun(id),
                adet        REAL NOT NULL,
                birim_fiyat REAL NOT NULL,
                toplam      REAL NOT NULL,
                odeme_turu  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS odeme (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                musteri_id INTEGER NOT NULL REFERENCES musteri(id),
                tarih      TEXT NOT NULL,
                tutar      REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS servis (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih           TEXT NOT NULL,
                musteri_id      INTEGER REFERENCES musteri(id),
                cihaz           TEXT NOT NULL,
                sikayet         TEXT,
                ucret           REAL NOT NULL DEFAULT 0,
                durum           TEXT NOT NULL DEFAULT 'Beklemede',
                teslim_tarihi   TEXT
            );
            CREATE TABLE IF NOT EXISTS ayar (
                anahtar TEXT PRIMARY KEY,
                deger   TEXT
            );
        """)
        # Eski veritabanlarına yeni sütunları ekle (veriler kaybolmaz)
        _sutunlari_tamamla(db, "urun", {
            "kategori": "TEXT NOT NULL DEFAULT 'Elektrik'",
            "aktif": "INTEGER NOT NULL DEFAULT 1",
            "alis_fiyat": "REAL NOT NULL DEFAULT 0",
            "barkod": "TEXT DEFAULT ''"  # v4 Yeniliği
        })
        _sutunlari_tamamla(db, "satis", {
            "iptal": "INTEGER NOT NULL DEFAULT 0",
            "maliyet": "REAL NOT NULL DEFAULT 0",
        })

# ---------------- Ayarlar / PIN ----------------
def _hashle(metin):
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()

def pin_kayitli_mi():
    with baglan() as db:
        satir = db.execute("SELECT deger FROM ayar WHERE anahtar='pin_hash'").fetchone()
    return satir is not None

def pin_belirle(pin):
    with baglan() as db:
        db.execute("INSERT OR REPLACE INTO ayar (anahtar, deger) VALUES ('pin_hash', ?)", (_hashle(pin),))

def pin_dogrula(pin):
    with baglan() as db:
        satir = db.execute("SELECT deger FROM ayar WHERE anahtar='pin_hash'").fetchone()
    return satir is not None and satir[0] == _hashle(pin)

# ---------------- Ürün / Stok ----------------
def urun_ekle(barkod, ad, kategori, alis_fiyat, satis_fiyat, stok, kritik):
    ad = ad.strip()
    barkod = barkod.strip()
    alis, satis, stok, kritik = (sayiya_cevir(alis_fiyat), sayiya_cevir(satis_fiyat),
                                 sayiya_cevir(stok), sayiya_cevir(kritik))
    if not ad:
        return False, "Ürün adı boş olamaz."
    if None in (alis, satis, stok, kritik) or min(alis, satis, stok, kritik) < 0:
        return False, "Fiyatlar, stok ve kritik stok sayı olmalı (0 ya da daha büyük)."
    with baglan() as db:
        db.execute(
            "INSERT INTO urun (barkod, ad, kategori, alis_fiyat, birim_fiyat, stok, kritik_stok) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (barkod, ad, kategori, alis, satis, stok, kritik))
    return True, "Ürün eklendi."

def urun_guncelle(urun_id, barkod, ad, kategori, alis_fiyat, satis_fiyat, kritik):
    ad = ad.strip()
    barkod = barkod.strip()
    alis, satis, kritik = sayiya_cevir(alis_fiyat), sayiya_cevir(satis_fiyat), sayiya_cevir(kritik)
    if not ad:
        return False, "Ürün adı boş olamaz."
    if None in (alis, satis, kritik) or min(alis, satis, kritik) < 0:
        return False, "Fiyatlar ve kritik stok sayı olmalı (0 ya da daha büyük)."
    with baglan() as db:
        db.execute("UPDATE urun SET barkod=?, ad=?, kategori=?, alis_fiyat=?, birim_fiyat=?, kritik_stok=? WHERE id=?",
                   (barkod, ad, kategori, alis, satis, kritik, urun_id))
    return True, "Ürün güncellendi."

def urun_sil(urun_id):
    with baglan() as db:
        db.execute("UPDATE urun SET aktif=0 WHERE id=?", (urun_id,))
    return True, "Ürün listeden kaldırıldı."

def urunleri_getir(sadece_aktif=True, arama=""):
    sorgu = "SELECT id, barkod, ad, kategori, alis_fiyat, birim_fiyat, stok, kritik_stok, aktif FROM urun WHERE 1=1"
    parametreler = []
    if sadece_aktif:
        sorgu += " AND aktif=1"
    if arama.strip():
        sorgu += " AND (ad LIKE ? OR barkod LIKE ?)"
        parametreler.extend([f"%{arama.strip()}%", f"%{arama.strip()}%"])
    sorgu += " ORDER BY ad"
    with baglan() as db:
        return db.execute(sorgu, parametreler).fetchall()

def stok_ekle(urun_id, adet):
    adet = sayiya_cevir(adet)
    if adet is None or adet <= 0:
        return False, "Adet 0'dan büyük bir sayı olmalı."
    with baglan() as db:
        db.execute("UPDATE urun SET stok = stok + ? WHERE id = ?", (adet, urun_id))
    return True, "Stok güncellendi."

def azalan_urunler():
    with baglan() as db:
        return db.execute(
            "SELECT barkod, ad, stok, kritik_stok FROM urun WHERE stok <= kritik_stok AND aktif=1 ORDER BY ad"
        ).fetchall()

# ---------------- Satış (sepetli) ----------------
def satis_tamamla(sepet, odeme_turu, musteri_id):
    if not sepet:
        return False, "Sepet boş. Önce ürün ekleyin."
    if odeme_turu == "Veresiye" and musteri_id is None:
        return False, "Veresiye satış için müşteri seçmelisin."

    with baglan() as db:
        for kalem in sepet:
            stok = db.execute("SELECT stok FROM urun WHERE id=?", (kalem["urun_id"],)).fetchone()[0]
            if kalem["adet"] > stok:
                return False, f"Yetersiz stok: {kalem['ad']} (elde {stok:g} adet var)."

        tarih = datetime.now().strftime("%Y-%m-%d %H:%M")
        toplam_tutar = 0.0
        for kalem in sepet:
            alis_fiyat = db.execute("SELECT alis_fiyat FROM urun WHERE id=?", (kalem["urun_id"],)).fetchone()[0]
            toplam = kalem["adet"] * kalem["birim_fiyat"]
            maliyet = kalem["adet"] * alis_fiyat
            toplam_tutar += toplam
            db.execute(
                """INSERT INTO satis (tarih, musteri_id, urun_id, adet, birim_fiyat, toplam, odeme_turu, iptal, maliyet)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (tarih, musteri_id if odeme_turu == "Veresiye" else None,
                 kalem["urun_id"], kalem["adet"], kalem["birim_fiyat"], toplam, odeme_turu, maliyet))
            db.execute("UPDATE urun SET stok = stok - ? WHERE id = ?", (kalem["adet"], kalem["urun_id"]))
    return True, f"Satış tamamlandı: {toplam_tutar:.2f} TL ({odeme_turu})"

def satis_iptal_et(satis_id):
    with baglan() as db:
        satir = db.execute("SELECT urun_id, adet, iptal FROM satis WHERE id=?", (satis_id,)).fetchone()
        if satir is None:
            return False, "Satış bulunamadı."
        if satir[2]:
            return False, "Bu satış zaten iptal edilmiş."
        db.execute("UPDATE satis SET iptal=1 WHERE id=?", (satis_id,))
        db.execute("UPDATE urun SET stok = stok + ? WHERE id=?", (satir[1], satir[0]))
    return True, "Satış iptal edildi, ürün stoğa geri eklendi."

def gunun_satislari(tarih):
    with baglan() as db:
        return db.execute(
            """SELECT s.id, substr(s.tarih, 12, 5), u.barkod, u.ad, s.adet, s.toplam,
                      s.odeme_turu, COALESCE(m.ad, '-'), s.iptal
               FROM satis s
               JOIN urun u ON u.id = s.urun_id
               LEFT JOIN musteri m ON m.id = s.musteri_id
               WHERE substr(s.tarih, 1, 10) = ?
               ORDER BY s.tarih""", (tarih,)).fetchall()

def gunluk_ozet(tarih):
    with baglan() as db:
        toplam, nakit, veresiye, maliyet = db.execute(
            """SELECT COALESCE(SUM(toplam), 0),
                      COALESCE(SUM(CASE WHEN odeme_turu = 'Nakit'    THEN toplam END), 0),
                      COALESCE(SUM(CASE WHEN odeme_turu = 'Veresiye' THEN toplam END), 0),
                      COALESCE(SUM(maliyet), 0)
               FROM satis WHERE substr(tarih, 1, 10) = ? AND iptal = 0""", (tarih,)).fetchone()
        tahsilat = db.execute(
            "SELECT COALESCE(SUM(tutar), 0) FROM odeme WHERE substr(tarih, 1, 10) = ?",
            (tarih,)).fetchone()[0]
    kar = toplam - maliyet
    return toplam, nakit, veresiye, tahsilat, kar

# ---------------- Müşteri / Veresiye ----------------
def musteri_ekle(ad, telefon):
    ad = ad.strip()
    if not ad:
        return False, "Müşteri adı boş olamaz."
    with baglan() as db:
        db.execute("INSERT INTO musteri (ad, telefon) VALUES (?, ?)", (ad, telefon.strip()))
    return True, "Müşteri eklendi."

def musterileri_getir(arama=""):
    sorgu = """SELECT m.id, m.ad, m.telefon,
                 COALESCE((SELECT SUM(toplam) FROM satis
                           WHERE musteri_id = m.id AND odeme_turu = 'Veresiye' AND iptal = 0), 0)
               - COALESCE((SELECT SUM(tutar) FROM odeme WHERE musteri_id = m.id), 0)
               FROM musteri m WHERE 1=1"""
    parametreler = []
    if arama.strip():
        sorgu += " AND m.ad LIKE ?"
        parametreler.append(f"%{arama.strip()}%")
    sorgu += " ORDER BY m.ad"
    with baglan() as db:
        return db.execute(sorgu, parametreler).fetchall()

def musteri_borcu(musteri_id):
    for m in musterileri_getir():
        if m[0] == musteri_id:
            return m[3]
    return 0

def odeme_al(musteri_id, tutar):
    tutar = sayiya_cevir(tutar)
    if tutar is None or tutar <= 0:
        return False, "Tutar 0'dan büyük bir sayı olmalı."
    borc = musteri_borcu(musteri_id)
    if tutar > borc + 0.001:
        return False, f"Ödeme borçtan fazla olamaz. Mevcut borç: {borc:.2f} TL"
    with baglan() as db:
        db.execute("INSERT INTO odeme (musteri_id, tarih, tutar) VALUES (?, ?, ?)",
                   (musteri_id, datetime.now().strftime("%Y-%m-%d %H:%M"), tutar))
    return True, f"{tutar:.2f} TL ödeme alındı. Kalan borç: {borc - tutar:.2f} TL"

def musteri_hareketleri(musteri_id):
    with baglan() as db:
        satislar = db.execute(
            """SELECT s.tarih, u.ad, s.adet, s.toplam, s.iptal
               FROM satis s JOIN urun u ON u.id = s.urun_id
               WHERE s.musteri_id = ? AND s.odeme_turu = 'Veresiye'
               ORDER BY s.tarih""", (musteri_id,)).fetchall()
        odemeler = db.execute(
            "SELECT tarih, tutar FROM odeme WHERE musteri_id = ? ORDER BY tarih", (musteri_id,)).fetchall()
    hareketler = []
    for tarih, urun_ad, adet, toplam, iptal in satislar:
        aciklama = f"{urun_ad} x {adet:g}" + (" (İPTAL)" if iptal else "")
        hareketler.append((tarih, aciklama, 0 if iptal else toplam))
    for tarih, tutar in odemeler:
        hareketler.append((tarih, "Ödeme alındı", -tutar))
    hareketler.sort(key=lambda h: h[0])
    return hareketler

# ---------------- Bilgisayar Tamir / Servis ----------------
def servis_ekle(musteri_id, cihaz, sikayet, ucret):
    cihaz = cihaz.strip()
    if not cihaz:
        return False, "Cihaz adı boş olamaz."
    ucret_sayi = sayiya_cevir(ucret) if ucret else 0
    if ucret_sayi is None or ucret_sayi < 0:
        return False, "Ücret sayı olmalı (0 ya da daha büyük)."
    with baglan() as db:
        db.execute(
            """INSERT INTO servis (tarih, musteri_id, cihaz, sikayet, ucret, durum)
               VALUES (?, ?, ?, ?, ?, 'Beklemede')""",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), musteri_id, cihaz, sikayet.strip(), ucret_sayi))
    return True, "Servis kaydı oluşturuldu."

def servis_durum_guncelle(servis_id, yeni_durum):
    with baglan() as db:
        if yeni_durum == "Teslim Edildi":
            db.execute("UPDATE servis SET durum=?, teslim_tarihi=? WHERE id=?",
                      (yeni_durum, datetime.now().strftime("%Y-%m-%d %H:%M"), servis_id))
        else:
            db.execute("UPDATE servis SET durum=? WHERE id=?", (yeni_durum, servis_id))
    return True, "Durum güncellendi."

def servisleri_getir():
    with baglan() as db:
        return db.execute(
            """SELECT s.id, substr(s.tarih,1,16), COALESCE(m.ad,'-'), s.cihaz, s.sikayet, s.ucret, s.durum
               FROM servis s LEFT JOIN musteri m ON m.id = s.musteri_id
               ORDER BY (s.durum = 'Teslim Edildi'), s.tarih DESC""").fetchall()

def yedek_al():
    klasor = os.path.join(os.path.dirname(DB_ADI), "yedekler")
    os.makedirs(klasor, exist_ok=True)
    hedef = os.path.join(klasor, f"dukkan_{datetime.now():%Y%m%d_%H%M%S}.db")
    shutil.copy(DB_ADI, hedef)
    return hedef

# ---------------- CSV / Excel'e Dışa Aktarma ----------------
def _csv_yaz(dosya_adi, basliklar, satirlar):
    os.makedirs(DISA_AKTARMA_KLASORU, exist_ok=True)
    yol = os.path.join(DISA_AKTARMA_KLASORU, dosya_adi)
    with open(yol, "w", newline="", encoding="utf-8-sig") as dosya:
        yazici = csv.writer(dosya, delimiter=";")
        yazici.writerow(basliklar)
        yazici.writerows(satirlar)
    return yol

def satislari_csv_aktar(tarih):
    satirlar = [(s[1], s[2], s[3], s[4], f"{s[5]:.2f}", s[6], s[7], "İptal" if s[8] else "Geçerli")
                for s in gunun_satislari(tarih)]
    return _csv_yaz(f"satislar_{tarih}.csv",
                    ["Saat", "Barkod", "Ürün", "Adet", "Tutar (TL)", "Ödeme", "Müşteri", "Durum"], satirlar)

def borc_listesi_csv_aktar():
    satirlar = [(m[1], m[2], f"{m[3]:.2f}") for m in musterileri_getir() if m[3] > 0.001]
    return _csv_yaz(f"borc_listesi_{datetime.now():%Y%m%d}.csv",
                    ["Müşteri", "Telefon", "Kalan Borç (TL)"], satirlar)

def servisleri_csv_aktar():
    satirlar = [(s[1], s[2], s[3], s[4], f"{s[5]:.2f}", s[6]) for s in servisleri_getir()]
    return _csv_yaz(f"servisler_{datetime.now():%Y%m%d}.csv",
                    ["Tarih", "Müşteri", "Cihaz", "Arıza", "Ücret (TL)", "Durum"], satirlar)

# ======================================================================
# 2) ARAYÜZ KATMANI
# ======================================================================

def etiketli_giris(ust, etiket, satir, sutun, genislik=15, varsayilan=""):
    ttk.Label(ust, text=etiket).grid(row=satir, column=sutun, padx=5, pady=5, sticky="e")
    kutu = ttk.Entry(ust, width=genislik)
    kutu.insert(0, varsayilan)
    kutu.grid(row=satir, column=sutun + 1, padx=5, sticky="w")
    return kutu

def tablo_olustur(ust, kolonlar, yukseklik=10):
    """
    v4 Güncellemesi: Tüm tablolara otomatik dikey scrollbar eklendi.
    Böylece kayıtlar arttığında sayfa yapısı bozulmaz.
    """
    kapsayici = ttk.Frame(ust)
    t = ttk.Treeview(kapsayici, columns=[k[0] for k in kolonlar], show="headings", height=yukseklik)
    vsb = ttk.Scrollbar(kapsayici, orient="vertical", command=t.yview)
    t.configure(yscrollcommand=vsb.set)
    
    for anahtar, baslik, genislik in kolonlar:
        t.heading(anahtar, text=baslik, anchor="w")
        t.column(anahtar, width=genislik, anchor="w")
        
    t.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    return t, kapsayici

def giris_kontrolu(ebeveyn):
    if not pin_kayitli_mi():
        mesaj = ("Bu, programın ilk çalıştırılması.\n"
                 "Dükkân bilgisayarına başkası erişse bile verileri görmesin diye "
                 "4 haneli bir PIN belirle (örn. 1234).")
        while True:
            pin = simpledialog.askstring("PIN Belirle", mesaj, show="*", parent=ebeveyn)
            if pin is None:
                return False
            if len(pin.strip()) < 4:
                messagebox.showwarning("Hata", "PIN en az 4 karakter olmalı.", parent=ebeveyn)
                continue
            pin_belirle(pin.strip())
            messagebox.showinfo("Tamam", "PIN belirlendi. Bir sonraki açılışta bunu kullanacaksın.", parent=ebeveyn)
            return True
    else:
        for deneme in range(3):
            pin = simpledialog.askstring("Giriş", "Güvenlik PIN'ini giriniz:", show="*", parent=ebeveyn)
            if pin is None:
                return False
            if pin_dogrula(pin.strip()):
                return True
            messagebox.showwarning("Hatalı PIN", f"Yanlış PIN. Kalan deneme: {2 - deneme}", parent=ebeveyn)
        return False


class Uygulama(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        if not giris_kontrolu(self):
            self.destroy()
            sys.exit(0)
        self.deiconify()

        self.title("Dükkân Takip Programı - PRO v4")
        self.geometry("1100x750")
        
        # v4 Arayüz Modernizasyonu
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview.Heading", font=('Helvetica', 10, 'bold'), background="#e0e0e0")
        style.configure("Treeview", font=('Helvetica', 10), rowheight=28)
        style.configure("TButton", font=('Helvetica', 10))

        self.bugun = datetime.now().strftime("%Y-%m-%d")
        self.urun_map = {}
        self.musteri_map = {}
        self.sepet = []
        self.duzenlenen_urun_id = None

        sekmeler = ttk.Notebook(self)
        sekmeler.pack(fill="both", expand=True, padx=8, pady=8)
        self.s_stok = ttk.Frame(sekmeler)
        self.s_satis = ttk.Frame(sekmeler)
        self.s_musteri = ttk.Frame(sekmeler)
        self.s_servis = ttk.Frame(sekmeler)
        self.s_rapor = ttk.Frame(sekmeler)
        
        sekmeler.add(self.s_stok, text="📦 Stok & Ürünler")
        sekmeler.add(self.s_satis, text="🛒 Hızlı Satış")
        sekmeler.add(self.s_musteri, text="👥 Müşteriler & Veresiye")
        sekmeler.add(self.s_servis, text="🔧 Teknik Servis")
        sekmeler.add(self.s_rapor, text="📊 Günlük Rapor")

        self.stok_sekmesi_kur()
        self.satis_sekmesi_kur()
        self.musteri_sekmesi_kur()
        self.servis_sekmesi_kur()
        self.rapor_sekmesi_kur()
        self.yenile()

    # ---------------- Stok sekmesi ----------------
    def stok_sekmesi_kur(self):
        f = self.s_stok
        form = ttk.LabelFrame(f, text="Ürün Ekle / Düzenle")
        form.pack(fill="x", padx=8, pady=8)
        
        self.e_urun_barkod = etiketli_giris(form, "Barkod / Kod:", 0, 0, 15)
        self.e_urun_ad = etiketli_giris(form, "Ürün adı:", 0, 2, 24)
        ttk.Label(form, text="Kategori:").grid(row=0, column=4, padx=5, sticky="e")
        self.c_urun_kategori = ttk.Combobox(form, state="readonly", width=12,
                                            values=["Elektrik", "Bilgisayar", "Aksesuar", "Diğer"])
        self.c_urun_kategori.set("Elektrik")
        self.c_urun_kategori.grid(row=0, column=5, padx=5, sticky="w")
        
        self.e_urun_alis = etiketli_giris(form, "Alış Fiyatı (TL):", 1, 0, 10)
        self.e_urun_fiyat = etiketli_giris(form, "Satış Fiyatı (TL):", 1, 2, 10)
        self.e_urun_stok = etiketli_giris(form, "Stok (İlk Giriş):", 1, 4, 10)
        self.e_urun_kritik = etiketli_giris(form, "Kritik Stok:", 2, 0, 10, "5")
        
        btns = ttk.Frame(form)
        btns.grid(row=2, column=2, columnspan=4, pady=5, sticky="w")
        ttk.Button(btns, text="➕ Yeni Ürün Ekle", command=self.urun_ekle_tik).pack(side="left", padx=3)
        ttk.Button(btns, text="💾 Seçiliyi Güncelle", command=self.urun_guncelle_tik).pack(side="left", padx=3)
        ttk.Button(btns, text="🧹 Formu Temizle", command=self.urun_form_temizle).pack(side="left", padx=3)

        arama = ttk.Frame(f)
        arama.pack(fill="x", padx=8)
        ttk.Label(arama, text="Ürün veya Barkod Ara:").pack(side="left")
        self.e_urun_arama = ttk.Entry(arama, width=30)
        self.e_urun_arama.pack(side="left", padx=5)
        self.e_urun_arama.bind("<KeyRelease>", lambda e: self.yenile())

        self.t_urun, f_urun = tablo_olustur(f, [
            ("barkod", "Barkod", 110), ("ad", "Ürün Adı", 230), ("kategori", "Kategori", 90), 
            ("alis", "Alış (TL)", 80), ("fiyat", "Satış (TL)", 80), ("stok", "Stok", 70), 
            ("kritik", "Kritik", 65), ("durum", "Durum", 90)], 11)
        
        self.t_urun.tag_configure("az", background="#ffcccc")
        self.t_urun.bind("<<TreeviewSelect>>", self.urun_secildi)
        f_urun.pack(fill="both", expand=True, padx=8, pady=8)

        alt = ttk.Frame(f)
        alt.pack(pady=(0, 8))
        ttk.Label(alt, text="Seçili ürüne mal girişi - adet:").pack(side="left")
        self.e_stok_giris = ttk.Entry(alt, width=10)
        self.e_stok_giris.pack(side="left", padx=5)
        ttk.Button(alt, text="Stok Ekle", command=self.stok_ekle_tik).pack(side="left", padx=3)
        ttk.Button(alt, text="🗑️ Seçiliyi Listeden Kaldır", command=self.urun_sil_tik).pack(side="left", padx=25)

    def urun_secili_id(self):
        secili = self.t_urun.selection()
        return int(secili[0]) if secili else None

    def urun_secildi(self, _olay=None):
        uid = self.urun_secili_id()
        if uid is None:
            return
        for u in urunleri_getir(sadece_aktif=False):
            if u[0] == uid:
                self.duzenlenen_urun_id = uid
                self.e_urun_barkod.delete(0, "end"); self.e_urun_barkod.insert(0, u[1] if u[1] else "")
                self.e_urun_ad.delete(0, "end"); self.e_urun_ad.insert(0, u[2])
                self.c_urun_kategori.set(u[3])
                self.e_urun_alis.delete(0, "end"); self.e_urun_alis.insert(0, f"{u[4]:g}")
                self.e_urun_fiyat.delete(0, "end"); self.e_urun_fiyat.insert(0, f"{u[5]:g}")
                self.e_urun_kritik.delete(0, "end"); self.e_urun_kritik.insert(0, f"{u[7]:g}")
                break

    def urun_form_temizle(self):
        self.duzenlenen_urun_id = None
        for kutu in (self.e_urun_barkod, self.e_urun_ad, self.e_urun_alis, self.e_urun_fiyat, self.e_urun_stok, self.e_urun_kritik):
            kutu.delete(0, "end")
        self.c_urun_kategori.set("Elektrik")

    def urun_ekle_tik(self):
        ok, mesaj = urun_ekle(self.e_urun_barkod.get(), self.e_urun_ad.get(), self.c_urun_kategori.get(),
                              self.e_urun_alis.get() or "0", self.e_urun_fiyat.get(),
                              self.e_urun_stok.get() or "0", self.e_urun_kritik.get())
        if not ok:
            messagebox.showwarning("Hata", mesaj)
            return
        self.urun_form_temizle()
        self.yenile()

    def urun_guncelle_tik(self):
        if self.duzenlenen_urun_id is None:
            messagebox.showwarning("Seçim yok", "Önce listeden bir ürün seçin.")
            return
        ok, mesaj = urun_guncelle(self.duzenlenen_urun_id, self.e_urun_barkod.get(), self.e_urun_ad.get(), self.c_urun_kategori.get(),
                                  self.e_urun_alis.get() or "0", self.e_urun_fiyat.get(), self.e_urun_kritik.get())
        if not ok:
            messagebox.showwarning("Hata", mesaj)
            return
        self.urun_form_temizle()
        self.yenile()

    def stok_ekle_tik(self):
        uid = self.urun_secili_id()
        if uid is None:
            messagebox.showwarning("Seçim yok", "Önce listeden bir ürün seçin.")
            return
        ok, mesaj = stok_ekle(uid, self.e_stok_giris.get())
        if ok:
            self.e_stok_giris.delete(0, "end")
            self.yenile()
        else:
            messagebox.showwarning("Hata", mesaj)

    def urun_sil_tik(self):
        uid = self.urun_secili_id()
        if uid is None:
            messagebox.showwarning("Seçim yok", "Önce listeden bir ürün seçin.")
            return
        if messagebox.askyesno("Onay", "Bu ürünü listeden kaldırmak istediğine emin misin?\n(Geçmiş satışlar etkilenmez.)"):
            urun_sil(uid)
            self.urun_form_temizle()
            self.yenile()

    # ---------------- Satış sekmesi ----------------
    def satis_sekmesi_kur(self):
        f = self.s_satis
        form = ttk.LabelFrame(f, text="Sepete Ürün Ekle")
        form.pack(fill="x", padx=8, pady=8)
        
        ttk.Label(form, text="Ürün Seç:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.c_urun = ttk.Combobox(form, state="readonly", width=55)
        self.c_urun.grid(row=0, column=1, padx=5, sticky="w")
        self.e_adet = etiketli_giris(form, "Adet:", 0, 2, 8, "1")
        ttk.Button(form, text="🛒 Sepete Ekle", command=self.sepete_ekle_tik).grid(row=0, column=4, padx=10)

        self.t_sepet, f_sepet = tablo_olustur(f, [
            ("urun", "Ürün", 320), ("adet", "Adet", 80), ("fiyat", "Birim Fiyat", 120),
            ("toplam", "Tutar (TL)", 120)], 4)
        f_sepet.pack(fill="x", padx=8, pady=(0, 4))

        odeme_cubugu = ttk.Frame(f)
        odeme_cubugu.pack(fill="x", padx=8, pady=4)
        ttk.Button(odeme_cubugu, text="Seçili Satırı Sepetten Çıkar", command=self.sepetten_cikar_tik).pack(side="left")
        
        ttk.Label(odeme_cubugu, text="   Ödeme Tipi:").pack(side="left")
        self.c_odeme = ttk.Combobox(odeme_cubugu, state="readonly", width=12, values=["Nakit", "Kredi Kartı", "Veresiye"])
        self.c_odeme.set("Nakit")
        self.c_odeme.pack(side="left", padx=5)
        
        ttk.Label(odeme_cubugu, text="Müşteri (Veresiye):").pack(side="left")
        self.c_musteri = ttk.Combobox(odeme_cubugu, state="readonly", width=22)
        self.c_musteri.pack(side="left", padx=5)
        
        self.l_sepet_toplam = ttk.Label(odeme_cubugu, text="Toplam: 0.00 TL", font=("Helvetica", 12, "bold"))
        self.l_sepet_toplam.pack(side="left", padx=15)
        ttk.Button(odeme_cubugu, text="✅ Satışı Tamamla", command=self.satis_tamamla_tik).pack(side="right")

        self.l_bugun = ttk.Label(f, text="", font=("Helvetica", 11, "bold"))
        self.l_bugun.pack(anchor="w", padx=10, pady=(8, 0))
        
        self.t_satis, f_satis = tablo_olustur(f, [
            ("saat", "Saat", 60), ("barkod", "Barkod", 100), ("urun", "Ürün", 200), ("adet", "Adet", 60),
            ("toplam", "Tutar (TL)", 90), ("odeme", "Ödeme", 90), ("musteri", "Müşteri", 140),
            ("durum", "Durum", 80)], 8)
        self.t_satis.tag_configure("iptal", foreground="#aaaaaa")
        f_satis.pack(fill="both", expand=True, padx=8, pady=8)
        
        alt_satis = ttk.Frame(f)
        alt_satis.pack(pady=(0, 8))
        ttk.Button(alt_satis, text="❌ Seçili Satışı İptal Et", command=self.satis_iptal_tik).pack(side="left", padx=5)
        ttk.Button(alt_satis, text="📄 Bugünün Satışlarını CSV'ye Aktar", command=self.satis_csv_tik).pack(side="left", padx=5)

    def sepete_ekle_tik(self):
        secim = self.c_urun.get()
        if secim not in self.urun_map:
            messagebox.showwarning("Eksik bilgi", "Lütfen listeden bir ürün seçin.")
            return
        adet = sayiya_cevir(self.e_adet.get())
        if adet is None or adet <= 0:
            messagebox.showwarning("Hata", "Adet 0'dan büyük bir sayı olmalı.")
            return
        uid, ad, fiyat = self.urun_map[secim]
        self.sepet.append({"urun_id": uid, "ad": ad, "adet": adet, "birim_fiyat": fiyat})
        self.sepeti_goster()

    def sepetten_cikar_tik(self):
        secili = self.t_sepet.selection()
        if not secili:
            return
        for iid in reversed(secili):  # Güvenli silme işlemi
            self.sepet.pop(int(iid))
        self.sepeti_goster()

    def sepeti_goster(self):
        self.t_sepet.delete(*self.t_sepet.get_children())
        toplam = 0
        for i, k in enumerate(self.sepet):
            satir_toplam = k["adet"] * k["birim_fiyat"]
            toplam += satir_toplam
            self.t_sepet.insert("", "end", iid=str(i),
                                values=(k["ad"], f"{k['adet']:g}", f"{k['birim_fiyat']:.2f}", f"{satir_toplam:.2f}"))
        self.l_sepet_toplam.config(text=f"Toplam: {toplam:.2f} TL")

    def satis_tamamla_tik(self):
        musteri_id = self.musteri_map.get(self.c_musteri.get())
        ok, mesaj = satis_tamamla(self.sepet, self.c_odeme.get(), musteri_id)
        if ok:
            messagebox.showinfo("Başarılı", mesaj)
            self.sepet = []
            self.sepeti_goster()
            self.yenile()
        else:
            messagebox.showwarning("Satış yapılamadı", mesaj)

    def satis_iptal_tik(self):
        secili = self.t_satis.selection()
        if not secili:
            messagebox.showwarning("Seçim yok", "Önce listeden bir satış seçin.")
            return
        if messagebox.askyesno("Onay", "Bu satışı iptal etmek istediğinize emin misiniz?\nÜrün stoğa geri eklenecektir."):
            ok, mesaj = satis_iptal_et(int(secili[0]))
            if not ok:
                messagebox.showwarning("Hata", mesaj)
            self.yenile()

    def satis_csv_tik(self):
        yol = satislari_csv_aktar(self.bugun)
        messagebox.showinfo("Dışa aktarıldı", f"Bugünün satışları kaydedildi:\n{yol}")

    # ---------------- Müşteriler / Veresiye sekmesi ----------------
    def musteri_sekmesi_kur(self):
        f = self.s_musteri
        form = ttk.LabelFrame(f, text="Yeni Müşteri Kaydı")
        form.pack(fill="x", padx=8, pady=8)
        self.e_m_ad = etiketli_giris(form, "Ad Soyad:", 0, 0, 28)
        self.e_m_tel = etiketli_giris(form, "Telefon:", 0, 2, 16)
        ttk.Button(form, text="➕ Müşteriyi Ekle", command=self.musteri_ekle_tik).grid(row=0, column=4, padx=10)

        arama = ttk.Frame(f)
        arama.pack(fill="x", padx=8)
        ttk.Label(arama, text="Müşteri ara:").pack(side="left")
        self.e_musteri_arama = ttk.Entry(arama, width=25)
        self.e_musteri_arama.pack(side="left", padx=5)
        self.e_musteri_arama.bind("<KeyRelease>", lambda e: self.yenile())

        self.t_musteri, f_musteri = tablo_olustur(f, [
            ("ad", "Müşteri Adı", 280), ("tel", "Telefon", 160), ("borc", "Güncel Kalan Borç (TL)", 160)], 11)
        self.t_musteri.tag_configure("borclu", background="#fff3cd")
        f_musteri.pack(fill="both", expand=True, padx=8, pady=8)

        alt = ttk.Frame(f)
        alt.pack(pady=(0, 8))
        ttk.Label(alt, text="Seçili Müşteriden Ödeme Al - Tutar (TL):").pack(side="left")
        self.e_odeme = ttk.Entry(alt, width=12)
        self.e_odeme.pack(side="left", padx=5)
        ttk.Button(alt, text="💳 Ödemeyi Kaydet", command=self.odeme_tik).pack(side="left", padx=3)
        ttk.Button(alt, text="📜 Hesap Ekstresini Görüntüle", command=self.ekstre_goster_tik).pack(side="left", padx=15)
        ttk.Button(alt, text="📄 Borç Listesini CSV'ye Aktar", command=self.borc_csv_tik).pack(side="left", padx=3)

    def musteri_secili_id(self):
        secili = self.t_musteri.selection()
        return int(secili[0]) if secili else None

    def musteri_ekle_tik(self):
        ok, mesaj = musteri_ekle(self.e_m_ad.get(), self.e_m_tel.get())
        if not ok:
            messagebox.showwarning("Hata", mesaj)
            return
        self.e_m_ad.delete(0, "end"); self.e_m_tel.delete(0, "end")
        self.yenile()

    def odeme_tik(self):
        mid = self.musteri_secili_id()
        if mid is None:
            messagebox.showwarning("Seçim yok", "Önce listeden bir müşteri seçin.")
            return
        ok, mesaj = odeme_al(mid, self.e_odeme.get())
        if ok:
            messagebox.showinfo("Başarılı", mesaj)
            self.e_odeme.delete(0, "end")
            self.yenile()
        else:
            messagebox.showwarning("Hata", mesaj)

    def borc_csv_tik(self):
        yol = borc_listesi_csv_aktar()
        messagebox.showinfo("Dışa aktarıldı", f"Borç listesi kaydedildi:\n{yol}")

    def ekstre_goster_tik(self):
        mid = self.musteri_secili_id()
        if mid is None:
            messagebox.showwarning("Seçim yok", "Lütfen detaylarını görmek istediğiniz müşteriyi seçin.")
            return
        musteri_adi = next((m[1] for m in musterileri_getir() if m[0] == mid), "")
        
        pencere = tk.Toplevel(self)
        pencere.title(f"Hesap Ekstresi - {musteri_adi}")
        pencere.geometry("600x450")
        
        ttk.Label(pencere, text=f"{musteri_adi} - Hesap Hareketleri", font=("Helvetica", 12, "bold")).pack(pady=8)
        
        tablo, f_tablo = tablo_olustur(pencere, [
            ("tarih", "Tarih", 150), ("aciklama", "Açıklama", 250), ("tutar", "Tutar (TL)", 120)], 14)
        f_tablo.pack(fill="both", expand=True, padx=8, pady=8)
        
        for tarih, aciklama, tutar in musteri_hareketleri(mid):
            isaret = "+" if tutar > 0 else ("-" if tutar < 0 else "")
            tablo.insert("", "end", values=(tarih, aciklama, f"{isaret}{abs(tutar):.2f}"))
            
        ttk.Label(pencere, text=f"Güncel Kalan Borç: {musteri_borcu(mid):.2f} TL",
                  font=("Helvetica", 11, "bold")).pack(pady=10)

    # ---------------- Bilgisayar Servisi sekmesi ----------------
    def servis_sekmesi_kur(self):
        f = self.s_servis
        form = ttk.LabelFrame(f, text="Yeni Servis / Tamir Kaydı")
        form.pack(fill="x", padx=8, pady=8)
        
        ttk.Label(form, text="Müşteri (Opsiyonel):").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.c_servis_musteri = ttk.Combobox(form, state="readonly", width=28)
        self.c_servis_musteri.grid(row=0, column=1, padx=5, sticky="w")
        self.e_cihaz = etiketli_giris(form, "Cihaz Marka/Model:", 0, 2, 24)
        
        ttk.Label(form, text="Arıza / Şikayet:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.e_sikayet = ttk.Entry(form, width=50)
        self.e_sikayet.grid(row=1, column=1, columnspan=2, padx=5, sticky="w")
        
        self.e_servis_ucret = etiketli_giris(form, "Tahmini Ücret (TL):", 1, 3, 10, "0")
        ttk.Button(form, text="➕ Kaydı Oluştur", command=self.servis_ekle_tik).grid(row=1, column=4, padx=10)

        self.t_servis, f_servis = tablo_olustur(f, [
            ("tarih", "Tarih", 130), ("musteri", "Müşteri", 150), ("cihaz", "Cihaz", 160),
            ("sikayet", "Arıza", 220), ("ucret", "Ücret (TL)", 90), ("durum", "Durum", 120)], 12)
        self.t_servis.tag_configure("tamamlandi", background="#d4edda")
        f_servis.pack(fill="both", expand=True, padx=8, pady=8)

        alt = ttk.Frame(f)
        alt.pack(pady=(0, 8))
        ttk.Label(alt, text="Seçili Kaydın Durumunu Değiştir:").pack(side="left")
        self.c_servis_durum = ttk.Combobox(alt, state="readonly", width=18, values=DURUMLAR)
        self.c_servis_durum.pack(side="left", padx=5)
        ttk.Button(alt, text="🔄 Durumu Güncelle", command=self.servis_durum_tik).pack(side="left", padx=5)
        ttk.Button(alt, text="📄 Servis Listesini CSV'ye Aktar", command=self.servis_csv_tik).pack(side="left", padx=25)

    def servis_ekle_tik(self):
        musteri_id = self.musteri_map.get(self.c_servis_musteri.get())
        ok, mesaj = servis_ekle(musteri_id, self.e_cihaz.get(), self.e_sikayet.get(), self.e_servis_ucret.get())
        if not ok:
            messagebox.showwarning("Hata", mesaj)
            return
        self.e_cihaz.delete(0, "end"); self.e_sikayet.delete(0, "end")
        self.e_servis_ucret.delete(0, "end"); self.e_servis_ucret.insert(0, "0")
        self.yenile()

    def servis_durum_tik(self):
        secili = self.t_servis.selection()
        if not secili:
            messagebox.showwarning("Seçim yok", "Önce listeden bir kayıt seçin.")
            return
        if not self.c_servis_durum.get():
            messagebox.showwarning("Eksik bilgi", "Lütfen güncellenecek yeni durumu seçin.")
            return
        servis_durum_guncelle(int(secili[0]), self.c_servis_durum.get())
        self.yenile()

    def servis_csv_tik(self):
        yol = servisleri_csv_aktar()
        messagebox.showinfo("Dışa aktarıldı", f"Servis listesi kaydedildi:\n{yol}")

    # ---------------- Rapor sekmesi ----------------
    def rapor_sekmesi_kur(self):
        f = self.s_rapor
        ust = ttk.Frame(f)
        ust.pack(padx=8, pady=15)
        ttk.Label(ust, text="Tarih Filtresi (YYYY-AA-GG):").pack(side="left")
        self.e_rapor = ttk.Entry(ust, width=14)
        self.e_rapor.insert(0, self.bugun)
        self.e_rapor.pack(side="left", padx=5)
        ttk.Button(ust, text="🔍 Raporu Getir", command=self.rapor_goster).pack(side="left")
        ttk.Button(ust, text="💾 Veritabanını Güvenli Yedekle", command=self.yedek_al_tik).pack(side="left", padx=30)

        self.l_rapor = ttk.Label(f, text="", font=("Helvetica", 12))
        self.l_rapor.pack(pady=10)

        ttk.Label(f, text="⚠️ Stoğu Azalan Ürünler (Kritik Seviyedekiler):", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=10, pady=(15, 0))
        self.t_azalan, f_azalan = tablo_olustur(f, [
            ("barkod", "Barkod", 120), ("ad", "Ürün", 380), ("stok", "Kalan Stok", 120), ("kritik", "Kritik Eşik", 120)], 8)
        f_azalan.pack(fill="both", expand=True, padx=8, pady=8)

    def rapor_goster(self):
        toplam, nakit, veresiye, tahsilat, kar = gunluk_ozet(self.e_rapor.get().strip())
        rapor_metni = (
            f"💰 Toplam Günlük Satış: {toplam:.2f} TL      |      📈 Tahmini Kâr: {kar:.2f} TL\n\n"
            f"💵 Nakit/Kart Alınan: {nakit:.2f} TL    |    📝 Veresiye Yazılan: {veresiye:.2f} TL\n\n"
            f"🤝 Geçmişe Dönük O Gün Tahsil Edilen Borç: {tahsilat:.2f} TL"
        )
        self.l_rapor.config(text=rapor_metni)

    def yedek_al_tik(self):
        hedef = yedek_al()
        messagebox.showinfo("Yedekleme Başarılı", f"Sistemin tam yedeği alındı:\n{hedef}")

    # ---------------- Ortak ----------------
    def yenile(self):
        # 1. Ürünleri Yenile
        urunler = urunleri_getir(sadece_aktif=False, arama=self.e_urun_arama.get())
        self.t_urun.delete(*self.t_urun.get_children())
        for u in urunler:
            # u: id, barkod, ad, kategori, alis, satis, stok, kritik, aktif
            az = u[6] <= u[7] and u[8]
            durum = "Pasif" if not u[8] else ("AZALDI!" if az else "Yeterli")
            self.t_urun.insert("", "end", iid=str(u[0]),
                               values=(u[1] if u[1] else "-", u[2], u[3], f"{u[4]:.2f}", f"{u[5]:.2f}", f"{u[6]:g}", f"{u[7]:g}", durum),
                               tags=("az",) if az else ())

        aktif_urunler = [u for u in urunler if u[8]]
        self.urun_map = {f"[{u[1] if u[1] else '-'}] {u[2]} - {u[5]:.2f} TL (Stok: {u[6]:g})": (u[0], u[2], u[5])
                         for u in aktif_urunler}
        self.c_urun["values"] = list(self.urun_map.keys())

        # 2. Müşterileri Yenile[cite: 1]
        musteriler = musterileri_getir(arama=self.e_musteri_arama.get() if hasattr(self, "e_musteri_arama") else "")
        self.t_musteri.delete(*self.t_musteri.get_children())
        for m in musteriler:
            self.t_musteri.insert("", "end", iid=str(m[0]),
                                  values=(m[1], m[2], f"{m[3]:.2f}"),
                                  tags=("borclu",) if m[3] > 0.001 else ())
        self.musteri_map = {f"{m[1]} (#{m[0]})": m[0] for m in musteriler}
        self.c_musteri["values"] = list(self.musteri_map.keys())
        self.c_servis_musteri["values"] = list(self.musteri_map.keys())

        # 3. Satışları Yenile[cite: 1]
        self.t_satis.delete(*self.t_satis.get_children())
        for s in gunun_satislari(self.bugun):
            self.t_satis.insert("", "end", iid=str(s[0]),
                                values=(s[1], s[2] if s[2] else "-", s[3], f"{s[4]:g}", f"{s[5]:.2f}", s[6], s[7],
                                        "İPTAL" if s[8] else "Geçerli"),
                                tags=("iptal",) if s[8] else ())
        toplam = gunluk_ozet(self.bugun)[0]
        self.l_bugun.config(text=f"Bugünkü Toplam Satış Hacmi: {toplam:.2f} TL")

        # 4. Servisleri Yenile[cite: 1]
        self.t_servis.delete(*self.t_servis.get_children())
        for s in servisleri_getir():
            self.t_servis.insert("", "end", iid=str(s[0]),
                                 values=(s[1], s[2], s[3], s[4], f"{s[5]:.2f}", s[6]),
                                 tags=("tamamlandi",) if s[6] in ("Tamamlandı", "Teslim Edildi") else ())

        # 5. Rapor & Azalanları Yenile[cite: 1]
        self.t_azalan.delete(*self.t_azalan.get_children())
        for a in azalan_urunler():
            self.t_azalan.insert("", "end", values=(a[0] if a[0] else "-", a[1], f"{a[2]:g}", f"{a[3]:g}"))
        self.rapor_goster()

if __name__ == "__main__":
    tablolari_olustur()
    Uygulama().mainloop()