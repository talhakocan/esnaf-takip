"""
Elektrik-Elektronik Dükkânı Takip Programı
Mesleki Çözümleme dersi projesi

Özellikler: Stok takibi + Satış + Veresiye (müşteri borç defteri) + Günlük rapor
Kullanılan teknolojiler (Python ile birlikte gelir, ekstra kurulum yok):
  - tkinter : pencere ve butonlar
  - sqlite3 : veritabanı (dukkan.db dosyası otomatik oluşur)
"""

import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

DB_ADI = "dukkan.db"


# ======================================================================
# 1) VERİTABANI KATMANI (arayüzden bağımsız, tek başına test edilebilir)
# ======================================================================

def baglan():
    return sqlite3.connect(DB_ADI)


def sayiya_cevir(metin):
    """'12,5' ya da '12.5' yazısını sayıya çevirir. Olmazsa None döner."""
    try:
        return float(str(metin).strip().replace(",", "."))
    except ValueError:
        return None


def tablolari_olustur():
    with baglan() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS urun (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ad          TEXT NOT NULL,
                birim_fiyat REAL NOT NULL,
                stok        REAL NOT NULL,
                kritik_stok REAL NOT NULL      -- bu sayının altına inince uyarı verilir
            );
            CREATE TABLE IF NOT EXISTS musteri (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ad      TEXT NOT NULL,
                telefon TEXT
            );
            CREATE TABLE IF NOT EXISTS satis (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih       TEXT NOT NULL,      -- 2026-10-05 14:30
                musteri_id  INTEGER REFERENCES musteri(id),   -- nakit satışta boş kalır
                urun_id     INTEGER NOT NULL REFERENCES urun(id),
                adet        REAL NOT NULL,
                birim_fiyat REAL NOT NULL,      -- satış anındaki fiyat
                toplam      REAL NOT NULL,
                odeme_turu  TEXT NOT NULL       -- 'Nakit' veya 'Veresiye'
            );
            CREATE TABLE IF NOT EXISTS odeme (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                musteri_id INTEGER NOT NULL REFERENCES musteri(id),
                tarih      TEXT NOT NULL,
                tutar      REAL NOT NULL
            );
        """)
        # Deneme için birkaç örnek ürün (tablo boşsa)
        if db.execute("SELECT COUNT(*) FROM urun").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO urun (ad, birim_fiyat, stok, kritik_stok) VALUES (?, ?, ?, ?)",
                [
                    ("Topraklı Priz", 45, 50, 10),
                    ("Sigorta 16A", 60, 30, 10),
                    ("NYA 1.5mm Kablo (metre)", 12, 200, 50),
                    ("LED Ampul 9W", 35, 40, 10),
                ],
            )


# ---------------- Ürün / Stok ----------------

def urun_ekle(ad, fiyat, stok, kritik):
    ad = ad.strip()
    fiyat, stok, kritik = sayiya_cevir(fiyat), sayiya_cevir(stok), sayiya_cevir(kritik)
    if not ad:
        return False, "Ürün adı boş olamaz."
    if None in (fiyat, stok, kritik) or fiyat < 0 or stok < 0 or kritik < 0:
        return False, "Fiyat, stok ve kritik stok sayı olmalı (0 ya da daha büyük)."
    with baglan() as db:
        db.execute(
            "INSERT INTO urun (ad, birim_fiyat, stok, kritik_stok) VALUES (?, ?, ?, ?)",
            (ad, fiyat, stok, kritik))
    return True, "Ürün eklendi."


def urunleri_getir():
    with baglan() as db:
        return db.execute(
            "SELECT id, ad, birim_fiyat, stok, kritik_stok FROM urun ORDER BY ad").fetchall()


def stok_ekle(urun_id, adet):
    """Toptancıdan mal geldiğinde stoğu artırır."""
    adet = sayiya_cevir(adet)
    if adet is None or adet <= 0:
        return False, "Adet 0'dan büyük bir sayı olmalı."
    with baglan() as db:
        db.execute("UPDATE urun SET stok = stok + ? WHERE id = ?", (adet, urun_id))
    return True, "Stok güncellendi."


def azalan_urunler():
    """Stoğu kritik seviyenin altına inen (sipariş verilmesi gereken) ürünler."""
    with baglan() as db:
        return db.execute(
            "SELECT ad, stok, kritik_stok FROM urun WHERE stok <= kritik_stok ORDER BY ad"
        ).fetchall()


# ---------------- Satış ----------------

def satis_yap(urun_id, adet, odeme_turu, musteri_id):
    """Satışı kaydeder ve stoktan düşer. (basarili_mi, mesaj) döndürür."""
    adet = sayiya_cevir(adet)
    if adet is None or adet <= 0:
        return False, "Adet 0'dan büyük bir sayı olmalı."
    if odeme_turu == "Veresiye" and musteri_id is None:
        return False, "Veresiye satış için müşteri seçmelisin."

    with baglan() as db:
        urun = db.execute(
            "SELECT ad, birim_fiyat, stok FROM urun WHERE id = ?", (urun_id,)).fetchone()
        if adet > urun[2]:
            return False, f"Yetersiz stok! Elde {urun[2]:g} adet var."
        toplam = adet * urun[1]
        db.execute(
            """INSERT INTO satis (tarih, musteri_id, urun_id, adet, birim_fiyat, toplam, odeme_turu)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().strftime("%Y-%m-%d %H:%M"),
             musteri_id if odeme_turu == "Veresiye" else None,
             urun_id, adet, urun[1], toplam, odeme_turu))
        db.execute("UPDATE urun SET stok = stok - ? WHERE id = ?", (adet, urun_id))
    return True, f"{urun[0]} x {adet:g} = {toplam:.2f} TL ({odeme_turu})"


