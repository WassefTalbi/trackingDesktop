import os
import time
import json
import psutil
import subprocess
from datetime import datetime
from pynput import keyboard, mouse
from threading import Thread
import lz4.frame
import lz4.block
# ------------------------ CONFIG ------------------------

IDLE_THRESHOLD_SECONDS = 60
LOG_FILE = "activity_log.json"

# ------------------------ GLOBALS ------------------------

keyboard_last_active = time.time()
mouse_last_active = time.time()

current_app = None
app_start_time = time.time()

# ------------------------ ACTIVITY DETECTION ------------------------

def on_key_press(key):
    global keyboard_last_active
    keyboard_last_active = time.time()

def on_mouse_event(*args):
    global mouse_last_active
    mouse_last_active = time.time()

def is_idle():
    now = time.time()
    idle_duration = now - max(keyboard_last_active, mouse_last_active)
    return idle_duration > IDLE_THRESHOLD_SECONDS, idle_duration

# def get_active_window_title():
#     try:
#         win_id = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True).stdout.strip()
#         if not win_id:
#             return None
#         output = subprocess.run(["xprop", "-id", win_id, "WM_NAME"], capture_output=True, text=True).stdout
#         title_result = subprocess.run(["xprop", "-id", win_id, "WM_NAME"], capture_output=True, text=True).stdout
#         title = title_result.split("=", 1)[-1].strip().strip('"\'')
#         print(title)
#         class_result = subprocess.run(["xprop", "-id", win_id, "WM_CLASS"], capture_output=True, text=True).stdout
#         wm_class = class_result.split(",")[-1].strip().strip('"')
#         print(wm_class)
#         if 'WM_NAME' in output:
#             print(output)
#             return output.split("=", 1)[1].strip().strip('"')
#
#         return None
#     except Exception as e:
#         print(f"[⚠️] Window detection error: {e}")
#         return None


FIREFOX_PROFILE_PATH = "/home/wassef/snap/firefox/common/.mozilla/firefox/3afnh5rk.default"

def get_firefox_tabs():
    session_file = os.path.join(
        FIREFOX_PROFILE_PATH, "sessionstore-backups", "recovery.jsonlz4"
    )
    try:
        if not os.path.exists(session_file):
            print("[⚠️] recovery.jsonlz4 not found")
            return None

        with open(session_file, "rb") as f:
            magic = f.read(8)  # Skip the 'mozLz40\0' header
            compressed_data = f.read()
            json_data = lz4.block.decompress(compressed_data)
            session = json.loads(json_data)

            tabs = []
            for window in session.get("windows", []):
                for tab in window.get("tabs", []):
                    index = tab.get("index", 1) - 1
                    entries = tab.get("entries", [])
                    if index < len(entries):
                        url = entries[index].get("url", "")
                        title = entries[index].get("title", "")
                        tabs.append(f"{title} ({url})")

            return tabs if tabs else None

    except Exception as e:
        print(f"[⚠️] Error reading Firefox tabs: {e}")
        return None

def get_active_window_title():
    try:
        # Use wmctrl to get the window title of the currently focused window
        title = subprocess.check_output(['wmctrl', '-lpG']).decode('utf-8')
        print(title)
        for line in title.splitlines():
            if '* ' in line:
                return line.split(None, 4)[-1]
        return None
    except Exception as e:
        print(f"[⚠️] Error getting active window title with wmctrl: {e}")
        return None



def log_activity(activity):
    try:
        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w") as f:
                json.dump([], f)
        with open(LOG_FILE, "r+") as f:
            data = json.load(f)
            data.append(activity)
            f.seek(0)
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[❌] Failed to log activity: {e}")

def activity_tracker_loop():
    global current_app, app_start_time

    while True:
        try:
            now = time.time()
            title = get_active_window_title()
            idle, idle_duration = is_idle()
            tabs = get_firefox_tabs()
            if tabs:
                print("Active Firefox tabs:")
                for tab in tabs:
                    print(tab)
            else:
                print("No active tabs found.")
            if title != current_app:
                if current_app:
                    duration = now - app_start_time
                    activity = {
                        "timestamp": datetime.now().isoformat(),
                        "application": current_app,
                        "duration_seconds": round(duration),
                        "idle": idle,

                    }
                    log_activity(activity)
                current_app = title
                app_start_time = now

            time.sleep(5)
        except Exception as e:
            print(f"[ERROR] Tracking loop: {e}")

# ------------------------ MAIN ENTRY ------------------------

if __name__ == "__main__":
    print("🟢 Smart Activity Tracker Started (logging to activity_log.json)")

    Thread(target=activity_tracker_loop, daemon=True).start()

    with keyboard.Listener(on_press=on_key_press) as k_listener, \
         mouse.Listener(on_click=on_mouse_event,
                        on_scroll=on_mouse_event,
                        on_move=on_mouse_event) as m_listener:
        k_listener.join()
        m_listener.join()
