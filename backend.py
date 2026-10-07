# -*- coding: utf-8 -*-
"""
YEMEK TARİFİ KAZIYICI — backend.py
==================================
Proje 2 dosyadan oluşur:
  backend.py  -> bu dosya: web kazıma (requests + BeautifulSoup) + siteyi çalıştıran sunucu
  index.html  -> sitenin görünen yüzü (tasarım + JavaScript)

Kurulum   : pip install requests beautifulsoup4
Çalıştır  : python backend.py
Sonra     : tarayıcıda http://localhost:8000 kendiliğinden açılır.

---------------------------------------------------------------------
SUNUM İÇİN: VERİ NEREDEN, NASIL ÇEKİLİYOR?
---------------------------------------------------------------------
Hiçbir hazır API (veri servisi) kullanılmıyor. Tüm veriler yemek.com'un
herkese açık sayfalarından WEB KAZIMA (web scraping) ile çekiliyor:

  1) requests      -> sayfanın HTML kodunu indirir (tarayıcının yaptığı gibi).
  2) BeautifulSoup -> o HTML'i okur, istediğimiz etiketleri bulur ve içindeki
                      yazıyı / resim adresini çıkarır.

  Sayfadaki yer (HTML etiketi)                         ->  Tarif nesnesindeki alan
  ---------------------------------------------------      ------------------------
  <h1 class="recipe-headline-main">                    ->  isim
  <meta property="og:description">                     ->  aciklama
  <meta property="og:image">                           ->  foto_url (yemeğin fotoğrafı)
  .breadcrumb-list a  (Ana sayfa > Tarifler > Sebze)   ->  kategori
  .content-recipe-small-infos  (KAÇ KİŞİLİK, SÜRELER)  ->  porsiyon, hazırlık, pişirme
  .recipe-ingredients  h3 + ul > li                    ->  malzeme_gruplari, malzemeler
  .recipe-instructions  ol > li                        ->  yapilis (+ adım fotoğrafları)
  .recipe-sss  h2 + .recipe-seo-body                   ->  puf_noktalari
  .recipe-calorie-box                                  ->  kalori
  .rating-box  (data-initial-average, data-count)      ->  puan, oy_sayisi
  .editor-box a[href*="/profil/"]                      ->  yazar
  .breadcrumb-date                                     ->  yayin_tarihi

  Kullanılan BeautifulSoup fonksiyonları:
    BeautifulSoup(html, "html.parser")  -> HTML'i ağaç yapısına çevirir
    select_one(".sinif") / select(...)  -> CSS seçiciyle etiket bulur
    find("etiket") / find_all(...)      -> etiket adına göre bulur
    get_text()                          -> etiketin içindeki yazıyı verir
    etiket["href"] / etiket.get("src")  -> etiketin özelliğini (link, resim) verir

Aramada kullanılan ~27.000 tariflik liste de sitenin "sitemap" sayfalarından
yine BeautifulSoup ile (find_all("url"), find("loc")) çıkarılıyor.

index.html'in konuştuğu "/api/..." adresleri dış bir API DEĞİLDİR; bu dosyadaki
küçük sunucunun kendi adresleridir (site ile Python kodu arasındaki köprü).
---------------------------------------------------------------------

Nasıl çalışır?
  1) "Yemek adıyla ara" sekmesi: yemeğin adını yazarsın ("karnıyarık"), kod sitemap
     listesinde arar, en iyi eşleşen tarifin sayfasını kazır ve gösterir.
  2) "Elimdekilerle öner" sekmesi: elindeki malzemeleri yazarsın, kod tarif
     sayfalarından kazıdığı malzeme listeleriyle karşılaştırıp yemek önerir.

Her tarif bir "Tarif" nesnesi olarak tutulur.

Program verilerini "veri/" klasöründe tutar (silsen de yeniden oluşur):
  veri/tarif_dizini.json  -> aramada kullanılan tarif listesi (+ öğrenilen malzemeler)
  veri/tarifler.json      -> bulduğun tarifler
  veri/fotograflar/       -> indirilen yemek fotoğrafları

Not: Python'da yorum satırı "#" ile yazılır (JavaScript'teki "//" ile aynı işi görür).
"""

# Python'un kendi modülleri (kurulum gerekmez)
import json
import os
import re
import threading
import time
import warnings
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import robotparser
from urllib.parse import parse_qs, urlparse

# Kurulması gereken kütüphaneler: pip install requests beautifulsoup4
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Sitemap bir XML dosyası; onu da BeautifulSoup'un "html.parser"ı ile okuyoruz
# (ekstra kütüphane gerekmesin diye). Bunun için verdiği uyarıyı gizliyoruz.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


# =====================================================================
#  AYARLAR  — Kodun davranışını buradan değiştirebilirsin
# =====================================================================

# NOT: BENZER TARİF SAYISINI ARTIRMA YERİ
# Bir yemek arandığında, bulunan tarifin yanında kaç tane benzer tarif listelensin?
# Örneğin "karnıyarık" için sitede 6 farklı tarif var; hepsini görmek için sayıyı artır.
BENZER_TARIF_SAYISI = 8

# NOT: BEKLEME SÜRESİ (saniye)
# Her istekten sonra bu kadar beklenir. Siteyi yormamak ve engellenmemek için
# 0.5 saniyenin altına düşürmemek iyi olur.
BEKLEME_SURESI = 0.5

# NOT: FOTOĞRAF AYARLARI
# FOTO_INDIR = False yaparsan fotoğraflar indirilmez, sadece linkleri kaydedilir.
# Fotoğraf, sayfanın <meta property="og:image"> etiketinden alınır (1200x675 boyutunda).
FOTO_INDIR = True
FOTO_KLASORU = "veri/fotograflar"

# NOT: ÇIKTI DOSYASI — bulunan tüm tarifler bu dosyada birikir.
CIKTI_DOSYASI = "veri/tarifler.json"

# NOT: TARİF LİSTESİ (DİZİN) AYARLARI
# İsimle arayabilmek için sitedeki tüm tariflerin adı ve adresi bir kez indirilip
# bu dosyaya kaydedilir (ilk seferde ~30 saniye sürer, sonra anında açılır).
# Liste DIZIN_YENILEME_GUNU günden eskiyse kendiliğinden yeniden indirilir
# (sitedeki yeni tarifler de aranabilsin diye). Hemen yenilemek için dosyayı sil.
DIZIN_DOSYASI = "veri/tarif_dizini.json"
DIZIN_YENILEME_GUNU = 7

# NOT: MALZEMEYLE ÖNERİ AYARLARI
# "Elimdekilerle öner" sekmesinde, her aramada sitede kaç yeni tarifin sayfası açılıp
# malzemesine bakılsın? Sayıyı artırırsan daha çok öneri gelir ama arama uzar
# (her tarif ~1 saniye). Bakılan tarifler kaydedilir; site kullandıkça zenginleşir.
ONERI_TARAMA_SAYISI = 12
# Ekranda en fazla kaç öneri gösterilsin?
ONERI_GOSTERIM_SAYISI = 24