def gunun_satislari(tarih):
    with baglan() as db:
        return db.execute(
            """SELECT s.id, substr(s.tarih, 12, 5), u.ad, s.adet, s.toplam,
                      s.odeme_turu, COALESCE(m.ad, '-')
               FROM satis s
               JOIN urun u ON u.id = s.urun_id
               LEFT JOIN musteri m ON m.id = s.musteri_id
               WHERE substr(s.tarih, 1, 10) = ?
               ORDER BY s.tarih""", (tarih,)).fetchall()


def gunluk_ozet(tarih):
    """(toplam satış, nakit, veresiye yazılan, veresiye tahsilatı) döndürür."""
    with baglan() as db:
        toplam, nakit, veresiye = db.execute(
            """SELECT COALESCE(SUM(toplam), 0),
                      COALESCE(SUM(CASE WHEN odeme_turu = 'Nakit'    THEN toplam END), 0),
                      COALESCE(SUM(CASE WHEN odeme_turu = 'Veresiye' THEN toplam END), 0)
               FROM satis WHERE substr(tarih, 1, 10) = ?""", (tarih,)).fetchone()
        tahsilat = db.execute(
            "SELECT COALESCE(SUM(tutar), 0) FROM odeme WHERE substr(tarih, 1, 10) = ?",
            (tarih,)).fetchone()[0]
    return toplam, nakit, veresiye, tahsilat


# ---------------- Müşteri / Veresiye ----------------

def musteri_ekle(ad, telefon):
    ad = ad.strip()
    if not ad:
        return False, "Müşteri adı boş olamaz."
    with baglan() as db:
        db.execute("INSERT INTO musteri (ad, telefon) VALUES (?, ?)", (ad, telefon.strip()))
    return True, "Müşteri eklendi."


def musterileri_getir():
    """(id, ad, telefon, borç) döndürür.
    Borç = veresiye yapılan satışların toplamı - müşterinin yaptığı ödemeler"""
    with baglan() as db:
        return db.execute(
            """SELECT m.id, m.ad, m.telefon,
                 COALESCE((SELECT SUM(toplam) FROM satis
                           WHERE musteri_id = m.id AND odeme_turu = 'Veresiye'), 0)
               - COALESCE((SELECT SUM(tutar) FROM odeme WHERE musteri_id = m.id), 0)
               FROM musteri m ORDER BY m.ad""").fetchall()


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


# ======================================================================
# 2) ARAYÜZ KATMANI
# ======================================================================

def etiketli_giris(ust, etiket, satir, sutun, genislik=15, varsayilan=""):
    """Yanında yazısı olan bir giriş kutusu oluşturur."""
    ttk.Label(ust, text=etiket).grid(row=satir, column=sutun, padx=5, pady=5, sticky="e")
    kutu = ttk.Entry(ust, width=genislik)
    kutu.insert(0, varsayilan)
    kutu.grid(row=satir, column=sutun + 1, padx=5, sticky="w")
    return kutu


