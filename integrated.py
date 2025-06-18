
from flask import Flask, jsonify
import os
import time
import subprocess
import psutil
import json
import lz4.block
import sqlite3
import requests
from bs4 import BeautifulSoup
from collections import defaultdict, deque
from datetime import datetime, timedelta
import threading

from evdev import InputDevice, ecodes, list_devices
from Xlib import display, X
from Xlib.ext import record
from Xlib.protocol import rq

app = Flask(__name__)

# === Global Usage Trackers ===
app_usage = defaultdict(float)
site_usage = defaultdict(float)
active_app = None
active_site = None
start_time = None
is_paused = False
AUTH_TOKEN=None
# === CONFIG ===
FIREFOX_PROFILE_PATH = "/home/wassef/snap/firefox/common/.mozilla/firefox/3afnh5rk.default"
RECOVERY_FILE = os.path.join(FIREFOX_PROFILE_PATH, "sessionstore-backups", "recovery.jsonlz4")

IGNORED_PROCESSES = {"Xwayland", "Xorg", "gnome-shell", "gnome-shell-calendar-server", "pipewire"}
IGNORED_DISPLAY_APPS = {"Isolated Web Co", "Unknown"}

CHROMIUM_PATHS = {
    "chrome": os.path.expanduser("~/.config/google-chrome/Default/History"),
    "brave": os.path.expanduser("~/.config/BraveSoftware/Brave-Browser/Default/History"),
    "edge": os.path.expanduser("~/.config/microsoft-edge/Default/History")
}

HISTORY_UPDATE_INTERVAL = 10  # seconds
history_cache = {}
last_history_update = datetime.min


# === ODOO SETUP ===
if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
    user_home = os.path.expanduser(f"~{os.environ['SUDO_USER']}")
else:
    user_home = os.path.expanduser("~")

TOKEN_FILE = os.path.join(user_home, "PycharmProjects/ScriptDev/checkin_token.txt")
ODOO_URL = "http://localhost:8069"

def reload_token():
    global AUTH_TOKEN
    try:
        with open(TOKEN_FILE, "r") as f:
            AUTH_TOKEN = f.read().strip()
        if not AUTH_TOKEN:
            raise ValueError("Token file is empty")
        return AUTH_TOKEN
    except Exception as e:
        print(f"❌ CRITICAL ERROR: Failed to load token - {e}")
        exit(1)


reload_token()

def get_headers():

    reload_token()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AUTH_TOKEN}"
    }

script_flag = {'used': False}
alert_sent = False

# === UTILITIES ===
def pause_tracking():
    global is_paused
    is_paused = True
    print("🛑 Tracking paused.")

def resume_tracking():
    global is_paused
    is_paused = False
    print("▶️ Tracking resumed.")
def is_gui_process(proc):
    try:
        with open(f"/proc/{proc.pid}/environ", "rb") as f:
            env = f.read().split(b'\x00')
            return any(var.startswith(b'DISPLAY=') or var.startswith(b'WAYLAND_DISPLAY=') for var in env)
    except Exception:
        return False


def get_focused_window_pid():
    try:
        win_id = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True).stdout.strip()
        if not win_id:
            return None
        pid = subprocess.run(["xdotool", "getwindowpid", win_id], capture_output=True, text=True).stdout.strip()
        return int(pid) if pid.isdigit() else None
    except Exception:
        return None


def resolve_main_process_name(pid):
    try:
        proc = psutil.Process(pid)
        while proc.ppid() != 1 and proc.name() not in IGNORED_PROCESSES:
            parent = proc.parent()
            if parent is None or parent.name() in IGNORED_PROCESSES:
                break
            proc = parent
        return proc.name()
    except Exception:
        return "Unknown"


def get_best_gui_app():
    pid = get_focused_window_pid()
    if pid:
        return resolve_main_process_name(pid)

    gui_candidates = []
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        if is_gui_process(proc):
            try:
                cpu = proc.cpu_percent(interval=0.1)
                gui_candidates.append((proc.info["name"], cpu))
            except Exception:
                continue

    gui_candidates = [p for p in gui_candidates if p[0] not in IGNORED_PROCESSES]
    gui_candidates.sort(key=lambda x: x[1], reverse=True)
    return gui_candidates[0][0] if gui_candidates else "Unknown"


