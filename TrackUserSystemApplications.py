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
import lz4.block
import re
from collections import deque
from evdev import InputDevice, ecodes, list_devices
import asyncio

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
    print(f"\u274c CRITICAL ERROR: Failed to load token - {str(e)}")
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
recent_mouse_events = deque(maxlen=50)
recent_keyboard_events = deque(maxlen=30)

def send_log_to_odoo(endpoint, data):
    try:
        response = requests.post(endpoint, json=data, headers=ODOO_HEADERS)
        if response.status_code == 401:
            print("\ud83d\udd10 Authentication failed - token might be invalid.")
        elif response.status_code == 200:
            print(f"\u2705 Log sent to {endpoint}")
        else:
            print(f"\u274c Failed to send log to {endpoint}: {response.text}")
    except Exception as e:
        print(f"\u274c Error sending log to Odoo: {e}")

def is_virtual_device(device):
    name = device.name.lower()
    return any(k in name for k in ['uinput', 'virtual', 'pynput', 'xvfb', 'xdotool'])

async def monitor_device(device, virtual_devices):
    try:
        async for event in device.async_read_loop():
            if device.path in virtual_devices:
                alert_data = {
                    "timestamp": datetime.now().isoformat(),
                    "alert_type": "anomalous_input",
                    "device": device.name,
                    "event": f"type={event.type}, code={event.code}, value={event.value}",
                    "message": f"\u26a0\ufe0f Suspicious input detected from {device.name}"
                }
                print(f"[ALERT] {alert_data['message']}")
                #send_log_to_odoo(ODOO_API_ALERT, alert_data)
    except Exception as e:
        print(f"[ERROR] Error monitoring {device.path}: {e}")

async def monitor_all_devices():
    devices = [InputDevice(path) for path in list_devices()]
    virtual_devices = {d.path for d in devices if is_virtual_device(d)}
    print(f"Devices virtuels détectés: {len(virtual_devices)}")
    for d in devices:
        print(f" - {d.path} : {d.name} {'(VIRTUAL)' if d.path in virtual_devices else '(PHYSICAL)'}")
    tasks = [asyncio.create_task(monitor_device(d, virtual_devices)) for d in devices]
    await asyncio.gather(*tasks)

def run_evdev_monitor():
    asyncio.run(monitor_all_devices())

def on_key_press(key):
    try:
        keyboard_activity["key_presses"] += 1
        keyboard_activity["keys"].append(str(key))
        recent_keyboard_events.append((str(key), time.time()))
    except Exception as e:
        print(f"[ERROR] key press: {e}")

def on_mouse_click(x, y, button, pressed):
    if pressed:
        mouse_activity["clicks"] += 1
        recent_mouse_events.append(("click", time.time()))

def on_mouse_scroll(x, y, dx, dy):
    mouse_activity["scrolls"] += 1
    recent_mouse_events.append(("scroll", time.time()))

def on_mouse_move(x, y):
    mouse_activity["movements"] += 1
    recent_mouse_events.append(("move", time.time()))

def log_user_activity():
    global mouse_activity, keyboard_activity
    while True:
        try:
            update_current_app_time()
            uptime = time.time() - psutil.boot_time()
            log_data = {
                "timestamp": datetime.now().isoformat(),
                "mouse_clicks": mouse_activity["clicks"],
                "scrolls": mouse_activity["scrolls"],
                "movements": mouse_activity["movements"],
                "key_presses": keyboard_activity["key_presses"],
                "keys": keyboard_activity["keys"],
                "system_uptime": f"{uptime:.2f} seconds",
                "application_usage": [
                    {"name": app, "time_spent": time_spent}
                    for app, time_spent in app_usage.items()
                ]
            }
            print(log_data)
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
        win_id = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True).stdout.strip()
        if win_id:
            xprop_out = subprocess.run(["xprop", "-id", win_id], capture_output=True, text=True).stdout
            match = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", xprop_out)
            if match:
                pid = match.group(1)
                app_name = subprocess.run(["ps", "-p", pid, "-o", "comm="], capture_output=True, text=True).stdout.strip()
                return f"Active Window: {app_name} (PID: {pid})"
            else:
                return "Unknown"
        else:
            return "No active window detected"
    except Exception as e:
        print(f"\u26a0\ufe0f Error determining active window: {e}")
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
        except Exception as e:
            print(f"[ERROR] log_system_usage: {e}")
        time.sleep(60)

if __name__ == "__main__":
    try:
        print("\u2705 Activity tracker started. Logging in background.")
        Thread(target=log_system_usage, daemon=True).start()
        Thread(target=log_user_activity, daemon=True).start()
        Thread(target=track_active_window, daemon=True).start()
        Thread(target=run_evdev_monitor, daemon=True).start()

        with keyboard.Listener(on_press=on_key_press) as k_listener, \
             mouse.Listener(on_click=on_mouse_click, on_scroll=on_mouse_scroll, on_move=on_mouse_move) as m_listener:
            k_listener.join()
            m_listener.join()

    except Exception as e:
        print(f"\u274c MAIN ERROR: {e}")
        traceback.print_exc()
