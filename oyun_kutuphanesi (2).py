"""
Oyun Kütüphanesi - masaüstü uygulaması (Python + tkinter)
Koyu mor "launcher" tasarımı. Oyunlar diskten otomatik bulunur, sağ panelde Steam arkadaşların görünür.

Çalıştırma:    python oyun_kutuphanesi.py
Kapaklar için: pip install pillow   (önerilir: yuvarlak köşe, Steam kapakları ve avatarlar için gerekli)

Otomatik bulunanlar: Steam (tüm kütüphane klasörleri), Epic Games, GOG ve D:\\Games, D:\\Oyunlar gibi
yaygın klasörler. Ayarlar (⚙) menüsünden istediğin klasörü ekleyebilir veya "derin tarama" ile
tüm diskleri tarayabilirsin. Verilerin  ~/OyunKutuphanesi  klasöründe durur.
"""
import colorsys
import json
import os
import queue
import re
import shutil
import string
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageOps, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

# ---------- Ayarlar / renkler ----------
APP_DIR = Path.home() / "OyunKutuphanesi"
COVERS = APP_DIR / "kapaklar"
AVATARS = APP_DIR / "avatarlar"
DATA = APP_DIR / "oyunlar.json"
SETTINGS = APP_DIR / "ayarlar.json"
for _d in (APP_DIR, COVERS, AVATARS):
    _d.mkdir(exist_ok=True)

BG = "#1a1724"        # orta alan
SIDE = "#14121b"      # sol menü
RIGHT = "#16141d"     # sağ panel
PANEL = "#201c2e"
PANEL2 = "#282439"
LINE = "#322d48"
TEXT = "#ece9f7"
MUTE = "#8f8aa8"
ACC = "#7c5cff"
ACC2 = "#a050f0"
BAD = "#ff5c6c"
OK = "#2ecc9a"

CW, CH = 278, 156     # kart (kapak) boyutu
GAP = 22
RADIUS = 16
FONT = "Segoe UI"
STEAM64 = 76561197960265728


# ---------- veri yardımcıları ----------
def load_games():
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_games(games):
    DATA.write_text(json.dumps(games, ensure_ascii=False, indent=1), encoding="utf-8")


def load_settings():
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(s):
    SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def is_uri(path):
    return "://" in path


def launch(path):
    """Exe, bat, html, link, steam:// vb. her şeyi kendi klasöründen başlatır."""
    if is_uri(path):
        if sys.platform.startswith("win"):
            try:
                os.startfile(path)  # noqa
                return
            except OSError:
                pass
        webbrowser.open(path)
        return
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dosya bulunamadı:\n{path}")
    wd = str(p.parent) if p.is_file() else str(p)
    if sys.platform.startswith("win"):
        if p.suffix.lower() in (".exe", ".bat", ".cmd", ".lnk"):
            subprocess.Popen(f'"{p}"', cwd=wd, shell=True)
        else:
            os.startfile(str(p))  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)], cwd=wd)
    else:
        if os.access(p, os.X_OK) and p.is_file() and p.suffix.lower() not in (".html", ".htm"):
            subprocess.Popen([str(p)], cwd=wd)
        else:
            subprocess.Popen(["xdg-open", str(p)], cwd=wd)


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


def http_get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 OyunKutuphanesi"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def hue_of(name):
    return sum(map(ord, name)) % 360


def rgb_for(name, l=.32, s=.55, shift=0):
    r, g, b = colorsys.hls_to_rgb(((hue_of(name) + shift) % 360) / 360, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def hex_for(name, **kw):
    return "#%02x%02x%02x" % rgb_for(name, **kw)


def ago(ts):
    d = max(0, time.time() - ts)
    if d < 90:
        return "az önce"
    if d < 3600:
        return f"{int(d // 60)} dk önce"
    if d < 86400:
        return f"{int(d // 3600)} saat önce"
    return f"{int(d // 86400)} gün önce"


def rrect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def badge_label(g):
    s = g.get("source")
    if s in ("steam", "epic", "gog"):
        return s.upper()
    p = g["path"]
    if is_uri(p):
        return "WEB"
    return "HTML" if Path(p).suffix.lower() in (".html", ".htm") else "PC"


def style_menu(m):
    m.configure(bg=PANEL2, fg=TEXT, activebackground=ACC, activeforeground="white",
                bd=0, relief="flat", tearoff=0, font=(FONT, 10))
    return m


# ---------- Valve (VDF) dosyaları ----------
_TOK = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text):
    """Steam'in .vdf / .acf dosyalarını sözlüğe çevirir."""
    text = re.sub(r'(?m)^\s*//.*$', '', text)
    stack, key = [{}], None
    for m in _TOK.finditer(text):
        s, b = m.group(1), m.group(2)
        if b == "{":
            d = {}
            stack[-1][key if key is not None else ""] = d
            stack.append(d)
            key = None
        elif b == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            s = s.replace("\\\\", "\\")
            if key is None:
                key = s
            else:
                stack[-1][key] = s
                key = None
    return stack[0]


def vget(d, *path):
    """Büyük/küçük harfe bakmadan iç içe anahtar okur."""
    for p in path:
        if not isinstance(d, dict):
            return None
        low = {k.lower(): v for k, v in d.items()}
        d = low.get(p.lower())
    return d


