#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Syl1g. Распространяется на условиях GNU GPL v3 или новее, см. файл LICENSE.
"""
DaSync: ноутбук в кармане. Живёт в трее, управляется с телефона.

Установка (один раз, в PowerShell):
    pip install pyautogui pyperclip psutil qrcode pillow pystray

Запуск: двойной клик по laptop_hub.pyw
Значок появится у часов, а двойной клик по нему открывает окно приложения.
Правый клик: окно, QR, автозапуск, выход.
"""
import base64
import hashlib
import hmac
import io
import ipaddress
import json
import mimetypes
import os
import platform
import random
import re
import socket
import struct
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

# при запуске через pythonw консоли нет
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

OS = platform.system()  # Windows / Darwin / Linux
APP_NAME = "DaSync"

# чтобы координаты экрана и мыши совпадали на мониторах с масштабом 125-150%
if OS == "Windows":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def alert(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x40)
    except Exception:
        print(msg)


try:
    import pyautogui
    import pyperclip
    import psutil
except ImportError:
    alert("Не хватает библиотек для этого Python:\n" + sys.executable + "\n\n"
          "Открой PowerShell и выполни:\n\n"
          '& "' + sys.executable + '" -m pip install pyautogui pyperclip psutil qrcode pillow pystray')
    sys.exit(1)

PORT = 8765
NCPU = psutil.cpu_count() or 1
DISK = (os.environ.get("SystemDrive", "C:") + "\\") if OS == "Windows" else "/"
CFG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "LaptopHub")
CFG_FILE = os.path.join(CFG_DIR, "config.json")
HUB_DIR = os.path.join(os.path.expanduser("~"), "LaptopHub")
MAX_UPLOAD = 4 * 1024 ** 3
SAMPLE_EVERY = 10  # секунд между записями истории
os.makedirs(CFG_DIR, exist_ok=True)
os.makedirs(HUB_DIR, exist_ok=True)

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False

PROTECTED = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe",
    "launchd", "kernel_task", "windowserver", "systemd", "init",
}
IDLE_NAMES = {"system idle process", "system", "idle"}

APP = {"on": True}
STATE = {}
fails = {}
TIMER = {"at": None, "obj": None}


# ---------- настройки ----------
def rand_hex(n=16):
    return os.urandom(n).hex()


def load_cfg():
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            return json.load(f), False
    except Exception:
        return {}, True


def save_cfg(cfg):
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


CFG, FIRST_RUN = load_cfg()
if CFG.pop("pin", None) is not None:  # старый PIN больше не используется
    save_cfg(CFG)
CFG.setdefault("paired", {})


# ---------- устройства и журнал ----------
DEV = {}
DEVL = threading.Lock()
LOG = []
LOGL = threading.Lock()
last_fail_log = {}
QR_CACHE = {}


def log(who, text, kind="info"):
    with LOGL:
        LOG.append({"ts": time.time(), "who": who, "text": text, "kind": kind})
        del LOG[:-300]


def parse_ua(ua):
    ua = ua or ""
    if "iPhone" in ua:
        kind, model = "phone", "iPhone"
    elif "iPad" in ua:
        kind, model = "tablet", "iPad"
    elif "Android" in ua:
        kind, model = "phone", "Android"
    elif "Macintosh" in ua:
        kind, model = "pc", "Mac"
    elif "Windows" in ua:
        kind, model = "pc", "ПК с Windows"
    elif "Linux" in ua:
        kind, model = "pc", "ПК с Linux"
    else:
        kind, model = "other", "Устройство"
    if "CriOS" in ua:
        br = "Chrome"
    elif "FxiOS" in ua:
        br = "Firefox"
    elif "Edg" in ua:
        br = "Edge"
    elif "Chrome" in ua:
        br = "Chrome"
    elif "Firefox" in ua:
        br = "Firefox"
    elif "Safari" in ua:
        br = "Safari"
    elif "Mobile/" in ua:
        br = "Приложение на экране Домой"
    else:
        br = ""
    return kind, model, br


def is_blocked(key, ip):
    bl = CFG.get("blocked", [])
    return key in bl or ip in bl


def dev_name(key):
    d = DEV.get(key)
    saved = CFG.get("devices", {}).get(key, {})
    return saved.get("name") or (d["model"] if d else CFG.get("paired", {}).get(key, {}).get("model") or key)


def touch_device(key, ip, ua):
    now = time.time()
    with DEVL:
        d = DEV.get(key)
        if d is None:
            kind, model, br = parse_ua(ua)
            devs = CFG.setdefault("devices", {})
            saved = devs.get(key)
            first = saved.get("first", now) if saved else now
            d = DEV[key] = {"key": key, "ip": ip, "kind": kind, "model": model, "browser": br,
                            "first": first, "last": now, "count": 0, "online": False,
                            "since": now, "last_action": ""}
            if not saved:
                devs[key] = {"first": now}
                save_cfg(CFG)
        d["ip"], d["last"] = ip, now
        d["count"] += 1
        fresh = not d["online"]
        if fresh:
            d["online"], d["since"], d["last_action"] = True, now, ""
    if fresh:
        log(dev_name(key), "подключился", "join")
    return d


def check_offline():
    now = time.time()
    gone = []
    with DEVL:
        for k, d in DEV.items():
            if d["online"] and now - d["last"] > 8:
                d["online"] = False
                gone.append(k)
    for k in gone:
        log(dev_name(k), "отключился", "leave")


def note_action(dev, text):
    if dev and text and dev["last_action"] != text:
        dev["last_action"] = text
        log(dev_name(dev["key"]), text)


def describe(d):
    a = d.get("a")
    if a in ("move", "click", "scroll", "down", "up"):
        return "использует тачпад"
    if a == "key":
        return "нажимает клавиши"
    if a == "tap":
        return "кликает по экрану ноута"
    if a == "shot":
        return "смотрит экран ноута"
    if a == "text":
        return f"вставил текст ({len(str(d.get('t', '')))} симв.)"
    if a == "combo":
        return "нажал сочетание клавиш"
    if a == "media":
        return "управляет звуком и плеером"
    if a == "stats":
        return "смотрит состояние ноутбука"
    if a == "history":
        return "смотрит историю нагрузки"
    if a == "kill":
        return "закрыл программу " + str(d.get("name"))
    if a == "power":
        return {"lock": "заблокировал ноут", "sleep": "отправил ноут в сон",
                "shutdown": "выключил ноут"}.get(d.get("m"), "")
    if a == "timer":
        return f"поставил таймер выключения на {d.get('min')} мин"
    if a == "cancel":
        return "отменил таймер выключения"
    if a == "notes":
        return "читает заметки"
    if a == "note_add":
        return "добавил заметку"
    if a == "note_del":
        return "удалил заметку"
    if a == "files":
        return "смотрит файлы"
    if a == "file_del":
        return "удалил файл " + str(d.get("name"))
    if a == "open_folder":
        return "открыл папку с файлами"
    if a == "say":
        return "озвучил текст на ноуте"
    if a == "popup":
        return "показал сообщение на экране ноута"
    if a == "openurl":
        return "открыл ссылку на ноуте"
    if a in ("clip_get", "clip_set"):
        return "работает с буфером обмена"
    return None


# ---------- сопряжение и подписи ----------
CAPS_DEFAULT = {"control": True, "screen": True, "files": True, "power": False}
CAP_TITLES = {"control": "управление мышью и клавиатурой", "screen": "просмотр экрана",
              "files": "файлы", "power": "питание и процессы"}
ACTION_CAP = {}
for _cap, _acts in {
    "control": "move click down up scroll key combo text media clip_get clip_set say popup openurl",
    "screen": "shot tap",
    "files": "files file_del open_folder",
    "power": "power timer cancel kill",
}.items():
    for _a in _acts.split():
        ACTION_CAP[_a] = _cap
OPEN_ACTIONS = {"ping", "stats", "history", "notes", "note_add", "note_set", "note_pin", "note_del"}
PAIR = {"s": "", "exp": 0, "tries": 0}
PENDING = {}
NONCES = {}
PAIR_HITS = {}
PAIRL = threading.Lock()
DESK_SEEN = {"t": 0}


def hmac_hex(key_hex, msg):
    return hmac.new(bytes.fromhex(key_hex), msg.encode() if isinstance(msg, str) else msg, hashlib.sha256).hexdigest()


def clean_hex(v, n=32):
    return re.sub(r"[^0-9a-f]", "", str(v or "").lower())[:n]


def current_pair():
    with PAIRL:
        now = time.time()
        if not PAIR["s"] or now > PAIR["exp"]:
            PAIR.update(s=rand_hex(16), exp=now + 120, tries=0)
        return dict(PAIR)


def rotate_pair():
    with PAIRL:
        PAIR.update(s=rand_hex(16), exp=time.time() + 120, tries=0)


def private_ip(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
        return a.is_private or a.is_loopback or a.is_link_local
    except ValueError:
        return False


def pair_rate_ok(ip):
    now = time.time()
    lst = [t for t in PAIR_HITS.get(ip, []) if now - t < 60] + [now]
    PAIR_HITS[ip] = lst
    return len(lst) <= 20


def pair_start(ip, ua, d):
    """Телефон доказал, что видел QR (знает одноразовый секрет S). Ключ K вычисляется
    на обеих сторонах из S и по сети не передаётся."""
    if not APP["on"]:
        return 503, {"error": "paused"}
    devid, cn = clean_hex(d.get("devid")), clean_hex(d.get("cn"))
    if len(devid) < 16 or len(cn) < 16:
        return 400, {"error": "bad"}
    if is_blocked(devid, ip):
        return 403, {"error": "blocked"}
    cur = current_pair()
    if not hmac.compare_digest(str(d.get("proof", "")), hmac_hex(cur["s"], f"pair1|{devid}|{cn}")):
        with PAIRL:
            PAIR["tries"] += 1
            if PAIR["tries"] >= 3:
                PAIR.update(s=rand_hex(16), exp=time.time() + 120, tries=0)
        log(ip, "неверный код сопряжения", "warn")
        return 401, {"error": "code"}
    sn = rand_hex(16)
    k = hmac_hex(cur["s"], f"key|{devid}|{cn}|{sn}")
    rotate_pair()
    PENDING[devid] = {"ip": ip, "ua": ua, "sn": sn, "k": k, "ts": time.time(), "status": "pending"}
    kind, model, br = parse_ua(ua)
    log(model, f"хочет подключиться ({ip}) — ждёт подтверждения", "warn")
    if TRAY.get("notify"):
        TRAY["notify"]("DaSync", f"{model} хочет подключиться. Подтверди в окне приложения.")
    if time.time() - DESK_SEEN["t"] > 5:
        open_desk()
    return 200, {"status": "pending", "sn": sn}


def pair_status(d):
    devid = clean_hex(d.get("devid"))
    p = PENDING.get(devid)
    if not p or time.time() - p["ts"] > 600:
        PENDING.pop(devid, None)
        return 404, {"status": "none"}
    if not hmac.compare_digest(str(d.get("mac", "")), hmac_hex(p["k"], f"status|{devid}")):
        return 401, {"error": "auth"}
    if p["status"] == "approved":
        return 200, {"status": "approved", "mac": hmac_hex(p["k"], f"approved|{devid}|{p['sn']}")}
    return 200, {"status": p["status"]}


# ---------- база: история и заметки ----------
DB = sqlite3.connect(os.path.join(CFG_DIR, "hub.db"), check_same_thread=False)
DBL = threading.Lock()
with DBL:
    DB.execute("CREATE TABLE IF NOT EXISTS samples(ts REAL, cpu REAL, ram REAL, bat REAL, down REAL, up REAL, active INT, top TEXT)")
    DB.execute("CREATE INDEX IF NOT EXISTS idx_ts ON samples(ts)")
    DB.execute("CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, pinned INT DEFAULT 0, ts REAL)")
    DB.commit()


def idle_seconds():
    if OS != "Windows":
        return None
    try:
        import ctypes

        class LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        lii = LII()
        lii.cbSize = ctypes.sizeof(LII)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
    except Exception:
        pass
    return None


def record(now, cpu, ram, bat, down, up, top):
    idle = idle_seconds()
    active = None if idle is None else int(idle < 120)
    with DBL:
        DB.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?)", (now, cpu, ram, bat, down, up, active, top))
        DB.commit()


def prune():
    with DBL:
        DB.execute("DELETE FROM samples WHERE ts<?", (time.time() - 8 * 86400,))
        DB.commit()


RANGES = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}


def history(key):
    span = RANGES.get(key, 3600)
    now = time.time()
    since = now - span
    buckets = 90
    size = span / buckets
    keys = ["cpu", "cpu_max", "ram", "bat", "down", "up"]
    out = {k: [None] * buckets for k in keys}
    with DBL:
        rows = DB.execute(
            "SELECT CAST((ts-?)/? AS INTEGER) b, AVG(cpu), MAX(cpu), AVG(ram), AVG(bat), AVG(down), AVG(up) "
            "FROM samples WHERE ts>=? GROUP BY b", (since, size, since)).fetchall()
        s = DB.execute(
            "SELECT COUNT(*), AVG(cpu), MAX(cpu), AVG(ram), MAX(ram), SUM(down), SUM(up), SUM(active), COUNT(active) "
            "FROM samples WHERE ts>=?", (since,)).fetchone()
        top = DB.execute(
            "SELECT top, COUNT(*) c FROM samples WHERE ts>=? AND top!='' GROUP BY top ORDER BY c DESC LIMIT 5",
            (since,)).fetchall()
    for b, cpu, cmax, ram, bat, down, up in rows:
        if 0 <= b < buckets:
            for k, v in zip(keys, (cpu, cmax, ram, bat, down, up)):
                out[k][b] = None if v is None else round(v, 1)
    n = s[0] or 0
    total = max(n, 1)
    out["since"], out["now"], out["span"] = since, now, span
    out["sum"] = {
        "n": n,
        "cpu_avg": round(s[1] or 0, 1), "cpu_max": round(s[2] or 0, 1),
        "ram_avg": round(s[3] or 0, 1), "ram_max": round(s[4] or 0, 1),
        "down": (s[5] or 0) * SAMPLE_EVERY, "up": (s[6] or 0) * SAMPLE_EVERY,
        "active_min": round((s[7] or 0) * SAMPLE_EVERY / 60) if s[8] else None,
        "cover": min(100, round(n * SAMPLE_EVERY / span * 100)),
    }
    out["top"] = [{"name": t[0], "pct": round(t[1] / total * 100, 1)} for t in top]
    return out


def notes_list():
    with DBL:
        rows = DB.execute("SELECT id, text, pinned, ts FROM notes ORDER BY pinned DESC, ts DESC").fetchall()
    return [{"id": r[0], "text": r[1], "pinned": r[2], "ts": r[3]} for r in rows]