# NOT: EVDE HEP OLAN MALZEMELER
# "Temel malzemeler evde var say" kutusu işaretliyse bunlar eksik sayılmaz.
# Kendi mutfağına göre ekleme/çıkarma yapabilirsin.
TEMEL_MALZEMELER = [
    "tuz", "karabiber", "su", "sıvı yağ", "ayçiçek yağı", "zeytinyağı", "pul biber",
    "toz kırmızı biber", "kimyon", "nane", "kekik", "toz şeker", "şeker", "un",
    "sirke", "kabartma tozu", "karbonat", "vanilin", "tarçın", "yenibahar", "buz",
]

# NOT: EŞ ANLAMLI MALZEMELER
# Tariflerde "tavuk" yerine "but", "göğüs" yazabiliyor. Soldaki malzemeyi yazan kişi,
# sağdakilerden biri geçen tariflerde de o malzemeye sahip sayılır. Yenilerini ekleyebilirsin.
ESANLAMLILAR = {
    "tavuk": ["piliç", "but", "göğüs", "kanat", "baget"],
    "et": ["dana eti", "kuzu eti", "kuşbaşı", "antrikot", "bonfile", "biftek", "pirzola"],
    "peynir": ["kaşar", "lor", "tulum", "mozzarella", "parmesan", "çökelek", "hellim"],
    "kaşar": ["kaşar peyniri"],
    "salça": ["domates salçası", "biber salçası"],
}

# Sitenin adresi (başka bir siteye geçersen burası ve seçiciler değişmeli)
SITE = "https://yemek.com"

# NOT: SİTEMAP ADRESİ
# Sitemap, sitenin "içindekiler" listesidir; arama motorları için hazırlanır ve
# robots.txt ile kazınmasına izin verilir. Sitenin kendi arama sayfası (?q=...)
# robots.txt'de yasak olduğu için onu değil, bu listeyi kullanıyoruz.
SITEMAP_ADRESI = SITE + "/sitemaps/sitemap_index.xml"

# NOT: İSTEK BAŞLIKLARI
# User-Agent ile kim olduğumuzu söylüyoruz; bazı siteler User-Agent'sız istekleri engeller.
BASLIKLAR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TarifKaziyici/1.0",
    "Accept-Language": "tr-TR,tr;q=0.9",
}


# =====================================================================
#  TARİF NESNESİ
# =====================================================================

class Tarif:
    """Bir yemek tarifini temsil eden nesne."""

    def __init__(self, isim, url):
        # --- Temel bilgiler ---
        self.isim = isim                # Yemeğin adı
        self.url = url                  # Tarifin sayfa adresi
        self.malzemeler = []            # Düz liste: ["2 adet yumurta", ...]
        self.malzeme_gruplari = {}      # Gruplu: {"Malzemeler": [...], "2. Grup": [...]}
        self.yapilis = []               # Adım adım yapılış
        self.adim_fotolari = []         # Her adımın fotoğrafı (yoksa "")
        self.puf_noktalari = []         # [{"soru": ..., "cevap": ...}, ...]

        # --- Ekstra bilgiler ---
        self.aciklama = ""
        self.kategori = ""
        self.mutfak = ""
        self.porsiyon = ""
        self.hazirlik_suresi = ""
        self.pisirme_suresi = ""
        self.toplam_sure = ""
        self.kalori = ""
        self.puan = None
        self.oy_sayisi = None
        self.yazar = ""
        self.yayin_tarihi = ""

        # --- Fotoğraf ---
        self.foto_url = ""              # Fotoğrafın internetteki adresi
        self.foto_dosyasi = ""          # İndirilen fotoğrafın bilgisayardaki yolu

    def sozluge_cevir(self):
        """Nesneyi JSON'a yazılabilecek sözlüğe çevirir."""
        return dict(self.__dict__)

    def __str__(self):
        """print(tarif) yazınca ekranda düzgün görünmesini sağlar."""
        satirlar = [
            "=" * 60,
            f"  {self.isim.upper()}",
            "=" * 60,
            f"Adres      : {self.url}",
            f"Kategori   : {self.kategori}   |   Mutfak: {self.mutfak}",
            f"Porsiyon   : {self.porsiyon}",
            f"Süre       : Hazırlık {self.hazirlik_suresi} / Pişirme {self.pisirme_suresi}"
            f" / Toplam {self.toplam_sure}",
            f"Kalori     : {self.kalori}",
            f"Puan       : {self.puan} / 5 ({self.oy_sayisi} oy)" if self.puan else "Puan       : henüz puanlanmamış",
            f"Yazar      : {self.yazar}",
            f"Fotoğraf   : {self.foto_dosyasi or self.foto_url}",
            "",
            "MALZEMELER:",
        ]
        for grup, liste in self.malzeme_gruplari.items():
            if len(self.malzeme_gruplari) > 1:
                satirlar.append(f"  [{grup}]")
            for m in liste:
                satirlar.append(f"   - {m}")
        satirlar.append("")
        satirlar.append("YAPILIŞI:")
        for i, adim in enumerate(self.yapilis, 1):
            satirlar.append(f"  {i}. {adim}")
        if self.puf_noktalari:
            satirlar.append("")
            satirlar.append("PÜF NOKTALARI:")
            for sss in self.puf_noktalari:
                satirlar.append(f"  ? {sss['soru']}")
                satirlar.append(f"    {sss['cevap']}")
        return "\n".join(satirlar)


# =====================================================================
#  YARDIMCI FONKSİYONLAR
# =====================================================================

# Türkçe harfleri sadeleştirmek için tablo (ç->c, ğ->g, ı->i ...)
TURKCE_HARF = str.maketrans("çğıöşüâîûÇĞİÖŞÜÂÎÛI", "cgiosuaiuCGIOSUAIUI")


def sadelestir(metin):
    """'Mercimek Çorbası!' -> 'mercimek corbasi' (arama karşılaştırması için)."""
    metin = (metin or "").translate(TURKCE_HARF).lower()
    return re.sub(r"[^a-z0-9]+", " ", metin).strip()


def dosya_adi_yap(metin):
    """'Biber Dolması' -> 'biber-dolmasi' (fotoğraf dosya adı ve adres tahmini için)."""
    return sadelestir(metin).replace(" ", "-")


def dakika_bul(sure):
    """'1 saat 20 dakika' -> 80   (bulamazsa None)"""
    saat = re.search(r"(\d+)\s*saat", sure or "")
    dakika = re.search(r"(\d+)\s*dakika", sure or "")
    if not saat and not dakika:
        return None
    return (int(saat.group(1)) * 60 if saat else 0) + (int(dakika.group(1)) if dakika else 0)


def sure_yaz(dakika):
    """80 -> '1 sa 20 dk'"""
    if dakika is None:
        return ""
    sa, dk = divmod(dakika, 60)
    return " ".join(p for p in (f"{sa} sa" if sa else "", f"{dk} dk" if dk else "") if p) or "0 dk"


