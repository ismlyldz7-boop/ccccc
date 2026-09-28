import json
import os
import re
import threading
import time
import urllib.parse
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


BASE = "https://skin.land"
MARKET = BASE + "/market/cs2/"
CONFIG_FILE = "config.json"

# Skin.Land filter IDs. 22, 23 and 25 are currently visible in the public site.
# 24 is kept as the remaining current charm collection slot; if Skin.Land changes
# the mapping, the scanner will simply skip pages where the filter does not match.
CHARM_CATEGORIES = {
    22: "Small Arms Charm Collection",
    23: "Missing Link Charm Collection",
    24: "Dr Boom Charm Collection",
    25: "Missing Link Community Charm Collection",
}


def app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def fpath(name):
    return os.path.join(app_dir(), name)


def load_config():
    try:
        with open(fpath(CONFIG_FILE), "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {
            "max_price": 100,
            "max_products_per_category": 10,
            "interval": 300,
            "page_wait": 1.4,
        }


def save_config(data):
    with open(fpath(CONFIG_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clean_text(node):
    return " ".join(node.get_text(" ", strip=True).split())


def money_values(text):
    vals = []
    for x in re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", text):
        try:
            vals.append(float(x.replace(",", "")))
        except Exception:
            pass
    return vals


def extract_charm_names(node):
    names = []
    # Prefer real text nodes/alt text from the rendered offer.
    for s in node.stripped_strings:
        t = " ".join(s.split())
        m = re.match(r"^(?:Souvenir\s+)?Charm\s*\|\s*(.+)$", t, re.I)
        if m:
            name = m.group(1).strip()
            # Avoid accidentally consuming the rest of an offer if text was merged.
            name = re.split(r"\s{2,}|\s+\$\d|\s+Buy now\b|\s+Add to cart\b", name, maxsplit=1, flags=re.I)[0]
            if name and name not in names:
                names.append(name)

    for img in node.find_all("img"):
        alt = (img.get("alt") or "").strip()
        m = re.match(r"^(?:Souvenir\s+)?Charm\s*\|\s*(.+)$", alt, re.I)
        if m:
            name = m.group(1).strip()
            if name and name not in names:
                names.append(name)
    return names


class BrowserScanner:
    def __init__(self, status_cb):
        self.status_cb = status_cb
        self.driver = None
        self.cfg = load_config()
        self.wait_after_load = float(self.cfg.get("page_wait", 1.4))
        self.charm_price_cache = {}

    def status(self, msg):
        self.status_cb(msg)

    def start_browser(self):
        if self.driver is not None:
            return
        opts = webdriver.ChromeOptions()
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-popup-blocking")
        # Intentionally NOT headless: use a normal visible Chrome window.
        # This is standard browser automation; no stealth/anti-bot bypass flags.
        self.status("Chrome açılıyor... İlk çalıştırmada sürücü hazırlanması biraz sürebilir.")
        try:
            self.driver = webdriver.Chrome(options=opts)
        except WebDriverException as e:
            raise RuntimeError(
                "Chrome başlatılamadı. Google Chrome'un güncel olduğundan emin ol. "
                "İlk çalıştırmada Selenium uygun ChromeDriver'ı hazırlamak için internete erişir.\n\n"
                + str(e)[:700]
            )

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def wait_for_skinland(self, timeout=90):
        start = time.time()
        last = ""
        while time.time() - start < timeout:
            try:
                body = self.driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                body = ""
            last = body
            low = body.lower()

            # Real market/product content is visible.
            if ("buy now" in low or "şimdi satın al" in low) and (
                "skin.land" in self.driver.current_url.lower()
            ):
                time.sleep(self.wait_after_load)
                return

            # Cloudflare / browser verification. Let the user solve it manually.
            if any(x in low for x in [
                "verify you are human", "checking your browser", "just a moment",
                "insan olduğunuzu doğrulayın", "tarayıcınız kontrol ediliyor"
            ]):
                self.status(
                    "Skin.Land tarayıcı doğrulaması gösteriyor. Açılan Chrome penceresindeki "
                    "kontrolü tamamla; program otomatik devam edecek."
                )
            time.sleep(1)

        raise RuntimeError(
            "Skin.Land sayfası 90 saniye içinde açılmadı. "
            "Açılan Chrome penceresinde bir doğrulama/hata varsa onu kontrol et."
        )

    def open(self, url):
        self.driver.get(url)
        self.wait_for_skinland()
        return self.driver.page_source

    def market_product_links(self, category_id, page_no=1, max_count=10):
        params = {
            "charm_category_id": category_id,
            "sort_by": "price_asc",
            "page": page_no,
        }
        url = MARKET + "?" + urllib.parse.urlencode(params)
        self.open(url)

        links = []
        seen = set()
        for a in self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/market/cs2/"]'):
            href = a.get_attribute("href") or ""
            txt = " ".join((a.text or "").split())
            if not href.startswith(MARKET):
                continue
            path = urllib.parse.urlparse(href).path.rstrip("/")
            if path == "/market/cs2":
                continue
            slug = path.split("/")[-1]
            if not slug or slug.startswith("charm-"):
                continue
            # Product cards normally contain "on sale" / "Buy now" and a price.
            low = txt.lower()
            if ("buy now" not in low and "şimdi satın al" not in low and "$" not in txt):
                continue
            href = href.split("?")[0]
            if href not in seen:
                seen.add(href)
                links.append(href)
            if len(links) >= max_count:
                break
        return links

    def offer_blocks(self, html):
        soup = BeautifulSoup(html, "html.parser")
        blocks = []
        seen = set()

        # Skin.Land offer cards all contain "Buy now" / localized equivalent.
        buy_re = re.compile(r"Buy now|Şimdi Satın Al", re.I)
        for txt_node in soup.find_all(string=buy_re):
            node = txt_node.parent
            candidate = None
            for _ in range(10):
                if node is None:
                    break
                t = clean_text(node)
                buys = len(buy_re.findall(t))
                dollars = len(re.findall(r"\$\s*\d", t))
                if buys == 1 and dollars >= 1 and 20 <= len(t) <= 4500:
                    candidate = node
                    if len(t) >= 70:
                        break
                node = node.parent
            if candidate is None:
                continue
            t = clean_text(candidate)
            key = t[:1600]
            if key not in seen:
                seen.add(key)
                blocks.append(candidate)
        return blocks

    def parse_offers(self, html, require_charm=None):
        rows = []
        for node in self.offer_blocks(html):
            text = clean_text(node)
            vals = money_values(text)
            if not vals:
                continue

            charms = extract_charm_names(node)
            if require_charm is True and not charms:
                continue
            if require_charm is False and charms:
                continue

            # The offer's payable price is generally the last dollar value in the
            # compact offer card, immediately before Buy now.
            price = vals[-1]
            floats = re.findall(r"\b0\.\d{6,16}\b", text)
            flt = floats[0] if floats else ""

            if charms:
                for charm in charms:
                    rows.append({"price": price, "float": flt, "charm": charm, "text": text})
            else:
                rows.append({"price": price, "float": flt, "charm": "", "text": text})

        # De-duplicate
        out, seen = [], set()
        for r in rows:
            k = (r["price"], r["float"], r["charm"])
            if k not in seen:
                seen.add(k)
                out.append(r)
        return out

    def page_title(self, html, url):
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        if h1:
            t = clean_text(h1)
            if t:
                return t
        title = clean_text(soup.title) if soup.title else ""
        title = re.sub(r"^Buy\s+", "", title, flags=re.I)
        title = re.sub(r"\s+[–-]\s+price.*$", "", title, flags=re.I)
        return title or url.rstrip("/").split("/")[-1]

    def charm_market_price(self, charm):
        if charm in self.charm_price_cache:
            return self.charm_price_cache[charm]

        q = "Charm | " + charm
        params = {"query": q, "sort_by": "price_asc"}
        url = MARKET + "?" + urllib.parse.urlencode(params)
        html = self.open(url)
        soup = BeautifulSoup(html, "html.parser")

        exact = q.lower()
        best = None
        for a in soup.find_all("a", href=True):
            t = clean_text(a)
            low = t.lower()
            if exact not in low:
                continue
            vals = money_values(t)
            if vals:
                p = min(vals)
                if best is None or p < best:
                    best = p
        self.charm_price_cache[charm] = best
        return best

    def scan_product(self, url, category_id):
        # 1) Unfiltered product page for a no-charm baseline.
        base_html = self.open(url)
        name = self.page_title(base_html, url)
        plain = self.parse_offers(base_html, require_charm=False)
        base_price = min((x["price"] for x in plain), default=None)

        # 2) Same product filtered to a charm collection.
        sep = "&" if "?" in url else "?"
        charmed_url = url + sep + urllib.parse.urlencode({"charm_category_id": category_id})
        charmed_html = self.open(charmed_url)
        charmed = self.parse_offers(charmed_html, require_charm=True)

        rows = []
        for o in charmed:
            cprice = self.charm_market_price(o["charm"])
            extra = None if base_price is None else o["price"] - base_price
            theoretical = None
            if extra is not None and cprice is not None:
                theoretical = cprice - extra
            rows.append({
                "skin": name,
                "charm": o["charm"],
                "buy_price": o["price"],
                "base_price": base_price,
                "extra_paid": extra,
                "charm_price": cprice,
                "theoretical": theoretical,
                "float": o["float"],
                "url": charmed_url,
            })
        return rows


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("CS2 Skin.Land Charm Scanner V3 — Browser Mode")
        self.root.geometry("1320x740")
        self.root.minsize(1050, 620)

        cfg = load_config()
        self.running = False
        self.scanner = None
        self.results = []

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Max alış $:").grid(row=0, column=0, sticky="w")
        self.max_price = ttk.Entry(top, width=8)
        self.max_price.insert(0, str(cfg.get("max_price", 100)))
        self.max_price.grid(row=0, column=1, padx=(5, 14))

        ttk.Label(top, text="Max ürün/kategori:").grid(row=0, column=2)
        self.max_products = ttk.Entry(top, width=6)
        self.max_products.insert(0, str(cfg.get("max_products_per_category", 10)))
        self.max_products.grid(row=0, column=3, padx=(5, 14))

        ttk.Label(top, text="Tarama (sn):").grid(row=0, column=4)
        self.interval = ttk.Entry(top, width=7)
        self.interval.insert(0, str(cfg.get("interval", 300)))
        self.interval.grid(row=0, column=5, padx=(5, 14))

        self.start_btn = ttk.Button(top, text="Otomatik Taramayı Başlat", command=self.toggle)
        self.start_btn.grid(row=0, column=6, padx=5)

        ttk.Button(top, text="Şimdi Tara", command=self.scan_once).grid(row=0, column=7, padx=5)
        ttk.Button(top, text="Chrome'u Kapat", command=self.close_browser).grid(row=0, column=8, padx=5)

        self.status_var = tk.StringVar(
            value="Hazır — API key yok. Tarama başlayınca normal Chrome penceresi açılır."
        )
        ttk.Label(root, textvariable=self.status_var, padding=(10, 0)).pack(fill="x")

        cols = ("skin", "charm", "buy", "base", "extra", "cprice", "adv", "float")
        self.tree = ttk.Treeview(root, columns=cols, show="headings")
        heads = {
            "skin": "Skin",
            "charm": "Takılı Charm",
            "buy": "Alış fiyatı",
            "base": "Charmsız taban",
            "extra": "Charm için fark",
            "cprice": "Charm market fiyatı",
            "adv": "Teorik avantaj",
            "float": "Float",
        }
        widths = {
            "skin": 335, "charm": 190, "buy": 90, "base": 105,
            "extra": 110, "cprice": 125, "adv": 110, "float": 125
        }
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=8)
        self.tree.bind("<Double-1>", self.open_selected)

        bottom = ttk.Frame(root, padding=10)
        bottom.pack(fill="x")
        ttk.Label(
            bottom,
            text=(
                "Chrome penceresini tarama sırasında kapatma. Program satın alma yapmaz. "
                "'Teorik avantaj' garanti/net kâr değildir."
            )
        ).pack(side="left")
        ttk.Button(bottom, text="Seçili ilan sayfasını aç", command=self.open_selected).pack(side="right")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def status(self, msg):
        self.root.after(0, lambda: self.status_var.set(msg))

    def read_settings(self):
        try:
            max_price = float(self.max_price.get())
            max_products = max(1, min(40, int(self.max_products.get())))
            interval = max(60, int(self.interval.get()))
        except ValueError:
            raise ValueError("Ayar alanlarına geçerli sayı gir.")
        cfg = load_config()
        cfg.update({
            "max_price": max_price,
            "max_products_per_category": max_products,
            "interval": interval
        })
        save_config(cfg)
        return max_price, max_products, interval

    def ensure_scanner(self):
        if self.scanner is None:
            self.scanner = BrowserScanner(self.status)
        self.scanner.start_browser()

    def scan_once(self):
        if self.running:
            return
        try:
            self.read_settings()
        except Exception as e:
            messagebox.showerror("Ayar", str(e))
            return
        threading.Thread(target=self.scan, daemon=True).start()

    def toggle(self):
        if self.running:
            self.running = False
            self.start_btn.config(text="Otomatik Taramayı Başlat")
            self.status("Otomatik tarama durduruldu.")
            return
        try:
            self.read_settings()
        except Exception as e:
            messagebox.showerror("Ayar", str(e))
            return
        self.running = True
        self.start_btn.config(text="Otomatik Taramayı Durdur")
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while self.running:
            self.scan()
            try:
                _, _, interval = self.read_settings()
            except Exception:
                interval = 300
            for _ in range(interval):
                if not self.running:
                    return
                time.sleep(1)

    def scan(self):
        try:
            max_price, max_products, _ = self.read_settings()
            self.ensure_scanner()

            all_rows = []
            scanned = 0
            for cid, cname in CHARM_CATEGORIES.items():
                if not self.running and threading.current_thread().name != "MainThread":
                    # For one-shot scans, running is False by design; don't use it as cancel flag.
                    pass
                self.status(f"{cname}: Skin.Land kataloğu Chrome ile açılıyor...")
                try:
                    links = self.scanner.market_product_links(
                        cid, page_no=1, max_count=max_products
                    )
                except Exception as e:
                    self.status(f"{cname}: atlandı — {str(e)[:180]}")
                    continue

                for idx, url in enumerate(links, 1):
                    self.status(f"{cname}: {idx}/{len(links)} ürün inceleniyor...")
                    try:
                        rows = self.scanner.scan_product(url, cid)
                    except Exception:
                        continue
                    scanned += 1
                    for r in rows:
                        if r["buy_price"] <= max_price:
                            all_rows.append(r)

            uniq = {}
            for r in all_rows:
                k = (r["skin"], r["charm"], r["buy_price"], r["float"])
                uniq[k] = r
            self.results = list(uniq.values())
            self.results.sort(
                key=lambda r: (
                    -(r["theoretical"] if r["theoretical"] is not None else -999999),
                    r["buy_price"]
                )
            )
            self.root.after(0, self.render)
            self.status(
                f"Bitti • {scanned} ürün sayfası incelendi • "
                f"{len(self.results)} charm'lı teklif bulundu."
            )
        except Exception as e:
            self.status("Hata: " + str(e))

    def fmt(self, v):
        return "-" if v is None else f"${v:,.2f}"

    def render(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, r in enumerate(self.results):
            self.tree.insert("", "end", iid=str(i), values=(
                r["skin"], r["charm"], self.fmt(r["buy_price"]),
                self.fmt(r["base_price"]), self.fmt(r["extra_paid"]),
                self.fmt(r["charm_price"]), self.fmt(r["theoretical"]),
                r["float"] or "-"
            ))

    def open_selected(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        webbrowser.open(self.results[idx]["url"])

    def close_browser(self):
        if self.scanner:
            self.scanner.close()
            self.scanner = None
            self.status("Chrome kapatıldı.")

    def on_close(self):
        self.running = False
        self.close_browser()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()