# ---------- сбор данных ----------
def sampler():
    last_net = psutil.net_io_counters()
    last_t = time.time()
    psutil.cpu_percent(None)
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(1)
    prune()
    tick = 0
    while True:
        now = time.time()
        net = psutil.net_io_counters()
        dt = max(now - last_t, 0.001)
        down = (net.bytes_recv - last_net.bytes_recv) / dt
        up = (net.bytes_sent - last_net.bytes_sent) / dt
        last_net, last_t = net, now

        groups = {}
        for p in psutil.process_iter():
            try:
                name = p.name()
                if name.lower() in IDLE_NAMES:
                    continue
                cpu = p.cpu_percent(None) / NCPU
                mem = p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            g = groups.setdefault(name, {"name": name, "cpu": 0.0, "mem": 0, "n": 0})
            g["cpu"] += cpu
            g["mem"] += mem
            g["n"] += 1
        for g in groups.values():
            g["protected"] = g["name"].lower() in PROTECTED
        glist = list(groups.values())
        by_cpu = sorted(glist, key=lambda g: g["cpu"], reverse=True)

        vm = psutil.virtual_memory()
        du = psutil.disk_usage(DISK)
        cpu_total = psutil.cpu_percent(None)
        bat = None
        try:
            b = psutil.sensors_battery()
            if b:
                bat = {"pct": round(b.percent), "plugged": bool(b.power_plugged),
                       "left": b.secsleft if isinstance(b.secsleft, int) and b.secsleft > 0 else None}
        except Exception:
            pass
        temp = None
        try:
            if hasattr(psutil, "sensors_temperatures"):
                vals = [t.current for lst in psutil.sensors_temperatures().values() for t in lst]
                if vals:
                    temp = round(max(vals))
        except Exception:
            pass

        STATE.update({
            "cpu": cpu_total,
            "ram": {"pct": vm.percent, "used": vm.used, "total": vm.total},
            "disk": {"pct": du.percent, "free": du.free, "total": du.total},
            "net": {"down": down, "up": up},
            "bat": bat, "temp": temp,
            "uptime": int(now - psutil.boot_time()),
            "host": socket.gethostname(),
            "top_cpu": by_cpu[:10],
            "top_mem": sorted(glist, key=lambda g: g["mem"], reverse=True)[:10],
        })

        check_offline()
        tick += 1
        if tick % (SAMPLE_EVERY // 2) == 0:
            try:
                topname = by_cpu[0]["name"] if by_cpu and by_cpu[0]["cpu"] >= 8 else ""
                record(now, cpu_total, vm.percent, bat["pct"] if bat else None, down, up, topname)
            except Exception:
                pass
        if tick % 1800 == 0:
            prune()
        time.sleep(2)


# ---------- действия ----------
def run(cmd, **kw):
    subprocess.run(cmd, check=False, creationflags=0x08000000 if OS == "Windows" else 0, **kw)


def mac_osa(script):
    subprocess.run(["osascript", "-e", script], check=False)


def media(name):
    if OS == "Darwin":
        if name == "volup":
            mac_osa("set volume output volume ((output volume of (get volume settings)) + 6)")
        elif name == "voldown":
            mac_osa("set volume output volume ((output volume of (get volume settings)) - 6)")
        elif name == "mute":
            mac_osa("set volume output muted (not (output muted of (get volume settings)))")
    else:
        keys = {"volup": "volumeup", "voldown": "volumedown", "mute": "volumemute",
                "playpause": "playpause", "next": "nexttrack", "prev": "prevtrack"}
        if name in keys:
            pyautogui.press(keys[name])


def power(mode):
    if OS == "Windows":
        cmds = {"lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
                "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                "shutdown": ["shutdown", "/s", "/t", "0"]}
    elif OS == "Darwin":
        cmds = {"lock": ["pmset", "displaysleepnow"], "sleep": ["pmset", "sleepnow"],
                "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down']}
    else:
        cmds = {"lock": ["loginctl", "lock-session"], "sleep": ["systemctl", "suspend"],
                "shutdown": ["systemctl", "poweroff"]}
    if mode in cmds:
        run(cmds[mode])


def set_timer(minutes):
    cancel_timer()
    t = threading.Timer(minutes * 60, lambda: power("shutdown"))
    t.daemon = True
    t.start()
    TIMER["obj"], TIMER["at"] = t, time.time() + minutes * 60


def cancel_timer():
    if TIMER["obj"]:
        TIMER["obj"].cancel()
    TIMER["obj"], TIMER["at"] = None, None


def kill(name):
    if name.lower() in PROTECTED:
        return 0
    n = 0
    for p in psutil.process_iter():
        try:
            if p.name() == name and p.pid != os.getpid():
                p.terminate()
                n += 1
        except Exception:
            pass
    return n


COMBOS = {
    "desktop": ("winleft", "d"), "switch": ("alt", "tab"), "close": ("alt", "f4"),
    "taskmgr": ("ctrl", "shift", "esc"), "shot": ("winleft", "shift", "s"),
    "copy": ("ctrl", "c"), "paste": ("ctrl", "v"), "undo": ("ctrl", "z"),
    "all": ("ctrl", "a"), "save": ("ctrl", "s"), "layout": ("alt", "shift"), "start": ("winleft",),
}
if OS == "Darwin":
    COMBOS.update({
        "desktop": ("f11",), "switch": ("command", "tab"), "close": ("command", "w"),
        "taskmgr": ("command", "option", "esc"), "shot": ("command", "shift", "4"),
        "copy": ("command", "c"), "paste": ("command", "v"), "undo": ("command", "z"),
        "all": ("command", "a"), "save": ("command", "s"), "layout": ("ctrl", "space"),
        "start": ("command", "space"),
    })


def speak(text):
    text = text[:500]
    try:
        if OS == "Windows":
            run(["powershell", "-NoProfile", "-Command",
                 "Add-Type -AssemblyName System.Speech; "
                 "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:HUB_TEXT)"],
                env=dict(os.environ, HUB_TEXT=text))
        elif OS == "Darwin":
            subprocess.run(["say", text], check=False)
        else:
            subprocess.run(["espeak", text], check=False)
    except Exception:
        pass


def popup(text):
    text = text[:500]
    try:
        if OS == "Windows":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, "Сообщение с телефона", 0x40 | 0x10000 | 0x40000)
        elif OS == "Darwin":
            mac_osa(f'display dialog {json.dumps(text)} with title "Сообщение с телефона" buttons {{"ОК"}}')
        else:
            subprocess.run(["notify-send", "Сообщение с телефона", text], check=False)
    except Exception:
        pass


def open_folder():
    if OS == "Windows":
        os.startfile(HUB_DIR)
    elif OS == "Darwin":
        subprocess.run(["open", HUB_DIR], check=False)
    else:
        subprocess.run(["xdg-open", HUB_DIR], check=False)


def screenshot():
    img = pyautogui.screenshot()
    w, h = pyautogui.size()
    pos = pyautogui.position()
    img.thumbnail((1100, 1100))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=55)
    return {"img": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
            "cx": pos[0] / w, "cy": pos[1] / h}


def safe_name(n):
    n = os.path.basename(n.replace("\\", "/"))
    n = "".join(c for c in n if c >= " " and c not in '<>:"|?*').strip(" .")
    return n or "file"


def unique_path(name):
    base, ext = os.path.splitext(name)
    p = os.path.join(HUB_DIR, name)
    i = 1
    while os.path.exists(p):
        p = os.path.join(HUB_DIR, f"{base} ({i}){ext}")
        i += 1
    return p


def files_list():
    out = []
    for n in os.listdir(HUB_DIR):
        p = os.path.join(HUB_DIR, n)
        if os.path.isfile(p):
            st = os.stat(p)
            out.append({"name": n, "size": st.st_size, "ts": st.st_mtime})
    out.sort(key=lambda f: f["ts"], reverse=True)
    return {"dir": HUB_DIR, "files": out}


def _unicode_events(text):
    """События для SendInput: каждая единица UTF-16 = нажатие + отпускание (флаг UNICODE).
    Работает с любой раскладкой, русский и эмодзи тоже. Enter и Tab идут обычными клавишами."""
    ev = []
    data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-16-le")
    for u in struct.unpack("<%dH" % (len(data) // 2), data):
        if u == 10:
            ev += [(0x0D, 0, 0), (0x0D, 0, 2)]
        elif u == 9:
            ev += [(0x09, 0, 0), (0x09, 0, 2)]
        else:
            ev += [(0, u, 4), (0, u, 6)]
    return ev


def _send_inputs(events, send=None):
    import ctypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                    ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_void_p)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                    ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_void_p)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("u", _U)]

    if send is None:
        send = ctypes.windll.user32.SendInput
    size = ctypes.sizeof(INPUT)
    for i in range(0, len(events), 200):
        part = events[i:i + 200]
        arr = (INPUT * len(part))()
        for j, (vk, scan, flags) in enumerate(part):
            arr[j].type = 1
            arr[j].u.ki = KEYBDINPUT(vk, scan, flags, 0, None)
        sent = send(len(part), arr, size)
        if sent != len(part):
            raise OSError("Windows не принял ввод (окно, куда печатаешь, запущено от администратора?)")
        time.sleep(0.004)
    return size


def paste_text(text):
    """Запасной способ: через буфер обмена. Паузы длинные: приложения читают буфер не мгновенно."""
    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    time.sleep(0.15)
    pyautogui.hotkey("command" if OS == "Darwin" else "ctrl", "v")
    time.sleep(0.7)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass


def type_text(text):
    text = text[:20000]
    if OS == "Windows":
        try:
            _send_inputs(_unicode_events(text))
            return
        except Exception:
            pass  # не вышло напрямую, пробуем через буфер
    paste_text(text)


def handle(d):
    a = d.get("a")
    # --- мышь и клавиатура ---
    if a == "move":
        pyautogui.moveRel(int(d["dx"]), int(d["dy"]), _pause=False)
    elif a == "click":
        pyautogui.click(button=d.get("b", "left"), clicks=int(d.get("n", 1)))
    elif a == "down":
        pyautogui.mouseDown()
    elif a == "up":
        pyautogui.mouseUp()
    elif a == "scroll":
        n = int(d["n"])
        pyautogui.scroll(n * 40 if OS == "Windows" else n)
    elif a == "key":
        pyautogui.press(d["k"])
    elif a == "combo":
        keys = COMBOS.get(d.get("id"))
        if keys:
            pyautogui.hotkey(*keys)
    elif a == "text":
        try:
            type_text(str(d["t"]))
        except Exception as e:
            return {"error": "Не удалось ввести текст: " + str(e)}
    elif a == "media":
        media(d["m"])
    # --- экран ---
    elif a == "shot":
        return screenshot()
    elif a == "tap":
        w, h = pyautogui.size()
        x = min(max(int(float(d["fx"]) * w), 0), w - 1)
        y = min(max(int(float(d["fy"]) * h), 0), h - 1)
        pyautogui.click(x, y, button=d.get("b", "left"), clicks=int(d.get("n", 1)))
    # --- мониторинг и питание ---
    elif a == "stats":
        out = dict(STATE)
        out["timer"] = max(0, int(TIMER["at"] - time.time())) if TIMER["at"] else None
        return out
    elif a == "history":
        return history(d.get("r", "1h"))
    elif a == "kill":
        return {"killed": kill(d["name"])}
    elif a == "power":
        threading.Thread(target=power, args=(d["m"],), daemon=True).start()
    elif a == "timer":
        set_timer(int(d["min"]))
    elif a == "cancel":
        cancel_timer()
    # --- заметки ---
    elif a == "notes":
        return {"notes": notes_list()}
    elif a == "note_add":
        t = str(d.get("text", ""))[:20000].strip()
        if t:
            with DBL:
                cur = DB.execute("INSERT INTO notes(text, pinned, ts) VALUES(?,0,?)", (t, time.time()))
                DB.commit()
            return {"id": cur.lastrowid}
    elif a == "note_set":
        with DBL:
            DB.execute("UPDATE notes SET text=? WHERE id=?", (str(d["text"])[:20000], int(d["id"])))
            DB.commit()
    elif a == "note_pin":
        with DBL:
            DB.execute("UPDATE notes SET pinned=? WHERE id=?", (1 if d.get("pinned") else 0, int(d["id"])))
            DB.commit()
    elif a == "note_del":
        with DBL:
            DB.execute("DELETE FROM notes WHERE id=?", (int(d["id"]),))
            DB.commit()
    # --- файлы ---
    elif a == "files":
        return files_list()
    elif a == "file_del":
        p = os.path.join(HUB_DIR, os.path.basename(str(d["name"])))
        if os.path.isfile(p):
            os.remove(p)
    elif a == "open_folder":
        open_folder()
    # --- фишки ---
    elif a == "say":
        threading.Thread(target=speak, args=(str(d["t"]),), daemon=True).start()
    elif a == "popup":
        threading.Thread(target=popup, args=(str(d["t"]),), daemon=True).start()
    elif a == "openurl":
        u = str(d["u"]).strip()
        if re.match(r"^https?://", u, re.I):
            import webbrowser
            webbrowser.open(u)
        else:
            return {"error": "Только ссылки http:// и https://"}
    elif a == "clip_get":
        try:
            return {"t": pyperclip.paste()[:20000]}
        except Exception:
            return {"t": ""}
    elif a == "clip_set":
        pyperclip.copy(str(d["t"])[:20000])
    return {"ok": True}


# ---------- сервер ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Now", str(int(time.time())))
        self.end_headers()
        self.wfile.write(data)

    def local_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return self.client_address[0] in ("127.0.0.1", "::1") and host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def deny(self, code, why, **extra):
        body = {"error": why}
        body.update(extra)
        return self.send(code, json.dumps(body))

    def fail(self, ip, why):
        cnt = fails.get(ip, (0, 0))[0] + 1
        fails[ip] = (0, time.time() + 30) if cnt >= 5 else (cnt, 0)
        if time.time() - last_fail_log.get(ip, 0) > 5:
            last_fail_log[ip] = time.time()
            log(ip, "неудачная попытка входа (" + why + ")" + (" — блокировка на 30 с" if cnt >= 5 else ""), "warn")

    def verify(self, method, path, body_hash):
        """Проверка подписи запроса. Возвращает (код, причина); 0 = всё хорошо."""
        ip = self.client_address[0]
        self.dev, self.caps = None, {}
        if not private_ip(ip):
            return 403, "network"
        devid = clean_hex(self.headers.get("X-Dev"))
        if is_blocked(devid, ip):
            return 403, "blocked"
        if time.time() < fails.get(ip, (0, 0))[1]:
            return 429, "locked"
        rec = CFG["paired"].get(devid)
        ts = (self.headers.get("X-Ts") or "")[:12]
        nonce = clean_hex(self.headers.get("X-Nonce"))
        sig = (self.headers.get("X-Sig") or "")[:64]
        try:
            tsv = int(ts)
        except ValueError:
            tsv = 0
        if not rec or len(nonce) < 8:
            self.fail(ip, "неизвестное устройство")
            return 401, "auth"
        if abs(time.time() - tsv) > 60:
            return 401, "ts"
        if not hmac.compare_digest(sig, hmac_hex(rec["k"], f"{method}\n{path}\n{ts}\n{nonce}\n{body_hash}")):
            self.fail(ip, "неверная подпись")
            return 401, "auth"
        now = time.time()
        seen = NONCES.setdefault(devid, {})
        for n in [n for n, t in seen.items() if now - t > 150]:
            del seen[n]
        if nonce in seen:
            self.fail(ip, "повтор запроса")
            return 401, "auth"
        seen[nonce] = now
        fails.pop(ip, None)
        rec["last"] = now
        self.dev = touch_device(devid, ip, self.headers.get("User-Agent", ""))
        self.caps = rec.get("caps", {})
        return (0, "") if APP["on"] else (503, "paused")

    def verify_url(self, u, qs):
        """Подписанная ссылка на скачивание файла (живёт до 5 минут)."""
        ip = self.client_address[0]
        self.dev, self.caps = None, {}
        if not private_ip(ip):
            return 403, "network"
        devid = clean_hex(qs.get("d", [""])[0])
        if is_blocked(devid, ip):
            return 403, "blocked"
        rec = CFG["paired"].get(devid)
        try:
            exp = int(qs.get("exp", ["0"])[0])
        except ValueError:
            exp = 0
        name = unquote(u.path[3:])
        sig = qs.get("sig", [""])[0][:64]
        if not rec or not (time.time() < exp < time.time() + 900):
            return 401, "auth"
        if not hmac.compare_digest(sig, hmac_hex(rec["k"], f"GET\n/f/{name}\n{exp}")):
            self.fail(ip, "неверная подпись ссылки")
            return 401, "auth"
        self.dev = touch_device(devid, ip, self.headers.get("User-Agent", ""))
        self.caps = rec.get("caps", {})
        return (0, "") if APP["on"] else (503, "paused")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/desk"):
            if not self.local_ok():
                return self.send(403, "{}")
            if u.path == "/desk":
                return self.send(200, DESK_PAGE, "text/html; charset=utf-8")
            return self.send(404, "{}")
        if u.path == "/":
            self.send(200, PAGE, "text/html; charset=utf-8")
        elif u.path in ("/icon.png", "/icon-v3.png"):
            try:
                buf = io.BytesIO()
                make_icon(180, rounded=False).save(buf, "PNG")
                self.send(200, buf.getvalue(), "image/png")
            except Exception:
                self.send(404, "{}")
        elif u.path == "/manifest.json":
            self.send(200, json.dumps({"name": APP_NAME, "short_name": "DaSync", "display": "standalone",
                                       "start_url": "/", "icons": [{"src": "/icon-v3.png", "sizes": "180x180", "type": "image/png"}], "background_color": "#15171c",
                                       "theme_color": "#15171c"}), "application/manifest+json")
        elif u.path.startswith("/f/"):
            qs = parse_qs(u.query)
            code, why = self.verify_url(u, qs)
            if code:
                return self.deny(code, why)
            if not self.caps.get("files"):
                return self.deny(403, "denied", cap="files", title=CAP_TITLES["files"])
            name = os.path.basename(unquote(u.path[3:]))
            full = os.path.join(HUB_DIR, name)
            if not os.path.isfile(full):
                return self.send(404, "{}")
            note_action(self.dev, "скачал файл " + name)
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            disp = "inline" if qs.get("inline") else "attachment"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(os.path.getsize(full)))
            self.send_header("Content-Disposition", f"{disp}; filename*=UTF-8''{quote(name)}")
            self.end_headers()
            try:
                with open(full, "rb") as f:
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send(404, "{}")

    def do_POST(self):
        path = urlparse(self.path).path
        ip = self.client_address[0]
        if path == "/desk/api":
            if not self.local_ok() or self.headers.get("X-Desk") != "1":
                return self.send(403, "{}")
            try:
                n = int(self.headers.get("Content-Length", 0))
                return self.send(200, json.dumps(desk_handle(json.loads(self.rfile.read(n) or b"{}"))))
            except Exception as e:
                return self.send(500, json.dumps({"error": str(e)}))
        try:
            if path in ("/pair/start", "/pair/status"):
                if not private_ip(ip):
                    return self.deny(403, "network")
                if not pair_rate_ok(ip):
                    return self.deny(429, "locked")
                n = int(self.headers.get("Content-Length", 0))
                if n > 4096:
                    return self.deny(413, "big")
                d = json.loads(self.rfile.read(n) or b"{}")
                if path == "/pair/start":
                    code, out = pair_start(ip, self.headers.get("User-Agent", ""), d)
                else:
                    code, out = pair_status(d)
                return self.send(code, json.dumps(out))
            if path == "/upload":
                length = int(self.headers.get("Content-Length", 0))
                fn_hdr = self.headers.get("X-Filename", "file")
                code, why = self.verify("POST", path, hashlib.sha256(f"{fn_hdr}|{length}".encode()).hexdigest())
                if code:
                    return self.deny(code, why)
                if not self.caps.get("files"):
                    return self.deny(403, "denied", cap="files", title=CAP_TITLES["files"])
                if length > MAX_UPLOAD:
                    return self.send(413, '{"error":"too big"}')
                dest = unique_path(safe_name(unquote(fn_hdr)))
                left = length
                with open(dest, "wb") as f:
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                note_action(self.dev, "загрузил файл " + os.path.basename(dest))
                return self.send(200, json.dumps({"name": os.path.basename(dest)}))
            if path != "/api":
                return self.send(404, "{}")
            n = int(self.headers.get("Content-Length", 0))
            if n > 1_000_000:
                return self.deny(413, "big")
            raw = self.rfile.read(n)
            code, why = self.verify("POST", path, hashlib.sha256(raw).hexdigest())
            if code:
                return self.deny(code, why)
            req = json.loads(raw or b"{}")
            a = req.get("a")
            cap = ACTION_CAP.get(a)
            if (cap is None and a not in OPEN_ACTIONS) or (cap and not self.caps.get(cap)):
                return self.deny(403, "denied", cap=cap or "?", title=CAP_TITLES.get(cap, "это действие"))
            note_action(self.dev, describe(req))
            self.send(200, json.dumps(handle(req)))
        except Exception as e:
            self.send(500, json.dumps({"error": str(e)}))

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def get_url():
    return f"http://{local_ip()}:{PORT}"


