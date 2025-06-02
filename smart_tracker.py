import time
import os
import json
import shutil
import traceback
import psutil
import subprocess
from pynput import keyboard, mouse
from threading import Thread
from datetime import datetime
import requests
import re
import lz4.block

# === Configuration ===
ODOO_URL = "http://localhost:8069"
ODOO_API_ENDPOINT_USER = f"{ODOO_URL}/api/user-activity"
ODOO_API_ENDPOINT_SYSTEM = f"{ODOO_URL}/api/system-usage"
ODOO_API_ALERT = f"{ODOO_URL}/api/activity-alert"
TOKEN_FILE = os.path.expanduser("~/PycharmProjects/ScriptDev/checkin_token.txt")
FIREFOX_PROFILE_PATH = "/home/wassef/snap/firefox/common/.mozilla/firefox/3afnh5rk.default"

try:
    with open(TOKEN_FILE, "r") as f:
        AUTH_TOKEN = f.read().strip()
    if not AUTH_TOKEN:
        raise ValueError("Token file is empty")
except Exception as e:
    print(f"❌ CRITICAL ERROR: Failed to load token - {str(e)}")
    exit(1)

ODOO_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {AUTH_TOKEN}"
}

mouse_activity = {"clicks": 0, "scrolls": 0, "movements": 0}
keyboard_activity = {"key_presses": 0, "keys": []}
app_usage = {}
active_app = None
app_start_time = time.time()

last_sites = []
site_usage = {}
site_last_time = time.time()

# === Utility Functions ===
def send_log_to_odoo(endpoint, data):
    try:
        response = requests.post(endpoint, json=data, headers=ODOO_HEADERS)
        if response.status_code == 401:
            print("🔐 Authentication failed - token might be invalid.")
        elif response.status_code == 200:
            print(f"✅ Log sent to {endpoint}")
        else:
            print(f"❌ Failed to send log to {endpoint}: {response.text}")
    except Exception as e:
        print(f"❌ Error sending log to Odoo: {e}")

def get_firefox_tabs():
    try:
        recovery_file = os.path.join(FIREFOX_PROFILE_PATH, "sessionstore-backups", "recovery.jsonlz4")
        if not os.path.exists(recovery_file):
            return []
        with open(recovery_file, "rb") as f:
            f.read(8)
            data = lz4.block.decompress(f.read())
            session = json.loads(data)
            urls = []
            for window in session.get("windows", []):
                for tab in window.get("tabs", []):
                    i = tab.get("index", 1) - 1
                    entries = tab.get("entries", [])
                    if 0 <= i < len(entries):
                        urls.append(entries[i].get("url", ""))
            return urls
    except Exception as e:
        print(f"[ERROR] get_firefox_tabs: {e}")
        return []

def get_chromium_tabs():
    try:
        response = requests.get("http://localhost:9222/json")
        return [tab["url"] for tab in response.json() if "url" in tab]
    except Exception as e:
        return []

def extract_domain(url):
    if "://" in url:
        url = url.split("://", 1)[1]
    return url.split("/", 1)[0]

# === Input Handlers ===
def on_key_press(key):
    try:
        keyboard_activity["key_presses"] += 1
        keyboard_activity["keys"].append(str(key))
    except Exception as e:
        print(f"[ERROR] key press: {e}")

def on_mouse_click(x, y, button, pressed):
    if pressed:
        mouse_activity["clicks"] += 1

def on_mouse_scroll(x, y, dx, dy):
    mouse_activity["scrolls"] += 1

def on_mouse_move(x, y):
    mouse_activity["movements"] += 1

def log_user_activity():
    global mouse_activity, keyboard_activity, last_sites, site_usage, site_last_time
    while True:
        try:
            update_current_app_time()
            now = time.time()
            current_sites = get_chromium_tabs() + get_firefox_tabs()
            current_domains = [extract_domain(url) for url in current_sites]
            for site in last_sites:
                site_usage[site] = site_usage.get(site, 0) + (now - site_last_time)
            last_sites = current_domains
            site_last_time = now

            uptime = now - psutil.boot_time()
            log_data = {
                "timestamp": datetime.now().isoformat(),
                #"mouse_clicks": mouse_activity["clicks"],
                #"scrolls": mouse_activity["scrolls"],
                #"movements": mouse_activity["movements"],
                #"key_presses": keyboard_activity["key_presses"],
                #"keys": keyboard_activity["keys"],
                "system_uptime": f"{uptime:.2f} seconds",
                "application_usage": [
                    {"name": app, "time_spent": time_spent}
                    for app, time_spent in app_usage.items()
                ],
                "site_usage": [
                    {"domain": site, "time_spent": time_spent}
                    for site, time_spent in site_usage.items()
                ]
            }
            print(log_data)
            #send_log_to_odoo(ODOO_API_ENDPOINT_USER, log_data)

            mouse_activity = {"clicks": 0, "scrolls": 0, "movements": 0}
            keyboard_activity = {"key_presses": 0, "keys": []}
        except Exception as e:
            print(f"[ERROR] log_user_activity: {e}")
        time.sleep(60)