def get_current_firefox_tab_url():
    try:
        with open(RECOVERY_FILE, "rb") as f:
            f.read(8)
            json_data = lz4.block.decompress(f.read()).decode("utf-8")
            session = json.loads(json_data)

            win_idx = session.get("selectedWindow", 1) - 1
            windows = session.get("windows", [])
            if not windows or win_idx >= len(windows):
                return None, None
            win = windows[win_idx]

            tab_idx = win.get("selected", 1) - 1
            tabs = win.get("tabs", [])
            if not tabs or tab_idx >= len(tabs):
                return None, None
            tab = tabs[tab_idx]

            entries = tab.get("entries", [])
            i = tab.get("index", 1) - 1
            if 0 <= i < len(entries):
                entry = entries[i]
                return entry.get("title", "").strip(), entry.get("url", "").strip()
    except Exception as e:
        print("⚠️ Error reading Firefox session:", e)
    return None, None


def get_active_window_title():
    try:
        return subprocess.check_output(['xdotool', 'getwindowfocus', 'getwindowname'],
                                       stderr=subprocess.DEVNULL).decode('utf-8').strip()
    except Exception:
        return None


def read_history(db_path):
    if not os.path.exists(db_path):
        return []
    tmp = "/tmp/browser_history_copy"
    try:
        if os.path.exists(tmp): os.remove(tmp)
        os.system(f"cp '{db_path}' '{tmp}'")
        conn = sqlite3.connect(tmp)
        cur = conn.cursor()
        cur.execute("""
            SELECT url, title, last_visit_time
            FROM urls
            ORDER BY last_visit_time DESC
            LIMIT 100
        """)
        res = cur.fetchall()
        conn.close()
        return res
    except Exception as e:
        print(f"Failed to read {db_path}: {e}")
        return []


def update_history_cache():
    global history_cache
    new = {}
    for _, path in CHROMIUM_PATHS.items():
        for url, title, _ in read_history(path):
            if url and title:
                new[title] = url
    history_cache = new


def search_duckduckgo(query):
    try:
        resp = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        soup = BeautifulSoup(resp.text, "html.parser")
        link = soup.select_one("a.result__a")
        return link["href"] if link else None
    except Exception as e:
        print(f"🔍 DuckDuckGo search failed: {e}")
    return None


def is_generic_url(url):
    return url.strip() in {"http://www.google.com/", "https://www.google.com/"}


def find_url_by_title(title):
    if title in history_cache and not is_generic_url(history_cache[title]):
        return history_cache[title]
    for t, u in history_cache.items():
        if (t in title or title in t) and not is_generic_url(u):
            return u
    fb = search_duckduckgo(title)
    return f"{fb} [🕵️ fallback]" if fb else "unknown"


def detect_firefox_private_windows():
    try:
        out = subprocess.check_output(["wmctrl", "-l"], text=True)
        priv = []
        for ln in out.splitlines():
            if "firefox" in ln.lower() and ("private browsing" in ln.lower() or "navigation privée" in ln.lower()):
                parts = ln.split(None, 3)
                if len(parts) >= 4: priv.append(parts[3])
        return priv
    except Exception as e:
        print(f"[WARN] Failed to detect private Firefox windows: {e}")
    return []

# === TRACKERS ===

def track_forever(interval=1):
    print("🟢 GUI + Website Tracker is running (Ctrl+C to stop)...")
    global app_usage, site_usage, active_app, active_site, start_time,last_history_update,is_paused

    try:
        while True:
            if is_paused:
                time.sleep(1)
                continue
            now = time.time()
            if (datetime.now() - last_history_update).total_seconds() > HISTORY_UPDATE_INTERVAL:
                update_history_cache()
                last_history_update = datetime.now()

            current_app = get_best_gui_app()
            current_site = None

            if current_app.lower() == "firefox":
                title, url = get_current_firefox_tab_url()
                privs = detect_firefox_private_windows()
                awt = get_active_window_title()
                if awt in privs:
                    current_site = f"{awt} (🕵️ Private Window)"
                elif url:
                    current_site = f"{title} ({url})"
                else:
                    current_site = "firefox (unknown tab)"

            elif current_app.lower() in {"chrome", "brave", "edge"}:
                wt = get_active_window_title()
                if wt:
                    u = find_url_by_title(wt)
                    current_site = f"{wt} ({u})" if u != "unknown" else f"{wt} (private/incognito or unknown)"

            if current_app != active_app or current_site != active_site:
                if active_app and active_app not in IGNORED_DISPLAY_APPS:
                    delta = now - start_time
                    app_usage[active_app] += delta
                    if active_site: site_usage[active_site] += delta
                active_app = current_app
                active_site = current_site
                start_time = now

            time.sleep(interval)

    except KeyboardInterrupt:
        if active_app and active_app not in IGNORED_DISPLAY_APPS:
            delta = time.time() - start_time
            app_usage[active_app] += delta
            if active_site: site_usage[active_site] += delta

        send_daily_report(app_usage, site_usage)

        print("\n\n📊 Application usage report:")
        for app, secs in sorted(app_usage.items(), key=lambda x: -x[1]):
            print(f" - {app}: {secs:.2f} seconds")

        print("\n🌐 Website usage report:")
        for site, secs in sorted(site_usage.items(), key=lambda x: -x[1]):
            print(f" - {site}: {secs:.2f} seconds")