def tablo_olustur(ust, kolonlar, yukseklik=10):
    """kolonlar: [(anahtar, başlık, genişlik), ...]"""
    t = ttk.Treeview(ust, columns=[k[0] for k in kolonlar], show="headings", height=yukseklik)
    for anahtar, baslik, genislik in kolonlar:
        t.heading(anahtar, text=baslik)
        t.column(anahtar, width=genislik)
    return t


class Uygulama(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Dükkân Takip Programı")
        self.geometry("900x620")
        self.bugun = datetime.now().strftime("%Y-%m-%d")
        self.urun_map = {}      # combobox yazısı -> ürün id
        self.musteri_map = {}   # combobox yazısı -> müşteri id

        sekmeler = ttk.Notebook(self)
        sekmeler.pack(fill="both", expand=True, padx=8, pady=8)
        self.s_stok = ttk.Frame(sekmeler)
        self.s_satis = ttk.Frame(sekmeler)
        self.s_musteri = ttk.Frame(sekmeler)
        self.s_rapor = ttk.Frame(sekmeler)
        sekmeler.add(self.s_stok, text="Stok")
        sekmeler.add(self.s_satis, text="Satış")
        sekmeler.add(self.s_musteri, text="Müşteriler / Veresiye")
        sekmeler.add(self.s_rapor, text="Günlük Rapor")

        self.stok_sekmesi_kur()
        self.satis_sekmesi_kur()
        self.musteri_sekmesi_kur()
        self.rapor_sekmesi_kur()
        self.yenile()

    # ---------------- Stok sekmesi ----------------
    def stok_sekmesi_kur(self):
        f = self.s_stok
        form = ttk.LabelFrame(f, text="Yeni Ürün")
        form.pack(fill="x", padx=8, pady=8)
        self.e_urun_ad = etiketli_giris(form, "Ürün adı:", 0, 0, 30)
        self.e_urun_fiyat = etiketli_giris(form, "Fiyat (TL):", 0, 2, 10)
        self.e_urun_stok = etiketli_giris(form, "Stok:", 1, 0, 10)
        self.e_urun_kritik = etiketli_giris(form, "Kritik stok:", 1, 2, 10, "5")
        ttk.Button(form, text="Ürünü Ekle", command=self.urun_ekle_tik).grid(
            row=1, column=4, padx=10)

        self.t_urun = tablo_olustur(f, [
            ("ad", "Ürün", 300), ("fiyat", "Fiyat (TL)", 100), ("stok", "Stok", 100),
            ("kritik", "Kritik stok", 100), ("durum", "Durum", 120)], 14)
        self.t_urun.tag_configure("az", background="#ffd6d6")
        self.t_urun.pack(fill="both", expand=True, padx=8, pady=8)

        alt = ttk.Frame(f)
        alt.pack(pady=(0, 8))
        ttk.Label(alt, text="Seçili ürüne mal girişi - adet:").pack(side="left")
        self.e_stok_giris = ttk.Entry(alt, width=10)
        self.e_stok_giris.pack(side="left", padx=5)
        ttk.Button(alt, text="Stok Ekle", command=self.stok_ekle_tik).pack(side="left")

    def urun_ekle_tik(self):
        ok, mesaj = urun_ekle(self.e_urun_ad.get(), self.e_urun_fiyat.get(),
                              self.e_urun_stok.get(), self.e_urun_kritik.get())
        if not ok:
            messagebox.showwarning("Hata", mesaj)
            return
        for kutu in (self.e_urun_ad, self.e_urun_fiyat, self.e_urun_stok):
            kutu.delete(0, "end")
        self.yenile()

    def stok_ekle_tik(self):
        secili = self.t_urun.selection()
        if not secili:
            messagebox.showwarning("Seçim yok", "Önce listeden bir ürün seçin.")
            return
        ok, mesaj = stok_ekle(int(secili[0]), self.e_stok_giris.get())
        if ok:
            self.e_stok_giris.delete(0, "end")
            self.yenile()
        else:
            messagebox.showwarning("Hata", mesaj)

    # ---------------- Satış sekmesi ----------------
    def satis_sekmesi_kur(self):
        f = self.s_satis
        form = ttk.LabelFrame(f, text="Yeni Satış")
        form.pack(fill="x", padx=8, pady=8)

        ttk.Label(form, text="Ürün:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.c_urun = ttk.Combobox(form, state="readonly", width=45)
        self.c_urun.grid(row=0, column=1, columnspan=3, padx=5, sticky="w")

        self.e_adet = etiketli_giris(form, "Adet:", 1, 0, 10, "1")
        ttk.Label(form, text="Ödeme:").grid(row=1, column=2, padx=5, sticky="e")
        self.c_odeme = ttk.Combobox(form, state="readonly", width=12, values=["Nakit", "Veresiye"])
        self.c_odeme.set("Nakit")
        self.c_odeme.grid(row=1, column=3, padx=5, sticky="w")

        ttk.Label(form, text="Müşteri (veresiye için):").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.c_musteri = ttk.Combobox(form, state="readonly", width=30)
        self.c_musteri.grid(row=2, column=1, columnspan=2, padx=5, sticky="w")
        ttk.Button(form, text="Satışı Kaydet", command=self.satis_tik).grid(
            row=2, column=3, padx=10)

        self.l_bugun = ttk.Label(f, text="", font=("Arial", 11, "bold"))
        self.l_bugun.pack(anchor="w", padx=10)
        self.t_satis = tablo_olustur(f, [
            ("saat", "Saat", 70), ("urun", "Ürün", 260), ("adet", "Adet", 70),
            ("toplam", "Tutar (TL)", 100), ("odeme", "Ödeme", 90), ("musteri", "Müşteri", 180)], 12)
        self.t_satis.pack(fill="both", expand=True, padx=8, pady=8)

    def satis_tik(self):
        urun_id = self.urun_map.get(self.c_urun.get())
        if urun_id is None:
            messagebox.showwarning("Eksik bilgi", "Lütfen bir ürün seçin.")
            return
        ok, mesaj = satis_yap(urun_id, self.e_adet.get(), self.c_odeme.get(),
                              self.musteri_map.get(self.c_musteri.get()))
        if ok:
            messagebox.showinfo("Satış kaydedildi", mesaj)
            self.e_adet.delete(0, "end")
            self.e_adet.insert(0, "1")
            self.yenile()
        else:
            messagebox.showwarning("Satış yapılamadı", mesaj)

    # ---------------- Müşteriler / Veresiye sekmesi ----------------
    def musteri_sekmesi_kur(self):
        f = self.s_musteri
        form = ttk.LabelFrame(f, text="Yeni Müşteri")
        form.pack(fill="x", padx=8, pady=8)
        self.e_m_ad = etiketli_giris(form, "Ad Soyad:", 0, 0, 30)
        self.e_m_tel = etiketli_giris(form, "Telefon:", 0, 2, 18)
        ttk.Button(form, text="Müşteriyi Ekle", command=self.musteri_ekle_tik).grid(
            row=0, column=4, padx=10)

        self.t_musteri = tablo_olustur(f, [
            ("ad", "Müşteri", 300), ("tel", "Telefon", 160), ("borc", "Kalan Borç (TL)", 140)], 14)
        self.t_musteri.tag_configure("borclu", background="#fff2cc")
        self.t_musteri.pack(fill="both", expand=True, padx=8, pady=8)

        alt = ttk.Frame(f)
        alt.pack(pady=(0, 8))
        ttk.Label(alt, text="Seçili müşteriden ödeme al - tutar (TL):").pack(side="left")
        self.e_odeme = ttk.Entry(alt, width=12)
        self.e_odeme.pack(side="left", padx=5)
        ttk.Button(alt, text="Ödemeyi Kaydet", command=self.odeme_tik).pack(side="left")

    def musteri_ekle_tik(self):
        ok, mesaj = musteri_ekle(self.e_m_ad.get(), self.e_m_tel.get())
        if not ok:
            messagebox.showwarning("Hata", mesaj)
            return
        self.e_m_ad.delete(0, "end")
        self.e_m_tel.delete(0, "end")
        self.yenile()

    def odeme_tik(self):
        secili = self.t_musteri.selection()
        if not secili:
            messagebox.showwarning("Seçim yok", "Önce listeden bir müşteri seçin.")
            return
        ok, mesaj = odeme_al(int(secili[0]), self.e_odeme.get())
        if ok:
            messagebox.showinfo("Ödeme alındı", mesaj)
            self.e_odeme.delete(0, "end")
            self.yenile()
        else:
            messagebox.showwarning("Hata", mesaj)

    # ---------------- Rapor sekmesi ----------------
    def rapor_sekmesi_kur(self):
        f = self.s_rapor
        ust = ttk.Frame(f)
        ust.pack(padx=8, pady=15)
        ttk.Label(ust, text="Tarih (YYYY-AA-GG):").pack(side="left")
        self.e_rapor = ttk.Entry(ust, width=14)
        self.e_rapor.insert(0, self.bugun)
        self.e_rapor.pack(side="left", padx=5)
        ttk.Button(ust, text="Raporu Göster", command=self.rapor_goster).pack(side="left")

        self.l_rapor = ttk.Label(f, text="", font=("Arial", 12))
        self.l_rapor.pack(pady=5)

        ttk.Label(f, text="Stoğu azalan ürünler (sipariş verilecekler):",
                  font=("Arial", 11, "bold")).pack(anchor="w", padx=10, pady=(15, 0))
        self.t_azalan = tablo_olustur(f, [
            ("ad", "Ürün", 350), ("stok", "Kalan stok", 120), ("kritik", "Kritik stok", 120)], 8)
        self.t_azalan.pack(fill="both", expand=True, padx=8, pady=8)

    def rapor_goster(self):
        toplam, nakit, veresiye, tahsilat = gunluk_ozet(self.e_rapor.get().strip())
        self.l_rapor.config(text=(
            f"Toplam satış: {toplam:.2f} TL\n"
            f"Nakit: {nakit:.2f} TL    Veresiye yazılan: {veresiye:.2f} TL\n"
            f"O gün tahsil edilen veresiye: {tahsilat:.2f} TL"))

    # ---------------- Ortak: ekrandaki her şeyi veritabanından tazele ----------------
    def yenile(self):
        # Ürünler
        urunler = urunleri_getir()
        self.t_urun.delete(*self.t_urun.get_children())
        for u in urunler:
            az = u[3] <= u[4]
            self.t_urun.insert("", "end", iid=str(u[0]),
                               values=(u[1], f"{u[2]:.2f}", f"{u[3]:g}", f"{u[4]:g}",
                                       "AZALDI!" if az else "Yeterli"),
                               tags=("az",) if az else ())
        self.urun_map = {f"{u[1]} (#{u[0]}) - {u[2]:.2f} TL, stok: {u[3]:g}": u[0] for u in urunler}
        self.c_urun["values"] = list(self.urun_map)
        self.c_urun.set("")

        # Müşteriler
        musteriler = musterileri_getir()
        self.t_musteri.delete(*self.t_musteri.get_children())
        for m in musteriler:
            self.t_musteri.insert("", "end", iid=str(m[0]),
                                  values=(m[1], m[2], f"{m[3]:.2f}"),
                                  tags=("borclu",) if m[3] > 0.001 else ())
        self.musteri_map = {f"{m[1]} (#{m[0]})": m[0] for m in musteriler}
        self.c_musteri["values"] = list(self.musteri_map)
        self.c_musteri.set("")

        # Bugünün satışları
        self.t_satis.delete(*self.t_satis.get_children())
        for s in gunun_satislari(self.bugun):
            self.t_satis.insert("", "end", iid=str(s[0]),
                                values=(s[1], s[2], f"{s[3]:g}", f"{s[4]:.2f}", s[5], s[6]))
        toplam = gunluk_ozet(self.bugun)[0]
        self.l_bugun.config(text=f"Bugünkü toplam satış: {toplam:.2f} TL")

        # Rapor sekmesindeki azalan ürünler
        self.t_azalan.delete(*self.t_azalan.get_children())
        for a in azalan_urunler():
            self.t_azalan.insert("", "end", values=(a[0], f"{a[1]:g}", f"{a[2]:g}"))
        self.rapor_goster()


if __name__ == "__main__":
    tablolari_olustur()
    Uygulama().mainloop()