def temizle(metin):
    """Fazla boşlukları ve HTML kalıntılarını temizler."""
    if not metin:
        return ""
    metin = BeautifulSoup(str(metin), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", metin).strip()


def yazi(etiket):
    """BeautifulSoup etiketinin içindeki yazıyı temiz şekilde verir (etiket yoksa "")."""
    if etiket is None:
        return ""
    return re.sub(r"\s+", " ", etiket.get_text(" ")).strip()


def tr_baslik(metin):
    """'SÜTLÜ TATLI TARİFLERİ' -> 'Sütlü Tatlı Tarifleri' (Türkçe İ/ı harflerine dikkat ederek)"""
    metin = metin.replace("I", "ı").replace("İ", "i").lower()
    return " ".join(k[:1].replace("i", "İ").upper() + k[1:] for k in metin.split())


# =====================================================================
#  KAZIYICI — sayfa indirme ve tarif sayfasını okuma
# =====================================================================

class TarifKaziyici:
    """Tarif sayfalarını indirip içinden bilgileri çeken sınıf."""

    def __init__(self, foto_indir=None):
        self.foto_indir_acik = FOTO_INDIR if foto_indir is None else foto_indir
        # Session: aynı bağlantıyı tekrar kullanır, her istekte yeniden bağlanmaz (daha hızlı)
        self.oturum = requests.Session()
        self.oturum.headers.update(BASLIKLAR)
        self.robots = self._robots_oku()

    # ---------------- robots.txt kontrolü ----------------
    def _robots_oku(self):
        # NOT: robots.txt, sitenin hangi sayfaların kazınmasına izin verdiğini söyler.
        # yemek.com "/tarif/" ve "/sitemaps/" adreslerine izin veriyor, "?q=" aramasına vermiyor.
        # robots.txt'yi requests ile indiriyoruz; Python'un kendi indiricisi User-Agent
        # göndermediği için site onu 403 ile reddediyor.
        rp = robotparser.RobotFileParser()
        try:
            cevap = self.oturum.get(SITE + "/robots.txt", timeout=20)
        except requests.RequestException:
            return None
        if cevap.status_code != 200:
            return None
        rp.parse(cevap.text.splitlines())
        return rp

    def izin_var_mi(self, url):
        if self.robots is None:
            return True
        return self.robots.can_fetch(BASLIKLAR["User-Agent"], url)

    # ---------------- istek atma ----------------
    def sayfa_getir(self, url, deneme=3, sessiz_404=False):
        """Sayfayı indirir. Hata olursa birkaç kez tekrar dener."""
        if not self.izin_var_mi(url):
            print(f"  [!] robots.txt bu sayfaya izin vermiyor: {url}")
            return None
        for i in range(deneme):
            try:
                cevap = self.oturum.get(url, timeout=20)
                time.sleep(BEKLEME_SURESI)
                if cevap.status_code == 200:
                    # NOT: Site, sitemap (XML) dosyalarında karakter kodlamasını belirtmiyor;
                    # requests o zaman yanlış tahmin edip "Köfte"yi "KÃ¶fte" yapıyor.
                    # Sayfa kodlamayı söylemiyorsa UTF-8 (Türkçe karakterler) kabul ediyoruz.
                    if "charset" not in cevap.headers.get("Content-Type", "").lower():
                        cevap.encoding = "utf-8"
                    return cevap
                if cevap.status_code == 404:
                    if not sessiz_404:
                        print(f"  [!] Sayfa yok (404): {url}")
                    return None
                # NOT: 429 = çok fazla istek. Olursa BEKLEME_SURESI'ni artır.
                print(f"  [!] {url} -> HTTP {cevap.status_code} (deneme {i + 1}/{deneme})")
                time.sleep(3 * (i + 1))
            except requests.RequestException as hata:
                print(f"  [!] Bağlantı hatası: {hata} (deneme {i + 1}/{deneme})")
                time.sleep(3 * (i + 1))
        return None

    # ---------------- tarif sayfası ----------------
    def tarif_cek(self, url, sessiz_404=False):
        """Tek bir tarif sayfasını kazıyıp Tarif nesnesi döndürür."""
        cevap = self.sayfa_getir(url, sessiz_404=sessiz_404)
        if cevap is None:
            return None
        # ============ BEAUTIFULSOUP İLE HTML'İ OKUMA ============
        # requests ile indirdiğimiz HTML yazısını BeautifulSoup'a veriyoruz; o da sayfayı
        # etiketlerden oluşan bir ağaca çeviriyor. Sonra istediğimiz etiketleri
        # CSS seçicileriyle (select_one / select) ya da find / find_all ile buluyoruz.
        # NOT: Site tasarımını değiştirirse önce buradaki seçiciler bozulur. Doğru seçiciyi
        # bulmak için tarayıcıda tarif sayfasına sağ tıkla > "İncele" de, etiketin class'ına bak.
        corba = BeautifulSoup(cevap.text, "html.parser")

        # ---- Yemeğin adı: <h1 class="recipe-headline-main">Karnıyarık Tarifi</h1> ----
        baslik = corba.select_one("h1.recipe-headline-main")
        if baslik is None:
            return None   # bu bir tarif sayfası değil
        isim = re.sub(r"\s+Tarifi$", "", yazi(baslik))      # sondaki "Tarifi" kelimesini at
        tarif = Tarif(isim, cevap.url)

        # ---- Açıklama ve fotoğraf: <meta property="og:..." content="..."> ----
        # Bu etiketler sayfanın <head> kısmında; içerik "content" özelliğinde duruyor.
        aciklama = corba.find("meta", property="og:description")
        tarif.aciklama = aciklama["content"].strip() if aciklama else ""
        foto = corba.find("meta", property="og:image")
        tarif.foto_url = foto["content"] if foto else ""

        # ---- Kategori: üstteki yol çubuğu  YEMEK > YEMEK TARİFLERİ > SEBZE TARİFLERİ ----
        yol = corba.select(".breadcrumb-list a.breadcrumb-link")
        if len(yol) >= 3:
            son = re.sub(r"\s*TAR[İI]FLER[İI]$", "", yazi(yol[-1]))   # "SEBZE TARİFLERİ" -> "SEBZE"
            tarif.kategori = tr_baslik(son)                              # -> "Sebze"
        tarif.yayin_tarihi = yazi(corba.select_one(".breadcrumb-date"))  # "18 Aralık 2025"

        # ---- Kaç kişilik / süreler: 3 kutucuk, her birinde <h3>başlık</h3><span>değer</span> ----
        bilgiler = {}
        for kutu in corba.select(".content-recipe-small-infos > div"):
            bilgiler[yazi(kutu.find("h3")).upper()] = yazi(kutu.find("span"))
        tarif.porsiyon = bilgiler.get("KAÇ KİŞİLİK", "")
        hazirlik = dakika_bul(bilgiler.get("HAZIRLAMA SÜRESİ"))
        pisirme = dakika_bul(bilgiler.get("PİŞİRME SÜRESİ"))
        tarif.hazirlik_suresi = sure_yaz(hazirlik)
        tarif.pisirme_suresi = sure_yaz(pisirme)
        if hazirlik is not None or pisirme is not None:
            tarif.toplam_sure = sure_yaz((hazirlik or 0) + (pisirme or 0))

        # ---- Kalori: "Karnıyarık Kalorisi Ne Kadar: 1 adet için 430/kcal" ----
        kalori = re.search(r"(\d+)\s*/?\s*kcal", yazi(corba.select_one(".recipe-calorie-box")))
        tarif.kalori = f"{kalori.group(1)} kalori" if kalori else ""

        # ---- Puan: <div class="rating-box" data-initial-average="4.6" data-count="153"> ----
        # Puan yazı olarak değil, etiketin "data-" özelliklerinde duruyor; .get() ile okuyoruz.
        puan_kutusu = corba.select_one(".rating-box")
        if puan_kutusu and puan_kutusu.get("data-initial-average"):
            tarif.puan = float(puan_kutusu["data-initial-average"])
            tarif.oy_sayisi = int(puan_kutusu.get("data-count") or 0)

        # ---- Yazar: yazarın profil linki  <a href="https://yemek.com/profil/...">Ad Soyad</a> ----
        yazar = corba.select_one(".editor-box a[href*='/profil/']")
        tarif.yazar = yazi(yazar) or yazi(corba.select_one(".author-info-box strong"))

        # ---- Malzemeler ----
        # <div class="recipe-ingredients">
        #   <h3>Karnıyarık için:</h3>
        #   <ul> <li><span>6 adet</span> orta boy patlıcan</li> ... </ul>
        #   <h3>Patlıcanları kızartmak için:</h3>
        #   <ul> <li><span>1 su bardağı</span> ayçiçek yağı</li> </ul>
        # </div>
        # <h3> grup başlığıdır; altındaki <ul> listesinin her <li>'si bir malzemedir.
        grup = "Malzemeler"
        malzeme_kutusu = corba.select_one(".recipe-ingredients")
        if malzeme_kutusu:
            for etiket in malzeme_kutusu.find_all(["h3", "ul"]):
                if etiket.name == "h3":
                    grup = yazi(etiket).rstrip(":")
                    continue
                for li in etiket.find_all("li"):
                    malzeme = yazi(li)                       # "6 adet orta boy patlıcan"
                    tarif.malzeme_gruplari.setdefault(grup, []).append(malzeme)
                    tarif.malzemeler.append(malzeme)

        # ---- Yapılış: <div class="recipe-instructions"><ol><li>adım...</li></ol> ----
        # Her adımın içinde bir de fotoğraf kutusu (.li-media) var: önce fotoğrafın
        # adresini alıyoruz, sonra o kutuyu çıkarıp (extract) geriye kalan yazıyı okuyoruz.
        for li in corba.select(".recipe-instructions ol > li"):
            medya = li.select_one(".li-media")
            resim = medya.find("img") if medya else None
            if medya:
                medya.extract()
            adim = yazi(li)
            if adim:
                tarif.yapilis.append(adim)
                tarif.adim_fotolari.append((resim.get("data-src") or resim.get("src") or "") if resim else "")

        # ---- Püf noktaları: her biri <h2>soru</h2> + <div class="recipe-seo-body">cevap</div> ----
        for blok in corba.select(".recipe-sss .recipe-title-wrapper"):
            soru, cevap_kutusu = yazi(blok.find("h2")), blok.select_one(".recipe-seo-body")
            # NOT: Site bu bölüme kendi uygulamasının reklamını da koyuyor; onu atlıyoruz.
            # Başka reklam görürsen kelimesini bu listeye ekle.
            if not soru or cevap_kutusu is None or any(k in soru.lower() for k in ("yemek.com", "uygulama")):
                continue
            tarif.puf_noktalari.append({"soru": soru, "cevap": yazi(cevap_kutusu)})

        if self.foto_indir_acik and tarif.foto_url:
            tarif.foto_dosyasi = self.foto_indir(tarif)

        return tarif

    # ---------------- fotoğraf indirme ----------------
    def foto_indir(self, tarif):
        """Tarifin fotoğrafını FOTO_KLASORU içine indirir, dosya yolunu döndürür."""
        os.makedirs(FOTO_KLASORU, exist_ok=True)
        uzanti = os.path.splitext(tarif.foto_url.split("?")[0])[1] or ".jpg"
        # Adresin son kısmını dosya adı yapıyoruz (aynı isimli farklı tarifler karışmasın)
        ad = tarif.url.rstrip("/").rsplit("/", 1)[-1] or dosya_adi_yap(tarif.isim)
        # "/" ile birleştiriyoruz ki Windows'ta da site fotoğraf yolunu doğru okusun
        yol = f"{FOTO_KLASORU}/{ad}{uzanti}"
        if os.path.exists(yol):
            return yol   # daha önce indirildiyse tekrar indirme
        try:
            cevap = self.oturum.get(tarif.foto_url, timeout=20)
            time.sleep(BEKLEME_SURESI)
            if cevap.status_code == 200:
                with open(yol, "wb") as f:
                    f.write(cevap.content)   # fotoğraf "bayt" olarak yazılır
                return yol
            print(f"  [!] Fotoğraf indirilemedi (HTTP {cevap.status_code})")
        except requests.RequestException as hata:
            print(f"  [!] Fotoğraf hatası: {hata}")
        return ""

    # ---------------- adres tahmini ----------------
    def adresten_dene(self, isim):
        """Liste hazır değilken hızlı yol: 'Mercimek Çorbası' -> yemek.com/tarif/mercimek-corbasi/"""
        # NOT: yemek.com tarif adreslerini yemeğin adından üretiyor. Bu yüzden ismi
        # adrese çevirip doğrudan o sayfayı deniyoruz. Tutmazsa (404) None döner.
        return self.tarif_cek(f"{SITE}/tarif/{dosya_adi_yap(isim)}/", sessiz_404=True)


# =====================================================================
#  TARİF DİZİNİ — isimle arama yapabilmek için tüm tariflerin listesi
# =====================================================================

class TarifDizini:
    """Sitedeki tüm tariflerin adını/adresini/fotoğrafını tutar ve içinde arama yapar."""

    def __init__(self):
        self.kayitlar = []      # [{"url", "ad", "baslik", "foto"}, ...]
        self.hazir = False      # Liste kullanıma hazır mı?
        self.indirilen = 0      # İlerleme: kaç sitemap dosyası indirildi
        self.toplam = 0         # İlerleme: toplam sitemap dosyası
        self.hata = ""

    # ---------------- yükleme ----------------
    def yukle(self, kaziyici=None):
        """Dizin dosyası varsa ve tazeyse onu okur; yoksa siteden indirir."""
        if os.path.exists(DIZIN_DOSYASI):
            yas_gun = (time.time() - os.path.getmtime(DIZIN_DOSYASI)) / 86400
            if yas_gun < DIZIN_YENILEME_GUNU:
                try:
                    with open(DIZIN_DOSYASI, encoding="utf-8") as f:
                        self._hazirla(json.load(f))
                    return
                except (json.JSONDecodeError, OSError):
                    pass
        self.indir(kaziyici or TarifKaziyici(foto_indir=False))

    def indir(self, kaziyici):
        """Sitemap'lerden tüm tarifleri indirip DIZIN_DOSYASI'na kaydeder."""
        print("Tarif listesi siteden indiriliyor (bir kereye mahsus)...")
        ana = kaziyici.sayfa_getir(SITEMAP_ADRESI)
        if ana is None:
            self.hata = "Tarif listesi indirilemedi. İnternet bağlantını kontrol et."
            print("  [!] " + self.hata)
            return

        # NOT: Ana sitemap, onlarca küçük sitemap dosyasının listesidir:
        #   <sitemap><loc>https://yemek.com/sitemaps/recipe-sitemap1.xml</loc></sitemap> ...
        # BeautifulSoup ile bütün <loc> etiketlerini bulup sadece tarif olanları alıyoruz
        # (adında "recipe-sitemap" geçenler; diğerleri yazı, yazar vb.).
        ana_corba = BeautifulSoup(ana.text, "html.parser")
        adresler = [yazi(loc) for loc in ana_corba.find_all("loc") if "/recipe-sitemap" in yazi(loc)]
        self.toplam = len(adresler)

        kayitlar, gorulen = [], set()
        for adres in adresler:
            cevap = kaziyici.sayfa_getir(adres)
            self.indirilen += 1
            print(f"  ({self.indirilen}/{self.toplam}) {adres}")
            if cevap is None:
                continue
            # Her tarif sitemap'te şöyle duruyor:
            #   <url>
            #     <loc>https://yemek.com/tarif/karniyarik/</loc>
            #     <image:image>
            #       <image:loc>https://.../4079-640xauto.jpg</image:loc>
            #       <image:caption>Patlıcanın En Güzel Hali Karnıyarık</image:caption>
            #     </image:image>
            #   </url>
            corba = BeautifulSoup(cevap.text, "html.parser")
            for u in corba.find_all("url"):
                url = yazi(u.find("loc"))
                if "/tarif/" not in url or url in gorulen:
                    continue
                gorulen.add(url)
                kayitlar.append({
                    "url": url,
                    "baslik": yazi(u.find("image:caption")),
                    "foto": yazi(u.find("image:loc")),
                })

        if not kayitlar:
            self.hata = "Tarif listesi boş geldi."
            return
        # Liste yenilenirken, daha önce öğrenilen malzeme bilgileri ("m") kaybolmasın
        eski = {}
        if os.path.exists(DIZIN_DOSYASI):
            try:
                with open(DIZIN_DOSYASI, encoding="utf-8") as f:
                    eski = {k["url"]: (k["m"], k.get("i", "")) for k in json.load(f) if k.get("m")}
            except (json.JSONDecodeError, OSError, KeyError):
                pass
        for k in kayitlar:
            if k["url"] in eski:
                k["m"], k["i"] = eski[k["url"]]
        self._hazirla(kayitlar)
        self.kaydet()
        print(f"  {len(kayitlar)} tarif listeye eklendi -> {DIZIN_DOSYASI}")

    def kaydet(self):
        """Listeyi (öğrenilen malzemelerle birlikte) DIZIN_DOSYASI'na yazar."""
        # "_" ile başlayan alanlar sadece hafızada kullanılır, dosyaya yazılmaz
        temiz = [{a: v for a, v in k.items() if not a.startswith("_") and a != "ad"} for k in self.kayitlar]
        with open(DIZIN_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(temiz, f, ensure_ascii=False)

    def _hazirla(self, kayitlar):
        """Her kayıt için arama sırasında kullanılacak sadeleştirilmiş kelimeleri hazırlar."""
        for k in kayitlar:
            slug = k["url"].rstrip("/").rsplit("/", 1)[-1]          # "karniyarik-3"
            k["_ek_var"] = bool(re.search(r"-\d+$", slug))           # sonunda -3 gibi ek var mı
            k["_slug"] = re.sub(r"-\d+$", "", slug).split("-")       # ["karniyarik"]
            k["_baslik"] = sadelestir(k.get("baslik")).split()
            # "i": tarif sayfasına bakıldıysa gerçek adı; yoksa başlıktan tahmin edilen ad
            k["ad"] = k.get("i") or self._ad_bul(k.get("baslik", ""), k["_slug"])
        # Aynı yemeğin sitede kaç farklı tarifi var? (karniyarik, karniyarik-2 ... -> 6)
        # Çok tarifi olan yemek popüler demektir; aramada eşitlik olursa öne geçer.
        sayac = Counter("-".join(k["_slug"]) for k in kayitlar)
        for k in kayitlar:
            k["_populerlik"] = sayac["-".join(k["_slug"])]
        self.kayitlar = kayitlar
        self.toplam = self.indirilen = max(self.toplam, 1)
        self.hazir = True

    # ---------------- malzemeyle öneri için aday bulma ----------------
    def aday_bul(self, malzemeler, adet):
        """Malzemesi henüz bilinmeyen tarifler içinden, ADINDA kullanıcının malzemeleri
        geçenleri seçer ("patlıcan" -> "Patlıcan Kebabı", "Kıymalı Börek" ...)."""
        aranan = [sadelestir(m).split() for m in malzemeler]
        adaylar = []
        for sira, k in enumerate(self.kayitlar):
            if "m" in k:                      # malzemesi zaten biliniyor, tekrar bakmaya gerek yok
                continue
            kelimeler = k["_slug"] + k["_baslik"]
            tutan = sum(1 for parca in aranan
                        if parca and all(any(kelime_eslesir(a, w) for w in kelimeler) for a in parca))
            if tutan:
                adaylar.append((-tutan, -k["_populerlik"], k["_ek_var"], sira, k))
        adaylar.sort(key=lambda x: x[:4])
        return [a[-1] for a in adaylar[:adet]], len(adaylar) > adet

    @staticmethod
    def _ad_bul(baslik, slug_kelimeleri):
        """'Patlıcanın En Güzel Hali Karnıyarık' -> 'Karnıyarık' (süs cümlesini atar)."""
        kelimeler = baslik.split()
        n = len(slug_kelimeleri)
        for i in range(len(kelimeler) - n + 1):
            parca = kelimeler[i:i + n]
            if [sadelestir(w) for w in parca] == slug_kelimeleri:
                return " ".join(parca)
        return baslik.strip() or " ".join(slug_kelimeleri).title()

    # ---------------- arama ----------------
    def ara(self, isim, adet=None):
        """İsme en çok benzeyen tarifleri puanlayıp sıralı döndürür."""
        adet = adet or BENZER_TARIF_SAYISI
        aranan = sadelestir(isim).split()
        if not aranan:
            return []

        # NOT: PUANLAMA — hangi tarif daha iyi eşleşiyor?
        #   100 : adres birebir aynı         (karnıyarık -> /tarif/karniyarik/)
        #    85 : adres aranan kelimelerle bitiyor   (sarma -> /tarif/yaprak-sarma/)
        #    75 : adres aranan kelimelerle başlıyor  (sarma -> /tarif/sarma-baklava/)
        #         (Türkçede yemeğin türü sonda gelir: "yaprak sarma" bir sarmadır,
        #          "sarma baklava" ise bir baklavadır. O yüzden "biten" daha yüksek puan alır.)
        #    65 : aranan tüm kelimeler adreste var
        #    55 : aranan tüm kelimeler başlıkta var
        #    45 : kelimeler yarım yazılmış ama tutuyor (mercim -> mercimek)
        #   <30 : sadece bazı kelimeler tutuyor
        # Puanları değiştirerek sonuç sıralamasını kendine göre ayarlayabilirsin.
        sonuclar = []
        for sira, k in enumerate(self.kayitlar):
            s, b = k["_slug"], k["_baslik"]
            n = len(aranan)
            if s == aranan:
                puan = 100
            elif s[-n:] == aranan:
                puan = 85
            elif s[:n] == aranan:
                puan = 75
            elif all(a in s for a in aranan):
                puan = 65
            elif all(a in b for a in aranan):
                puan = 55
            elif all(any(w.startswith(a) for w in s) for a in aranan):
                puan = 45
            else:
                tutan = sum(1 for a in aranan if len(a) > 2 and any(w.startswith(a) for w in s + b))
                if tutan == 0:
                    continue
                puan = 30 * tutan / n
            # Eşit puanda sıralama: önce popüler yemek, sonra sonunda "-2" gibi eki
            # olmayan (asıl) tarif, sonra kısa adresli olan
            sonuclar.append((-puan, -k["_populerlik"], k["_ek_var"], len(s), sira, k))
        sonuclar.sort(key=lambda x: x[:5])

        # NOT: ÇEŞİTLİLİK — aynı yemeğin en fazla AYNI_YEMEK_SINIRI tarifi listelenir,
        # yoksa "tiramisu" araması 10 tane aynı isimli tiramisuyla dolar.
        AYNI_YEMEK_SINIRI = 3
        secilen, yedek, gorulen = [], [], Counter()
        for satir in sonuclar:
            k = satir[-1]
            anahtar = "-".join(k["_slug"])
            (secilen if gorulen[anahtar] < AYNI_YEMEK_SINIRI else yedek).append(satir)
            gorulen[anahtar] += 1
            if len(secilen) >= adet:
                break
        secilen = (secilen + yedek)[:adet]
        return [{"url": k["url"], "ad": k["ad"], "baslik": k["baslik"], "foto": k["foto"],
                 "puan": -satir[0]} for satir in secilen for k in [satir[-1]]]

# =====================================================================
#  MALZEMEYLE ÖNERİ — elimdeki malzemelerle hangi yemekleri yapabilirim?
# =====================================================================

# NOT: ÖLÇÜ KELİMELERİ
# "2 su bardağı sıcak su" satırından malzemeyi bulmak için önce ölçüleri atıyoruz.
# Yoksa "su bardağı"ndaki "su" kelimesi suyla, "yemek kaşığı"ndaki "yemek" başka şeyle karışır.
IKILI_OLCULER = {"su bardagi", "su bardak", "cay bardagi", "yemek kasigi", "tatli kasigi",
                 "cay kasigi", "kahve kasigi", "kahve fincani", "orta boy", "buyuk boy",
                 "kucuk boy", "oda sicakliginda"}
TEKLI_OLCULER = {"adet", "gram", "gr", "g", "kg", "kilo", "kilogram", "ml", "litre", "lt", "l",
                 "paket", "tutam", "dis", "demet", "dal", "avuc", "kase", "fincan", "bardak",
                 "kasik", "dilim", "parca", "kutu", "kavanoz", "silme", "tepeleme", "dolu",
                 "yarim", "ceyrek", "buyuk", "kucuk", "orta", "boy", "iri", "tane", "bas",
                 "kalip", "rulo"}
# NOT: Bu ifadeler geçen malzemeler "isteğe bağlı" sayılır, eksik listesine girmez
ISTEGE_BAGLI = ("istege bagli", "suslemek icin", "servis icin", "uzeri icin", "susleme icin")


def kelime_eslesir(aranan, kelime):
    """Kullanıcının yazdığı kelime, tarifteki kelimeyle eşleşiyor mu?
    'kiyma' -> 'kiymali', 'kiymasi' | 'ekmek' -> 'ekmegi' | 'et' -> 'etli' (ama 'etsiz' değil)"""
    if kelime == aranan:
        return True
    if kelime.endswith(("siz", "suz")):     # "etsiz", "sekersiz" eşleşmesin
        return False
    if len(aranan) >= 5:
        # Son harfi yumuşayabilir: ekmek -> ekmeği, kitap -> kitabı
        return kelime.startswith(aranan[:-1])
    # Kısa kelimelerde (et, un, süt) sadece küçük ekleri kabul et: etli, sütlü, unu
    return kelime.startswith(aranan) and len(kelime) - len(aranan) <= 3


def malzeme_kelimeleri(satir):
    """'2 su bardağı sıcak su' -> ['sicak', 'su']   (ölçü ve sayıları atar)"""
    satir = re.sub(r"\(.*?\)", " ", satir)                 # parantez içini at
    kelimeler = [w for w in sadelestir(satir).split() if not w.isdigit()]
    sonuc, i = [], 0
    while i < len(kelimeler):
        if i + 1 < len(kelimeler) and f"{kelimeler[i]} {kelimeler[i + 1]}" in IKILI_OLCULER:
            i += 2
            continue
        if kelimeler[i] not in TEKLI_OLCULER:
            sonuc.append(kelimeler[i])
        i += 1
    return sonuc


def malzeme_adi(satir):
    """Ekranda göstermek için: '2 diş sarımsak (ezilmiş)' -> 'sarımsak'"""
    temiz = re.sub(r"\(.*?\)", " ", satir)
    kelimeler = temiz.split()
    sonuc, i = [], 0
    while i < len(kelimeler):
        ikili = sadelestir(" ".join(kelimeler[i:i + 2]))
        if i + 1 < len(kelimeler) and ikili in IKILI_OLCULER:
            i += 2
            continue
        sade = sadelestir(kelimeler[i])
        if sade and not re.fullmatch(r"[\d\s]+", sade) and sade not in TEKLI_OLCULER \
                and not re.fullmatch(r"[\d.,/½¼¾-]+", kelimeler[i]):
            sonuc.append(kelimeler[i])
        i += 1
    return " ".join(sonuc).strip(" ,.-") or satir


def satir_eslesir(malzeme, kelimeler):
    """Kullanıcının bir malzemesi ('domates' ya da 'sıvı yağ') bu satırda var mı?
    Eş anlamlıları da dener: 'tavuk' -> 'but', 'göğüs' ..."""
    secenekler = [malzeme] + ESANLAMLI_SADE.get(sadelestir(malzeme), [])
    for secenek in secenekler:
        parcalar = sadelestir(secenek).split()
        if parcalar and all(any(kelime_eslesir(p, w) for w in kelimeler) for p in parcalar):
            return True
    return False


# Eş anlamlılar sözlüğünün anahtarları sadeleştirilmiş hali ("kaşar" -> "kasar")
ESANLAMLI_SADE = {sadelestir(a): v for a, v in ESANLAMLILAR.items()}


def tarifi_puanla(satirlar, malzemeler, temel_var):
    """Bir tarifin malzeme listesini, kullanıcının malzemeleriyle karşılaştırır.

    Döner: {kullanilan: [kullanıcının işe yarayan malzemeleri],
            eksik: [eksik malzeme satırları], toplam, sende, uyum (0-100), puan}
    """
    kontrol = list(malzemeler) + (TEMEL_MALZEMELER if temel_var else [])
    kullanilan, eksik, toplam, sende = set(), [], 0, 0
    for satir in satirlar:
        kelimeler = malzeme_kelimeleri(satir)
        if not kelimeler:
            continue
        sade = sadelestir(satir)
        # "1 çay kaşığı pul biber (arzuya göre)" gibi satırlar isteğe bağlıdır
        istege_bagli = any(ib in sade for ib in ISTEGE_BAGLI) or sade.endswith("arzuya gore")
        tutan = [m for m in kontrol if satir_eslesir(m, kelimeler)]
        kullanilan.update(m for m in tutan if m in malzemeler)
        if istege_bagli:
            continue                      # "arzuya göre" malzemeler eksik sayılmaz
        toplam += 1
        if tutan:
            sende += 1
        else:
            eksik.append(satir)
    uyum = round(100 * sende / toplam) if toplam else 0
    kapsama = 100 * len(kullanilan) / len(malzemeler) if malzemeler else 0
    # NOT: ÖNERİ PUANI (0-100) iki şeye bakar:
    #   uyum    : tarifin malzemelerinin yüzde kaçı sende var   (eksiğin az mı?)
    #   kapsama : senin malzemelerinin yüzde kaçını kullanıyor  (elindekileri değerlendiriyor mu?)
    # Ağırlıkları (0.55 / 0.45) değiştirerek sıralamayı kendine göre ayarlayabilirsin.
    puan = round(0.55 * uyum + 0.45 * kapsama)
    return {"kullanilan": sorted(kullanilan), "eksik": eksik, "toplam": toplam,
            "sende": sende, "uyum": uyum, "puan": puan}


def oneri_sozlugu(kayit, sonuc):
    """Ekrana gönderilecek öneri kartı bilgileri."""
    return {"url": kayit["url"], "ad": kayit.get("ad") or kayit.get("baslik", ""),
            "foto": kayit.get("foto", ""), "kullanilan": sonuc["kullanilan"],
            "eksik": list(dict.fromkeys(malzeme_adi(e) for e in sonuc["eksik"])),   # tekrarsız
            "eksik_satirlar": sonuc["eksik"],
            "toplam": sonuc["toplam"], "sende": sonuc["sende"], "uyum": sonuc["uyum"],
            "puan": sonuc["puan"]}


# =====================================================================
#  TARİFİ KAYDETME
# =====================================================================

def tarifi_kaydet(tarif):
    """Tarifi tarifler.json'a ekler (aynısı varsa eskisini siler, yenisini en üste koyar)."""
    liste = []
    if os.path.exists(CIKTI_DOSYASI):
        try:
            with open(CIKTI_DOSYASI, encoding="utf-8") as f:
                liste = json.load(f)
        except (json.JSONDecodeError, OSError):
            liste = []
    sozluk = tarif.sozluge_cevir()
    liste = [t for t in liste if t.get("url") != sozluk["url"]]
    liste.insert(0, sozluk)
    with open(CIKTI_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(liste, f, ensure_ascii=False, indent=2)


# =====================================================================
#  GÖRSEL SİTE — tarayıcıdaki index.html ile konuşan küçük sunucu
# =====================================================================
#
# Sunucunun adresleri:
#   /                     -> index.html (sitenin kendisi)
#   /api/durum            -> tarif listesi hazır mı, kaç tarif var
#   /api/ara?isim=...     -> yemeği arar, sonucu canlı gönderir (SSE)
#   /api/tarif?url=...    -> benzer tariflerden birine tıklanınca o tarifi getirir
#   /api/oner?malzemeler= -> elimdeki malzemelerle yapılabilecek yemekleri önerir (SSE)
#   /api/kayitli          -> daha önce bulunup tarifler.json'a kaydedilmiş tarifler
#   /api/temizle          -> kayıtlı tarif listesini boşaltır
#   /veri/fotograflar/... -> indirilen yemek fotoğrafları

# NOT: PORT AYARI
# Kendi bilgisayarında site http://localhost:8000 adresinde açılır.
# 8000 doluysa 8080, 5000 gibi başka bir sayı yaz.
# İnternette (Render gibi bir sunucuda) çalışırken sunucu kendi port numarasını
# "PORT" ortam değişkeniyle verir; o zaman otomatik olarak o kullanılır.
PORT = int(os.environ.get("PORT", 8000))
INTERNETTE_MI = "PORT" in os.environ   # Render'da True, kendi bilgisayarında False

# Dosyalar her zaman bu Python dosyasının yanındaki klasöre kaydedilsin
KLASOR = os.path.dirname(os.path.abspath(__file__))
os.chdir(KLASOR)
os.makedirs(FOTO_KLASORU, exist_ok=True)   # "veri/" ve "veri/fotograflar/" yoksa oluştur

# Tarif sayfalarını çeken kazıyıcı (aynı anda tek istek atsın diye kilitli kullanılır)
kaziyici = TarifKaziyici()
# Öneri için tarif sayfalarına bakarken fotoğraf indirmeye gerek yok (sadece malzemeler lazım)
oneri_kaziyici = TarifKaziyici(foto_indir=False)
kaziyici_kilidi = threading.Lock()

# NOT: Tarif listesi (dizin) sunucu açılır açılmaz arka planda yüklenir.
# İlk çalıştırmada siteden indirildiği için ~30 saniye sürer; o sırada arama yine de
# çalışır (yemeğin adından adres tahmin edilir), liste hazır olunca benzer tarifler de gelir.
dizin = TarifDizini()
threading.Thread(target=dizin.yukle, daemon=True).start()


# =====================================================================
#  tarifler.json okuma / yazma
# =====================================================================

def kayitli_tarifler():
    if not os.path.exists(CIKTI_DOSYASI):
        return []
    try:
        with open(CIKTI_DOSYASI, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def tarif_getir(url):
    """Kilitli şekilde tarifi çeker ve tarifler.json'a kaydeder."""
    with kaziyici_kilidi:
        tarif = kaziyici.tarif_cek(url)
    if tarif:
        tarifi_kaydet(tarif)
    return tarif


# =====================================================================
#  İSTEKLERİ KARŞILAYAN SINIF
# =====================================================================

class Istekci(BaseHTTPRequestHandler):

    # ---------------- yardımcılar ----------------
    def json_gonder(self, veri, kod=200):
        govde = json.dumps(veri, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def dosya_gonder(self, yol, tur):
        if not os.path.isfile(yol):
            self.send_error(404, "Dosya bulunamadı")
            return
        with open(yol, "rb") as f:
            govde = f.read()
        self.send_response(200)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def olay_gonder(self, ad, veri):
        """Tarayıcıya canlı bir 'olay' (Server-Sent Event) gönderir."""
        mesaj = f"event: {ad}\ndata: {json.dumps(veri, ensure_ascii=False)}\n\n"
        self.wfile.write(mesaj.encode("utf-8"))
        self.wfile.flush()

    def log_message(self, bicim, *args):
        pass  # her isteği terminale yazmasın, ekran temiz kalsın

    # ---------------- adresler ----------------
    def do_GET(self):
        adres = urlparse(self.path)
        yol = adres.path
        sorgu = parse_qs(adres.query)

        if yol in ("/", "/index.html"):
            self.dosya_gonder("index.html", "text/html; charset=utf-8")

        elif yol == "/api/durum":
            self.json_gonder({"hazir": dizin.hazir, "tarif_sayisi": len(dizin.kayitlar),
                              "indirilen": dizin.indirilen, "toplam": dizin.toplam, "hata": dizin.hata})

        elif yol == "/api/ara":
            self.ara(sorgu.get("isim", [""])[0].strip())

        elif yol == "/api/tarif":
            url = sorgu.get("url", [""])[0]
            # Güvenlik: sadece yemek.com tarif adresleri kabul edilir
            if not url.startswith(SITE + "/tarif/"):
                self.json_gonder({"hata": "Geçersiz tarif adresi."}, 400)
                return
            tarif = tarif_getir(url)
            if tarif is None:
                self.json_gonder({"hata": "Bu tarif açılamadı. Biraz sonra tekrar dene."}, 502)
            else:
                veri = tarif.sozluge_cevir()
                # Öneri sekmesinden açıldıysa: hangi malzemeler eksik, onu da hesapla
                elimdeki = [m.strip() for m in sorgu.get("malzemeler", [""])[0].split(",") if m.strip()]
                if elimdeki:
                    veri["eksik_satirlar"] = tarifi_puanla(
                        tarif.malzemeler, elimdeki, sorgu.get("temel", ["1"])[0] == "1")["eksik"]
                self.json_gonder(veri)

        elif yol == "/api/oner":
            liste = [m.strip() for m in sorgu.get("malzemeler", [""])[0].split(",") if m.strip()]
            self.oner(liste, sorgu.get("temel", ["1"])[0] == "1")

        elif yol == "/api/kayitli":
            self.json_gonder(kayitli_tarifler())

        elif yol.startswith(f"/{FOTO_KLASORU}/"):
            # Güvenlik: sadece fotoğraf klasöründeki dosya adını kabul et ("../" ile dışarı çıkılmasın)
            ad = os.path.basename(yol)
            uzanti = os.path.splitext(ad)[1].lower()
            tur = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(uzanti, "image/jpeg")
            self.dosya_gonder(os.path.join(FOTO_KLASORU, ad), tur)

        else:
            self.send_error(404, "Sayfa bulunamadı")

    def do_POST(self):
        if urlparse(self.path).path == "/api/temizle":
            with open(CIKTI_DOSYASI, "w", encoding="utf-8") as f:
                json.dump([], f)
            self.json_gonder({"tamam": True})
        else:
            self.send_error(404, "Sayfa bulunamadı")

    # ---------------- arama ----------------
    def ara(self, isim):
        # Canlı yayın (SSE): bağlantı açık kalır, adım adım sonuç gönderilir
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")   # aradaki sunucular canlı yayını bekletmesin
        self.end_headers()

        try:
            if not isim:
                self.olay_gonder("hata", {"mesaj": "Önce bir yemek adı yaz."})
                return

            gonderilen = None   # ekrana gönderilen tarifin adresi

            # 1) Liste henüz hazır değilse: yemeğin adından adres tahmin et (hızlı yol)
            if not dizin.hazir:
                self.olay_gonder("durum", {"mesaj": f"“{isim}” aranıyor…"})
                with kaziyici_kilidi:
                    tarif = kaziyici.adresten_dene(isim)
                if tarif:
                    tarifi_kaydet(tarif)
                    gonderilen = tarif.url
                    self.olay_gonder("tarif", tarif.sozluge_cevir())

                # Listenin hazır olmasını bekle (benzer tarifler ve daha iyi arama için)
                while not dizin.hazir and not dizin.hata:
                    self.olay_gonder("durum", {
                        "mesaj": f"Tarif listesi hazırlanıyor ({dizin.indirilen}/{dizin.toplam or '?'}). "
                                 "Bu sadece ilk açılışta olur."})
                    time.sleep(1)

            # 2) Listede ara
            sonuclar = dizin.ara(isim, BENZER_TARIF_SAYISI + 1) if dizin.hazir else []

            if gonderilen is None:
                if sonuclar:
                    self.olay_gonder("durum", {"mesaj": f"“{sonuclar[0]['ad']}” tarifi getiriliyor…"})
                    tarif = tarif_getir(sonuclar[0]["url"])
                    if tarif:
                        gonderilen = tarif.url
                        self.olay_gonder("tarif", tarif.sozluge_cevir())

            if gonderilen is None:
                self.olay_gonder("hata", {"mesaj": f"“{isim}” için tarif bulunamadı. "
                                                   "Yazımı kontrol et ya da daha kısa yaz (ör. “sarma”)."})
                return

            # 3) Benzer tarifler (gösterilen tarif hariç)
            benzerler = [s for s in sonuclar if s["url"].rstrip("/") != gonderilen.rstrip("/")]
            self.olay_gonder("benzerler", benzerler[:BENZER_TARIF_SAYISI])
            self.olay_gonder("bitti", {})

        except (BrokenPipeError, ConnectionResetError):
            pass   # tarayıcı sayfayı kapattı
        except Exception as hata:
            try:
                self.olay_gonder("hata", {"mesaj": f"Beklenmeyen hata: {hata}"})
            except OSError:
                pass


    # ---------------- malzemeyle öneri ----------------
    def oner(self, malzemeler, temel_var):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            if not malzemeler:
                self.olay_gonder("hata", {"mesaj": "Önce elindeki malzemelerden en az birini ekle."})
                return
            while not dizin.hazir and not dizin.hata:
                self.olay_gonder("durum", {"mesaj": f"Tarif listesi hazırlanıyor ({dizin.indirilen}/{dizin.toplam or '?'})…"})
                time.sleep(1)
            if not dizin.hazir:
                self.olay_gonder("hata", {"mesaj": dizin.hata})
                return

            # 1) Malzemesi zaten bilinen tarifler: anında puanlanır
            bilinen = []
            for k in dizin.kayitlar:
                if k.get("m"):
                    sonuc = tarifi_puanla(k["m"], malzemeler, temel_var)
                    if sonuc["kullanilan"]:
                        bilinen.append(oneri_sozlugu(k, sonuc))
            bilinen.sort(key=lambda o: -o["puan"])
            self.olay_gonder("oneriler", bilinen[:ONERI_GOSTERIM_SAYISI])

            # 2) Adında bu malzemeler geçen, henüz bakılmamış tarifler: sayfası açılıp bakılır
            adaylar, daha_var = dizin.aday_bul(malzemeler, ONERI_TARAMA_SAYISI)
            for i, k in enumerate(adaylar, 1):
                self.olay_gonder("durum", {"mesaj": f"Yeni tarifler inceleniyor ({i}/{len(adaylar)}): {k['ad']}"})
                with kaziyici_kilidi:
                    tarif = oneri_kaziyici.tarif_cek(k["url"], sessiz_404=True)
                k["m"] = tarif.malzemeler if tarif else []
                if tarif:
                    k["i"] = k["ad"] = tarif.isim     # gerçek adı da öğrenmiş olduk
                    sonuc = tarifi_puanla(k["m"], malzemeler, temel_var)
                    if sonuc["kullanilan"]:
                        self.olay_gonder("oneri", oneri_sozlugu(k, sonuc))
            if adaylar:
                dizin.kaydet()   # öğrenilen malzemeleri dosyaya yaz, bir dahakine hızlı olsun
            self.olay_gonder("bitti", {"daha_var": daha_var})
        except (BrokenPipeError, ConnectionResetError):
            if dizin.hazir:
                dizin.kaydet()
        except Exception as hata:
            try:
                self.olay_gonder("hata", {"mesaj": f"Beklenmeyen hata: {hata}"})
            except OSError:
                pass


# =====================================================================
#  SUNUCUYU BAŞLAT
# =====================================================================

if __name__ == "__main__":
    # Kendi bilgisayarında sadece bu bilgisayardan erişilir (127.0.0.1);
    # internette çalışırken herkesin erişebilmesi için tüm adreslere (0.0.0.0) açılır.
    sunucu = ThreadingHTTPServer(("0.0.0.0" if INTERNETTE_MI else "127.0.0.1", PORT), Istekci)
    adres = f"http://localhost:{PORT}"
    print(f"Tarif sitesi çalışıyor: {adres}", flush=True)
    if not INTERNETTE_MI:
        print("Kapatmak için bu pencerede Ctrl+C'ye bas.\n")
        # NOT: Tarayıcının kendiliğinden açılmasını istemiyorsan bu satırı sil.
        threading.Timer(1.0, lambda: webbrowser.open(adres)).start()
    try:
        sunucu.serve_forever()
    except KeyboardInterrupt:
        print("\nSite kapatıldı.")