# === INPUT DETECTION ===

scroll_events = deque()

def find_device(keywords):
    for dev in (InputDevice(p) for p in list_devices()):
        if any(k in dev.name.lower() for k in keywords): return dev
    return None


def get_mouse_position():
    d = display.Display().screen().root.query_pointer()._data
    return d['root_x'], d['root_y']


def monitor_device(device, buffer, key):
    for e in device.read_loop():
        if e.type in {ecodes.EV_REL, ecodes.EV_ABS, ecodes.EV_KEY}:
            buffer[key].append((time.time(), e))


def record_x11_events(buffer):
    dpy = display.Display()
    def cb(reply):
        if reply.category != record.FromServer or reply.client_swapped or not reply.data: return
        data = reply.data
        while data:
            ev, data = rq.EventField(None).parse_binary_value(data, dpy.display, None, None)
            ts = time.time()
            if ev.type in (X.KeyPress, X.KeyRelease): buffer['scripted_keyboard'].append((ts, ev))
            elif ev.type in (X.ButtonPress, X.ButtonRelease): buffer['scripted_mouse'].append((ts, ev))
            elif ev.type == X.MotionNotify: buffer['scripted_motion'].append((ts, ev))

    ctx = dpy.record_create_context(0, [record.AllClients], [dict(
        core_requests=(0,0), core_replies=(0,0), ext_requests=(0,0,0,0), ext_replies=(0,0,0,0),
        delivered_events=(X.KeyPress, X.KeyRelease, X.ButtonPress, X.ButtonRelease, X.MotionNotify),
        device_events=(X.KeyPress, X.KeyRelease, X.ButtonPress, X.ButtonRelease, X.MotionNotify),
        errors=(0,0), client_started=False, client_died=False
    )])
    dpy.record_enable_context(ctx, cb)
    dpy.record_free_context(ctx)


def monitor_scroll_devices():
    for dev in (InputDevice(p) for p in list_devices()):
        def handler(d):
            for e in d.read_loop():
                if e.type == ecodes.EV_REL and e.code in (ecodes.REL_WHEEL, ecodes.REL_HWHEEL):
                    scroll_events.append((time.time(), d.name, e.code, e.value))
        threading.Thread(target=handler, args=(dev,), daemon=True).start()

def send_log_to_odoo(endpoint, data):
    try:
        headers = get_headers()
        resp = requests.get(endpoint, json=data, headers=headers, timeout=5)
        if resp.status_code == 401:
            print("🔒 Authentication failed - token invalid")
        elif resp.status_code in (200, 201):
            print(f"✅ Log sent to {endpoint}")
        else:
            print(f"❌ Failed to send log: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"❌ Error sending log: {e}")

def send_script_alert():
    global alert_sent
    if alert_sent:
        return
    payload = {
        "timestamp": datetime.now().isoformat(),
        "details": "Scripted input detected (keyboard, click, or cursor)."
    }
    send_log_to_odoo(f"{ODOO_URL}/api/script_alert", payload)
    alert_sent = True
    print("🚨 Administration notified about scripted input.")

def format_duration(secs):
    total_seconds = int(secs)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}min")
    parts.append(f"{seconds}seconds")

    return " ".join(parts)

def send_daily_report(app_usage, site_usage):
    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "app_usage": [{"name": k, "time_spent": format_duration(v)} for k, v in app_usage.items()],
        "site_usage": [{"name": k, "time_spent": format_duration(v)} for k, v in site_usage.items()],
        "script_used": script_flag['used']
    }
    send_log_to_odoo(f"{ODOO_URL}/api/employee_daily_work", payload)