def update_current_app_time():
    global active_app, app_start_time, app_usage
    now = time.time()
    if active_app and active_app != "Unknown":
        duration = now - app_start_time
        app_usage[active_app] = app_usage.get(active_app, 0) + duration
        app_start_time = now

def get_active_window():
    try:
        # First try xdotool
        win_id = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True).stdout.strip()

        if not win_id or not win_id.isdigit():
            # Fallback to wmctrl if xdotool fails
            wmctrl_output = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True).stdout
            active_win = None
            for line in wmctrl_output.splitlines():
                if "-1" in line.split():  # '-1' = currently active window
                    active_win = line
                    break
            if active_win:
                parts = active_win.split()
                pid = parts[2]
                win_name = " ".join(parts[4:])
                proc_name = subprocess.run(["ps", "-p", pid, "-o", "comm="], capture_output=True, text=True).stdout.strip()
                return f"{proc_name or win_name}"
            return "Unknown (wmctrl fallback)"

        # Normal xdotool path
        xprop_out = subprocess.run(["xprop", "-id", win_id], capture_output=True, text=True).stdout
        match = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", xprop_out)
        if match:
            pid = match.group(1)
            app_name = subprocess.run(["ps", "-p", pid, "-o", "comm="], capture_output=True, text=True).stdout.strip()
            return app_name
        else:
            win_name = subprocess.run(["xdotool", "getwindowname", win_id], capture_output=True, text=True).stdout.strip()
            return win_name or "Unknown"

    except Exception as e:
        print(f"[get_active_window ERROR]: {e}")
        return "Unknown"


def track_active_window(interval=5):
    global active_app, app_start_time, app_usage
    while True:
        try:
            current_app = get_active_window()
            now = time.time()
            if current_app != active_app:
                if active_app and active_app != "Unknown":
                    duration = now - app_start_time
                    app_usage[active_app] = app_usage.get(active_app, 0) + duration
                    print(f"[SWITCH] {active_app} → {current_app} ({duration:.2f} sec)")
                active_app = current_app
                app_start_time = now
        except Exception as e:
            print(f"[ERROR] track_active_window: {e}")
        time.sleep(interval)

def log_system_usage():
    while True:
        try:
            cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
            memory = psutil.virtual_memory()
            total, used, free = shutil.disk_usage("/")
            net = psutil.net_io_counters()
            log_data = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "cpu_usage": cpu_percent,
                "memory_used": f"{memory.used / 1024 ** 3:.2f} GB",
                "memory_percent": memory.percent,
                "disk_usage": f"Total: {total / 1024 ** 3:.2f} GB, Used: {used / 1024 ** 3:.2f} GB, Free: {free / 1024 ** 3:.2f} GB",
                "network_sent": f"{net.bytes_sent / 1024 ** 2:.2f} MB",
                "network_received": f"{net.bytes_recv / 1024 ** 2:.2f} MB"
            }
            #send_log_to_odoo(ODOO_API_ENDPOINT_SYSTEM, log_data)
        except Exception as e:
            print(f"[ERROR] log_system_usage: {e}")
        time.sleep(60)

# === Main Entry ===
if __name__ == "__main__":
    try:
        print("\u2705 Activity tracker started. Logging in background.")
        Thread(target=log_system_usage, daemon=True).start()
        Thread(target=log_user_activity, daemon=True).start()
        Thread(target=track_active_window, daemon=True).start()

        with keyboard.Listener(on_press=on_key_press) as k_listener, \
             mouse.Listener(on_click=on_mouse_click, on_scroll=on_mouse_scroll, on_move=on_mouse_move) as m_listener:
            k_listener.join()
            m_listener.join()

    except Exception as e:
        print(f"\u274c MAIN ERROR: {e}")
        traceback.print_exc()