PAGE = r"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="DaSync">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#15171c">
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon-v3.png">
<title>DaSync</title>
<style>
:root{--bg:#15171c;--card:#1d2027;--line:#2b303a;--ink:#e9ecf1;--dim:#8a93a3;--acc:#7fb4ff;--ok:#5cc98a;--warn:#e8b04b;--bad:#e0705c;--vio:#b69cff}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none}
html,body{height:100%;margin:0;background:var(--bg);color:var(--ink);font:16px/1.3 -apple-system,"Segoe UI",Roboto,sans-serif;overscroll-behavior:none}
body{display:flex;flex-direction:column;padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
header{padding:12px 18px 4px;display:flex;justify-content:space-between;align-items:baseline;gap:10px}
header b{font-size:18px;font-weight:650}
header span{color:var(--dim);font-size:13px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--bad);margin-right:7px}
.dot.on{background:var(--ok)}
main{flex:1;min-height:0;display:flex;flex-direction:column;padding:6px 12px 8px}
.tab,.pane{display:none;flex:1;min-height:0;flex-direction:column;gap:10px;overflow-y:auto;-webkit-overflow-scrolling:touch}
.tab.show,.pane.show{display:flex}
.card{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:14px 16px;flex:none}
.top{display:flex;justify-content:space-between;align-items:baseline}
.lbl{color:var(--dim);font-size:14px}
.val{font-size:28px;font-weight:650;font-variant-numeric:tabular-nums}
.val.s{font-size:20px}
.sub{color:var(--dim);font-size:13px;margin-top:6px}
.h{color:var(--dim);font-size:13px;padding:2px 6px 0;flex:none}
.bar{height:8px;border-radius:4px;background:var(--line);margin-top:10px;overflow:hidden}
.bar i{display:block;height:100%;width:0;border-radius:4px;background:var(--ok);transition:width .6s,background .3s}
canvas{width:100%;height:36px;display:block;margin-top:8px}
canvas.big{height:90px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px;flex:none}
button{border:1px solid var(--line);border-radius:16px;background:var(--card);color:var(--ink);font:inherit;font-weight:600;min-height:52px;padding:0 14px}
button:active,button.on{background:var(--acc);color:#0b1a30;border-color:var(--acc)}
.row{display:flex;gap:10px;flex:none}.row>button{flex:1}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;flex:none}
.keys{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;flex:none}
.keys button,.grid3 button{padding:0}
.seg{display:flex;gap:6px;flex:none}.seg button{flex:1;min-height:40px;font-weight:500;padding:0 6px;font-size:15px}
.danger{color:var(--bad)}
textarea,input[type=text],input[type=search]{width:100%;flex:none;border-radius:16px;border:1px solid var(--line);background:var(--card);color:var(--ink);font:16px/1.4 inherit;padding:12px 14px;user-select:text;-webkit-user-select:text}
textarea{min-height:100px;resize:none}
#pad{flex:1;min-height:200px;border-radius:22px;background:var(--card);border:1px solid var(--line);touch-action:none;display:flex;align-items:flex-end;justify-content:center;padding:14px;color:#4b5363;font-size:14px;text-align:center}
#scrw{position:relative;flex:none;border-radius:14px;overflow:hidden;border:1px solid var(--line);background:#000;min-height:120px}
#scr{width:100%;display:block;touch-action:manipulation}
#cur{position:absolute;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;border:2px solid var(--warn);pointer-events:none;display:none}
.proc{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--line)}
.proc:first-child{border-top:0}
.proc .n{flex:1;min-width:0}
.proc .n b{display:block;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.proc .n span{color:var(--dim);font-size:13px}
.proc button{min-height:38px;font-size:14px}
.act{display:grid;grid-template-columns:1fr 1fr;gap:10px;flex:none}.act .full{grid-column:1/-1}
.timers{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}
.timers button{padding:0;min-height:44px}
#tleft{font-size:15px;margin-top:10px;color:var(--warn);min-height:20px}
.back{align-self:flex-start;min-height:36px;border:0;background:transparent;color:var(--acc);padding:0 4px;font-weight:500;flex:none}
.menu{display:grid;grid-template-columns:1fr 1fr;gap:10px;flex:none}
.menu button{text-align:left;padding:14px 16px;min-height:96px;display:flex;flex-direction:column;justify-content:space-between;align-items:flex-start}
.menu button span{font-weight:400;color:var(--dim);font-size:13px}
.menu button:active span{color:#0b1a30}
.note{padding:12px 14px}
.note.pin{border-color:#4a5a78}
.note div{word-break:break-word;white-space:pre-wrap;font-size:15px;line-height:1.45}
.nf{display:flex;justify-content:space-between;align-items:center;margin-top:10px;color:var(--dim);font-size:12px;gap:8px;flex-wrap:wrap}
.nb{display:flex;gap:6px;flex-wrap:wrap}
.nb button{min-height:32px;font-size:13px;padding:0 10px;border-radius:10px;font-weight:500}
.ck{display:flex;gap:10px;align-items:flex-start;padding:3px 0;font-size:15px;line-height:1.45;word-break:break-word}
.box{flex:none;width:20px;height:20px;border:2px solid var(--dim);border-radius:6px;margin-top:1px}
.box.on{background:var(--ok);border-color:var(--ok)}
.done{text-decoration:line-through;color:var(--dim)}
.file{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--line)}
.file:first-child{border-top:0}
.file .n{flex:1;min-width:0}
.file .n b{display:block;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px}
.file .n span{color:var(--dim);font-size:12px}
.file a{color:var(--acc);text-decoration:none;font-size:14px;padding:6px 8px}
.upl{display:flex;align-items:center;justify-content:center;min-height:56px;border:1.5px dashed #4a5a78;border-radius:16px;color:var(--acc);font-weight:600;flex:none}
.stat .val{font-size:22px}
.topbar{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line)}
.topbar:first-child{border-top:0}
.topbar b{flex:1;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px}
.topbar span{color:var(--dim);font-size:13px}
nav{display:flex;gap:2px;padding:4px 8px 8px;border-top:1px solid var(--line)}
nav button{flex:1;border:0;background:transparent;color:var(--dim);font-weight:500;font-size:13px;padding:0;min-height:44px;border-radius:12px}
nav button.on{color:var(--acc);background:transparent}
#toast{position:fixed;left:50%;bottom:calc(76px + env(safe-area-inset-bottom));transform:translateX(-50%);background:#2b303a;padding:10px 16px;border-radius:14px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:8;max-width:90%;text-align:center}
#toast.show{opacity:1}
#lock{position:fixed;inset:0;background:var(--bg);display:none;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:32px;text-align:center;z-index:9}
#lock.show{display:flex}
#lock input{width:200px;text-align:center;font-size:30px;letter-spacing:6px}
#lock button{width:200px}
#msg{color:var(--bad);min-height:20px;font-size:14px}
.lb,.lw{animation:lsync 3.8s ease-in-out infinite}
.lb{--d:-3px}.lw{--d:3px}
@keyframes lsync{0%,20%,80%,100%{transform:translateY(0)}50%{transform:translateY(var(--d))}}
@media (prefers-reduced-motion:reduce){.lb,.lw{animation:none}}
</style></head><body>
<header><b id="host">Ноутбук</b><span><i class="dot" id="dot"></i><span id="st">Подключение…</span></span></header>
<main>

  <!-- ПУЛЬТ -->
  <section class="tab show" id="t-pad">
    <div class="seg" id="pseg"><button class="on" data-pane="pad">Тачпад</button><button data-pane="screen">Экран</button><button data-pane="keys">Клавиши</button></div>
    <div class="pane show" id="p-pad">
      <div id="pad">Один палец — курсор, касание — клик<br>Два пальца — прокрутка, касание — правый клик</div>
      <div class="row"><button id="bl">Левая</button><button id="bd">Тащить</button><button id="br">Правая</button></div>
    </div>
    <div class="pane" id="p-screen">
      <div class="row"><button data-mode="click" class="on">Клик</button><button data-mode="double">Двойной</button><button data-mode="right">Правый</button></div>
      <div class="row"><button id="shotB">Обновить</button><button id="liveB">Live: выкл</button></div>
      <div id="scrw"><img id="scr" alt=""><div id="cur"></div></div>
      <div class="h">Тапни по картинке, и на ноуте произойдёт клик в этом месте. Live обновляет экран пару раз в секунду.</div>
    </div>
    <div class="pane" id="p-keys">
      <textarea id="txt" placeholder="Напиши текст — он вставится там, где курсор на ноуте"></textarea>
      <div class="row"><button id="send">Вставить</button><button id="sendEnter">Вставить + Enter</button></div>
      <div class="keys">
        <button data-k="escape">Esc</button><button data-k="tab">Tab</button><button data-k="backspace">⌫</button><button data-k="enter">Enter</button>
        <button data-k="left">←</button><button data-k="up">↑</button><button data-k="down">↓</button><button data-k="right">→</button>
        <button data-k="space">Пробел</button><button data-k="delete">Del</button><button data-k="home">Home</button><button data-k="end">End</button>
      </div>
      <div class="h">Звук и плеер</div>
      <div class="grid3">
        <button data-m="voldown">Тише</button><button data-m="mute">Mute</button><button data-m="volup">Громче</button>
        <button data-m="prev">⏮</button><button data-m="playpause">⏯</button><button data-m="next">⏭</button>
      </div>
      <div class="h">Презентация</div>
      <div class="grid3"><button data-k="left">◀ Назад</button><button data-k="f5">F5</button><button data-k="right">Вперёд ▶</button></div>
    </div>
  </section>

  <!-- ОБЗОР -->
  <section class="tab" id="t-home">
    <div class="card"><div class="top"><span class="lbl">Процессор</span><span class="val" id="cpu">–</span></div><div class="bar"><i id="cpuB"></i></div><canvas id="spark"></canvas><div class="sub" id="temp"></div></div>
    <div class="two">
      <div class="card"><div class="lbl">Память</div><div class="val" id="ram">–</div><div class="bar"><i id="ramB"></i></div><div class="sub" id="ramS"></div></div>
      <div class="card"><div class="lbl">Диск</div><div class="val" id="disk">–</div><div class="bar"><i id="diskB"></i></div><div class="sub" id="diskS"></div></div>
    </div>
    <div class="two">
      <div class="card"><div class="lbl">Батарея</div><div class="val" id="bat">–</div><div class="bar"><i id="batB"></i></div><div class="sub" id="batS"></div></div>
      <div class="card"><div class="val s" id="down">–</div><div class="sub" style="margin-top:2px">загрузка</div><div class="val s" style="margin-top:8px" id="upl">–</div><div class="sub" style="margin-top:2px">отдача</div></div>
    </div>
    <div class="h" id="up"></div>
  </section>

  <!-- ЗАМЕТКИ -->
  <section class="tab" id="t-notes">
    <textarea id="nnew" style="min-height:84px" placeholder="Новая заметка…&#10;Строка, начинающаяся с [ ], станет чекбоксом"></textarea>
    <div class="row"><button id="nadd">Добавить</button><button id="nchk">+ Чек-лист</button></div>
    <input type="search" id="nq" placeholder="Поиск по заметкам">
    <div id="nlist" style="display:flex;flex-direction:column;gap:10px"></div>
  </section>

  <!-- ФАЙЛЫ -->
  <section class="tab" id="t-files">
    <label class="upl">Отправить файлы на ноут<input type="file" id="fup" multiple hidden></label>
    <div class="h" id="upst"></div>
    <div class="card" id="flist"></div>
    <div class="row"><button id="fopen">Открыть папку на ноуте</button></div>
    <div class="h" id="fdir"></div>
  </section>

  <!-- ЕЩЁ -->
  <section class="tab" id="t-more">
    <div class="menu">
      <button data-go="hist">История<span>нагрузка за час, день, неделю</span></button>
      <button data-go="proc">Процессы<span>что жрёт ресурсы</span></button>
      <button data-go="fun">Фишки<span>озвучка, сообщения, буфер</span></button>
      <button data-go="power">Питание<span>сон, блок, таймер</span></button>
    </div>
  </section>

  <section class="tab" id="t-hist">
    <button class="back" data-go="more">‹ Ещё</button>
    <div class="seg" id="hseg"><button class="on" data-r="1h">Час</button><button data-r="6h">6 часов</button><button data-r="24h">Сутки</button><button data-r="7d">Неделя</button></div>
    <div class="two">
      <div class="card stat"><div class="lbl">Процессор</div><div class="val" id="hCpu">–</div><div class="sub" id="hCpuS"></div></div>
      <div class="card stat"><div class="lbl">Память</div><div class="val" id="hRam">–</div><div class="sub" id="hRamS"></div></div>
    </div>
    <div class="two">
      <div class="card stat"><div class="lbl">Трафик</div><div class="val" id="hNet" style="font-size:18px">–</div><div class="sub" id="hNetS"></div></div>
      <div class="card stat"><div class="lbl">За компом</div><div class="val" id="hAct">–</div><div class="sub" id="hActS"></div></div>
    </div>
    <div class="card"><div class="top"><span class="lbl">Процессор, %</span><span class="sub" style="margin:0" id="cCpuL">среднее / пик</span></div><canvas class="big" id="cCpu"></canvas></div>
    <div class="card"><div class="lbl">Память, %</div><canvas class="big" id="cRam"></canvas></div>
    <div class="card"><div class="top"><span class="lbl">Сеть</span><span class="sub" style="margin:0" id="cNetL"></span></div><canvas class="big" id="cNet"></canvas></div>
    <div class="card" id="cBatC"><div class="lbl">Батарея, %</div><canvas class="big" id="cBat"></canvas></div>
    <div class="card"><div class="lbl" style="margin-bottom:6px">Что чаще всего грузило ноут</div><div id="htop"></div></div>
    <div class="h" id="hAxis" style="text-align:center"></div>
    <div class="h" id="hCover"></div>
  </section>

  <section class="tab" id="t-proc">
    <button class="back" data-go="more">‹ Ещё</button>
    <div class="seg"><button id="sCpu" class="on">По процессору</button><button id="sMem">По памяти</button></div>
    <div class="card" id="plist"></div>
    <div class="h">Закрытие завершает все окна программы. Несохранённое пропадёт.</div>
  </section>

  <section class="tab" id="t-fun">
    <button class="back" data-go="more">‹ Ещё</button>
    <div class="h">Горячие клавиши на ноуте</div>
    <div class="grid3">
      <button data-c="desktop">Рабочий стол</button><button data-c="switch">Alt+Tab</button><button data-c="close">Закрыть окно</button>
      <button data-c="taskmgr">Диспетчер</button><button data-c="shot">Скриншот</button><button data-c="layout">Раскладка</button>
      <button data-c="copy">Копировать</button><button data-c="paste">Вставить</button><button data-c="undo">Отмена</button>
    </div>
    <div class="h">Сказать вслух на ноуте</div>
    <input type="text" id="sayT" placeholder="Например: иди спать">
    <div class="row"><button id="sayB">Сказать</button><button id="popB">Окно на экран</button></div>
    <div class="h">Открыть ссылку на ноуте</div>
    <input type="text" id="urlT" placeholder="https://…" inputmode="url" autocapitalize="off">
    <div class="row"><button id="urlB">Открыть</button></div>
    <div class="h">Буфер обмена</div>
    <textarea id="clipT" placeholder="Здесь появится содержимое буфера ноута, или напиши текст и отправь"></textarea>
    <div class="row"><button id="clipGet">Взять с ноута</button><button id="clipSet">Отправить на ноут</button></div>
  </section>

  <section class="tab" id="t-power">
    <button class="back" data-go="more">‹ Ещё</button>
    <div class="act">
      <button id="lockB">Заблокировать</button><button id="sleepB">Сон</button>
      <button id="offB" class="full danger">Выключить сейчас</button>
    </div>
    <div class="card">
      <div class="lbl">Выключить через…</div>
      <div class="timers"><button data-t="15">15 мин</button><button data-t="30">30 мин</button><button data-t="60">1 час</button><button data-t="120">2 часа</button></div>
      <div id="tleft"></div>
      <button id="tcancel" style="width:100%;margin-top:8px;display:none">Отменить таймер</button>
    </div>
  </section>
</main>
<nav>
  <button class="on" data-tab="pad">Пульт</button>
  <button data-tab="home">Обзор</button>
  <button data-tab="notes">Заметки</button>
  <button data-tab="files">Файлы</button>
  <button data-tab="more">Ещё</button>
</nav>
<div id="toast"></div>
<div id="lock">
  <div style="width:72px;height:72px;border-radius:18px;box-shadow:0 0 40px rgba(110,231,255,.35)"><svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g1" gradientUnits="userSpaceOnUse" x1="0" y1="17" x2="0" y2="53"><stop offset="0" stop-color="#6ee7ff"/><stop offset="1" stop-color="#60a5fa"/></linearGradient><linearGradient id="g2" gradientUnits="userSpaceOnUse" x1="0" y1="11" x2="0" y2="47"><stop offset="0" stop-color="#818cf8"/><stop offset="1" stop-color="#c084fc"/></linearGradient><linearGradient id="db" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#171d44"/><stop offset="1" stop-color="#0b1020"/></linearGradient></defs><rect width="64" height="64" rx="16" fill="url(#db)"/><rect class="lb" x="15" y="17" width="10" height="36" rx="5" fill="url(#g1)"/><path class="lw" d="M31 13A16 16 0 0 1 31 45Z" fill="url(#g2)" stroke="url(#g2)" stroke-width="4" stroke-linejoin="round"/></svg></div>
  <div id="lt" style="font-size:21px;font-weight:650">DaSync</div>
  <div id="ld" class="lbl" style="max-width:310px;line-height:1.5"></div>
  <input type="text" id="plink" placeholder="Вставь ссылку подключения" autocapitalize="off" autocorrect="off" style="display:none;width:100%;max-width:320px;font-size:15px;letter-spacing:0;text-align:left">
  <button id="go" style="display:none">Повторить</button>
</div>
<script>
const $=s=>document.querySelector(s);
/*CRYPTO-START*/
const K256=new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
function sha256(m){
  const l=m.length,nb=((l+9+63)>>6)<<6,buf=new Uint8Array(nb);buf.set(m);buf[l]=0x80;
  const dv=new DataView(buf.buffer);dv.setUint32(nb-4,(l*8)>>>0);dv.setUint32(nb-8,Math.floor(l/0x20000000));
  let h0=0x6a09e667,h1=0xbb67ae85,h2=0x3c6ef372,h3=0xa54ff53a,h4=0x510e527f,h5=0x9b05688c,h6=0x1f83d9ab,h7=0x5be0cd19;
  const w=new Uint32Array(64);
  for(let o=0;o<nb;o+=64){
    for(let i=0;i<16;i++)w[i]=dv.getUint32(o+i*4);
    for(let i=16;i<64;i++){
      const x=w[i-15],y=w[i-2];
      const s0=((x>>>7)|(x<<25))^((x>>>18)|(x<<14))^(x>>>3);
      const s1=((y>>>17)|(y<<15))^((y>>>19)|(y<<13))^(y>>>10);
      w[i]=(w[i-16]+s0+w[i-7]+s1)|0;
    }
    let a=h0,b=h1,c=h2,d=h3,e=h4,f=h5,g=h6,h=h7;
    for(let i=0;i<64;i++){
      const S1=((e>>>6)|(e<<26))^((e>>>11)|(e<<21))^((e>>>25)|(e<<7));
      const t1=(h+S1+((e&f)^(~e&g))+K256[i]+w[i])|0;
      const S0=((a>>>2)|(a<<30))^((a>>>13)|(a<<19))^((a>>>22)|(a<<10));
      const t2=(S0+((a&b)^(a&c)^(b&c)))|0;
      h=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;
    }
    h0=(h0+a)|0;h1=(h1+b)|0;h2=(h2+c)|0;h3=(h3+d)|0;h4=(h4+e)|0;h5=(h5+f)|0;h6=(h6+g)|0;h7=(h7+h)|0;
  }
  const out=new Uint8Array(32),ov=new DataView(out.buffer);
  [h0,h1,h2,h3,h4,h5,h6,h7].forEach((v,i)=>ov.setUint32(i*4,v));
  return out;
}
function hmac(key,msg){
  if(key.length>64)key=sha256(key);
  const ip=new Uint8Array(64+msg.length),op=new Uint8Array(96);
  for(let i=0;i<64;i++){const k=i<key.length?key[i]:0;ip[i]=k^0x36;op[i]=k^0x5c}
  ip.set(msg,64);op.set(sha256(ip),64);return sha256(op);
}
const enc=new TextEncoder();
const hex=u=>Array.from(u,x=>x.toString(16).padStart(2,'0')).join('');
const unhex=h=>new Uint8Array(h.match(/../g).map(x=>parseInt(x,16)));
const hmacHex=(kh,s)=>hex(hmac(unhex(kh),enc.encode(s)));
const rand=n=>hex(crypto.getRandomValues(new Uint8Array(n)));
/*CRYPTO-END*/
let creds=null;try{creds=JSON.parse(localStorage.getItem('dasync')||'null')}catch(e){}
let skew=0,lastDeny=0;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function signHeaders(method,path,bh){
  const ts=Math.floor(Date.now()/1000+skew),nonce=rand(8);
  return{'X-Dev':creds.devid,'X-Ts':String(ts),'X-Nonce':nonce,'X-Sig':hmacHex(creds.k,method+'\n'+path+'\n'+ts+'\n'+nonce+'\n'+bh)};
}
function signedUrl(name){
  const exp=Math.floor(Date.now()/1000+skew)+300;
  return '/f/'+encodeURIComponent(name)+'?d='+creds.devid+'&exp='+exp+'&sig='+hmacHex(creds.k,'GET\n/f/'+name+'\n'+exp);
}
function syncClock(r){const n=r.headers.get('X-Now');if(n)skew=Number(n)-Date.now()/1000}
let S=null,sortBy='cpu',hist=[],curTab='pad',curPane='pad',locked=false,busy=false,mx=0,my=0,sc=0,drag=false;

async function api(body){
  if(!creds){forget();throw 0}
  const str=JSON.stringify(body),bh=hex(sha256(enc.encode(str)));
  for(let n=0;n<2;n++){
    const h=signHeaders('POST','/api',bh);h['Content-Type']='application/json';
    const r=await fetch('/api',{method:'POST',headers:h,body:str});
    syncClock(r);
    if(r.ok){online(true);return r.json()}
    const j=await r.json().catch(()=>({}));
    if(r.status===401){if(j.error==='ts'&&n===0)continue;forget('Ноутбук не узнал это устройство. Подключи его заново.');throw 0}
    if(r.status===429){showPair('Слишком много попыток','Подожди полминуты и обнови страницу.',{btn:true});throw 0}
    if(r.status===403){
      if(j.error==='denied'){if(Date.now()-lastDeny>2500){lastDeny=Date.now();toast('Нет разрешения: '+(j.title||j.cap)+'. Включи в DaSync на ноуте → Устройства')}throw 3}
      if(j.error==='blocked'){showPair('Устройство заблокировано','Ноутбук запретил этому телефону подключаться.');throw 0}
      showPair('Нет доступа','Ноутбук принимает подключения только из домашней сети.',{btn:true});throw 0;
    }
    if(r.status===503){online(false,'Пауза на ноуте');throw 2}
    throw 1;
  }
}
function online(v,t){$('#dot').classList.toggle('on',v);$('#st').textContent=v?'На связи':(t||'Нет связи')}
function showPair(title,text,o){
  o=o||{};locked=true;$('#lt').textContent=title;$('#ld').textContent=text;
  $('#plink').style.display=o.input?'block':'none';$('#go').style.display=o.btn?'block':'none';
  $('#lock').classList.add('show');online(false);
}
function forget(msg){
  creds=null;try{localStorage.removeItem('dasync')}catch(e){}
  showPair('Подключи ноутбук',(msg?msg+' ':'')+'Открой DaSync на ноутбуке и наведи камеру телефона на QR. Если открыто как приложение с домашнего экрана, скопируй ссылку подключения в DaSync на ноуте и вставь сюда.',{input:true});
}
async function startPairing(S){
  const devid=rand(16),cn=rand(16);
  showPair('Подключаюсь…','Проверяю код…');
  let r;
  try{r=await fetch('/pair/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({devid,cn,proof:hmacHex(S,'pair1|'+devid+'|'+cn)})})}
  catch(e){showPair('Нет связи с ноутбуком','Проверь, что телефон в той же Wi-Fi, что и ноутбук, и что DaSync запущен.',{btn:true});return}
  syncClock(r);
  const j=await r.json().catch(()=>({}));
  if(r.status===401){showPair('Код устарел','QR действует 2 минуты и работает один раз. Обнови QR в окне DaSync и отсканируй снова.',{input:true});return}
  if(r.status===403){showPair(j.error==='blocked'?'Устройство заблокировано':'Нет доступа',j.error==='blocked'?'Ноутбук запретил этому телефону подключаться.':'Подключаться можно только из домашней сети.');return}
  if(r.status===429){showPair('Слишком много попыток','Подожди минуту.',{btn:true});return}
  if(r.status===503){showPair('DaSync на паузе','Включи «Принимать команды» на ноутбуке и повтори.',{btn:true});return}
  if(!r.ok||!j.sn){showPair('Что-то пошло не так','Попробуй ещё раз.',{btn:true});return}
  const k=hmacHex(S,'key|'+devid+'|'+cn+'|'+j.sn);
  showPair('Подтверди на ноутбуке','На ноутбуке появился запрос на подключение. Нажми «Разрешить» в окне DaSync.');
  for(let i=0;i<150;i++){
    await sleep(2000);
    let sj;
    try{const sr=await fetch('/pair/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({devid,mac:hmacHex(k,'status|'+devid)})});sj=await sr.json()}catch(e){continue}
    if(sj.status==='approved'){
      if(sj.mac!==hmacHex(k,'approved|'+devid+'|'+j.sn)){showPair('Ошибка безопасности','Ответ ноутбука не прошёл проверку. Подключение отменено.',{btn:true});return}
      creds={devid,k};try{localStorage.setItem('dasync',JSON.stringify(creds))}catch(e){}
      locked=false;$('#lock').classList.remove('show');toast('Подключено');poll();return;
    }
    if(sj.status==='denied'){showPair('Отклонено','Ноутбук отклонил подключение.');return}
    if(sj.status==='none'){break}
  }
  showPair('Время вышло','Запрос не подтвердили. Отсканируй QR заново.',{input:true});
}
let tt=null;function toast(m){const e=$('#toast');e.textContent=m;e.classList.add('show');clearTimeout(tt);tt=setTimeout(()=>e.classList.remove('show'),1800)}
const run=(body,msg)=>api(body).then(r=>{if(r&&r.error)toast(r.error);else if(msg)toast(msg);return r}).catch(()=>{});
$('#go').onclick=()=>location.reload();
$('#plink').oninput=e=>{const m=e.target.value.toLowerCase().match(/[0-9a-f]{32}/);if(m){e.target.value='';startPairing(m[0])}};
function esc(t){return String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
const gb=b=>(b/1073741824).toFixed(b>=1.07e10?0:1)+' ГБ';
const mb=b=>b>=1073741824?(b/1073741824).toFixed(1)+' ГБ':Math.round(b/1048576)+' МБ';
const fsz=b=>b>=1073741824?(b/1073741824).toFixed(1)+' ГБ':b>=1048576?(b/1048576).toFixed(1)+' МБ':Math.max(1,Math.round(b/1024))+' КБ';
const rate=b=>b>=1048576?(b/1048576).toFixed(1)+' МБ/с':Math.round(b/1024)+' КБ/с';
const fmtD=ts=>new Date(ts*1000).toLocaleString('ru',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
function dur(s){const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return(d?d+' д ':'')+(h?h+' ч ':'')+m+' мин'}
function copyLocal(t){const a=document.createElement('textarea');a.value=t;a.style.cssText='position:fixed;opacity:0;top:0';document.body.appendChild(a);a.select();a.setSelectionRange(0,1e6);let ok=false;try{ok=document.execCommand('copy')}catch(e){}a.remove();return ok}

/* ---------- навигация ---------- */
const NAVOF={pad:'pad',home:'home',notes:'notes',files:'files',more:'more',hist:'more',proc:'more',fun:'more',power:'more'};
function go(t){
  curTab=t;
  document.querySelectorAll('main>.tab').forEach(x=>x.classList.toggle('show',x.id==='t-'+t));
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.tab===NAVOF[t]));
  if(t==='home')spark();
  if(t==='hist')loadHist();
  if(t==='notes')loadNotes();
  if(t==='files')loadFiles();
  if(t==='pad'&&curPane==='screen')shot();
  poll();
}
document.querySelectorAll('nav [data-tab]').forEach(b=>b.onclick=()=>go(b.dataset.tab));
document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>go(b.dataset.go));
function setPane(p){
  curPane=p;
  document.querySelectorAll('.pane').forEach(x=>x.classList.toggle('show',x.id==='p-'+p));
  document.querySelectorAll('#pseg button').forEach(b=>b.classList.toggle('on',b.dataset.pane===p));
  if(p==='screen')shot();
}
document.querySelectorAll('#pseg button').forEach(b=>b.onclick=()=>setPane(b.dataset.pane));

/* ---------- тачпад ---------- */
setInterval(async()=>{
  if(busy||locked)return;
  const dx=Math.trunc(mx),dy=Math.trunc(my),n=Math.trunc(sc);
  if(!dx&&!dy&&!n)return;
  mx-=dx;my-=dy;sc-=n;busy=true;
  try{if(dx||dy)await api({a:'move',dx,dy});if(n)await api({a:'scroll',n})}catch(e){}
  busy=false;
},16);
const pad=$('#pad');let last=null,t0=0,moved=0,maxT=0;
const cen=ts=>{let x=0,y=0;for(const t of ts){x+=t.clientX;y+=t.clientY}return{x:x/ts.length,y:y/ts.length}};
pad.addEventListener('touchstart',e=>{e.preventDefault();if(e.touches.length===1){t0=Date.now();moved=0;maxT=0}maxT=Math.max(maxT,e.touches.length);last=cen(e.touches)},{passive:false});
pad.addEventListener('touchmove',e=>{
  e.preventDefault();const c=cen(e.touches),dx=c.x-last.x,dy=c.y-last.y;last=c;moved+=Math.abs(dx)+Math.abs(dy);
  if(e.touches.length===1){const g=1.3+Math.min(Math.hypot(dx,dy),40)/25;mx+=dx*g;my+=dy*g}else{sc+=dy/12}
},{passive:false});
pad.addEventListener('touchend',e=>{
  e.preventDefault();if(e.touches.length){last=cen(e.touches);return}
  if(moved<8&&Date.now()-t0<250&&!drag)api({a:'click',b:maxT>=2?'right':'left'}).catch(()=>{});
},{passive:false});
$('#bl').onclick=()=>api({a:'click',b:'left'}).catch(()=>{});
$('#br').onclick=()=>api({a:'click',b:'right'}).catch(()=>{});
$('#bd').onclick=async e=>{drag=!drag;e.currentTarget.classList.toggle('on',drag);try{await api({a:drag?'down':'up'})}catch(_){}};

/* ---------- экран ---------- */
let live=false,shotBusy=false,mode='click';
const screenOn=()=>curTab==='pad'&&curPane==='screen'&&!document.hidden&&!locked;
async function shot(){
  if(shotBusy||!screenOn())return;shotBusy=true;
  try{const r=await api({a:'shot'});$('#scr').src=r.img;const c=$('#cur');c.style.display='block';c.style.left=r.cx*100+'%';c.style.top=r.cy*100+'%'}catch(e){if(e===3){live=false;$('#liveB').classList.remove('on');$('#liveB').textContent='Live: выкл'}}
  shotBusy=false;if(live&&screenOn())setTimeout(shot,350);
}
$('#shotB').onclick=shot;
$('#liveB').onclick=e=>{live=!live;e.currentTarget.classList.toggle('on',live);e.currentTarget.textContent='Live: '+(live?'вкл':'выкл');if(live)shot()};
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;document.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('on',x===b))});
$('#scr').addEventListener('click',async e=>{
  const r=e.currentTarget.getBoundingClientRect();
  const fx=(e.clientX-r.left)/r.width,fy=(e.clientY-r.top)/r.height;
  try{await api({a:'tap',fx,fy,b:mode==='right'?'right':'left',n:mode==='double'?2:1})}catch(_){return}
  setTimeout(shot,450);
});

/* ---------- ввод ---------- */
const sendText=async enter=>{const t=$('#txt').value;if(!t)return;try{const r=await api({a:'text',t});if(r&&r.error){toast(r.error);return}if(enter)await api({a:'key',k:'enter'});$('#txt').value='';toast('Отправлено')}catch(e){if(e===1)toast('Не удалось отправить текст')}};
$('#send').onclick=()=>sendText(false);$('#sendEnter').onclick=()=>sendText(true);
document.querySelectorAll('[data-k]').forEach(b=>b.onclick=()=>api({a:'key',k:b.dataset.k}).catch(()=>{}));
document.querySelectorAll('[data-m]').forEach(b=>b.onclick=()=>api({a:'media',m:b.dataset.m}).catch(()=>{}));

/* ---------- обзор ---------- */
function bar(id,p,w=75,b=90){const e=$(id);e.style.width=Math.min(100,p)+'%';e.style.background=p>=b?'var(--bad)':p>=w?'var(--warn)':'var(--ok)'}
function spark(){
  const c=$('#spark');if(!c.clientWidth)return;const w=c.clientWidth*devicePixelRatio,h=c.clientHeight*devicePixelRatio;
  c.width=w;c.height=h;const x=c.getContext('2d');
  x.strokeStyle='#7fb4ff';x.lineWidth=2*devicePixelRatio;x.lineJoin='round';x.beginPath();
  hist.forEach((v,i)=>{const px=i/59*w,py=h-(v/100)*(h-4)-2;i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke();
}
function render(s){
  S=s;$('#host').textContent=s.host;$('#up').textContent='Ноутбук включён '+dur(s.uptime);
  $('#cpu').textContent=Math.round(s.cpu)+'%';bar('#cpuB',s.cpu);
  hist.push(s.cpu);if(hist.length>60)hist.shift();spark();
  $('#temp').textContent=s.temp!=null?'Температура: '+s.temp+' °C':'';
  $('#ram').textContent=Math.round(s.ram.pct)+'%';bar('#ramB',s.ram.pct);$('#ramS').textContent=gb(s.ram.used)+' из '+gb(s.ram.total);
  $('#disk').textContent=Math.round(s.disk.pct)+'%';bar('#diskB',s.disk.pct,85,95);$('#diskS').textContent='свободно '+gb(s.disk.free);
  $('#down').textContent=rate(s.net.down);$('#upl').textContent=rate(s.net.up);
  if(s.bat){
    $('#bat').textContent=s.bat.pct+'%';const e=$('#batB');e.style.width=s.bat.pct+'%';
    e.style.background=s.bat.pct<=15&&!s.bat.plugged?'var(--bad)':s.bat.pct<=30&&!s.bat.plugged?'var(--warn)':'var(--ok)';
    $('#batS').textContent=s.bat.plugged?'заряжается':(s.bat.left?'осталось '+Math.floor(s.bat.left/3600)+' ч '+Math.floor(s.bat.left%3600/60)+' мин':'от батареи');
  }else{$('#bat').textContent='–';$('#batS').textContent='нет батареи';$('#batB').style.width='0'}
  if(s.timer!=null){$('#tleft').textContent='Выключение через '+Math.floor(s.timer/60)+' мин '+(s.timer%60)+' с';$('#tcancel').style.display='block'}
  else{$('#tleft').textContent='';$('#tcancel').style.display='none'}
  renderProcs();
}

/* ---------- процессы и питание ---------- */
function renderProcs(){
  if(!S)return;const list=sortBy==='cpu'?S.top_cpu:S.top_mem;
  $('#plist').innerHTML=list.map(p=>`<div class="proc"><div class="n"><b>${esc(p.name)}</b><span>${p.cpu.toFixed(1)}% ЦП · ${mb(p.mem)}${p.n>1?' · процессов: '+p.n:''}</span></div>${p.protected?'':`<button class="danger" data-kill="${esc(p.name)}">Закрыть</button>`}</div>`).join('');
}
$('#plist').onclick=async e=>{
  const n=e.target.dataset&&e.target.dataset.kill;if(!n)return;
  if(!confirm('Закрыть «'+n+'»? Несохранённые данные пропадут.'))return;
  run({a:'kill',name:n},'Закрыто');
};
$('#sCpu').onclick=()=>{sortBy='cpu';$('#sCpu').classList.add('on');$('#sMem').classList.remove('on');renderProcs()};
$('#sMem').onclick=()=>{sortBy='mem';$('#sMem').classList.add('on');$('#sCpu').classList.remove('on');renderProcs()};
$('#lockB').onclick=()=>run({a:'power',m:'lock'});
$('#sleepB').onclick=()=>{if(confirm('Отправить ноутбук в сон? Связь с ним пропадёт.'))run({a:'power',m:'sleep'})};
$('#offB').onclick=()=>{if(confirm('Выключить ноутбук прямо сейчас?'))run({a:'power',m:'shutdown'})};
document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{if(confirm('Выключить ноутбук через '+b.textContent+'?'))run({a:'timer',min:+b.dataset.t}).then(()=>poll())});
$('#tcancel').onclick=()=>run({a:'cancel'}).then(()=>poll());

/* ---------- история ---------- */
let hr='1h',histTimer=null;
function chart(cv,series,max){
  const d=devicePixelRatio,w=cv.clientWidth*d,h=cv.clientHeight*d;cv.width=w;cv.height=h;const x=cv.getContext('2d');
  if(!max){max=1;series.forEach(s=>s.v.forEach(v=>{if(v!=null&&v>max)max=v}));max*=1.1}
  x.strokeStyle='#2b303a';x.lineWidth=d;
  [0,.5,1].forEach(f=>{const y=h-4*d-f*(h-8*d);x.beginPath();x.moveTo(0,y);x.lineTo(w,y);x.stroke()});
  series.forEach(s=>{
    x.strokeStyle=s.c;x.lineWidth=2*d;x.lineJoin='round';x.beginPath();let pen=false;const n=s.v.length;
    s.v.forEach((v,i)=>{if(v==null){pen=false;return}const px=i/(n-1)*w,py=h-4*d-Math.min(v/max,1)*(h-8*d);pen?x.lineTo(px,py):x.moveTo(px,py);pen=true});
    x.stroke();
  });
  return max;
}
const tfmt=(ts,span)=>new Date(ts*1000).toLocaleString('ru',span>86400?{weekday:'short',hour:'2-digit',minute:'2-digit'}:{hour:'2-digit',minute:'2-digit'});
function hm(min){return min>=60?Math.floor(min/60)+' ч '+(min%60)+' мин':min+' мин'}
function renderHist(r){
  const s=r.sum;
  if(!s.n){['hCpu','hRam','hNet','hAct'].forEach(i=>$('#'+i).textContent='–');$('#hCover').textContent='Данных пока нет: приложение копит их каждые 10 секунд. Загляни позже.';return}
  $('#hCpu').textContent=Math.round(s.cpu_avg)+'%';$('#hCpuS').textContent='пик '+Math.round(s.cpu_max)+'%';
  $('#hRam').textContent=Math.round(s.ram_avg)+'%';$('#hRamS').textContent='пик '+Math.round(s.ram_max)+'%';
  $('#hNet').textContent='↓ '+fsz(s.down);$('#hNetS').textContent='↑ '+fsz(s.up);
  if(s.active_min!=null){$('#hAct').textContent=hm(s.active_min);$('#hActS').textContent='активно из '+hm(Math.round(r.span/60))}
  else{$('#hAct').textContent='–';$('#hActS').textContent='только на Windows'}
  chart($('#cCpu'),[{v:r.cpu_max,c:'#4a5a78'},{v:r.cpu,c:'#7fb4ff'}],100);
  chart($('#cRam'),[{v:r.ram,c:'#b69cff'}],100);
  const m=chart($('#cNet'),[{v:r.down,c:'#5cc98a'},{v:r.up,c:'#e8b04b'}]);
  $('#cNetL').textContent='макс '+rate(m/1.1)+' · зелёный ↓ жёлтый ↑';
  const hasBat=r.bat.some(v=>v!=null);$('#cBatC').style.display=hasBat?'block':'none';
  if(hasBat)chart($('#cBat'),[{v:r.bat,c:'#5cc98a'}],100);
  $('#htop').innerHTML=r.top.length?r.top.map(t=>`<div class="topbar"><b>${esc(t.name)}</b><span>${t.pct}% времени</span></div>`).join(''):'<div class="sub">Никто не нагружал ноут заметно</div>';
  $('#hAxis').textContent=tfmt(r.since,r.span)+'  →  '+tfmt(r.now,r.span);
  $('#hCover').textContent=s.cover<90?'Записано '+s.cover+'% периода: в остальное время приложение не работало или ноут спал.':'';
}
async function loadHist(){
  clearTimeout(histTimer);if(curTab!=='hist'||locked)return;
  try{renderHist(await api({a:'history',r:hr}))}catch(e){}
  histTimer=setTimeout(loadHist,30000);
}
document.querySelectorAll('#hseg button').forEach(b=>b.onclick=()=>{hr=b.dataset.r;document.querySelectorAll('#hseg button').forEach(x=>x.classList.toggle('on',x===b));loadHist()});

/* ---------- заметки ---------- */
let NOTES=[],editing=null,nq='';
function noteHtml(n){
  return n.text.split('\n').map((ln,i)=>{
    const m=ln.match(/^\s*\[( |x|X)\]\s?(.*)$/);
    if(m){const on=m[1]!==' ';return `<label class="ck" data-n="${n.id}" data-i="${i}"><span class="box ${on?'on':''}"></span><span class="${on?'done':''}">${esc(m[2])}</span></label>`}
    return `<div>${esc(ln)||'&nbsp;'}</div>`;
  }).join('');
}
function renderNotes(){
  const q=nq.toLowerCase();const list=NOTES.filter(n=>!q||n.text.toLowerCase().includes(q));
  $('#nlist').innerHTML=list.length?list.map(n=>{
    if(editing===n.id)return `<div class="card note"><textarea id="ned" style="min-height:140px">${esc(n.text)}</textarea><div class="row" style="margin-top:10px"><button data-act="save" data-id="${n.id}">Сохранить</button><button data-act="cancel">Отмена</button></div></div>`;
    return `<div class="card note ${n.pinned?'pin':''}">${noteHtml(n)}<div class="nf"><span>${n.pinned?'📌 ':''}${fmtD(n.ts)}</span><span class="nb"><button data-act="pin" data-id="${n.id}">${n.pinned?'Открепить':'Закрепить'}</button><button data-act="edit" data-id="${n.id}">Изменить</button><button data-act="toPc" data-id="${n.id}">На ноут</button><button data-act="copy" data-id="${n.id}">Копия</button><button class="danger" data-act="del" data-id="${n.id}">✕</button></span></div></div>`;
  }).join(''):'<div class="h" style="text-align:center;padding:24px">Пока пусто</div>';
}
async function loadNotes(){try{NOTES=(await api({a:'notes'})).notes;renderNotes()}catch(e){}}
$('#nadd').onclick=async()=>{const t=$('#nnew').value.trim();if(!t)return;try{await api({a:'note_add',text:t});$('#nnew').value='';loadNotes()}catch(e){}};
$('#nchk').onclick=()=>{const a=$('#nnew');a.value+=(a.value&&!a.value.endsWith('\n')?'\n':'')+'[ ] ';a.focus()};
$('#nq').oninput=e=>{nq=e.target.value;renderNotes()};
$('#nlist').onclick=async e=>{
  const ck=e.target.closest('.ck');
  if(ck){
    const n=NOTES.find(x=>x.id==ck.dataset.n),i=+ck.dataset.i;if(!n)return;
    const lines=n.text.split('\n');lines[i]=lines[i].replace(/\[( |x|X)\]/,(m,c)=>c===' '?'[x]':'[ ]');
    n.text=lines.join('\n');renderNotes();run({a:'note_set',id:n.id,text:n.text});return;
  }
  const b=e.target.closest('button');if(!b)return;
  const id=+b.dataset.id,n=NOTES.find(x=>x.id===id);
  switch(b.dataset.act){
    case 'pin':await run({a:'note_pin',id,pinned:n.pinned?0:1});loadNotes();break;
    case 'edit':editing=id;renderNotes();break;
    case 'cancel':editing=null;renderNotes();break;
    case 'save':{const t=$('#ned').value;editing=null;await run({a:'note_set',id,text:t});loadNotes();break}
    case 'toPc':run({a:'clip_set',t:n.text},'Скопировано в буфер ноута');break;
    case 'copy':toast(copyLocal(n.text)?'Скопировано':'Не вышло скопировать');break;
    case 'del':if(confirm('Удалить заметку?')){await run({a:'note_del',id});loadNotes()}break;
  }
};

/* ---------- файлы ---------- */
async function loadFiles(){
  try{
    const r=await api({a:'files'});$('#fdir').textContent='Папка на ноуте: '+r.dir;
    $('#flist').innerHTML=r.files.length?r.files.map(f=>{
      const u=signedUrl(f.name);
      return `<div class="file"><div class="n"><b>${esc(f.name)}</b><span>${fsz(f.size)} · ${fmtD(f.ts)}</span></div><a href="${u}&inline=1" target="_blank">Открыть</a><a href="${u}" download>Скачать</a><button class="danger" style="min-height:34px;padding:0 10px;font-size:14px" data-del="${esc(f.name)}">✕</button></div>`;
    }).join(''):'<div class="sub" style="text-align:center;padding:14px">Папка пуста. Кинь сюда файл с телефона, и он появится на ноуте.</div>';
  }catch(e){}
}
$('#flist').onclick=async e=>{const n=e.target.dataset&&e.target.dataset.del;if(n&&confirm('Удалить «'+n+'» с ноутбука?')){await run({a:'file_del',name:n});loadFiles()}};
$('#fopen').onclick=()=>run({a:'open_folder'});
$('#fup').onchange=e=>{
  const list=[...e.target.files];if(!list.length)return;let i=0;
  const next=()=>{
    if(i>=list.length){$('#upst').textContent='Готово: '+list.length+' шт.';loadFiles();e.target.value='';return}
    const f=list[i++],x=new XMLHttpRequest();
    const fn=encodeURIComponent(f.name);x.open('POST','/upload');const hh=signHeaders('POST','/upload',hex(sha256(enc.encode(fn+'|'+f.size))));for(const k in hh)x.setRequestHeader(k,hh[k]);x.setRequestHeader('X-Filename',fn);
    x.upload.onprogress=ev=>{if(ev.lengthComputable)$('#upst').textContent=i+'/'+list.length+' · '+f.name+' · '+Math.round(ev.loaded/ev.total*100)+'%'};
    x.onload=()=>{if(x.status!==200){$('#upst').textContent=x.status===403?'Нет разрешения на файлы: включи в DaSync на ноуте → Устройства':'Ошибка загрузки ('+x.status+')';return}next()};
    x.onerror=()=>{$('#upst').textContent='Нет связи с ноутом'};
    x.send(f);
  };
  next();
};

/* ---------- фишки ---------- */
document.querySelectorAll('[data-c]').forEach(b=>b.onclick=()=>run({a:'combo',id:b.dataset.c}));
$('#sayB').onclick=()=>{const t=$('#sayT').value.trim();if(t)run({a:'say',t},'Говорит…')};
$('#popB').onclick=()=>{const t=$('#sayT').value.trim();if(t)run({a:'popup',t},'Показано на экране')};
$('#urlB').onclick=()=>{const u=$('#urlT').value.trim();if(u)run({a:'openurl',u},'Открываю на ноуте')};
$('#clipGet').onclick=async()=>{const r=await run({a:'clip_get'});if(r){$('#clipT').value=r.t;toast('Буфер ноута получен')}};
$('#clipSet').onclick=()=>{const t=$('#clipT').value;if(t)run({a:'clip_set',t},'Отправлено в буфер ноута')};

/* ---------- опрос ---------- */
let timer=null;
async function poll(){
  clearTimeout(timer);
  if(!locked&&!document.hidden){
    try{const s=await api({a:['home','proc','power'].includes(curTab)?'stats':'ping'});$('#lock').classList.remove('show');if(s.cpu!==undefined)render(s)}
    catch(e){if(e!==0&&e!==2&&e!==3)online(false)}
  }
  timer=setTimeout(poll,2000);
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden){poll();if(curTab==='pad'&&curPane==='screen')shot()}});
const pm=location.hash.match(/p=([0-9a-f]{32})/);
if(pm){history.replaceState(null,'',location.pathname);startPairing(pm[1])}
else if(creds)poll();
else forget();
</script></body></html>
"""


# ---------- логотип ----------
def make_icon(size=180, on=True, rounded=True, scale=1.0, bg=True):
    """Логотип DaSync: буква D, разрезанная на две части. Полоска и полукруг чуть сдвинуты
    друг относительно друга: два устройства, которые синхронизируются.
    bg=False даёт прозрачный фон (для adaptive-иконок)."""
    import math
    from PIL import Image, ImageDraw, ImageOps
    S = size
    N = S * (4 if S <= 256 else 2)
    if on:
        top, bot = (23, 29, 68), (11, 16, 32)
        g1, g2 = ((110, 231, 255), (96, 165, 250)), ((129, 140, 248), (192, 132, 252))
    else:
        top, bot = (44, 48, 58), (24, 27, 34)
        g1, g2 = ((150, 158, 172), (120, 128, 142)), ((130, 138, 152), (104, 112, 126))

    def P(u):  # координаты в системе 64x64
        return N * (0.5 + (u / 64 - 0.5) * scale)

    def Ln(u):
        return N * (u / 64) * scale

    def vgrad(y0, y1, c0, c1):
        h = max(int(y1 - y0), 1)
        g = Image.new("L", (N, N), 0)
        g.paste(Image.linear_gradient("L").resize((N, h)), (0, int(y0)))
        ImageDraw.Draw(g).rectangle((0, int(y1), N, N), fill=255)
        return ImageOps.colorize(g, c0, c1).convert("RGBA")

    if bg:
        img = ImageOps.colorize(Image.linear_gradient("L").resize((N, N)), top, bot).convert("RGBA")
    else:
        img = Image.new("RGBA", (N, N), (0, 0, 0, 0))

    # полоска (ствол D)
    bar = Image.new("L", (N, N), 0)
    ImageDraw.Draw(bar).rounded_rectangle((P(15), P(17), P(25), P(53)), radius=Ln(5), fill=255)
    img.paste(vgrad(P(17), P(53), *g1), (0, 0), bar)

    # полукруг (изгиб D) со скруглёнными углами
    # уменьшенный полукруг + диск радиуса 2 по всему контуру = скруглённые углы без артефактов
    rc = 2.0
    inner = [(P(33 + 14 * math.cos(math.radians(a))), P(29 + 14 * math.sin(math.radians(a)))) for a in range(-90, 91)]
    flat = [(P(33), P(15 + t * 0.25)) for t in range(0, int(28 / 0.25) + 1)]
    bowl = Image.new("L", (N, N), 0)
    bd = ImageDraw.Draw(bowl)
    bd.polygon(inner, fill=255)
    rr = Ln(rc)
    for cx, cy in inner + flat:
        bd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=255)
    img.paste(vgrad(P(11), P(47), *g2), (0, 0), bowl)

    if rounded and bg:
        mask = Image.new("L", (N, N), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), radius=int(N * 0.25), fill=255)
        img.putalpha(mask)
    return img.resize((S, S), Image.LANCZOS)


# ---------- окно приложения ----------
TRAY = {}


def open_desk():
    url = f"http://127.0.0.1:{PORT}/desk"
    try:
        flags = ["--window-size=1180,780", "--no-first-run", "--no-default-browser-check",
                 f"--user-data-dir={os.path.join(CFG_DIR, 'window')}"]
        if OS == "Windows":
            cands = []
            for k in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData"):
                base = os.environ.get(k)
                if base:
                    cands += [os.path.join(base, r"Microsoft\Edge\Application\msedge.exe"),
                              os.path.join(base, r"Google\Chrome\Application\chrome.exe")]
            for exe in cands:
                if os.path.exists(exe):
                    subprocess.Popen([exe, f"--app={url}"] + flags)
                    return
        elif OS == "Darwin":
            for app in ("Google Chrome", "Microsoft Edge"):
                if os.path.exists(f"/Applications/{app}.app"):
                    subprocess.Popen(["open", "-na", app, "--args", f"--app={url}"] + flags)
                    return
    except Exception:
        pass
    import webbrowser
    webbrowser.open(url)


def qr_matrix(text):
    m = QR_CACHE.get(text)
    if m is None:
        try:
            import qrcode
            q = qrcode.QRCode(border=0)
            q.add_data(text)
            q.make(fit=True)
            m = [[1 if v else 0 for v in row] for row in q.get_matrix()]
        except Exception:
            m = []
        QR_CACHE[text] = m
    return m


def desk_state():
    DESK_SEEN["t"] = time.time()
    now = time.time()
    keys = list(dict.fromkeys(list(DEV) + list(CFG["paired"])))
    devs = []
    with DEVL:
        for k in keys:
            dv, rec = DEV.get(k), CFG["paired"].get(k)
            if dv is None and rec is None:
                continue
            b = dv or {"ip": rec.get("ip", ""), "kind": rec.get("kind", "other"), "model": rec.get("model", "Устройство"),
                       "browser": rec.get("browser", ""),
                       "first": CFG.get("devices", {}).get(k, {}).get("first", rec.get("added", now)),
                       "last": rec.get("last", rec.get("added", now)), "count": 0, "online": False,
                       "since": now, "last_action": ""}
            devs.append({"key": k, "name": dev_name(k), "ip": b["ip"], "kind": b["kind"], "model": b["model"],
                         "browser": b["browser"], "first": b["first"], "last": b["last"], "count": b["count"],
                         "online": b["online"], "since": b["since"], "last_action": b["last_action"],
                         "blocked": is_blocked(k, b["ip"]), "caps": rec.get("caps") if rec else None,
                         "paired": bool(rec)})
    devs.sort(key=lambda d: (not d["online"], -d["last"]))
    with PAIRL:
        for k in [k for k, p in PENDING.items() if now - p["ts"] > 600]:
            PENDING.pop(k, None)
        pend = []
        for k, p in PENDING.items():
            if p["status"] == "pending" and now - p["ts"] < 300:
                kind, model, br = parse_ua(p["ua"])
                pend.append({"key": k, "kind": kind, "model": model, "browser": br, "ip": p["ip"], "ts": p["ts"]})
    with LOGL:
        entries = list(reversed(LOG[-150:]))
    cur = current_pair()
    url = get_url()
    if len(QR_CACHE) > 10:
        QR_CACHE.clear()
    return {
        "stats": dict(STATE), "devices": devs, "pending": pend, "log": entries,
        "qr": qr_matrix(f"{url}/#p={cur['s']}"),
        "cfg": {"url": url, "pair": cur["s"], "pair_exp": cur["exp"], "caps_default": CAPS_DEFAULT,
                "on": APP["on"], "autostart": autostart_enabled(), "os": OS,
                "host": socket.gethostname(), "folder": HUB_DIR, "port": PORT,
                "blocked": CFG.get("blocked", [])},
    }


def desk_handle(d):
    a = d.get("a")
    if a == "state":
        return desk_state()
    if a == "history":
        return history(d.get("r", "1h"))
    if a == "pause":
        on = bool(d.get("on"))
        if TRAY.get("set_on"):
            TRAY["set_on"](on)
        else:
            APP["on"] = on
        log("Ноутбук", "принимает команды" if on else "поставил приложение на паузу")
    elif a == "autostart" and OS == "Windows":
        set_autostart(bool(d.get("on")))
    elif a == "new_qr":
        rotate_pair()
    elif a == "pair_approve":
        key = clean_hex(d.get("key"))
        p = PENDING.get(key)
        if p and p["status"] == "pending":
            given = d.get("caps") or {}
            caps = {c: bool(given.get(c, CAPS_DEFAULT[c])) for c in CAPS_DEFAULT}
            kind, model, br = parse_ua(p["ua"])
            CFG["paired"][key] = {"k": p["k"], "caps": caps, "added": time.time(), "ip": p["ip"],
                                  "kind": kind, "model": model, "browser": br}
            CFG.setdefault("devices", {}).setdefault(key, {"first": time.time()})
            save_cfg(CFG)
            p["status"] = "approved"
            log("Ноутбук", f"разрешил подключение: {model}", "join")
    elif a == "pair_deny":
        p = PENDING.get(clean_hex(d.get("key")))
        if p and p["status"] == "pending":
            p["status"] = "denied"
            log("Ноутбук", "отклонил запрос на подключение", "warn")
    elif a == "set_caps":
        rec = CFG["paired"].get(clean_hex(d.get("key")))
        if rec and d.get("cap") in CAPS_DEFAULT:
            rec["caps"][d["cap"]] = bool(d.get("on"))
            save_cfg(CFG)
    elif a == "forget":
        key = clean_hex(d.get("key"))
        CFG["paired"].pop(key, None)
        CFG.get("devices", {}).pop(key, None)
        dv = DEV.pop(key, None)
        NONCES.pop(key, None)
        PENDING.pop(key, None)
        save_cfg(CFG)
        log("Ноутбук", "забыл устройство " + (dv["model"] if dv else ""), "warn")
    elif a == "forget_all":
        CFG["paired"].clear()
        DEV.clear()
        NONCES.clear()
        PENDING.clear()
        save_cfg(CFG)
        rotate_pair()
        log("Ноутбук", "забыл все устройства", "warn")
    elif a == "rename":
        CFG.setdefault("devices", {}).setdefault(str(d["key"]), {})["name"] = str(d["name"])[:30]
        save_cfg(CFG)
    elif a == "block":
        key = str(d["key"])
        dv = DEV.get(key)
        vals = [key] + ([dv["ip"]] if dv else [])
        bl = CFG.setdefault("blocked", [])
        for v in vals:
            if d.get("on") and v not in bl:
                bl.append(v)
            if not d.get("on") and v in bl:
                bl.remove(v)
        save_cfg(CFG)
        if dv and d.get("on"):
            dv["online"] = False
        log("Ноутбук", ("заблокировал " if d.get("on") else "разблокировал ") + dev_name(key), "warn")
    elif a == "unblock":
        bl = CFG.setdefault("blocked", [])
        if d.get("value") in bl:
            bl.remove(d["value"])
            save_cfg(CFG)
    elif a == "clear_log":
        with LOGL:
            LOG.clear()
    elif a == "open_folder":
        open_folder()
    elif a == "show":
        open_desk()
    elif a == "quit":
        if TRAY.get("quit"):
            TRAY["quit"]()
        else:
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
    return {"ok": True}


DESK_PAGE = r"""<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<title>DaSync</title>
<link rel="icon" type="image/png" href="/icon-v3.png">
<style>
:root{--bg:#141922;--side:#0e1218;--card:#1a212c;--card2:#202938;--line:#2a3445;--ink:#e6ecf5;--dim:#8995a8;--acc:#66c0f4;--ok:#5cc98a;--warn:#e8b04b;--bad:#e0705c;--vio:#b69cff}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{display:flex;background:radial-gradient(1200px 600px at 75% -10%,#1d2b40 0%,var(--bg) 60%) no-repeat,var(--bg);color:var(--ink);font:14px/1.4 "Segoe UI",system-ui,sans-serif;overflow:hidden;user-select:none}
::-webkit-scrollbar{width:10px}::-webkit-scrollbar-thumb{background:#2a3445;border-radius:6px;border:2px solid transparent;background-clip:padding-box}::-webkit-scrollbar-track{background:transparent}
aside{width:228px;background:var(--side);border-right:1px solid #19202a;padding:18px 12px;display:flex;flex-direction:column;gap:4px;flex:none}
.brand{display:flex;align-items:center;gap:10px;padding:4px 10px 20px;font-weight:700;font-size:16px}
.logo{width:34px;height:34px;border-radius:9px;display:grid;place-items:center}.logo svg{width:100%;height:100%;display:block}
.logo i{width:10px;height:10px;border-radius:50%;background:#0e1218}
.nav{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:10px;color:var(--dim);cursor:pointer;font-size:14.5px;position:relative;transition:background .15s,color .15s}
.nav:hover{background:#161d28;color:var(--ink)}
.nav.on{background:linear-gradient(90deg,rgba(102,192,244,.2),rgba(102,192,244,.03));color:#fff}
.nav.on:before{content:"";position:absolute;left:-12px;top:8px;bottom:8px;width:3px;border-radius:3px;background:var(--acc)}
svg.i{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;flex:none}
.badge{margin-left:auto;background:var(--ok);color:#06210f;border-radius:20px;padding:0 7px;font-size:12px;font-weight:700;display:none}
.sp{flex:1}
.side-foot{border-top:1px solid #19202a;padding:14px 8px 4px;color:var(--dim);font-size:13px;display:flex;align-items:center;gap:8px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--bad);flex:none}.dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
main{flex:1;min-width:0;display:flex;flex-direction:column}
.top{padding:22px 30px 8px;display:flex;align-items:center;gap:14px}
.top h1{margin:0;font-size:24px;font-weight:650}
.top .r{margin-left:auto;color:var(--dim);font-size:13px}
#off{display:none;margin:0 30px;padding:10px 14px;border-radius:12px;background:rgba(224,112,92,.15);color:var(--bad);align-items:center}
.pages{flex:1;overflow-y:auto;padding:8px 30px 30px}
.page{display:none}.page.show{display:block;animation:in .25s}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}
.c4{grid-column:span 4}.c5{grid-column:span 5}.c6{grid-column:span 6}.c7{grid-column:span 7}.c8{grid-column:span 8}.c12{grid-column:span 12}
.card{background:linear-gradient(180deg,var(--card2),var(--card));border:1px solid var(--line);border-radius:16px;padding:18px 20px;position:relative}
.card h3{margin:0 0 14px;font-size:13px;font-weight:600;color:var(--dim);text-transform:uppercase;letter-spacing:.8px}
.hero{overflow:hidden;background:linear-gradient(120deg,#23446c 0%,#1b2a40 55%,#182030 100%);display:flex;align-items:center;gap:22px;min-height:132px}
.hero:after{content:"";position:absolute;right:-70px;top:-90px;width:280px;height:280px;border-radius:50%;background:radial-gradient(circle,rgba(102,192,244,.32),transparent 65%)}
.hero svg.big{width:76px;height:76px;stroke:#bfe3fb;fill:none;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round;flex:none}
.hero h2{margin:0;font-size:26px;font-weight:700}
.hero p{margin:4px 0 12px;color:#a9bbd2}
.pill{display:inline-flex;align-items:center;gap:8px;padding:5px 12px;border-radius:20px;background:rgba(92,201,138,.16);color:var(--ok);font-weight:600;font-size:13px}
.pill.off{background:rgba(224,112,92,.16);color:var(--bad)}
.gauges{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.g{text-align:center;position:relative}
.g svg{width:100%;max-width:104px;display:block;margin:0 auto}
.g circle{fill:none;stroke-width:7}
.g .gt{stroke:#263042}.g .gv{stroke-linecap:round;transition:stroke-dasharray .6s,stroke .3s}
.gn{position:absolute;left:0;right:0;top:34%;font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.gl{margin-top:6px;font-weight:600}.gs{color:var(--dim);font-size:12px}
.qrbox{display:flex;flex-direction:column;align-items:center;gap:12px;text-align:center}
#qr{border-radius:12px;background:#fff;padding:0;max-width:100%}
.url{font-family:Consolas,monospace;font-size:13px;color:var(--acc)}
.pinrow{display:flex;align-items:center;gap:8px;justify-content:center}
.pinv{font-family:Consolas,monospace;font-size:22px;letter-spacing:4px;font-weight:700}
.btn{border:1px solid var(--line);background:#222c3c;color:var(--ink);border-radius:9px;padding:7px 12px;font:inherit;cursor:pointer;transition:background .15s}
.btn:hover{background:#2b384d}.btn.acc{background:var(--acc);color:#07263a;border-color:var(--acc);font-weight:600}.btn.bad{color:var(--bad)}
.net{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.net b{font-size:22px;font-variant-numeric:tabular-nums}.net span{display:block;color:var(--dim);font-size:12px}
canvas{width:100%;height:56px;display:block;margin-top:8px}canvas.big{height:130px}
.item{display:flex;align-items:center;gap:12px;padding:10px 0;border-top:1px solid #243044}
.item:first-child{border-top:0}
.av{width:38px;height:38px;border-radius:12px;background:#243349;display:grid;place-items:center;color:var(--acc);flex:none;position:relative}
.av .dot{position:absolute;right:-2px;bottom:-2px;border:2px solid var(--card)}
.item .t{flex:1;min-width:0}.item .t b{display:block;font-weight:600}.item .t span{color:var(--dim);font-size:12.5px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.empty{color:var(--dim);text-align:center;padding:22px 10px}
.devs{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.dev .head{display:flex;align-items:center;gap:14px;margin-bottom:14px}
.dev .head .av{width:52px;height:52px;border-radius:16px}.dev .head .av svg{width:28px;height:28px}
.dev h4{margin:0;font-size:17px}.dev .st{color:var(--dim);font-size:12.5px}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px;margin-bottom:14px}
.kv span{display:block;color:var(--dim);font-size:12px}.kv b{font-weight:600;font-size:13.5px}
.last{background:#161d28;border-radius:10px;padding:9px 12px;color:#b9c6d9;font-size:13px;margin-bottom:14px}
.acts{display:flex;gap:8px}
.log{display:flex;gap:12px;padding:9px 0;border-top:1px solid #243044;align-items:baseline}.log:first-child{border-top:0}
.log time{color:var(--dim);font-variant-numeric:tabular-nums;font-size:12.5px;width:66px;flex:none}
.log i{width:8px;height:8px;border-radius:50%;background:var(--dim);flex:none;align-self:center}
.log i.join{background:var(--ok)}.log i.warn{background:var(--bad)}.log i.file{background:var(--acc)}.log i.leave{background:#5b6678}
.log b{font-weight:600}
.seg{display:inline-flex;background:#10151d;border:1px solid var(--line);border-radius:12px;padding:4px;gap:4px;margin-bottom:16px}
.seg button{border:0;background:transparent;color:var(--dim);padding:7px 16px;border-radius:9px;font:inherit;cursor:pointer}
.seg button.on{background:var(--acc);color:#07263a;font-weight:600}
.stats4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}
.stats4 .card b{font-size:26px;font-variant-numeric:tabular-nums}.stats4 .card span{display:block;color:var(--dim);font-size:12.5px;margin-top:2px}
.set{display:flex;align-items:center;gap:16px;padding:14px 0;border-top:1px solid #243044}
.set:first-of-type{border-top:0}.set .t{flex:1}.set .t b{display:block;font-weight:600}.set .t span{color:var(--dim);font-size:12.5px}
.sw{width:46px;height:26px;border-radius:13px;background:#323d50;position:relative;cursor:pointer;transition:background .2s;flex:none}
.sw:after{content:"";position:absolute;left:3px;top:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:left .2s}
.sw.on{background:var(--ok)}.sw.on:after{left:23px}
.topbar{display:flex;align-items:center;gap:10px;padding:7px 0;border-top:1px solid #243044}.topbar:first-child{border-top:0}
.topbar b{flex:1;font-weight:500}.topbar span{color:var(--dim);font-size:13px}

.lb,.lw{animation:lsync 3.8s ease-in-out infinite}
.lb{--d:-3px}.lw{--d:3px}
@keyframes lsync{0%,20%,80%,100%{transform:translateY(0)}50%{transform:translateY(var(--d))}}
@media (prefers-reduced-motion:reduce){.lb,.lw{animation:none}}
/* ---- DaSync: QR, ambient, анимации ---- */
#qr{width:200px;height:200px;margin:0;border-radius:16px;background:#fff;display:block;animation:qrg 3.6s ease-in-out infinite alternate}
@keyframes qrg{from{box-shadow:0 0 0 6px rgba(255,255,255,.95),0 8px 36px rgba(102,192,244,.18)}to{box-shadow:0 0 0 6px rgba(255,255,255,.95),0 8px 56px rgba(182,156,255,.42)}}
.logo{box-shadow:0 0 22px rgba(110,231,255,.45);animation:glow 4s ease-in-out infinite alternate}
@keyframes glow{from{box-shadow:0 0 14px rgba(102,192,244,.35)}to{box-shadow:0 0 30px rgba(182,156,255,.7)}}
.amb{position:fixed;inset:0;z-index:-1;overflow:hidden;pointer-events:none}
.amb i{position:absolute;border-radius:50%;filter:blur(110px);opacity:.36;transition:background 2.5s}
.amb i:nth-child(1){width:540px;height:540px;left:16%;top:-16%;background:hsl(var(--h,210) 85% 56%);animation:d1 26s ease-in-out infinite alternate}
.amb i:nth-child(2){width:470px;height:470px;right:-6%;top:20%;background:hsl(calc(var(--h,210) + 60) 80% 58%);animation:d2 32s ease-in-out infinite alternate}
.amb i:nth-child(3){width:580px;height:580px;left:34%;bottom:-34%;background:hsl(calc(var(--h,210) - 45) 75% 50%);opacity:.26;animation:d3 38s ease-in-out infinite alternate}
@keyframes d1{to{transform:translate(180px,140px) scale(1.18)}}
@keyframes d2{to{transform:translate(-200px,120px) scale(.9)}}
@keyframes d3{to{transform:translate(-160px,-110px) scale(1.12)}}
.card{background:linear-gradient(180deg,rgba(34,44,60,.72),rgba(26,33,44,.72));backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);transition:transform .25s,border-color .25s,box-shadow .25s}
.card:hover{transform:translateY(-2px);border-color:rgba(102,192,244,.38);box-shadow:0 14px 44px -14px rgba(102,192,244,.32)}
.hero{background:linear-gradient(120deg,#23446c,#1b2a40 45%,#2a2552 75%,#23446c);background-size:220% 220%;animation:flow 18s ease infinite}
@keyframes flow{0%{background-position:0 50%}50%{background-position:100% 50%}100%{background-position:0 50%}}
.page.show .grid>.card,.page.show .stats4>.card{animation:rise .6s cubic-bezier(.2,.8,.2,1) backwards}
.page.show .grid>.card:nth-child(2),.page.show .stats4>.card:nth-child(2){animation-delay:.06s}
.page.show .grid>.card:nth-child(3),.page.show .stats4>.card:nth-child(3){animation-delay:.12s}
.page.show .grid>.card:nth-child(4),.page.show .stats4>.card:nth-child(4){animation-delay:.18s}
.page.show .grid>.card:nth-child(5){animation-delay:.24s}.page.show .grid>.card:nth-child(6){animation-delay:.3s}
@keyframes rise{from{opacity:0;transform:translateY(16px) scale(.985)}}
.dot.on{animation:pulse 2.4s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(92,201,138,.6)}70%{box-shadow:0 0 0 9px rgba(92,201,138,0)}100%{box-shadow:0 0 0 0 rgba(92,201,138,0)}}
.nav svg{transition:transform .2s}.nav:hover svg{transform:translateX(3px)}
.nav.on:before{animation:bar .35s ease backwards}@keyframes bar{from{transform:scaleY(0)}}
.item,.log{animation:fade .35s ease backwards}@keyframes fade{from{opacity:0;transform:translateX(-8px)}}
.btn{transition:background .15s,transform .1s}.btn:active{transform:scale(.96)}
.sw{box-shadow:inset 0 0 0 1px rgba(255,255,255,.05)}.sw.on{box-shadow:0 0 14px rgba(92,201,138,.45)}
.gauges .g{transition:transform .25s}.gauges .g:hover{transform:scale(1.05)}
.g .gv{filter:drop-shadow(0 0 5px currentColor)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
#modal{position:fixed;inset:0;background:rgba(6,9,14,.66);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);display:none;align-items:center;justify-content:center;z-index:50}
#modal.show{display:flex;animation:fade2 .25s}
@keyframes fade2{from{opacity:0}}
.mbox{width:430px;max-width:92vw;background:linear-gradient(180deg,#232e42,#1a212c);border:1px solid #33425a;border-radius:22px;padding:28px;text-align:center;box-shadow:0 30px 80px rgba(0,0,0,.55),0 0 70px rgba(102,192,244,.2);animation:pop .35s cubic-bezier(.2,.9,.3,1.2)}
@keyframes pop{from{transform:scale(.9);opacity:0}}
.mbox h3{margin:0 0 10px;font-size:19px;text-transform:none;letter-spacing:0;color:var(--ink)}
.mdev b{display:block;font-size:17px}.mdev span{color:var(--dim)}
.mwarn{margin:14px 0;padding:10px 12px;border-radius:10px;background:rgba(232,176,75,.12);color:#e8c27a;font-size:13px}
.mcaps{display:grid;grid-template-columns:1fr 1fr;gap:8px;text-align:left;margin-bottom:18px}
.mcaps label{display:flex;gap:8px;align-items:center;padding:9px 11px;background:#161d28;border-radius:10px;cursor:pointer}
.mbtn{display:flex;gap:10px}.mbtn .btn{flex:1;padding:11px}
.caps{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.cap{padding:5px 11px;border-radius:20px;background:#161d28;color:var(--dim);font-size:12.5px;cursor:pointer;border:1px solid transparent;transition:.15s}
.cap.on{background:rgba(92,201,138,.14);color:var(--ok);border-color:rgba(92,201,138,.35)}
.hint{color:var(--dim);font-size:12.5px}
</style></head><body>
<div class="amb"><i></i><i></i><i></i></div>
<div id="modal"><div class="mbox" id="mbox"></div></div>
<aside>
  <div class="brand"><div class="logo"><svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g1" gradientUnits="userSpaceOnUse" x1="0" y1="17" x2="0" y2="53"><stop offset="0" stop-color="#6ee7ff"/><stop offset="1" stop-color="#60a5fa"/></linearGradient><linearGradient id="g2" gradientUnits="userSpaceOnUse" x1="0" y1="11" x2="0" y2="47"><stop offset="0" stop-color="#818cf8"/><stop offset="1" stop-color="#c084fc"/></linearGradient><linearGradient id="db" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#171d44"/><stop offset="1" stop-color="#0b1020"/></linearGradient></defs><rect width="64" height="64" rx="16" fill="url(#db)"/><rect class="lb" x="15" y="17" width="10" height="36" rx="5" fill="url(#g1)"/><path class="lw" d="M31 13A16 16 0 0 1 31 45Z" fill="url(#g2)" stroke="url(#g2)" stroke-width="4" stroke-linejoin="round"/></svg></div>DaSync</div>
  <div class="nav on" data-p="home"><svg class="i" viewBox="0 0 24 24"><path d="M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg>Главная</div>
  <div class="nav" data-p="devices"><svg class="i" viewBox="0 0 24 24"><rect x="7" y="2" width="10" height="20" rx="2.5"/><path d="M11 18h2"/></svg>Устройства<span class="badge" id="bdg">0</span></div>
  <div class="nav" data-p="activity"><svg class="i" viewBox="0 0 24 24"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>Активность</div>
  <div class="nav" data-p="history"><svg class="i" viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>История</div>
  <div class="nav" data-p="settings"><svg class="i" viewBox="0 0 24 24"><path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/></svg>Настройки</div>
  <div class="sp"></div>
  <div class="side-foot"><i class="dot" id="sdot"></i><span id="stxt">Запуск…</span></div>
</aside>
<main>
  <div class="top"><h1 id="title">Главная</h1><div class="r" id="hostTop"></div></div>
  <div id="off">Нет связи с приложением. Возможно, оно закрыто.</div>
  <div class="pages">

    <section class="page show" id="p-home">
      <div class="grid">
        <div class="card hero c8">
          <svg class="big" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20M9 19l.5-3h5l.5 3"/></svg>
          <div style="position:relative;z-index:1"><h2 id="hHost">–</h2><p id="hSub">–</p><span class="pill" id="hPill"><i class="dot on"></i><span>На связи</span></span></div>
        </div>
        <div class="card c4" style="grid-row:span 2">
          <h3>Подключить телефон</h3>
          <div class="qrbox"><canvas id="qr"></canvas><div id="qrMiss" class="empty" style="display:none">Для QR поставь библиотеку:<br><b>pip install qrcode</b></div>
            <div class="url" id="hUrl">–</div>
            <div class="pinrow"><button class="btn" id="qrNew">Обновить QR</button><button class="btn" id="qrCopy">Копировать ссылку</button></div><div class="hint" id="qrTimer"></div>
            <div style="color:var(--dim);font-size:12.5px">Наведи камеру телефона на QR.<br>Код одноразовый и живёт 2 минуты.</div></div>
        </div>
        <div class="card c8"><h3>Состояние ноутбука</h3><div class="gauges" id="gauges"><div class="empty" style="grid-column:span 4">Собираю данные…</div></div></div>
        <div class="card c4"><h3>Сеть</h3><div class="net"><div><b id="nDown">–</b><span>загрузка</span></div><div><b id="nUp">–</b><span>отдача</span></div></div><canvas id="netc"></canvas></div>
        <div class="card c4"><h3>Сейчас на связи</h3><div id="hDevs"></div></div>
        <div class="card c4"><h3>Недавняя активность</h3><div id="hLog"></div></div>
      </div>
    </section>

    <section class="page" id="p-devices"><div class="devs" id="devs"></div></section>

    <section class="page" id="p-activity"><div class="card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><h3 style="margin:0">Журнал событий</h3><button class="btn" id="clrLog">Очистить</button></div><div id="logs"></div></div></section>

    <section class="page" id="p-history">
      <div class="seg" id="hseg"><button class="on" data-r="1h">Час</button><button data-r="6h">6 часов</button><button data-r="24h">Сутки</button><button data-r="7d">Неделя</button></div>
      <div class="stats4">
        <div class="card"><b id="sCpu">–</b><span id="sCpuS">процессор</span></div>
        <div class="card"><b id="sRam">–</b><span id="sRamS">память</span></div>
        <div class="card"><b id="sNet" style="font-size:20px">–</b><span id="sNetS">трафик</span></div>
        <div class="card"><b id="sAct">–</b><span id="sActS">за компьютером</span></div>
      </div>
      <div class="grid">
        <div class="card c6"><h3>Процессор, %</h3><canvas class="big" id="ch1"></canvas></div>
        <div class="card c6"><h3>Память, %</h3><canvas class="big" id="ch2"></canvas></div>
        <div class="card c6"><h3>Сеть <span id="chNetL" style="text-transform:none;letter-spacing:0"></span></h3><canvas class="big" id="ch3"></canvas></div>
        <div class="card c6" id="batCard"><h3>Батарея, %</h3><canvas class="big" id="ch4"></canvas></div>
        <div class="card c12"><h3>Что чаще всего грузило ноут</h3><div id="topApps"></div><div style="color:var(--dim);font-size:12.5px;margin-top:8px" id="cover"></div></div>
      </div>
    </section>

    <section class="page" id="p-settings">
      <div class="grid"><div class="card c8">
        <h3>Основное</h3>
        <div class="set"><div class="t"><b>Принимать команды с телефона</b><span>Выключи, чтобы временно отрезать телефон, например в чужой Wi-Fi</span></div><div class="sw" id="swOn"></div></div>
        <div class="set" id="autoRow"><div class="t"><b>Запускать вместе с Windows</b><span>Значок появится у часов сам</span></div><div class="sw" id="swAuto"></div></div>
        <div class="set"><div class="t"><b>Защита</b><span>Одноразовый QR, подтверждение на ноуте, подпись каждого запроса, только домашняя сеть</span></div><button class="btn bad" id="forgetAll">Забыть все устройства</button></div>
        <div class="set"><div class="t"><b>Адрес в домашней сети</b><span id="setUrl">–</span></div></div>
        <div class="set"><div class="t"><b>Папка для файлов</b><span id="setDir">–</span></div><button class="btn" id="openDir">Открыть</button></div>
      </div>
      <div class="card c4"><h3>Заблокированные</h3><div id="blocked"></div></div>
      <div class="card c12" style="display:flex;align-items:center;gap:16px"><div style="flex:1"><b>Выйти из приложения</b><div style="color:var(--dim);font-size:12.5px">Телефон перестанет видеть ноутбук, пока ты не запустишь DaSync снова.</div></div><button class="btn bad" id="quitB">Выйти</button></div></div>
    </section>

  </div>
</main>
<script>
const $=s=>document.querySelector(s);
const esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function dapi(b){const r=await fetch('/desk/api',{method:'POST',headers:{'X-Desk':'1','Content-Type':'application/json'},body:JSON.stringify(b)});if(!r.ok)throw 0;return r.json()}
const ICON={
  phone:'<svg class="i" viewBox="0 0 24 24"><rect x="7" y="2" width="10" height="20" rx="2.5"/><path d="M11 18h2"/></svg>',
  tablet:'<svg class="i" viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="2.5"/><path d="M11 18h2"/></svg>',
  pc:'<svg class="i" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>'};
const CAPS=[['control','Управление'],['screen','Экран'],['files','Файлы'],['power','Питание']];
const T=ts=>new Date(ts*1000).toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
const D=ts=>new Date(ts*1000).toLocaleString('ru',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
function ago(ts){const s=Math.max(0,Date.now()/1000-ts);if(s<10)return 'только что';if(s<60)return Math.floor(s)+' с назад';if(s<3600)return Math.floor(s/60)+' мин назад';if(s<86400)return Math.floor(s/3600)+' ч назад';return Math.floor(s/86400)+' д назад'}
function dur(s){s=Math.max(0,Math.floor(s));const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return(d?d+' д ':'')+(h?h+' ч ':'')+m+' мин'}
const fsz=b=>b>=1073741824?(b/1073741824).toFixed(1)+' ГБ':b>=1048576?(b/1048576).toFixed(1)+' МБ':Math.max(1,Math.round(b/1024))+' КБ';
const rate=b=>b>=1048576?(b/1048576).toFixed(1)+' МБ/с':Math.round(b/1024)+' КБ/с';
const gb=b=>(b/1073741824).toFixed(b>=1.07e10?0:1)+' ГБ';
const col=(p,w=75,b=90)=>p>=b?'#e0705c':p>=w?'#e8b04b':'#5cc98a';

let ST=null,page='home',hr='1h',histT=null,netD=[],netU=[],pinShown=false,qrKey='';
const TITLES={home:'Главная',devices:'Устройства',activity:'Активность',history:'История',settings:'Настройки'};
function go(p){
  page=p;$('#title').textContent=TITLES[p];
  document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('on',n.dataset.p===p));
  document.querySelectorAll('.page').forEach(x=>x.classList.toggle('show',x.id==='p-'+p));
  if(p==='history')loadHist();render();
}
document.querySelectorAll('.nav').forEach(n=>n.onclick=()=>go(n.dataset.p));

function gauge(label,pct,sub,w,b){
  const C=2*Math.PI*34,c=col(pct,w,b);
  return `<div class="g"><svg viewBox="0 0 80 80"><circle class="gt" cx="40" cy="40" r="34"/><circle class="gv" cx="40" cy="40" r="34" stroke="${c}" stroke-dasharray="${C*Math.min(pct,100)/100} ${C}" transform="rotate(-90 40 40)"/></svg><div class="gn">${Math.round(pct)}%</div><div class="gl">${label}</div><div class="gs">${sub}</div></div>`;
}
function devRow(d){
  return `<div class="item"><div class="av">${ICON[d.kind]||ICON.pc}<i class="dot ${d.online?'on':''}"></i></div><div class="t"><b>${esc(d.name)}</b><span>${d.online?'на связи '+dur(Date.now()/1000-d.since):'был '+ago(d.last)}${d.last_action?' · '+esc(d.last_action):''}</span></div></div>`;
}
function logRow(l,full){return `<div class="log"><time>${T(l.ts)}</time><i class="${l.kind}"></i><div><b>${esc(l.who)}</b> ${esc(l.text)}</div></div>`}

function drawQR(m,url){
  const cv=$('#qr'),miss=$('#qrMiss');
  if(!m.length){cv.style.display='none';miss.style.display='block';return}
  cv.style.display='block';miss.style.display='none';
  const key=m.length+url;if(key===qrKey)return;qrKey=key;
  const n=m.length,cell=Math.max(4,Math.ceil(420/(n+4))),sz=cell*(n+4);cv.width=sz;cv.height=sz;
  const x=cv.getContext('2d');x.fillStyle='#fff';x.fillRect(0,0,sz,sz);x.fillStyle='#0e1218';
  m.forEach((row,r)=>row.forEach((v,c)=>{if(v)x.fillRect((c+2)*cell,(r+2)*cell,cell,cell)}));
}
function spark(cv,series,max){
  const d=devicePixelRatio,w=cv.clientWidth*d,h=cv.clientHeight*d;cv.width=w;cv.height=h;const x=cv.getContext('2d');
  if(!max){max=1;series.forEach(s=>s.v.forEach(v=>{if(v!=null&&v>max)max=v}));max*=1.1}
  x.strokeStyle='#263042';x.lineWidth=d;[0,.5,1].forEach(f=>{const y=h-4*d-f*(h-8*d);x.beginPath();x.moveTo(0,y);x.lineTo(w,y);x.stroke()});
  series.forEach(s=>{x.strokeStyle=s.c;x.lineWidth=2*d;x.lineJoin='round';x.beginPath();let pen=false;const n=s.v.length;
    s.v.forEach((v,i)=>{if(v==null){pen=false;return}const px=i/Math.max(n-1,1)*w,py=h-4*d-Math.min(v/max,1)*(h-8*d);pen?x.lineTo(px,py):x.moveTo(px,py);pen=true});x.stroke()});
  return max;
}

let gBuilt=false;
const GN=['Процессор','Память','Диск','Батарея'],GC=2*Math.PI*34;
function buildGauges(){
  $('#gauges').innerHTML=GN.map((n,i)=>`<div class="g" id="gauge${i}"><svg viewBox="0 0 80 80"><circle class="gt" cx="40" cy="40" r="34"/><circle class="gv" cx="40" cy="40" r="34" stroke="#5cc98a" stroke-dasharray="0 ${GC}" transform="rotate(-90 40 40)"/></svg><div class="gn">0%</div><div class="gl">${n}</div><div class="gs"></div></div>`).join('');
  gBuilt=true;
}
function tween(el,to,suf){
  const from=el._v==null?0:el._v;el._v=to;
  if(Math.abs(from-to)<0.5){el.textContent=Math.round(to)+suf;return}
  const t0=performance.now();cancelAnimationFrame(el._r);
  const step=t=>{const k=Math.min(1,(t-t0)/700),e=1-Math.pow(1-k,3);el.textContent=Math.round(from+(to-from)*e)+suf;if(k<1)el._r=requestAnimationFrame(step)};
  el._r=requestAnimationFrame(step);
}
function setG(i,pct,sub,color){
  const el=$('#gauge'+i);if(!el)return;const v=el.querySelector('.gv');
  v.setAttribute('stroke',color);v.style.color=color;v.setAttribute('stroke-dasharray',(GC*Math.min(pct,100)/100)+' '+GC);
  tween(el.querySelector('.gn'),pct,'%');el.querySelector('.gs').textContent=sub;
}
function updGauges(s){
  if(!gBuilt)buildGauges();
  setG(0,s.cpu,s.temp!=null?s.temp+' °C':'нагрузка',col(s.cpu));
  setG(1,s.ram.pct,gb(s.ram.used)+' из '+gb(s.ram.total),col(s.ram.pct));
  setG(2,s.disk.pct,'свободно '+gb(s.disk.free),col(s.disk.pct,85,95));
  if(s.bat){const b=s.bat;setG(3,b.pct,b.plugged?'заряжается':(b.left?'ещё '+Math.floor(b.left/3600)+' ч '+Math.floor(b.left%3600/60)+' мин':'от батареи'),b.pct<=15&&!b.plugged?'#e0705c':b.pct<=30&&!b.plugged?'#e8b04b':'#5cc98a')}
  else setG(3,0,'батареи нет','#3a4658');
}
// не перерисовываем списки, если ничего не изменилось (иначе анимации моргают)
['hDevs','hLog','devs','logs'].forEach(id=>{
  const el=document.getElementById(id),d=Object.getOwnPropertyDescriptor(Element.prototype,'innerHTML');
  Object.defineProperty(el,'innerHTML',{set(v){if(el._h!==v){el._h=v;d.set.call(el,v)}},get(){return d.get.call(el)}});
});

let pendKey='';
function renderPending(){
  const p=(ST.pending||[])[0],m=$('#modal');
  if(!p){m.classList.remove('show');pendKey='';return}
  if(pendKey!==p.key){
    pendKey=p.key;
    $('#mbox').innerHTML=`<div class="av" style="margin:0 auto 14px;width:64px;height:64px;border-radius:20px">${ICON[p.kind]||ICON.phone}</div><h3>Новое устройство хочет подключиться</h3><div class="mdev"><b>${esc(p.model)}</b><span>${esc(p.browser||'')} · ${esc(p.ip)}</span></div><div class="mwarn">Разрешай, только если это твой телефон и QR ты сканировал сам.</div><div class="mcaps">${CAPS.map(([k,t])=>`<label><input type="checkbox" data-pc="${k}" ${ST.cfg.caps_default[k]?'checked':''}> ${t}</label>`).join('')}</div><div class="mbtn"><button class="btn" id="pDeny">Отклонить</button><button class="btn acc" id="pOk">Разрешить</button></div>`;
    $('#pOk').onclick=async()=>{const caps={};document.querySelectorAll('[data-pc]').forEach(i=>caps[i.dataset.pc]=i.checked);await dapi({a:'pair_approve',key:p.key,caps});tick(true)};
    $('#pDeny').onclick=async()=>{await dapi({a:'pair_deny',key:p.key});tick(true)};
  }
  m.classList.add('show');
}
function render(){
  if(!ST)return;const s=ST.stats,c=ST.cfg,devs=ST.devices;
  renderPending();
  const online=devs.filter(d=>d.online);
  const b=$('#bdg');b.textContent=online.length;b.style.display=online.length?'inline-block':'none';
  $('#sdot').classList.toggle('on',c.on);$('#stxt').textContent=c.on?'Принимает команды':'На паузе';
  $('#hostTop').textContent=c.host;
  if(s.cpu!==undefined)document.documentElement.style.setProperty('--h',Math.round(210-1.9*Math.min(s.cpu,100)));
  if(page==='home'){
    $('#hHost').textContent=c.host;
    $('#hSub').textContent=(s.uptime!=null?c.os+' · включён '+dur(s.uptime):c.os);
    const p=$('#hPill');p.classList.toggle('off',!c.on);p.innerHTML=`<i class="dot ${c.on?'on':''}"></i><span>${c.on?(online.length?'Подключено устройств: '+online.length:'Ждёт подключения'):'Пауза: команды отключены'}</span>`;
    if(s.cpu!==undefined){
      updGauges(s);
      $('#nDown').textContent=rate(s.net.down);$('#nUp').textContent=rate(s.net.up);
      netD.push(s.net.down);netU.push(s.net.up);if(netD.length>60){netD.shift();netU.shift()}
      spark($('#netc'),[{v:netD,c:'#5cc98a'},{v:netU,c:'#e8b04b'}]);
    }
    drawQR(ST.qr,c.pair);
    $('#hUrl').textContent=c.url;$('#qrTimer').textContent='Код обновится через '+Math.max(0,Math.round(c.pair_exp-Date.now()/1000))+' с';
    $('#hDevs').innerHTML=online.length?online.map(devRow).join(''):'<div class="empty">Пока никто не подключён.<br>Отсканируй QR телефоном.</div>';
    $('#hLog').innerHTML=ST.log.length?ST.log.slice(0,6).map(l=>logRow(l)).join(''):'<div class="empty">Событий пока нет</div>';
  }
  if(page==='devices'){
    $('#devs').innerHTML=devs.length?devs.map(d=>`<div class="card dev"><div class="head"><div class="av">${ICON[d.kind]||ICON.pc}<i class="dot ${d.online?'on':''}"></i></div><div><h4>${esc(d.name)}</h4><div class="st">${d.blocked?'Заблокировано':d.online?'На связи '+dur(Date.now()/1000-d.since):'Не в сети · был '+ago(d.last)}</div></div></div>
      <div class="kv"><div><span>Устройство</span><b>${esc(d.model)}</b></div><div><span>Браузер</span><b>${esc(d.browser||'–')}</b></div><div><span>IP-адрес</span><b>${esc(d.ip)}</b></div><div><span>Запросов</span><b>${d.count}</b></div><div><span>Впервые</span><b>${D(d.first)}</b></div><div><span>Последний раз</span><b>${ago(d.last)}</b></div></div>
      <div class="last">${d.last_action?'Сейчас: '+esc(d.last_action):'Пока без действий'}</div>
      <div class="caps">${d.caps?CAPS.map(([k,t])=>`<span class="cap ${d.caps[k]?'on':''}" data-cap="${k}" data-key="${esc(d.key)}">${t}</span>`).join(''):'<span class="hint">Не сопряжено</span>'}</div>
      <div class="acts"><button class="btn" data-ren="${esc(d.key)}" data-n="${esc(d.name)}">Переименовать</button><button class="btn ${d.blocked?'':'bad'}" data-blk="${esc(d.key)}" data-on="${d.blocked?0:1}">${d.blocked?'Разблокировать':'Заблокировать'}</button>${d.paired?`<button class="btn" data-forget="${esc(d.key)}">Забыть</button>`:''}</div></div>`).join(''):'<div class="card empty" style="grid-column:1/-1;padding:50px">Ещё ни одно устройство не подключалось.<br>Открой «Главную» и отсканируй QR телефоном.</div>';
  }
  if(page==='activity')$('#logs').innerHTML=ST.log.length?ST.log.map(l=>logRow(l)).join(''):'<div class="empty">Событий пока нет</div>';
  if(page==='settings'){
    $('#swOn').classList.toggle('on',c.on);$('#swAuto').classList.toggle('on',c.autostart);$('#autoRow').style.display=c.os==='Windows'?'flex':'none';
    
    $('#setUrl').textContent=c.url;$('#setDir').textContent=c.folder;
    $('#blocked').innerHTML=c.blocked.length?c.blocked.map(v=>`<div class="topbar"><b>${esc(v)}</b><button class="btn" data-unb="${esc(v)}">Разблокировать</button></div>`).join(''):'<div class="empty">Никого</div>';
  }
}

$('#devs').onclick=async e=>{
  const r=e.target.dataset.ren,bk=e.target.dataset.blk;
  if(e.target.dataset.cap){await dapi({a:'set_caps',key:e.target.dataset.key,cap:e.target.dataset.cap,on:!e.target.classList.contains('on')});tick(true);return}
  if(e.target.dataset.forget){if(confirm('Забыть устройство? Чтобы подключить его снова, придётся заново отсканировать QR.')){await dapi({a:'forget',key:e.target.dataset.forget});tick(true)}return}
  if(r){const n=prompt('Как назвать это устройство?',e.target.dataset.n);if(n&&n.trim()){await dapi({a:'rename',key:r,name:n.trim()});tick(true)}}
  if(bk){const on=e.target.dataset.on==='1';if(!on||confirm('Заблокировать устройство? Оно больше не сможет управлять ноутбуком.')){await dapi({a:'block',key:bk,on});tick(true)}}
};
$('#blocked').onclick=async e=>{const v=e.target.dataset.unb;if(v){await dapi({a:'unblock',value:v});tick(true)}};
$('#qrNew').onclick=async()=>{await dapi({a:'new_qr'});tick(true)};
$('#qrCopy').onclick=()=>{navigator.clipboard.writeText(ST.cfg.url+'/#p='+ST.cfg.pair);$('#qrCopy').textContent='Скопировано';setTimeout(()=>$('#qrCopy').textContent='Копировать ссылку',1400)};
$('#forgetAll').onclick=async()=>{if(confirm('Забыть все устройства? Каждый телефон придётся подключать заново через QR.')){await dapi({a:'forget_all'});tick(true)}};
$('#swOn').onclick=async()=>{await dapi({a:'pause',on:!ST.cfg.on});tick(true)};
$('#swAuto').onclick=async()=>{await dapi({a:'autostart',on:!ST.cfg.autostart});tick(true)};
$('#openDir').onclick=()=>dapi({a:'open_folder'});
$('#clrLog').onclick=async()=>{await dapi({a:'clear_log'});tick(true)};
$('#quitB').onclick=async()=>{if(confirm('Выйти из DaSync? Телефон потеряет связь с ноутбуком.'))dapi({a:'quit'}).catch(()=>{})};

/* история */
const tfmt=(ts,span)=>new Date(ts*1000).toLocaleString('ru',span>86400?{weekday:'short',hour:'2-digit',minute:'2-digit'}:{hour:'2-digit',minute:'2-digit'});
const hm=m=>m>=60?Math.floor(m/60)+' ч '+(m%60)+' мин':m+' мин';
async function loadHist(){
  clearTimeout(histT);if(page!=='history')return;
  try{
    const r=await dapi({a:'history',r:hr}),s=r.sum;
    if(!s.n){$('#cover').textContent='Данных пока нет: приложение копит их каждые 10 секунд.';}
    else{
      $('#sCpu').textContent=Math.round(s.cpu_avg)+'%';$('#sCpuS').textContent='процессор, пик '+Math.round(s.cpu_max)+'%';
      $('#sRam').textContent=Math.round(s.ram_avg)+'%';$('#sRamS').textContent='память, пик '+Math.round(s.ram_max)+'%';
      $('#sNet').textContent='↓ '+fsz(s.down)+'  ↑ '+fsz(s.up);$('#sNetS').textContent='трафик за период';
      $('#sAct').textContent=s.active_min!=null?hm(s.active_min):'–';$('#sActS').textContent=s.active_min!=null?'за компьютером':'только Windows';
      spark($('#ch1'),[{v:r.cpu_max,c:'#3a4f70'},{v:r.cpu,c:'#66c0f4'}],100);
      spark($('#ch2'),[{v:r.ram,c:'#b69cff'}],100);
      const m=spark($('#ch3'),[{v:r.down,c:'#5cc98a'},{v:r.up,c:'#e8b04b'}]);$('#chNetL').textContent='макс '+rate(m/1.1)+' · ↓ зелёный, ↑ жёлтый';
      const hasBat=r.bat.some(v=>v!=null);$('#batCard').style.display=hasBat?'block':'none';if(hasBat)spark($('#ch4'),[{v:r.bat,c:'#5cc98a'}],100);
      $('#topApps').innerHTML=r.top.length?r.top.map(t=>`<div class="topbar"><b>${esc(t.name)}</b><span>${t.pct}% времени</span></div>`).join(''):'<div class="empty">Никто не нагружал ноут заметно</div>';
      $('#cover').textContent=(s.cover<90?'Записано '+s.cover+'% периода: в остальное время приложение не работало. ':'')+tfmt(r.since,r.span)+' → '+tfmt(r.now,r.span);
    }
  }catch(e){}
  histT=setTimeout(loadHist,30000);
}
document.querySelectorAll('#hseg button').forEach(b=>b.onclick=()=>{hr=b.dataset.r;document.querySelectorAll('#hseg button').forEach(x=>x.classList.toggle('on',x===b));loadHist()});

let tm=null;
async function tick(once){
  clearTimeout(tm);
  let got=false;
  try{ST=await dapi({a:'state'});got=true}catch(e){$('#off').style.display='flex'}
  if(got){$('#off').style.display='none';try{render()}catch(e){console.error('render:',e)}}
  if(!once)tm=setTimeout(tick,1500);else tm=setTimeout(tick,1500);
}
tick();
</script></body></html>
"""


# ---------- трей ----------
SRV = {"obj": None}


def make_server():
    return ThreadingHTTPServer(("0.0.0.0", PORT), H)


def show_qr():
    open_desk()


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    vbs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_hub.vbs")
    if os.path.exists(vbs):
        return f'wscript.exe "{vbs}"'
    import shutil
    exe = shutil.which("pythonw") or sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    if OS != "Windows":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "LaptopHub")
            return True
    except Exception:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "LaptopHub", 0, winreg.REG_SZ, launch_cmd())
        else:
            try:
                winreg.DeleteValue(k, "LaptopHub")
            except FileNotFoundError:
                pass


def tray():
    import pystray
    from PIL import Image, ImageDraw

    def icon_img(on=True):
        return make_icon(64, on)

    def toggle_on(icon, item):
        APP["on"] = not APP["on"]
        icon.icon = icon_img(APP["on"])
        icon.notify("Команды с телефона " + ("включены" if APP["on"] else "на паузе"), APP_NAME)

    def toggle_autostart(icon, item):
        try:
            set_autostart(not autostart_enabled())
        except Exception as e:
            icon.notify(f"Не вышло: {e}", APP_NAME)

    def forget_all(icon, item):
        desk_handle({"a": "forget_all"})
        icon.notify("Все устройства забыты. Подключай заново через QR.", APP_NAME)

    def copy_link(icon, item):
        try:
            pyperclip.copy(get_url())
        except Exception:
            pass

    def quit_app(icon, item):
        cancel_timer()
        threading.Thread(target=SRV["obj"].shutdown, daemon=True).start()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Открыть окно", lambda i, it: open_desk(), default=True),
        pystray.MenuItem("Показать QR для телефона", lambda i, it: show_qr()),
        pystray.MenuItem("Скопировать ссылку", copy_link),
        pystray.MenuItem("Открыть папку с файлами", lambda i, it: open_folder()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Принимать команды", toggle_on, checked=lambda it: APP["on"]),
        pystray.MenuItem("Запускать с Windows", toggle_autostart,
                         checked=lambda it: autostart_enabled(), visible=OS == "Windows"),
        pystray.MenuItem("Забыть все устройства", forget_all),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    icon = pystray.Icon("LaptopHub", icon_img(), APP_NAME, menu)

    def set_on(state):
        APP["on"] = state
        icon.icon = icon_img(state)

    TRAY["set_on"] = set_on
    TRAY["quit"] = lambda: quit_app(icon, None)
    TRAY["notify"] = lambda title, msg: icon.notify(msg, title)

    def setup(ic):
        ic.visible = True
        if FIRST_RUN:
            open_desk()
        else:
            ic.notify(f"Работает. Адрес: {get_url()}", APP_NAME)

    icon.run(setup=setup)


def main():
    try:
        SRV["obj"] = make_server()
    except OSError:
        try:
            import urllib.request
            urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{PORT}/desk/api", json.dumps({"a": "show"}).encode(),
                {"X-Desk": "1"}), timeout=3)
        except Exception:
            alert("Пульт уже запущен (иконка у часов).")
        return
    threading.Thread(target=sampler, daemon=True).start()
    threading.Thread(target=SRV["obj"].serve_forever, daemon=True).start()
    try:
        tray()
    except ImportError:
        open_desk()
        print(f"Нет pystray/pillow, работаю без значка.\nАдрес: {get_url()}")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