def detect_non_scripted_inputs(poll_interval=0.05, event_window=0.15):
    print("🔍 Input Detection Tracker is running...")
    mouse_dev = find_device(["mouse","touchpad"])
    kb_dev = find_device(["keyboard"])
    if not mouse_dev or not kb_dev:
        print("❌ Input devices not found.")
        return
    buffer = {'mouse':deque(),'keyboard':deque(),'scripted_keyboard':deque(),'scripted_mouse':deque(),'scripted_motion':deque()}
    threading.Thread(target=monitor_device, args=(mouse_dev, buffer, 'mouse'), daemon=True).start()
    threading.Thread(target=monitor_device, args=(kb_dev, buffer, 'keyboard'), daemon=True).start()
    threading.Thread(target=record_x11_events, args=(buffer,), daemon=True).start()
    monitor_scroll_devices()
    last_pos = get_mouse_position()
    last_print = {}
    def should_print(k, cd=0.3):
        now=time.time();
        if k not in last_print or now-last_print[k]>cd:
            last_print[k]=now; return True
        return False

    try:
        while True:
            s = time.time()
            now = s
            pos = get_mouse_position()

            # Cursor movement
            if pos != last_pos:
                if buffer['mouse'] and should_print('cursor_real'):
                    print(f"✅ Cursor moved from {last_pos} to {pos} (real)")
                    buffer['scripted_motion'].clear()
                elif not buffer['mouse'] and should_print('cursor_scripted'):
                    print(f"⚠️ Cursor moved from {last_pos} to {pos} (scripted)")
                    script_flag['used'] = True
                    send_script_alert()
                    buffer['mouse'].clear()
                last_pos = pos

            # Real mouse click
            for _, e in list(buffer['mouse']):
                if e.type == ecodes.EV_KEY and e.code in [ecodes.BTN_LEFT, ecodes.BTN_RIGHT,
                                                          ecodes.BTN_MIDDLE] and e.value == 1:
                    if should_print('click_real'):
                        print("✅ Mouse click detected (real)")
                        buffer['scripted_mouse'].clear()

            # Scripted mouse click
            for _, e in list(buffer['scripted_mouse']):
                if e.type == X.ButtonPress and should_print('click_scripted'):
                    print(f"⚠️ Scripted mouse click detected (button {e.detail})")
                    script_flag['used'] = True
                    send_script_alert()
                    buffer['mouse'].clear()
                    buffer['scripted_mouse'].clear()

            # Real scroll detection
            while scroll_events and now - scroll_events[0][0] <= event_window:
                _, name, code, val = scroll_events.popleft()
                if should_print('scroll_real'):
                    direction = '↑' if val > 0 else '↓'
                    print(f"🖱️ Scroll on {name}: {direction} (real)")
                    buffer['scripted_mouse'].clear()

            # Keyboard detection
            if buffer['keyboard']:
                if should_print('keyboard_real'):
                    print("✅ Keyboard input detected (real)")
                buffer['scripted_keyboard'].clear()
                buffer['keyboard'].clear()
            elif buffer['scripted_keyboard']:
                if should_print('keyboard_scripted'):
                    print("⚠️ Scripted keyboard input detected")
                    script_flag['used'] = True
                    send_script_alert()
                buffer['scripted_keyboard'].clear()
                buffer['keyboard'].clear()

            # Cleanup old events
            for buf in buffer.values():
                while buf and now - buf[0][0] > event_window:
                    buf.popleft()

            time.sleep(max(0, poll_interval - (time.time() - s)))

    except KeyboardInterrupt:
        print("\n🔒 Input Detection Tracker stopped.")
@app.route("/pause", methods=["GET"])
def pause():
    pause_tracking()
    return jsonify({"status": "Tracking paused"}), 200

@app.route("/resume", methods=["GET"])
def resume():
    resume_tracking()
    return jsonify({"status": "Tracking resumed"}), 200
@app.route("/checkout", methods=["GET"])
def checkout():
    print("⛔ Checkout requested")

    global app_usage, site_usage

    try:

        send_daily_report(app_usage, site_usage)
        print("📤 Daily report sent during checkout.")
        payload = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "app_usage": [{"name": k, "time_spent": format_duration(v)} for k, v in app_usage.items()],
            "site_usage": [{"name": k, "time_spent": format_duration(v)} for k, v in site_usage.items()],
            "script_used": script_flag['used'],
            "AUTH_TOKEN":AUTH_TOKEN
        }

        return payload #jsonify({"status": "checkout in progress"})

    except Exception as e:
        print(f"❌ Failed to send daily report: {e}")
        return jsonify({"status": "Error sending daily report when checkout", "error": str(e)})

def start_flask():
    app.run(port=5001, debug=True, use_reloader=False)

if __name__=="__main__":
    threading.Thread(target=detect_non_scripted_inputs,daemon=True).start()
    flask_thread = threading.Thread(target=start_flask, daemon=True).start()
    track_forever()
