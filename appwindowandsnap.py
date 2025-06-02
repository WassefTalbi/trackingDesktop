import os
import time
import subprocess
import psutil
import json
import lz4.block
import sqlite3
import requests
from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime, timedelta
import threading

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

# === UTILITIES ===
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
            f.read(8)  # Skip LZ4 magic header
            json_data = lz4.block.decompress(f.read()).decode("utf-8")
            session = json.loads(json_data)

            selected_win_idx = session.get("selectedWindow", 1) - 1
            windows = session.get("windows", [])
            if not windows or selected_win_idx >= len(windows):
                return None, None
            win = windows[selected_win_idx]

            selected_tab_idx = win.get("selected", 1) - 1
            tabs = win.get("tabs", [])
            if not tabs or selected_tab_idx >= len(tabs):
                return None, None
            tab = tabs[selected_tab_idx]

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
    temp_copy = "/tmp/browser_history_copy"
    try:
        if os.path.exists(temp_copy):
            os.remove(temp_copy)
        os.system(f"cp '{db_path}' '{temp_copy}'")
        conn = sqlite3.connect(temp_copy)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT urls.url, urls.title, urls.last_visit_time
            FROM urls
            ORDER BY last_visit_time DESC
            LIMIT 100
        """)
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        print(f"Failed to read {db_path}: {e}")
        return []

def update_history_cache():
    global history_cache
    new_cache = {}
    for _, path in CHROMIUM_PATHS.items():
        entries = read_history(path)
        for url, title, _ in entries:
            if url and title:
                new_cache[title] = url
    history_cache = new_cache

# === 🔍 DuckDuckGo fallback ===
def search_duckduckgo(query):
    try:
        url = "https://html.duckduckgo.com/html/"
        headers = {"User-Agent": "Mozilla/5.0"}
        data = {"q": query}
        print(f"displaying the url,data{url}||||{data}")
        response = requests.post(url, data=data, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.select("a.result__a")
        if links:
            return links[0]["href"]
    except Exception as e:
        print(f"🔍 DuckDuckGo search failed: {e}")
    return None


def is_generic_url(url):
    return url.strip() in {"http://www.google.com/", "https://www.google.com/"}


def find_url_by_title(title):
    print(f"[DEBUG] Checking history for title: {title}")

    # Exact title match
    if title in history_cache and not is_generic_url(history_cache[title]):
        return history_cache[title]

    # Fuzzy match
    for cached_title, url in history_cache.items():
        if (cached_title in title or title in cached_title) and not is_generic_url(url):
            print(f"[DEBUG] Fuzzy matched: '{cached_title}' → {url}")
            return url

    # Fallback to DuckDuckGo
    print(f"[DEBUG] Title not found or was generic, falling back to DuckDuckGo: {title}")
    fallback_url = search_duckduckgo(title)
    if fallback_url:
        return f"{fallback_url} [🕵️ fallback]"
    return "unknown"

def detect_firefox_private_windows():
    """Returns a list of titles of Firefox private windows."""
    try:
        output = subprocess.check_output(["wmctrl", "-l"], text=True)
        private_windows = []
        for line in output.strip().split("\n"):
            if "firefox" in line.lower() and ("Private Browsing" in line or "Navigation privée" in line):
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    title = parts[3]
                    private_windows.append(title)
        return private_windows
    except Exception as e:
        print(f"[WARN] Failed to detect private Firefox windows: {e}")
        return []

# === TRACKING ===
def track_forever(interval=1):
    print("🟢 GUI + Website Tracker is running (Ctrl+C to stop)...")

    app_usage = defaultdict(float)
    site_usage = defaultdict(float)
    active_app = None
    active_site = None
    app_start_time = time.time()

    global last_history_update
    try:
        while True:
            now = time.time()

            if (datetime.now() - last_history_update).total_seconds() > HISTORY_UPDATE_INTERVAL:
                update_history_cache()
                last_history_update = datetime.now()

            current_app = get_best_gui_app()
            current_site = None

            if current_app == "firefox":
                title, url = get_current_firefox_tab_url()
                private_windows = detect_firefox_private_windows()
                active_title = get_active_window_title()

                if active_title in private_windows:
                    current_site = f"{active_title} (🕵️ Private Window)"
                    print(f"🕵️ Switched to Firefox Private Window: {active_title}")
                elif url:
                    current_site = f"{title} ({url})"
                else:
                    current_site = "firefox (unknown tab)"

            elif current_app.lower() in {"chrome", "brave", "edge"}:
                window_title = get_active_window_title()
                if window_title:
                    url = find_url_by_title(window_title)
                    if url and url != "unknown":
                        current_site = f"{window_title} ({url})"
                    else:
                        current_site = f"{window_title} (private/incognito or unknown)"

            if current_app != active_app or current_site != active_site:
                if active_app and active_app != "Unknown":
                    delta = now - app_start_time
                    app_usage[active_app] += delta
                    if active_site:
                        site_usage[active_site] += delta
                active_app = current_app
                active_site = current_site
                app_start_time = now

            time.sleep(interval)

    except KeyboardInterrupt:

        if active_app and active_app != "Unknown":
            delta = time.time() - app_start_time
            app_usage[active_app] += delta
            if active_site:
                site_usage[active_site] += delta

        print("\n\n📊 Application usage report:")
        for app, seconds in sorted(app_usage.items(), key=lambda x: -x[1]):
            if app not in IGNORED_DISPLAY_APPS:
                print(f" - {app}: {seconds:.2f} seconds")

        print("\n🌐 Website usage report:")
        for site, seconds in sorted(site_usage.items(), key=lambda x: -x[1]):
            print(f" - {site}: {seconds:.2f} seconds")

# === MAIN ===
if __name__ == "__main__":
    track_forever()
