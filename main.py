import json
import os
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

import requests

API_URL = "https://www.steamwebapi.com/market/skinland/prices"
CONFIG_FILE = "config.json"
CHARMS_FILE = "charms.json"


def load_charms():
    try:
        with open(CHARMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("charms", [])
    except Exception:
        return []


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"api_key": "", "interval": 300, "max_price": 10000.0}


def save_config(c):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("CS2 Skin.Land Charm Scanner")
        self.root.geometry("1100x650")
        self.root.minsize(900, 550)

        self.config = load_config()
        self.charms = load_charms()
        self.running = False
        self.last_items = []

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="SteamWebAPI Key:").grid(row=0, column=0, sticky="w")
        self.key = ttk.Entry(top, width=55, show="*")
        self.key.insert(0, self.config.get("api_key", ""))
        self.key.grid(row=0, column=1, padx=6)

        ttk.Label(top, text="Tarama (sn):").grid(row=0, column=2, padx=(15, 3))
        self.interval = ttk.Entry(top, width=8)
        self.interval.insert(0, str(self.config.get("interval", 300)))
        self.interval.grid(row=0, column=3)

        ttk.Label(top, text="Max fiyat $:").grid(row=0, column=4, padx=(15, 3))
        self.max_price = ttk.Entry(top, width=10)
        self.max_price.insert(0, str(self.config.get("max_price", 10000)))
        self.max_price.grid(row=0, column=5)

        self.start_btn = ttk.Button(top, text="Taramayı Başlat", command=self.toggle)
        self.start_btn.grid(row=0, column=6, padx=12)

        ttk.Button(top, text="Şimdi Tara", command=self.scan_once).grid(row=0, column=7)

        self.status = tk.StringVar(value="Hazır")
        ttk.Label(root, textvariable=self.status, padding=(10, 0)).pack(fill="x")

        columns = ("name", "charm", "price", "quantity", "created")
        self.tree = ttk.Treeview(root, columns=columns, show="headings")
        headings = {
            "name": "Skin / Item",
            "charm": "Charm",
            "price": "Skin.Land Fiyatı",
            "quantity": "Adet",
            "created": "Veri zamanı",
        }
        widths = {"name": 540, "charm": 180, "price": 120, "quantity": 70, "created": 160}
        for c in columns:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=8)
        self.tree.bind("<Double-1>", self.open_selected)

        bottom = ttk.Frame(root, padding=10)
        bottom.pack(fill="x")
        ttk.Label(
            bottom,
            text="Çift tıklayarak Skin.Land aramasını aç. Program hiçbir satın alma işlemi yapmaz."
        ).pack(side="left")
        ttk.Button(bottom, text="Seçili Skin.Land'de Aç", command=self.open_selected).pack(side="right")

    def set_status(self, text):
        self.root.after(0, lambda: self.status.set(text))

    def toggle(self):
        if self.running:
            self.running = False
            self.start_btn.config(text="Taramayı Başlat")
            self.set_status("Tarama durduruldu.")
            return

        key = self.key.get().strip()
        if not key:
            messagebox.showwarning("API Key", "Önce SteamWebAPI API key gir.")
            return

        try:
            interval = max(60, int(self.interval.get()))
            max_price = float(self.max_price.get())
        except ValueError:
            messagebox.showerror("Ayar", "Tarama süresi ve maksimum fiyat sayı olmalı.")
            return

        self.config.update({"api_key": key, "interval": interval, "max_price": max_price})
        save_config(self.config)

        self.running = True
        self.start_btn.config(text="Taramayı Durdur")
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while self.running:
            self.scan()
            for _ in range(int(self.config["interval"])):
                if not self.running:
                    return
                time.sleep(1)

    def scan_once(self):
        if not self.key.get().strip():
            messagebox.showwarning("API Key", "Önce SteamWebAPI API key gir.")
            return
        try:
            self.config["max_price"] = float(self.max_price.get())
            self.config["api_key"] = self.key.get().strip()
            save_config(self.config)
        except ValueError:
            messagebox.showerror("Ayar", "Maksimum fiyat sayı olmalı.")
            return
        threading.Thread(target=self.scan, daemon=True).start()

    def scan(self):
        self.set_status("Skin.Land verisi alınıyor...")
        try:
            r = requests.get(
                API_URL,
                headers={"X-Api-Key": self.config["api_key"]},
                timeout=30,
            )
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            if isinstance(data, dict):
                # Bazı API sürümlerinde liste bir alan altında dönebilir.
                for k in ("items", "data", "results"):
                    if isinstance(data.get(k), list):
                        data = data[k]
                        break
            if not isinstance(data, list):
                raise RuntimeError("API beklenen liste formatında veri döndürmedi.")

            results = []
            max_price = float(self.config["max_price"])

            for item in data:
                name = str(item.get("market_hash_name", item.get("name", "")))
                price = item.get("price")
                try:
                    price = float(price)
                except (TypeError, ValueError):
                    continue

                if price > max_price:
                    continue

                matches = [c for c in self.charms if c.lower() in name.lower()]
                for charm in matches:
                    results.append((
                        name,
                        charm,
                        price,
                        item.get("quantity", 1),
                        item.get("createdat", "")
                    ))

            results.sort(key=lambda x: x[2])
            self.last_items = results
            self.root.after(0, self.render)
            self.set_status(f"{len(data):,} item tarandı • {len(results)} charm eşleşmesi bulundu.")
        except Exception as e:
            self.set_status(f"Hata: {e}")

    def render(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for row in self.last_items:
            self.tree.insert("", "end", values=(
                row[0], row[1], f"${row[2]:,.2f}", row[3], row[4]
            ))

    def open_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        name = values[0]
        # Skin.Land'in site aramasını güvenli şekilde aç.
        import urllib.parse
        url = "https://skin.land/market/cs2/?search=" + urllib.parse.quote(name)
        webbrowser.open(url)


if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()
