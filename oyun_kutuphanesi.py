"""
Oyun Kütüphanesi - masaüstü uygulaması (Python + tkinter)
Oyunlarını ekle, kapaklarını göster, Oyna tuşuyla başlat.

Çalıştırma:   python oyun_kutuphanesi.py
Kapak için:   pip install pillow   (önerilir; olmazsa sadece PNG/GIF kapaklar çalışır)
"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageOps
    PIL_OK = True
except ImportError:
    PIL_OK = False

# ---------- Ayarlar / renkler ----------
APP_DIR = Path.home() / "OyunKutuphanesi"
COVERS = APP_DIR / "kapaklar"
DATA = APP_DIR / "oyunlar.json"
APP_DIR.mkdir(exist_ok=True)
COVERS.mkdir(exist_ok=True)

BG, PANEL, PANEL2, LINE = "#0e1015", "#171a22", "#1f2430", "#2a3040"
TEXT, MUTE, ACC, OK, BAD = "#e8ebf2", "#8b93a7", "#4f8cff", "#2ecc71", "#ff5c6c"
CW, CH = 190, 253          # kapak boyutu
CARD_W = CW + 24


def load_games():
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_games(games):
    DATA.write_text(json.dumps(games, ensure_ascii=False, indent=1), encoding="utf-8")


def launch(path):
    """Exe, bat, html, link ya da herhangi bir dosyayı başlatır."""
    if path.lower().startswith(("http://", "https://")):
        webbrowser.open(path)
        return
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dosya bulunamadı:\n{path}")
    workdir = str(p.parent)  # oyunlar kendi klasöründen başlamalı
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # noqa  (cwd için aşağıdaki yedek)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)], cwd=workdir)
    else:
        if os.access(p, os.X_OK) and p.is_file() and p.suffix.lower() not in (".html", ".htm"):
            subprocess.Popen([str(p)], cwd=workdir)
        else:
            subprocess.Popen(["xdg-open", str(p)], cwd=workdir)


def launch_win_cwd(path):
    """Windows'ta oyunu kendi klasöründe çalıştırır (exe'ler kaynak dosyalarını bulsun diye)."""
    p = Path(path)
    if p.suffix.lower() in (".exe", ".bat", ".cmd", ".lnk"):
        subprocess.Popen(f'"{p}"', cwd=str(p.parent), shell=True)
    else:
        os.startfile(str(p))  # noqa


def make_cover_image(file):
    """Kapağı kayıtlı klasöre kopyalar/boyutlandırır, yeni dosya adını döner."""
    name = f"{uuid.uuid4().hex}.png"
    dest = COVERS / name
    if PIL_OK:
        img = Image.open(file).convert("RGB")
        img = ImageOps.fit(img, (CW * 2, CH * 2), Image.LANCZOS)
        img.save(dest)
    else:
        shutil.copy(file, dest)
    return name


class AddDialog(tk.Toplevel):
    def __init__(self, master, game=None):
        super().__init__(master)
        self.title("Oyunu Düzenle" if game else "Oyun Ekle")
        self.configure(bg=PANEL, padx=20, pady=18)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.old = game
        self.cover = game.get("cover") if game else None
        self.new_cover_file = None

        self.v_name = tk.StringVar(value=game["name"] if game else "")
        self.v_path = tk.StringVar(value=game["path"] if game else "")
        self.v_cover = tk.StringVar(value="(mevcut kapak)" if self.cover else "(kapak seçilmedi)")

        def row(label, var, btn=None, cmd=None):
            tk.Label(self, text=label, bg=PANEL, fg=MUTE, anchor="w").pack(fill="x", pady=(8, 2))
            f = tk.Frame(self, bg=PANEL)
            f.pack(fill="x")
            e = tk.Entry(f, textvariable=var, bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                         relief="flat", width=46, highlightthickness=1,
                         highlightbackground=LINE, highlightcolor=ACC)
            e.pack(side="left", ipady=6, fill="x", expand=True)
            if btn:
                tk.Button(f, text=btn, command=cmd, bg=PANEL2, fg=TEXT, relief="flat",
                          activebackground=LINE, activeforeground=TEXT, padx=10).pack(side="left", padx=(6, 0), ipady=3)
            return e

        row("Oyun adı", self.v_name)
        row("Oyun dosyası veya link (.exe, .bat, .html, https://...)", self.v_path, "Seç...", self.pick_game)
        tk.Label(self, text="Kapak resmi", bg=PANEL, fg=MUTE, anchor="w").pack(fill="x", pady=(8, 2))
        f = tk.Frame(self, bg=PANEL)
        f.pack(fill="x")
        tk.Label(f, textvariable=self.v_cover, bg=PANEL2, fg=TEXT, anchor="w").pack(side="left", fill="x", expand=True, ipady=6, ipadx=6)
        tk.Button(f, text="Seç...", command=self.pick_cover, bg=PANEL2, fg=TEXT, relief="flat",
                  activebackground=LINE, activeforeground=TEXT, padx=10).pack(side="left", padx=(6, 0), ipady=3)
        if not PIL_OK:
            tk.Label(self, text="İpucu: 'pip install pillow' ile her tür resim (jpg dahil) kapak olur.",
                     bg=PANEL, fg=MUTE, font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

        b = tk.Frame(self, bg=PANEL)
        b.pack(fill="x", pady=(18, 0))
        tk.Button(b, text="Kaydet", command=self.save, bg=ACC, fg="white", relief="flat",
                  font=("Segoe UI", 10, "bold"), padx=18, pady=6).pack(side="right")
        tk.Button(b, text="Vazgeç", command=self.destroy, bg=PANEL2, fg=MUTE, relief="flat",
                  padx=14, pady=6).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_visibility()
        self.focus_force()

    def pick_game(self):
        f = filedialog.askopenfilename(title="Oyun dosyasını seç")
        if f:
            self.v_path.set(f)
            if not self.v_name.get().strip():
                self.v_name.set(Path(f).stem)

    def pick_cover(self):
        types = [("Resimler", "*.png *.jpg *.jpeg *.webp *.bmp *.gif")] if PIL_OK else [("PNG / GIF", "*.png *.gif")]
        f = filedialog.askopenfilename(title="Kapak resmini seç", filetypes=types)
        if f:
            self.new_cover_file = f
            self.v_cover.set(Path(f).name)

    def save(self):
        name, path = self.v_name.get().strip(), self.v_path.get().strip().strip('"')
        if not name or not path:
            messagebox.showwarning("Eksik bilgi", "Oyun adı ve oyun dosyası/link gerekli.", parent=self)
            return
        cover = self.cover
        if self.new_cover_file:
            try:
                cover = make_cover_image(self.new_cover_file)
            except Exception as e:
                messagebox.showerror("Kapak hatası", str(e), parent=self)
                return
        self.result = {"id": self.old["id"] if self.old else uuid.uuid4().hex,
                       "name": name, "path": path, "cover": cover,
                       "added": self.old.get("added", time.time()) if self.old else time.time(),
                       "last": self.old.get("last", 0) if self.old else 0,
                       "plays": self.old.get("plays", 0) if self.old else 0}
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Oyun Kütüphanesi")
        self.geometry("1100x720")
        self.minsize(560, 420)
        self.configure(bg=BG)
        self.games = load_games()
        self.imgs = {}
        self.cols = 0

        # Üst çubuk
        top = tk.Frame(self, bg=PANEL, padx=18, pady=12)
        top.pack(fill="x")
        tk.Label(top, text="🎮  Oyun Kütüphanesi", bg=PANEL, fg=TEXT, font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Button(top, text="+ Oyun Ekle", command=self.add, bg=ACC, fg="white", relief="flat",
                  font=("Segoe UI", 10, "bold"), padx=16, pady=6, cursor="hand2").pack(side="right")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self.render(force=True))
        e = tk.Entry(top, textvariable=self.q, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat",
                     width=26, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC)
        e.pack(side="right", padx=14, ipady=6)
        tk.Label(top, text="Ara:", bg=PANEL, fg=MUTE).pack(side="right")

        # Kaydırılabilir alan
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.on_resize)
        self.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))
        self.render(force=True)

    # ----- veri -----
    def add(self):
        d = AddDialog(self)
        self.wait_window(d)
        if d.result:
            self.games.insert(0, d.result)
            save_games(self.games)
            self.render(force=True)

    def edit(self, g):
        d = AddDialog(self, g)
        self.wait_window(d)
        if d.result:
            i = self.games.index(g)
            self.games[i] = d.result
            self.imgs.pop(g["id"], None)
            save_games(self.games)
            self.render(force=True)

    def delete(self, g):
        if messagebox.askyesno("Sil", f"“{g['name']}” kütüphaneden silinsin mi?\n(Oyunun kendisi bilgisayardan silinmez.)"):
            self.games.remove(g)
            if g.get("cover"):
                try:
                    (COVERS / g["cover"]).unlink()
                except OSError:
                    pass
            self.imgs.pop(g["id"], None)
            save_games(self.games)
            self.render(force=True)

    def play(self, g):
        try:
            if sys.platform.startswith("win") and not g["path"].lower().startswith("http"):
                p = Path(g["path"])
                if not p.exists():
                    raise FileNotFoundError(f"Dosya bulunamadı:\n{g['path']}")
                launch_win_cwd(g["path"])
            else:
                launch(g["path"])
            g["plays"] = g.get("plays", 0) + 1
            g["last"] = time.time()
            save_games(self.games)
        except Exception as e:
            messagebox.showerror("Oyun başlatılamadı", str(e))

    # ----- çizim -----
    def cover_image(self, g):
        if g["id"] in self.imgs:
            return self.imgs[g["id"]]
        img = None
        f = COVERS / g["cover"] if g.get("cover") else None
        if f and f.exists():
            try:
                if PIL_OK:
                    im = ImageOps.fit(Image.open(f).convert("RGB"), (CW, CH), Image.LANCZOS)
                    img = ImageTk.PhotoImage(im)
                else:
                    img = tk.PhotoImage(file=str(f))
                    k = max(1, -(-img.width() // CW), -(-img.height() // CH))
                    img = img.subsample(k, k)
            except Exception:
                img = None
        self.imgs[g["id"]] = img
        return img

    def placeholder(self, parent, g):
        h = sum(map(ord, g["name"])) % 360
        import colorsys
        r, gg, b = colorsys.hls_to_rgb(h / 360, .32, .55)
        col = "#%02x%02x%02x" % (int(r * 255), int(gg * 255), int(b * 255))
        c = tk.Canvas(parent, width=CW, height=CH, bg=col, highlightthickness=0, cursor="hand2")
        c.create_text(CW // 2, CH // 2, text=g["name"][:1].upper(), fill="white", font=("Segoe UI", 64, "bold"))
        return c

    def on_resize(self, e):
        self.canvas.itemconfigure(self.win, width=e.width)
        cols = max(1, e.width // (CARD_W + 16))
        if cols != self.cols:
            self.render(force=True)

    def render(self, force=False):
        w = self.canvas.winfo_width()
        cols = max(1, (w if w > 1 else 1000) // (CARD_W + 16))
        self.cols = cols
        for c in self.inner.winfo_children():
            c.destroy()
        q = self.q.get().strip().lower()
        shown = [g for g in self.games if q in g["name"].lower()]
        if not shown:
            msg = "Kütüphanen boş.\nSağ üstteki “+ Oyun Ekle” ile ilk oyunu ekle." if not self.games else "Aramaya uygun oyun yok."
            tk.Label(self.inner, text=msg, bg=BG, fg=MUTE, font=("Segoe UI", 13), pady=120).grid(row=0, column=0, padx=40)
            return
        for i, g in enumerate(shown):
            card = tk.Frame(self.inner, bg=PANEL, highlightthickness=1, highlightbackground=LINE, padx=10, pady=10)
            card.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="n")
            img = self.cover_image(g)
            if img:
                lbl = tk.Label(card, image=img, bg=PANEL, cursor="hand2", bd=0)
            else:
                lbl = self.placeholder(card, g)
            lbl.pack()
            lbl.bind("<Double-Button-1>", lambda e, g=g: self.play(g))
            tk.Label(card, text=g["name"], bg=PANEL, fg=TEXT, font=("Segoe UI", 11, "bold"),
                     wraplength=CW, pady=6).pack()
            plays = g.get("plays", 0)
            tk.Label(card, text=f"{plays} kez oynandı" if plays else "Henüz oynanmadı",
                     bg=PANEL, fg=MUTE, font=("Segoe UI", 8)).pack()
            tk.Button(card, text="▶  Oyna", command=lambda g=g: self.play(g), bg=OK, fg="#06210f",
                      relief="flat", font=("Segoe UI", 10, "bold"), cursor="hand2", pady=5,
                      activebackground="#27ae60").pack(fill="x", pady=(8, 4))
            sub = tk.Frame(card, bg=PANEL)
            sub.pack(fill="x")
            tk.Button(sub, text="Düzenle", command=lambda g=g: self.edit(g), bg=PANEL2, fg=MUTE, relief="flat",
                      font=("Segoe UI", 8)).pack(side="left", expand=True, fill="x", padx=(0, 2))
            tk.Button(sub, text="Sil", command=lambda g=g: self.delete(g), bg=PANEL2, fg=BAD, relief="flat",
                      font=("Segoe UI", 8)).pack(side="left", expand=True, fill="x", padx=(2, 0))


if __name__ == "__main__":
    App().mainloop()