# ---------- disk tarama ----------
def drive_roots():
    if sys.platform.startswith("win"):
        return [Path(f"{c}:\\") for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
    return [Path.home()]


def steam_root():
    cands = []
    if sys.platform.startswith("win"):
        try:
            import winreg
            for hive, sub, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        cands.append(winreg.QueryValueEx(k, val)[0])
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                cands.append(os.path.join(os.environ[env], "Steam"))
    elif sys.platform == "darwin":
        cands.append(str(Path.home() / "Library/Application Support/Steam"))
    else:
        h = Path.home()
        cands += [str(h / ".steam/steam"), str(h / ".local/share/Steam"),
                  str(h / ".var/app/com.valvesoftware.Steam/.local/share/Steam")]
    for c in cands:
        p = Path(c)
        try:
            if (p / "steamapps").exists() or (p / "config").exists():
                return p
        except OSError:
            pass
    return None


STEAM_SKIP_NAMES = ("steamworks", "proton", "steam linux runtime", "steam controller")


def scan_steam():
    out, root = [], steam_root()
    libs, seen = [], set()

    def add(p):
        p = Path(p)
        sa = p / "steamapps"
        try:
            if sa.is_dir() and str(sa).lower() not in seen:
                seen.add(str(sa).lower())
                libs.append(sa)
        except OSError:
            pass

    if root:
        add(root)
        try:
            data = parse_vdf((root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="ignore"))
            lf = vget(data, "libraryfolders") or {}
            for k, v in lf.items():
                if not k.isdigit():
                    continue
                p = v if isinstance(v, str) else vget(v, "path")
                if p:
                    add(p)
        except Exception:
            pass
    for dr in drive_roots():
        add(dr / "SteamLibrary")
        add(dr / "Steam")
    for sa in libs:
        for mf in sa.glob("appmanifest_*.acf"):
            try:
                st = vget(parse_vdf(mf.read_text(encoding="utf-8", errors="ignore")), "AppState")
                appid, name, idir = vget(st, "appid"), vget(st, "name"), vget(st, "installdir")
            except Exception:
                continue
            if not (appid and name and idir) or appid == "228980":
                continue
            if name.lower().startswith(STEAM_SKIP_NAMES):
                continue
            d = sa / "common" / idir
            if not d.exists():
                continue
            out.append({"name": name, "path": f"steam://rungameid/{appid}", "source": "steam",
                        "appid": appid, "dir": str(d)})
    return out


def scan_epic():
    out = []
    base = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    try:
        items = list(base.glob("*.item")) if base.is_dir() else []
    except OSError:
        items = []
    for f in items:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        name, loc = d.get("DisplayName"), d.get("InstallLocation")
        if not name or not loc or d.get("bIsIncompleteInstall") or not Path(loc).exists():
            continue
        cats = [str(c).lower() for c in d.get("AppCategories", [])]
        if cats and "games" not in cats:
            continue
        ns, cid, app = d.get("CatalogNamespace", ""), d.get("CatalogItemId", ""), d.get("AppName", "")
        uri = f"com.epicgames.launcher://apps/{ns}%3A{cid}%3A{app}?action=launch&silent=true"
        out.append({"name": name, "path": uri, "source": "epic", "appid": app, "dir": loc})
    return out


def scan_gog():
    out = []
    if not sys.platform.startswith("win"):
        return out
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games") as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as g:
                        name = winreg.QueryValueEx(g, "gameName")[0]
                        exe = winreg.QueryValueEx(g, "exe")[0]
                        path = winreg.QueryValueEx(g, "path")[0]
                    if Path(exe).exists():
                        out.append({"name": name, "path": exe, "source": "gog", "appid": sub, "dir": path})
                except OSError:
                    continue
    except OSError:
        pass
    return out


SKIP_WORDS = ("unins", "uninst", "setup", "install", "redist", "vcredist", "vc_redist", "dxsetup", "dotnet",
              "crash", "report", "updater", "update", "cleanup", "notification_helper", "dxwebsetup", "oalinst",
              "physx", "easyanticheat", "battleye", "7z", "cefprocess", "subprocess", "webhelper", "helper")
SKIP_DIRS = {"_commonredist", "commonredist", "redist", "redistributables", "directx", "dotnet", "vcredist",
             "__installer", "installer", "crashreporter", "crashpad", "_redist", "support", "tools"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def best_exe(folder, maxdepth=3):
    """Klasördeki asıl oyun exe'sini tahmin eder (kaldırıcı/kurulum dosyalarını atlar)."""
    folder = Path(folder)
    fn = norm(folder.name)
    base = len(folder.parts)
    best, bestkey = None, None
    for root, dirs, files in os.walk(folder):
        depth = len(Path(root).parts) - base
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS] if depth < maxdepth else []
        for f in files:
            if not f.lower().endswith(".exe"):
                continue
            stem = f[:-4].lower()
            if any(w in stem for w in SKIP_WORDS):
                continue
            p = os.path.join(root, f)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if size < 50_000:
                continue
            en = norm(stem)
            match = 1 if (fn and len(en) >= 3 and (fn in en or en in fn)) else 0
            key = (match * 2 + (1 if depth == 0 else 0), size)
            if bestkey is None or key > bestkey:
                best, bestkey = p, key
    return best


def pretty(name):
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip()


def scan_folder_games(root, known_dirs):
    """Bir klasörün altındaki her alt klasörü bir oyun sayar (ya da klasörün kendisi oyunsa onu)."""
    out = []
    root = Path(root)
    try:
        if not root.is_dir():
            return out
        ex = best_exe(root, 0)
        if ex and (norm(root.name) in norm(Path(ex).stem) or norm(Path(ex).stem) in norm(root.name)):
            return [{"name": pretty(root.name), "path": ex, "source": "folder", "dir": str(root)}]
        subs = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    for sub in subs:
        if str(sub).lower() in known_dirs or sub.name.lower() in ("steam", "steamlibrary", "common files"):
            continue
        ex = best_exe(sub)
        if ex:
            out.append({"name": pretty(sub.name), "path": ex, "source": "folder", "dir": str(sub)})
    return out


COMMON_GAME_DIRS = ["Games", "Oyunlar", "Oyun", "Game", "XboxGames",
                    r"Program Files\EA Games", r"Program Files (x86)\EA Games",
                    r"Program Files\Origin Games", r"Program Files (x86)\Origin Games",
                    r"Program Files\Ubisoft\Ubisoft Game Launcher\games",
                    r"Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games",
                    r"Program Files\Rockstar Games", r"Program Files\Riot Games"]

DEEP_SKIP = {"windows", "$recycle.bin", "system volume information", "programdata", "appdata", "node_modules",
             ".git", "winsxs", "windowsapps", "recovery", "perflogs", "msocache", "$windows.~bt", "windows.old",
             "intel", "amd", "nvidia", "drivers", "common files", "windows kits", "microsoft", "anaconda3",
             "miniconda3", "onedrive", "workshop", "shadercache", "downloading", "temp", "site-packages",
             "__pycache__", ".venv", "venv", "oyunkutuphanesi"}
GENERIC_DIRS = {"win64", "win32", "binaries", "x64", "x86", "bin", "bin64", "bin32", "shipping",
                "windowsnoeditor", "windows", "retail", "release"}


def is_marker(files):
    for f in files:
        if f in ("steam_api.dll", "steam_api64.dll", "unityplayer.dll", "galaxy64.dll") \
                or f.startswith("unitycrashhandler") or f.endswith(("-win64-shipping.exe", "-win32-shipping.exe")):
            return True
    return False


def deep_scan(known_dirs, status=None):
    """Tüm diskleri gezip oyun belirtisi (steam_api.dll, UnityPlayer.dll...) olan klasörleri bulur."""
    out, seen_exe, n = [], set(), 0
    for dr in drive_roots():
        stack = [(str(dr), 0)]
        while stack:
            cur, depth = stack.pop()
            if cur.lower() in known_dirs:
                continue
            n += 1
            if status and n % 300 == 0:
                status(f"Derin tarama: {n} klasör…")
            try:
                with os.scandir(cur) as it:
                    entries = list(it)
            except OSError:
                continue
            files, dirs = [], []
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        dirs.append(e)
                    elif e.is_file(follow_symlinks=False):
                        files.append(e.name.lower())
                except OSError:
                    pass
            if depth > 0 and is_marker(files):
                ex = best_exe(cur, 0)
                if ex and ex.lower() not in seen_exe:
                    seen_exe.add(ex.lower())
                    p = Path(cur)
                    for _ in range(4):
                        if p.name.lower() in GENERIC_DIRS and p.parent != p:
                            p = p.parent
                        else:
                            break
                    out.append({"name": pretty(p.name), "path": ex, "source": "folder", "dir": str(p)})
                continue
            if depth >= 8:
                continue
            for e in dirs:
                nm = e.name.lower()
                if nm in DEEP_SKIP or nm.startswith("python"):
                    continue
                stack.append((e.path, depth + 1))
    return out


def scan_all(deep=False, extra_folders=(), status=None):
    found = scan_steam() + scan_epic() + scan_gog()
    known = {os.path.normcase(f["dir"]).lower() for f in found if f.get("dir")}
    known |= {str(Path(f["dir"])).lower() for f in found if f.get("dir")}
    roots = []
    for dr in drive_roots():
        for sub in COMMON_GAME_DIRS:
            if sub.startswith("Program Files") and not sys.platform.startswith("win"):
                continue
            roots.append(dr / sub)
    roots += [Path(p) for p in extra_folders]
    if not sys.platform.startswith("win"):
        roots.append(Path.home() / "Games")
    for r in roots:
        if status:
            status(f"Taranıyor: {r}")
        found += scan_folder_games(r, known)
    if deep:
        known |= {str(Path(f["dir"])).lower() for f in found if f.get("dir")}
        exes = {f["path"].lower() for f in found}
        for g in deep_scan(known, status):
            if g["path"].lower() not in exes:
                found.append(g)
    return found


# ---------- Steam arkadaşları ----------
STATE_TXT = {1: "Çevrimiçi", 2: "Meşgul", 3: "Uzakta", 4: "Uykuda", 5: "Çevrimiçi", 6: "Çevrimiçi"}
STATE_COL = {1: "#57cbde", 2: BAD, 3: "#f5b041", 4: "#f5b041", 5: "#57cbde", 6: "#57cbde"}


def detect_steam_id(root):
    if not root:
        return ""
    try:
        d = parse_vdf((root / "config" / "loginusers.vdf").read_text(encoding="utf-8", errors="ignore"))
        users = vget(d, "users") or {}
        ids = [k for k in users if k.isdigit()]
        for k in ids:
            if str(vget(users[k], "MostRecent")) == "1":
                return k
        return ids[0] if ids else ""
    except Exception:
        return ""


def local_friends(root, sid):
    """API anahtarı yokken Steam'in yerel dosyasından arkadaş isimlerini okur (durum bilgisi yok)."""
    if not root:
        return []
    ud = root / "userdata"
    f = None
    try:
        if sid and str(sid).isdigit():
            c = ud / str(int(sid) - STEAM64) / "config" / "localconfig.vdf"
            if c.exists():
                f = c
        if not f:
            cs = sorted(ud.glob("*/config/localconfig.vdf"), key=lambda p: p.stat().st_mtime, reverse=True)
            f = cs[0] if cs else None
        if not f:
            return []
        data = parse_vdf(f.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    out = []
    for k, v in (vget(data, "UserLocalConfigStore", "friends") or {}).items():
        if k.isdigit() and isinstance(v, dict):
            name = vget(v, "name")
            if isinstance(name, str) and name:
                out.append({"id": str(int(k) + STEAM64), "name": name, "state": 0, "game": None,
                            "avatar": None, "api": False})
    return out


def fetch_friends(settings):
    """(arkadaşlar, mesaj) döner. API anahtarı varsa durum/oyun bilgisiyle, yoksa yerel isimlerle."""
    root = steam_root()
    sid = str(settings.get("steam_id") or "") or detect_steam_id(root)
    key = settings.get("steam_key")
    msg = ""
    if key and sid:
        try:
            u = f"https://api.steampowered.com/ISteamUser/GetFriendList/v1/?key={key}&steamid={sid}&relationship=friend"
            ids = [f["steamid"] for f in json.loads(http_get(u)).get("friendslist", {}).get("friends", [])]
            friends = []
            for i in range(0, len(ids), 100):
                u = ("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key=%s&steamids=%s"
                     % (key, ",".join(ids[i:i + 100])))
                for p in json.loads(http_get(u)).get("response", {}).get("players", []):
                    friends.append({"id": p["steamid"], "name": p.get("personaname", "?"),
                                    "state": int(p.get("personastate", 0)), "game": p.get("gameextrainfo"),
                                    "avatar_url": p.get("avatarmedium"), "avatar": None, "api": True})
            return friends, ""
        except urllib.error.HTTPError as e:
            msg = ("Arkadaş listen gizli. Steam → Profil → Gizlilik → 'Arkadaş listesi' herkese açık olmalı."
                   if e.code == 401 else
                   "Steam API anahtarı geçersiz görünüyor." if e.code == 403 else f"Steam hatası ({e.code}).")
        except Exception as e:
            msg = f"Steam'e bağlanılamadı: {e}"
    else:
        msg = "Çevrimiçi durumlarını görmek için Steam API anahtarı gir."
    return local_friends(root, sid), msg


# ---------- Pencereler ----------
class AddDialog(tk.Toplevel):
    def __init__(self, master, game=None):
        super().__init__(master)
        self.title("Oyunu Düzenle" if game else "Oyun Ekle")
        self.configure(bg=PANEL, padx=22, pady=20)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.old = game
        self.cover = game.get("cover") if game else None
        self.new_cover_file = None

        self.v_name = tk.StringVar(value=game["name"] if game else "")
        self.v_path = tk.StringVar(value=game["path"] if game else "")
        self.v_cover = tk.StringVar(value="(mevcut kapak)" if self.cover else "(kapak seçilmedi)")

        tk.Label(self, text="Oyunu Düzenle" if game else "Yeni Oyun Ekle", bg=PANEL, fg=TEXT,
                 font=(FONT, 14, "bold")).pack(anchor="w", pady=(0, 6))

        def btn(parent, text, cmd):
            return tk.Button(parent, text=text, command=cmd, bg=PANEL2, fg=TEXT, relief="flat",
                             activebackground=LINE, activeforeground=TEXT, padx=12, cursor="hand2")

        def row(label, var, bt=None, cmd=None):
            tk.Label(self, text=label, bg=PANEL, fg=MUTE, anchor="w").pack(fill="x", pady=(10, 3))
            f = tk.Frame(self, bg=PANEL)
            f.pack(fill="x")
            e = tk.Entry(f, textvariable=var, bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                         relief="flat", width=46, highlightthickness=1,
                         highlightbackground=LINE, highlightcolor=ACC)
            e.pack(side="left", ipady=7, fill="x", expand=True)
            if bt:
                btn(f, bt, cmd).pack(side="left", padx=(6, 0), ipady=3)
            return e

        self.e_name = row("Oyun adı", self.v_name)
        row("Oyun dosyası veya link (.exe, .bat, .html, https://...)", self.v_path, "Seç...", self.pick_game)
        tk.Label(self, text="Kapak resmi (yatay resimler en iyi görünür)", bg=PANEL, fg=MUTE,
                 anchor="w").pack(fill="x", pady=(10, 3))
        f = tk.Frame(self, bg=PANEL)
        f.pack(fill="x")
        tk.Label(f, textvariable=self.v_cover, bg=PANEL2, fg=TEXT, anchor="w").pack(
            side="left", fill="x", expand=True, ipady=7, ipadx=8)
        btn(f, "Seç...", self.pick_cover).pack(side="left", padx=(6, 0), ipady=3)
        if not PIL_OK:
            tk.Label(self, text="İpucu: 'pip install pillow' ile her tür resim (jpg dahil) kapak olur.",
                     bg=PANEL, fg=MUTE, font=(FONT, 8)).pack(anchor="w", pady=(6, 0))

        b = tk.Frame(self, bg=PANEL)
        b.pack(fill="x", pady=(20, 0))
        tk.Button(b, text="Kaydet", command=self.save, bg=ACC, fg="white", relief="flat",
                  activebackground=ACC2, activeforeground="white", cursor="hand2",
                  font=(FONT, 10, "bold"), padx=20, pady=7).pack(side="right")
        tk.Button(b, text="Vazgeç", command=self.destroy, bg=PANEL2, fg=MUTE, relief="flat",
                  cursor="hand2", padx=16, pady=7).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_visibility()
        self.focus_force()
        self.e_name.focus_set()

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
        r = dict(self.old or {})
        r.update({"id": r.get("id", uuid.uuid4().hex), "name": name, "path": path, "cover": cover,
                  "added": r.get("added", time.time()), "last": r.get("last", 0),
                  "plays": r.get("plays", 0), "fav": r.get("fav", False)})
        self.result = r
        self.destroy()


class SteamDialog(tk.Toplevel):
    def __init__(self, master, settings, detected_id):
        super().__init__(master)
        self.title("Steam'i bağla")
        self.configure(bg=PANEL, padx=22, pady=20)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.v_id = tk.StringVar(value=str(settings.get("steam_id") or detected_id or ""))
        self.v_key = tk.StringVar(value=settings.get("steam_key", ""))

        tk.Label(self, text="Steam arkadaşların", bg=PANEL, fg=TEXT, font=(FONT, 14, "bold")).pack(anchor="w")
        tk.Label(self, bg=PANEL, fg=MUTE, justify="left", wraplength=430, text=(
            "Arkadaşlarının çevrimiçi durumunu ve oynadığı oyunu görmek için ücretsiz bir Steam Web API "
            "anahtarı gerekir. Ayrıca Steam → Profil → Gizlilik ayarında 'Arkadaş listesi' herkese açık olmalı.\n"
            "Anahtar girmezsen yalnızca arkadaşlarının isimleri yerel Steam dosyasından okunur.")).pack(
            anchor="w", pady=(6, 4))

        def row(label, var):
            tk.Label(self, text=label, bg=PANEL, fg=MUTE, anchor="w").pack(fill="x", pady=(10, 3))
            tk.Entry(self, textvariable=var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", width=52,
                     highlightthickness=1, highlightbackground=LINE, highlightcolor=ACC).pack(fill="x", ipady=7)

        row("SteamID64 (17 haneli, otomatik bulundu)", self.v_id)
        row("Steam Web API anahtarı", self.v_key)
        link = tk.Label(self, text="Anahtarı buradan al (alan adı olarak 'localhost' yazabilirsin)", bg=PANEL,
                        fg=ACC, cursor="hand2", font=(FONT, 9, "underline"))
        link.pack(anchor="w", pady=(6, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open("https://steamcommunity.com/dev/apikey"))

        b = tk.Frame(self, bg=PANEL)
        b.pack(fill="x", pady=(18, 0))
        tk.Button(b, text="Kaydet", command=self.save, bg=ACC, fg="white", relief="flat", cursor="hand2",
                  activebackground=ACC2, activeforeground="white", font=(FONT, 10, "bold"),
                  padx=20, pady=7).pack(side="right")
        tk.Button(b, text="Vazgeç", command=self.destroy, bg=PANEL2, fg=MUTE, relief="flat", cursor="hand2",
                  padx=16, pady=7).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_visibility()
        self.focus_force()

    def save(self):
        sid, key = self.v_id.get().strip(), self.v_key.get().strip()
        if sid and not sid.isdigit():
            messagebox.showwarning("SteamID64", "SteamID64 sadece rakamlardan oluşur (17 hane).", parent=self)
            return
        self.result = {"steam_id": sid, "steam_key": key}
        self.destroy()


# ---------- Ana uygulama ----------
class App(tk.Tk):
    SORTS = {"added": "Eklenme tarihi", "name": "Ada göre (A-Z)",
             "last": "Son oynanan", "plays": "En çok oynanan"}

    def __init__(self):
        super().__init__()
        self.title("Oyun Kütüphanesi")
        self.geometry("1320x800")
        self.minsize(900, 540)
        self.configure(bg=BG)
        self.games = load_games()
        self.settings = load_settings()
        self.imgs = {}
        self.av_imgs = {}
        self.cols = 0
        self.view = "all"       # all / installed / fav
        self.sort = "added"
        self.ph = True          # arama kutusunda yer tutucu yazı var mı
        self.events = queue.Queue()
        self.scanning = False
        self.friends, self.friends_msg, self.friends_busy = [], "", False
        self.show_offline = False
        self.dirty = False

        self.build_sidebar()
        self.build_right()
        self.build_center()
        self.set_view("all")
        self.render_side()
        self.poll()
        # açılışta sessizce oyunları ara, arkadaşları getir
        self.after(300, lambda: self.start_scan(silent=bool(self.games)))
        self.after(500, self.start_friends)
        self.after(90_000, self.friends_loop)
        self.fetch_missing_covers()

    # ----- arayüz iskeleti -----
    def build_sidebar(self):
        side = tk.Frame(self, bg=SIDE, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        logo = tk.Frame(side, bg=SIDE)
        logo.pack(anchor="w", padx=28, pady=(34, 38))
        for ch, col in (("▲", "#6f6af8"), ("■", "#5b5fd6"), ("✕", "#8a5cf6"), ("●", "#a855f7")):
            tk.Label(logo, text=ch, bg=SIDE, fg=col, font=(FONT, 15, "bold")).pack(side="left", padx=1)

        self.nav = {}
        head = tk.Frame(side, bg=SIDE)
        head.pack(fill="x")
        tk.Frame(head, bg=ACC, width=3).pack(side="left", fill="y")
        tk.Label(head, text="🎮  Oyunlarım", bg=SIDE, fg=TEXT, font=(FONT, 11), anchor="w").pack(
            side="left", padx=22, pady=6)

        for key, label in (("all", "Tüm oyunlar"), ("installed", "Yüklü")):
            l = tk.Label(side, text=label, bg=SIDE, fg=MUTE, font=(FONT, 10), anchor="w", cursor="hand2")
            l.pack(fill="x", padx=(48, 0), pady=6)
            l.bind("<Button-1>", lambda e, k=key: self.set_view(k))
            self.nav[key] = l
        fav = tk.Label(side, text="🔖  Favoriler", bg=SIDE, fg=MUTE, font=(FONT, 11), anchor="w", cursor="hand2")
        fav.pack(fill="x", padx=(28, 0), pady=(22, 0))
        fav.bind("<Button-1>", lambda e: self.set_view("fav"))
        self.nav["fav"] = fav

        bottom = tk.Frame(side, bg=SIDE)
        bottom.pack(side="bottom", pady=(0, 30))
        av = tk.Canvas(bottom, width=60, height=60, bg=SIDE, highlightthickness=0)
        av.create_oval(4, 4, 56, 56, fill=ACC2, outline="")
        av.create_oval(12, 12, 48, 48, fill="#ff9f43", outline="")
        av.create_oval(21, 21, 39, 39, fill="#ffd166", outline="")
        av.create_oval(40, 40, 54, 54, fill=OK, outline=SIDE, width=3)
        av.pack()
        self.count_lbl = tk.Label(bottom, text="", bg=SIDE, fg=MUTE, font=(FONT, 10))
        self.count_lbl.pack(pady=(8, 0))

    def build_right(self):
        right = tk.Frame(self, bg=RIGHT, width=290)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self.right = right
        self.rcanvas = tk.Canvas(right, bg=RIGHT, highlightthickness=0)
        self.rcanvas.pack(fill="both", expand=True)
        self.side_inner = tk.Frame(self.rcanvas, bg=RIGHT)
        self.rwin = self.rcanvas.create_window((0, 0), window=self.side_inner, anchor="nw")
        self.side_inner.bind("<Configure>", lambda e: self.rcanvas.configure(scrollregion=self.rcanvas.bbox("all")))
        self.rcanvas.bind("<Configure>", lambda e: self.rcanvas.itemconfigure(self.rwin, width=e.width))

    def build_center(self):
        center = tk.Frame(self, bg=BG)
        center.pack(side="left", fill="both", expand=True)
        self.center = center

        top = tk.Frame(center, bg=BG)
        top.pack(fill="x", padx=48, pady=(30, 22))

        sbox = tk.Frame(top, bg=PANEL, highlightthickness=1, highlightbackground=PANEL)
        sbox.pack(side="left")
        tk.Label(sbox, text="🔍", bg=PANEL, fg=MUTE, font=(FONT, 10)).pack(side="left", padx=(12, 4))
        self.q = tk.StringVar()
        self.entry = tk.Entry(sbox, textvariable=self.q, bg=PANEL, fg=MUTE, insertbackground=TEXT,
                              relief="flat", width=26, font=(FONT, 11))
        self.entry.pack(side="left", ipady=9, padx=(0, 12))
        self.entry.insert(0, "Oyun ara...")
        self.entry.bind("<FocusIn>", self.search_in)
        self.entry.bind("<FocusOut>", self.search_out)
        self.q.trace_add("write", lambda *a: self.render())

        def icon_btn(text, cmd):
            return tk.Button(top, text=text, command=cmd, bg=PANEL, fg=MUTE, relief="flat", bd=0,
                             activebackground=PANEL2, activeforeground=TEXT, cursor="hand2",
                             font=(FONT, 12), width=3, pady=5)

        self.btn_sort = icon_btn("☰", self.sort_menu)
        self.btn_sort.pack(side="left", padx=(14, 0))
        self.btn_scan = icon_btn("⟳", lambda: self.start_scan())
        self.btn_scan.pack(side="left", padx=(8, 0))
        self.btn_set = icon_btn("⚙", self.settings_menu)
        self.btn_set.pack(side="right")
        self.status = tk.Label(top, text="", bg=BG, fg=MUTE, font=(FONT, 9))
        self.status.pack(side="right", padx=14)

        wrap = tk.Frame(center, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="n")
        self.inner.bind("<Configure>", self.on_inner)
        self.canvas.bind("<Configure>", self.on_resize)
        self.bind_all("<MouseWheel>", lambda e: self.scroll(e, -1 if e.delta > 0 else 1))
        self.bind_all("<Button-4>", lambda e: self.scroll(e, -1))
        self.bind_all("<Button-5>", lambda e: self.scroll(e, 1))

        fab = tk.Canvas(center, width=58, height=58, bg=BG, highlightthickness=0, cursor="hand2")
        rrect(fab, 4, 4, 54, 54, 16, fill=ACC, outline="")
        fab.create_text(29, 28, text="+", fill="white", font=(FONT, 22, "bold"))
        fab.bind("<Button-1>", lambda e: self.add())
        fab.place(relx=1.0, rely=1.0, x=-44, y=-30, anchor="se")

    def scroll(self, e, d):
        target = self.canvas
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except Exception:
            w = None
        while w is not None:
            if w is self.right:
                target = self.rcanvas
                break
            w = getattr(w, "master", None)
        target.yview_scroll(d * 2, "units")

    # ----- arama kutusu yer tutucusu -----
    def search_in(self, _=None):
        if self.ph:
            self.ph = False
            self.entry.delete(0, "end")
            self.entry.configure(fg=TEXT)

    def search_out(self, _=None):
        if not self.entry.get().strip():
            self.ph = True
            self.entry.delete(0, "end")
            self.entry.insert(0, "Oyun ara...")
            self.entry.configure(fg=MUTE)
            self.render()

    def query(self):
        return "" if self.ph else self.q.get().strip().lower()

    def set_status(self, text, clear_after=None):
        self.status.configure(text=text)
        if clear_after:
            self.after(clear_after, lambda t=text: self.status.cget("text") == t and self.status.configure(text=""))

    # ----- menüler / görünüm -----
    def set_view(self, v):
        self.view = v
        for k, l in self.nav.items():
            l.configure(fg=TEXT if k == v else MUTE)
        self.render()

    def sort_menu(self):
        m = style_menu(tk.Menu(self))
        for k, label in self.SORTS.items():
            m.add_command(label=("✓  " if k == self.sort else "     ") + label, command=lambda k=k: self.set_sort(k))
        m.tk_popup(self.btn_sort.winfo_rootx(), self.btn_sort.winfo_rooty() + self.btn_sort.winfo_height())

    def set_sort(self, k):
        self.sort = k
        self.render()

    def settings_menu(self):
        m = style_menu(tk.Menu(self))
        m.add_command(label="Diski tara (hızlı)", command=lambda: self.start_scan())
        m.add_command(label="Klasör ekle ve tara…", command=self.add_folder)
        m.add_command(label="Derin tarama (tüm diskler, yavaş)", command=lambda: self.start_scan(deep=True))
        m.add_separator()
        m.add_command(label="Steam'i bağla (arkadaşlar)…", command=self.steam_dialog)
        m.add_command(label="Arkadaş listesini yenile", command=self.start_friends)
        m.add_separator()
        m.add_command(label="Silinen oyunları geri getir", command=self.clear_ignored)
        m.add_command(label="Kapak klasörünü aç", command=lambda: launch(str(COVERS)))
        m.add_command(label="Kütüphane klasörünü aç", command=lambda: launch(str(APP_DIR)))
        m.tk_popup(self.btn_set.winfo_rootx() - 190, self.btn_set.winfo_rooty() + self.btn_set.winfo_height())

    def add_folder(self):
        d = filedialog.askdirectory(title="Oyunların bulunduğu klasörü seç")
        if d:
            fl = self.settings.setdefault("scan_folders", [])
            if d not in fl:
                fl.append(d)
                save_settings(self.settings)
            self.start_scan()

    def clear_ignored(self):
        self.settings["ignored"] = []
        save_settings(self.settings)
        self.start_scan()

    def steam_dialog(self):
        d = SteamDialog(self, self.settings, detect_steam_id(steam_root()))
        self.wait_window(d)
        if d.result:
            self.settings.update(d.result)
            save_settings(self.settings)
            self.start_friends()

    # ----- tarama -----
    def start_scan(self, deep=False, silent=False):
        if self.scanning:
            return
        self.scanning = True
        self.set_status("Oyunlar aranıyor…" if not deep else "Derin tarama başladı (uzun sürebilir)…")
        folders = list(self.settings.get("scan_folders", []))

        def work():
            try:
                found = scan_all(deep, folders, status=lambda t: self.events.put(("status", t)))
                self.events.put(("scan_done", found, silent, None))
            except Exception as e:
                self.events.put(("scan_done", [], silent, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def merge_found(self, found):
        have_paths = {g["path"].lower() for g in self.games}
        have_ids = {(g.get("source"), str(g.get("appid"))) for g in self.games if g.get("appid")}
        have_names = {g["name"].lower() for g in self.games}
        ignored = set(self.settings.get("ignored", []))
        new = []
        now = time.time()
        for f in sorted(found, key=lambda x: x["name"].lower(), reverse=True):
            p = f["path"].lower()
            if p in have_paths or p in ignored or f["name"].lower() in have_names:
                continue
            if f.get("appid") and (f["source"], str(f["appid"])) in have_ids:
                continue
            have_paths.add(p)
            have_names.add(f["name"].lower())
            g = {"id": uuid.uuid4().hex, "name": f["name"], "path": f["path"], "cover": None,
                 "added": now + len(new) * 0.001, "last": 0, "plays": 0, "fav": False,
                 "source": f["source"]}
            for k in ("dir", "appid"):
                if f.get(k):
                    g[k] = f[k]
            new.append(g)
        if new:
            self.games = new + self.games
            save_games(self.games)
        return new

    def fetch_missing_covers(self):
        """Kapağı olmayan Steam oyunları için kapağı Steam'den (yerel önbellek ya da internet) alır."""
        if not PIL_OK:
            return
        todo = [(g["id"], g["appid"]) for g in self.games
                if g.get("source") == "steam" and g.get("appid") and not g.get("cover")]
        if not todo:
            return

        def work():
            root = steam_root()
            for gid, appid in todo:
                tmp = APP_DIR / f"tmp_{appid}.jpg"
                try:
                    src = None
                    if root:
                        lc = root / "appcache" / "librarycache"
                        for pat in (f"{appid}_header.jpg", f"{appid}/header.jpg", f"{appid}/*/header.jpg",
                                    f"{appid}/*/library_header.jpg"):
                            hits = list(lc.glob(pat))
                            if hits:
                                src = hits[0]
                                break
                    if not src:
                        for url in (f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
                                    f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"):
                            try:
                                tmp.write_bytes(http_get(url))
                                src = tmp
                                break
                            except Exception:
                                continue
                    if src:
                        self.events.put(("cover", gid, make_cover_image(src)))
                except Exception:
                    pass
                finally:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass

        threading.Thread(target=work, daemon=True).start()

    # ----- arkadaşlar -----
    def start_friends(self):
        if self.friends_busy:
            return
        self.friends_busy = True
        settings = dict(self.settings)

        def work():
            try:
                friends, msg = fetch_friends(settings)
            except Exception as e:
                friends, msg = [], f"Steam hatası: {e}"
            for f in friends:
                u = f.get("avatar_url")
                if u:
                    p = AVATARS / u.rsplit("/", 1)[-1]
                    f["avatar"] = str(p) if p.exists() else None
            self.events.put(("friends", [dict(f) for f in friends], msg))
            changed = False
            if PIL_OK:
                for f in friends:
                    u = f.get("avatar_url")
                    if u and not f["avatar"]:
                        p = AVATARS / u.rsplit("/", 1)[-1]
                        try:
                            p.write_bytes(http_get(u))
                            f["avatar"] = str(p)
                            changed = True
                        except Exception:
                            pass
            if changed:
                self.events.put(("friends", [dict(f) for f in friends], msg))
            self.events.put(("friends_done",))

        threading.Thread(target=work, daemon=True).start()

    def friends_loop(self):
        if self.settings.get("steam_key"):
            self.start_friends()
        self.after(90_000, self.friends_loop)

    # ----- olay kuyruğu (arka plan iş parçacıkları → arayüz) -----
    def poll(self):
        try:
            while True:
                self.handle(self.events.get_nowait())
        except queue.Empty:
            pass
        if self.dirty:
            self.dirty = False
            self.render()
        self.after(200, self.poll)

    def handle(self, ev):
        kind = ev[0]
        if kind == "status":
            self.set_status(ev[1])
        elif kind == "scan_done":
            _, found, silent, err = ev
            self.scanning = False
            if err:
                self.set_status(f"Tarama hatası: {err}", 8000)
                return
            new = self.merge_found(found)
            if new:
                self.dirty = True
                self.render_side()
                self.fetch_missing_covers()
                self.set_status(f"{len(new)} yeni oyun bulundu ve eklendi", 8000)
            else:
                self.set_status("" if silent else "Yeni oyun bulunamadı", 5000)
        elif kind == "cover":
            for g in self.games:
                if g["id"] == ev[1]:
                    g["cover"] = ev[2]
                    self.imgs.pop(g["id"], None)
                    self.dirty = True
            save_games(self.games)
        elif kind == "friends":
            self.friends, self.friends_msg = ev[1], ev[2]
            self.render_side()
        elif kind == "friends_done":
            self.friends_busy = False

    # ----- veri -----
    def add(self):
        d = AddDialog(self)
        self.wait_window(d)
        if d.result:
            self.games.insert(0, d.result)
            save_games(self.games)
            self.refresh()

    def edit(self, g):
        d = AddDialog(self, g)
        self.wait_window(d)
        if d.result:
            self.games[self.games.index(g)] = d.result
            self.imgs.pop(g["id"], None)
            save_games(self.games)
            self.refresh()

    def delete(self, g):
        if messagebox.askyesno("Sil", f"“{g['name']}” kütüphaneden silinsin mi?\n(Oyunun kendisi bilgisayardan silinmez; "
                                      "otomatik taramada tekrar eklenmez.)"):
            self.games.remove(g)
            self.settings.setdefault("ignored", []).append(g["path"].lower())
            save_settings(self.settings)
            if g.get("cover"):
                try:
                    (COVERS / g["cover"]).unlink()
                except OSError:
                    pass
            self.imgs.pop(g["id"], None)
            save_games(self.games)
            self.refresh()

    def toggle_fav(self, g):
        g["fav"] = not g.get("fav", False)
        save_games(self.games)
        self.render()
        self.render_side()

    def play(self, g):
        try:
            launch(g["path"])
            g["plays"] = g.get("plays", 0) + 1
            g["last"] = time.time()
            save_games(self.games)
            self.render_side()
        except Exception as e:
            messagebox.showerror("Oyun başlatılamadı", str(e))

    def refresh(self):
        self.render()
        self.render_side()

    def installed(self, g):
        try:
            if g.get("dir"):
                return Path(g["dir"]).exists()
            return is_uri(g["path"]) or Path(g["path"]).exists()
        except OSError:
            return False

    def visible(self):
        q = self.query()
        gs = [g for g in self.games if q in g["name"].lower()]
        if self.view == "fav":
            gs = [g for g in gs if g.get("fav")]
        elif self.view == "installed":
            gs = [g for g in gs if self.installed(g)]
        if self.sort == "name":
            gs.sort(key=lambda g: g["name"].lower())
        elif self.sort == "last":
            gs.sort(key=lambda g: g.get("last", 0), reverse=True)
        elif self.sort == "plays":
            gs.sort(key=lambda g: g.get("plays", 0), reverse=True)
        else:
            gs.sort(key=lambda g: g.get("added", 0), reverse=True)
        return gs

    # ----- kart görseli -----
    def card_image(self, g):
        """(PhotoImage|None, kapak_var_mı). PIL varsa yuvarlak köşe + alt gradyan işlenir."""
        key = g["id"]
        if key in self.imgs:
            return self.imgs[key]
        f = COVERS / g["cover"] if g.get("cover") else None
        has = bool(f and f.exists())
        out = None
        try:
            if PIL_OK:
                W, H = CW * 2, CH * 2
                if has:
                    base = ImageOps.fit(Image.open(f).convert("RGB"), (W, H), Image.LANCZOS)
                else:
                    grad = Image.linear_gradient("L").resize((W, H)).rotate(35, expand=False)
                    base = Image.composite(Image.new("RGB", (W, H), rgb_for(g["name"], l=.38, s=.6)),
                                           Image.new("RGB", (W, H), rgb_for(g["name"], l=.16, s=.5, shift=50)), grad)
                base = base.convert("RGBA")
                gh = int(H * .55)
                alpha = Image.linear_gradient("L").resize((W, gh)).point(lambda v: int(v * .85))
                shade = Image.new("RGBA", (W, gh), (0, 0, 0, 255))
                shade.putalpha(alpha)
                base.alpha_composite(shade, (0, H - gh))
                mask = Image.new("L", (W, H), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), RADIUS * 2, fill=255)
                bg = Image.new("RGBA", (W, H), BG)
                bg.paste(base, (0, 0), mask)
                out = ImageTk.PhotoImage(bg.convert("RGB").resize((CW, CH), Image.LANCZOS))
            elif has:
                im = tk.PhotoImage(file=str(f))
                k = max(1, -(-im.width() // CW), -(-im.height() // CH))
                out = im.subsample(k, k)
        except Exception:
            out = None
        self.imgs[key] = (out, has)
        return self.imgs[key]

    def make_card(self, g, i, cols):
        c = tk.Canvas(self.inner, width=CW, height=CH, bg=BG, highlightthickness=0, cursor="hand2")
        c.grid(row=i // cols, column=i % cols, padx=GAP // 2, pady=GAP // 2)
        img, has = self.card_image(g)
        if PIL_OK and img:
            c.create_image(0, 0, image=img, anchor="nw")
        else:
            c.create_rectangle(0, 0, CW, CH, fill=hex_for(g["name"]), outline="")
            if img:
                c.create_image(CW // 2, CH // 2, image=img)
            c.create_rectangle(0, CH - 52, CW, CH, fill="black", stipple="gray50", outline="")
        if not has:
            c.create_text(CW // 2, CH // 2 - 14, text=g["name"][:1].upper(), fill="#ffffff", font=(FONT, 46, "bold"))

        c.create_rectangle(0, 0, CW, CH, fill="black", stipple="gray25", outline="", tags="hv", state="hidden")

        label = badge_label(g)
        w = 8 * len(label) + 16
        rrect(c, 12, 12, 12 + w, 34, 8, fill="#0b0a12", outline="")
        c.create_text(12 + w // 2, 23, text=label, fill="white", font=(FONT, 8, "bold"))
        fav = g.get("fav", False)
        c.create_polygon(CW - 36, 14, CW - 16, 14, CW - 16, 42, CW - 26, 34, CW - 36, 42,
                         fill="white" if fav else "", outline="white", width=2)

        name = g["name"] if len(g["name"]) <= 27 else g["name"][:26] + "…"
        c.create_text(19, CH - 25, text=name, fill="#000000", anchor="w", font=(FONT, 13))
        c.create_text(18, CH - 26, text=name, fill="white", anchor="w", font=(FONT, 13))

        rrect(c, CW // 2 - 30, CH // 2 - 30, CW // 2 + 30, CH // 2 + 30, 18, fill=ACC, outline="",
              tags="hv", state="hidden")
        c.create_text(CW // 2 + 2, CH // 2, text="▶", fill="white", font=(FONT, 20), tags="hv", state="hidden")

        c.bind("<Enter>", lambda e, c=c: c.itemconfigure("hv", state="normal"))
        c.bind("<Leave>", lambda e, c=c: c.itemconfigure("hv", state="hidden"))
        c.bind("<Button-1>", lambda e, g=g: self.card_click(e, g))
        for b in ("<Button-3>", "<Button-2>"):
            c.bind(b, lambda e, g=g: self.card_menu(e, g))

    def card_click(self, e, g):
        if e.x >= CW - 48 and e.y <= 48:
            self.toggle_fav(g)
        else:
            self.play(g)

    def card_menu(self, e, g):
        m = style_menu(tk.Menu(self))
        m.add_command(label="▶  Oyna", command=lambda: self.play(g))
        m.add_command(label="Favoriden çıkar" if g.get("fav") else "Favoriye ekle", command=lambda: self.toggle_fav(g))
        m.add_command(label="Düzenle", command=lambda: self.edit(g))
        if g.get("dir") and Path(g["dir"]).exists():
            m.add_command(label="Oyun klasörünü aç", command=lambda: launch(g["dir"]))
        m.add_separator()
        m.add_command(label="Sil", command=lambda: self.delete(g))
        m.tk_popup(e.x_root, e.y_root)

    # ----- orta alan çizimi -----
    def on_inner(self, e):
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), self.inner.winfo_reqheight() + 10))

    def on_resize(self, e):
        self.canvas.coords(self.win, e.width // 2, 0)
        cols = max(1, (e.width - 40) // (CW + GAP))
        if cols != self.cols:
            self.render()

    def render(self):
        w = self.canvas.winfo_width()
        cols = max(1, ((w if w > 1 else 940) - 40) // (CW + GAP))
        self.cols = cols
        y = self.canvas.yview()[0]
        for c in self.inner.winfo_children():
            c.destroy()
        shown = self.visible()
        self.count_lbl.configure(text=f"{len(self.games)} oyun")
        if not shown:
            if not self.games:
                msg = "Oyunların aranıyor…\nBulunamazsa ⚙ menüsünden klasör ekleyebilirsin."
            elif self.view == "fav" and not self.query():
                msg = "Henüz favorin yok.\nKartın sağ üstündeki işarete tıkla."
            else:
                msg = "Uygun oyun bulunamadı."
            tk.Label(self.inner, text=msg, bg=BG, fg=MUTE, font=(FONT, 13), pady=140).grid(row=0, column=0, padx=60)
            return
        for i, g in enumerate(shown):
            self.make_card(g, i, cols)
        tk.Frame(self.inner, bg=BG, height=80).grid(row=(len(shown) - 1) // cols + 1, column=0)
        self.update_idletasks()
        self.canvas.yview_moveto(y)

    # ----- sağ panel -----
    def avatar_image(self, f):
        p = f.get("avatar")
        if not (PIL_OK and p and Path(p).exists()):
            return None
        if p in self.av_imgs:
            return self.av_imgs[p]
        try:
            im = Image.open(p).convert("RGBA").resize((80, 80), Image.LANCZOS)
            mask = Image.new("L", (80, 80), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 79, 79), fill=255)
            bg = Image.new("RGBA", (80, 80), RIGHT)
            bg.paste(im, (0, 0), mask)
            self.av_imgs[p] = ImageTk.PhotoImage(bg.convert("RGB").resize((40, 40), Image.LANCZOS))
        except Exception:
            self.av_imgs[p] = None
        return self.av_imgs[p]

    def person_row(self, parent, name, sub, color, on_click, avatar=None, dot=None, sub_color=MUTE):
        row = tk.Frame(parent, bg=RIGHT, cursor="hand2")
        row.pack(fill="x", padx=24, pady=5)
        av = tk.Canvas(row, width=40, height=40, bg=RIGHT, highlightthickness=0)
        if avatar:
            av.create_image(0, 0, image=avatar, anchor="nw")
        else:
            av.create_oval(1, 1, 39, 39, fill=color, outline="")
            av.create_text(20, 20, text=name[:1].upper(), fill="white", font=(FONT, 13, "bold"))
        if dot:
            av.create_oval(28, 28, 39, 39, fill=dot, outline=RIGHT, width=2)
        av.pack(side="left")
        col = tk.Frame(row, bg=RIGHT)
        col.pack(side="left", padx=10, fill="x", expand=True)
        n = name if len(name) <= 18 else name[:17] + "…"
        tk.Label(col, text=n, bg=RIGHT, fg=TEXT, font=(FONT, 11), anchor="w").pack(fill="x")
        s = sub if len(sub) <= 24 else sub[:23] + "…"
        tk.Label(col, text=s, bg=RIGHT, fg=sub_color, font=(FONT, 8), anchor="w").pack(fill="x")
        for wdg in (row, av, col, *col.winfo_children()):
            wdg.bind("<Button-1>", lambda e: on_click())

    def friend_row(self, f):
        if f.get("game"):
            sub, sc, dot = f"Oynuyor: {f['game']}", ACC2, OK
        elif f["state"] > 0:
            sub, sc, dot = STATE_TXT.get(f["state"], "Çevrimiçi"), MUTE, STATE_COL.get(f["state"], "#57cbde")
        elif f.get("api"):
            sub, sc, dot = "Çevrimdışı", MUTE, None
        else:
            sub, sc, dot = "Steam arkadaşı", MUTE, None
        self.person_row(self.side_inner, f["name"], sub, hex_for(f["name"], l=.4, s=.6),
                        lambda fid=f["id"]: launch(f"steam://friends/message/{fid}"),
                        avatar=self.avatar_image(f), dot=dot, sub_color=sc)

    def heading(self, text, on_click=None):
        l = tk.Label(self.side_inner, text=text, bg=RIGHT, fg=MUTE, font=(FONT, 10), anchor="w",
                     cursor="hand2" if on_click else "")
        l.pack(fill="x", padx=24, pady=(16, 6))
        if on_click:
            l.bind("<Button-1>", lambda e: on_click())
        return l

    def toggle_offline(self):
        self.show_offline = not self.show_offline
        self.render_side()

    def render_side(self):
        for c in self.side_inner.winfo_children():
            c.destroy()

        h = tk.Frame(self.side_inner, bg=RIGHT)
        h.pack(fill="x", padx=24, pady=(34, 0))
        tk.Label(h, text="Steam arkadaşları", bg=RIGHT, fg=TEXT, font=(FONT, 12, "bold")).pack(side="left")
        r = tk.Label(h, text="↻", bg=RIGHT, fg=MUTE, font=(FONT, 13), cursor="hand2")
        r.pack(side="right")
        r.bind("<Button-1>", lambda e: self.start_friends())

        fr = self.friends
        if not fr:
            tk.Label(self.side_inner, text=self.friends_msg or ("Arkadaşlar yükleniyor…" if self.friends_busy
                                                                 else "Steam bulunamadı."),
                     bg=RIGHT, fg=MUTE, font=(FONT, 9), wraplength=230, justify="left", anchor="w").pack(
                fill="x", padx=24, pady=(10, 6))
            self.link_button("Steam'i bağla", self.steam_dialog)
        else:
            api = any(f.get("api") for f in fr)
            order = lambda f: (0 if f.get("game") else 1 if f["state"] > 0 else 2, f["name"].lower())
            if not api:
                tk.Label(self.side_inner, text=self.friends_msg, bg=RIGHT, fg=MUTE, font=(FONT, 9),
                         wraplength=230, justify="left", anchor="w").pack(fill="x", padx=24, pady=(8, 0))
                self.link_button("Steam'i bağla", self.steam_dialog)
                self.heading(f"Arkadaşlar ({len(fr)})")
                for f in sorted(fr, key=order)[:60]:
                    self.friend_row(f)
            else:
                online = sorted([f for f in fr if f["state"] > 0 or f.get("game")], key=order)
                offline = sorted([f for f in fr if f not in online], key=order)
                self.heading(f"Çevrimiçi ({len(online)})")
                for f in online:
                    self.friend_row(f)
                if not online:
                    tk.Label(self.side_inner, text="Şu an çevrimiçi kimse yok", bg=RIGHT, fg=LINE,
                             font=(FONT, 9)).pack(anchor="w", padx=24)
                if offline:
                    self.heading(f"Çevrimdışı ({len(offline)})  {'▾' if self.show_offline else '▸'}",
                                 self.toggle_offline)
                    if self.show_offline:
                        for f in offline:
                            self.friend_row(f)

        recent = sorted([g for g in self.games if g.get("last")], key=lambda g: g["last"], reverse=True)[:4]
        if recent:
            self.heading("Son oynananlar")
            for g in recent:
                self.person_row(self.side_inner, g["name"], ago(g["last"]), hex_for(g["name"], l=.4, s=.6),
                                lambda g=g: self.play(g))
        tk.Frame(self.side_inner, bg=RIGHT, height=30).pack()

    def link_button(self, text, cmd):
        b = tk.Button(self.side_inner, text=text, command=cmd, bg=PANEL2, fg=TEXT, relief="flat", cursor="hand2",
                      activebackground=ACC, activeforeground="white", font=(FONT, 9), padx=12, pady=4)
        b.pack(anchor="w", padx=24, pady=(4, 0))


if __name__ == "__main__":
    App().mainloop()
