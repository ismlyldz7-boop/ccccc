import json
import os
import re
import threading
import time
import urllib.parse
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

import requests
from bs4 import BeautifulSoup

BASE = "https://skin.land"
MARKET = BASE + "/market/cs2/"
CONFIG_FILE = "config.json"
CHARMS_FILE = "charms.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0.0.0 Safari/537.36"
)

COLLECTION_NAMES = [
    "Dr Boom Charm Collection",
    "Missing Link Charm Collection",
    "Missing Link Community Charm Collection",
    "Small Arms Charm Collection",
]


def app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def fpath(name):
    return os.path.join(app_dir(), name)


def load_json(name, default):
    try:
        with open(fpath(name), "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(name, data):
    with open(fpath(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def money_values(text):
    vals = []
    for x in re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", text):
        try:
            vals.append(float(x.replace(",", "")))
        except Exception:
            pass
    return vals


def clean_text(node):
    return " ".join(node.get_text(" ", strip=True).split())


class Scanner:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
        })
        cfg = load_json(CONFIG_FILE, {})
        self.delay = float(cfg.get("request_delay", 0.45))
        self.timeout = int(cfg.get("timeout", 20))
        charm_data = load_json(CHARMS_FILE, {"charms": []})
        self.charms = list(dict.fromkeys(charm_data.get("charms", [])))

    def get(self, url):
        r = self.s.get(url, timeout=self.timeout)
        if r.status_code in (401, 402):
            raise RuntimeError(
                f"Skin.Land HTTP {r.status_code}. Bu sürüm SteamWebAPI kullanmaz; "
                "bu cevap doğrudan Skin.Land'den geldiyse sayfa erişimi kısıtlanmış olabilir."
            )
        if r.status_code == 403:
            raise RuntimeError(
                "Skin.Land HTTP 403 döndürdü. Site otomatik isteği engelliyor olabilir. "
                "Bu durumda tarayıcı tabanlı sürüme geçmemiz gerekir."
            )
        r.raise_for_status()
        time.sleep(self.delay)
        return r.text

    def discover_charm_names(self, max_pages=8):
        found = set(self.charms)
        for page in range(1, max_pages + 1):
            url = MARKET + "?" + urllib.parse.urlencode({"query": "Charm", "page": page})
            html = self.get(url)
            names = set(re.findall(r"Charm\s*\|\s*([^<\n\r$]{2,80})", html, re.I))
            before = len(found)
            for n in names:
                n = re.sub(r"\s+", " ", BeautifulSoup(n, "html.parser").get_text(" ", strip=True)).strip()
                if n and len(n) <= 80:
                    found.add(n)
            if page > 2 and len(found) == before:
                break
        self.charms = sorted(found, key=len, reverse=True)
        save_json(CHARMS_FILE, {"charms": sorted(found)})
        return len(found)

    def discover_category_ids(self):
        # First try to extract IDs from Skin.Land's own HTML/embedded JSON.
        html = self.get(MARKET)
        result = {}
        for cname in COLLECTION_NAMES:
            pos = html.lower().find(cname.lower())
            if pos >= 0:
                snippet = html[max(0, pos - 1000): pos + 1000]
                patterns = [
                    r'charm_category_id[^0-9]{0,80}([0-9]{1,3})',
                    r'["\']id["\'][^0-9]{0,30}([0-9]{1,3})',
                    r'\\?"id\\?"\s*:\s*([0-9]{1,3})',
                ]
                for pat in patterns:
                    ids = re.findall(pat, snippet, re.I)
                    if ids:
                        result[cname] = int(ids[-1])
                        break

        # Known current Small Arms ID, verified on Skin.Land.
        result.setdefault("Small Arms Charm Collection", 22)

        # If HTML did not expose the remaining IDs, probe a narrow range around 22.
        missing = [x for x in COLLECTION_NAMES if x not in result]
        if missing:
            for cid in range(15, 31):
                if cid in result.values():
                    continue
                url = MARKET + f"?charm_category_id={cid}"
                try:
                    h = self.get(url)
                except Exception:
                    continue
                text = BeautifulSoup(h, "html.parser").get_text(" ", strip=True)
                for cname in list(missing):
                    # A selected filter is rendered near the word Charm on current Skin.Land pages.
                    if re.search(r"Charm\s+" + re.escape(cname), text, re.I):
                        result[cname] = cid
                        missing.remove(cname)
                if not missing:
                    break
        return result

    def catalog_product_urls(self, category_id, pages=1, max_price=None):
        urls = []
        seen = set()
        for page in range(1, pages + 1):
            params = {"charm_category_id": category_id, "page": page}
            if max_price is not None:
                # Site currently accepts price filters through its UI; harmless if ignored.
                params["price_to"] = str(max_price)
            url = MARKET + "?" + urllib.parse.urlencode(params)
            html = self.get(url)
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if "/market/cs2/" not in href:
                    continue
                full = urllib.parse.urljoin(BASE, href)
                path = urllib.parse.urlparse(full).path.rstrip("/")
                if path in ("/market/cs2",):
                    continue
                slug = path.split("/")[-1]
                if not slug or slug.startswith("charm-"):
                    continue
                txt = clean_text(a)
                if "Buy now" not in txt and "on sale" not in txt.lower():
                    continue
                full = full.split("?")[0]
                if full not in seen:
                    seen.add(full)
                    urls.append(full)
        return urls

    def offer_blocks(self, html):
        soup = BeautifulSoup(html, "html.parser")
        blocks = []
        seen = set()
        # Locate each "Buy now" and climb to the smallest sensible container.
        for txt in soup.find_all(string=re.compile(r"Buy now", re.I)):
            node = txt.parent
            candidate = None
            for _ in range(9):
                if node is None:
                    break
                t = clean_text(node)
                if 30 <= len(t) <= 3500 and len(re.findall(r"Buy now", t, re.I)) == 1:
                    candidate = node
                    if len(t) > 90:
                        break
                node = node.parent
            if candidate is None:
                continue
            t = clean_text(candidate)
            key = t[:1000]
            if key not in seen:
                seen.add(key)
                blocks.append((candidate, t))
        return blocks

    def match_charms(self, text):
        low = text.lower()
        matches = []
        for c in self.charms:
            if c.lower() in low:
                matches.append(c)
        # longest names first and remove names that are substrings of a longer match
        matches.sort(key=len, reverse=True)
        out = []
        for m in matches:
            if not any(m.lower() in x.lower() for x in out):
                out.append(m)
        return out

    def parse_offers(self, html, product_url, only_charmed=False):
        offers = []
        for _, text in self.offer_blocks(html):
            vals = money_values(text)
            if not vals:
                continue
            # Final offer price is normally the last $ value immediately before Buy now.
            price = vals[-1]
            floats = re.findall(r"\b0\.\d{6,16}\b", text)
            flt = floats[0] if floats else ""
            charms = self.match_charms(text)
            if only_charmed and not charms:
                continue

            for charm in (charms or [""]):
                charm_value = None
                if charm:
                    pos = text.lower().find(charm.lower())
                    after = text[pos + len(charm): pos + len(charm) + 160]
                    cv = money_values(after)
                    if cv:
                        charm_value = cv[0]
                offers.append({
                    "price": price,
                    "float": flt,
                    "charm": charm,
                    "charm_value": charm_value,
                    "text": text,
                    "url": product_url,
                })
        # de-dupe
        uniq = []
        keys = set()
        for x in offers:
            k = (x["price"], x["float"], x["charm"])
            if k not in keys:
                keys.add(k)
                uniq.append(x)
        return uniq

    def product_name(self, html, fallback_url):
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        if h1:
            t = clean_text(h1)
            if t:
                return t
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        title = re.sub(r"^Buy\s+", "", title, flags=re.I)
        title = re.sub(r"\s+[–-]\s+price.*$", "", title, flags=re.I)
        return title or fallback_url.rstrip("/").split("/")[-1]

    def scan_product(self, url, category_id):
        base_html = self.get(url)
        name = self.product_name(base_html, url)

        # Find the cheapest visible offer with no recognized charm as baseline.
        base_offers = self.parse_offers(base_html, url, only_charmed=False)
        plain = [x for x in base_offers if not x["charm"]]
        base_price = min((x["price"] for x in plain), default=None)

        charmed_url = url + "?" + urllib.parse.urlencode({"charm_category_id": category_id})
        charmed_html = self.get(charmed_url)
        charmed = self.parse_offers(charmed_html, charmed_url, only_charmed=True)

        rows = []
        for o in charmed:
            extra_paid = None if base_price is None else o["price"] - base_price
            advantage = None
            if extra_paid is not None and o["charm_value"] is not None:
                advantage = o["charm_value"] - extra_paid
            rows.append({
                "skin": name,
                "charm": o["charm"],
                "price": o["price"],
                "base_price": base_price,
                "extra_paid": extra_paid,
                "charm_value": o["charm_value"],
                "advantage": advantage,
                "float": o["float"],
                "url": charmed_url,
            })
        return rows


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("CS2 Skin.Land Charm Scanner V2")
        self.root.geometry("1280x720")
        self.root.minsize(1000, 600)

        cfg = load_json(CONFIG_FILE, {})
        self.running = False
        self.results = []
        self.scanner = None

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Max alış $:").grid(row=0, column=0, sticky="w")
        self.max_price = ttk.Entry(top, width=9)
        self.max_price.insert(0, str(cfg.get("max_price", 100)))
        self.max_price.grid(row=0, column=1, padx=(5, 15))

        ttk.Label(top, text="Katalog sayfası/kategori:").grid(row=0, column=2)
        self.pages = ttk.Entry(top, width=6)
        self.pages.insert(0, str(cfg.get("pages", 1)))
        self.pages.grid(row=0, column=3, padx=(5, 15))

        ttk.Label(top, text="Tarama (sn):").grid(row=0, column=4)
        self.interval = ttk.Entry(top, width=7)
        self.interval.insert(0, str(cfg.get("interval", 300)))
        self.interval.grid(row=0, column=5, padx=(5, 15))

        self.start_btn = ttk.Button(top, text="Taramayı Başlat", command=self.toggle)
        self.start_btn.grid(row=0, column=6, padx=5)
        ttk.Button(top, text="Şimdi Tara", command=self.scan_once).grid(row=0, column=7, padx=5)

        self.status = tk.StringVar(value="Hazır — API key gerekmez.")
        ttk.Label(root, textvariable=self.status, padding=(10, 0)).pack(fill="x")

        columns = ("skin", "charm", "buy", "base", "extra", "charmv", "adv", "float")
        self.tree = ttk.Treeview(root, columns=columns, show="headings")
        heads = {
            "skin": "Skin",
            "charm": "Takılı Charm",
            "buy": "Alış fiyatı",
            "base": "Charmsız taban",
            "extra": "Charm için fark",
            "charmv": "Skin.Land charm değeri",
            "adv": "Teorik avantaj",
            "float": "Float",
        }
        widths = {"skin": 340, "charm": 170, "buy": 90, "base": 100,
                  "extra": 105, "charmv": 130, "adv": 105, "float": 120}
        for c in columns:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=8)
        self.tree.bind("<Double-1>", self.open_selected)

        bottom = ttk.Frame(root, padding=10)
        bottom.pack(fill="x")
        ttk.Label(
            bottom,
            text=("Not: 'Teorik avantaj' gerçek satış kârı değildir. "
                  "Skin.Land'deki görünen charm değeri ile charmsız tabana göre hesaplanır.")
        ).pack(side="left")
        ttk.Button(bottom, text="Seçili ilan sayfasını aç", command=self.open_selected).pack(side="right")

    def set_status(self, s):
        self.root.after(0, lambda: self.status.set(s))

    def settings(self):
        try:
            max_price = float(self.max_price.get())
            pages = max(1, min(10, int(self.pages.get())))
            interval = max(60, int(self.interval.get()))
        except ValueError:
            raise ValueError("Ayar alanlarına geçerli sayı gir.")
        cfg = load_json(CONFIG_FILE, {})
        cfg.update({"max_price": max_price, "pages": pages, "interval": interval})
        save_json(CONFIG_FILE, cfg)
        return max_price, pages, interval

    def toggle(self):
        if self.running:
            self.running = False
            self.start_btn.config(text="Taramayı Başlat")
            self.set_status("Tarama durduruldu.")
            return
        try:
            self.settings()
        except Exception as e:
            messagebox.showerror("Ayar", str(e))
            return
        self.running = True
        self.start_btn.config(text="Taramayı Durdur")
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while self.running:
            self.scan()
            try:
                _, _, interval = self.settings()
            except Exception:
                interval = 300
            for _ in range(interval):
                if not self.running:
                    return
                time.sleep(1)

    def scan_once(self):
        if self.running:
            return
        try:
            self.settings()
        except Exception as e:
            messagebox.showerror("Ayar", str(e))
            return
        threading.Thread(target=self.scan, daemon=True).start()

    def scan(self):
        try:
            max_price, pages, _ = self.settings()
            self.scanner = Scanner()

            self.set_status("Charm isimleri güncelleniyor...")
            try:
                ncharms = self.scanner.discover_charm_names()
            except Exception:
                ncharms = len(self.scanner.charms)

            self.set_status(f"{ncharms} charm biliniyor. Charm kategorileri bulunuyor...")
            cats = self.scanner.discover_category_ids()
            if not cats:
                raise RuntimeError("Skin.Land charm kategori ID'leri bulunamadı.")

            all_rows = []
            scanned_products = 0

            for cname, cid in cats.items():
                self.set_status(f"{cname}: katalog taranıyor...")
                urls = self.scanner.catalog_product_urls(cid, pages=pages, max_price=max_price)
                for idx, url in enumerate(urls, 1):
                    self.set_status(
                        f"{cname}: {idx}/{len(urls)} skin inceleniyor • toplam {scanned_products}"
                    )
                    try:
                        rows = self.scanner.scan_product(url, cid)
                    except Exception:
                        continue
                    scanned_products += 1
                    for r in rows:
                        if r["price"] <= max_price:
                            all_rows.append(r)

            # Keep unique rows, sort strongest theoretical advantage first, then price.
            uniq = {}
            for r in all_rows:
                k = (r["skin"], r["charm"], r["price"], r["float"])
                uniq[k] = r
            self.results = list(uniq.values())
            self.results.sort(
                key=lambda x: (
                    -(x["advantage"] if x["advantage"] is not None else -999999),
                    x["price"]
                )
            )
            self.root.after(0, self.render)
            self.set_status(
                f"Bitti • {scanned_products} skin sayfası incelendi • "
                f"{len(self.results)} charm'lı teklif bulundu."
            )
        except Exception as e:
            self.set_status("Hata: " + str(e))

    def fmt(self, v):
        return "-" if v is None else f"${v:,.2f}"

    def render(self):
        for x in self.tree.get_children():
            self.tree.delete(x)
        for i, r in enumerate(self.results):
            self.tree.insert("", "end", iid=str(i), values=(
                r["skin"],
                r["charm"],
                self.fmt(r["price"]),
                self.fmt(r["base_price"]),
                self.fmt(r["extra_paid"]),
                self.fmt(r["charm_value"]),
                self.fmt(r["advantage"]),
                r["float"] or "-",
            ))

    def open_selected(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        webbrowser.open(self.results[idx]["url"])


if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()
