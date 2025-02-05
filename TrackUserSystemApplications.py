import time
import os
import json
import shutil
import traceback
import pyautogui
import psutil
import subprocess
from pynput import keyboard, mouse
from threading import Thread
from datetime import datetime

# Constants
LOG_FILE = "user_activity_detailed.log"
LOG_SYSTEM="system_usage_detailed.log"
SCREENSHOT_FOLDER = "screenshots"
INACTIVITY_THRESHOLD = 180  # 3 minutes
SCREENSHOT_INTERVAL = 600  # 10 minutes
AUTOMATION_THRESHOLD = 0.02  # For detecting robotic movement

# Activity tracking
mouse_activity = {"clicks": 0, "scrolls": 0, "movements": 0}
keyboard_activity = {"key_presses": 0, "keys": []}
app_usage = {}
last_activity_time = time.time()
last_screenshot_time = time.time()
last_mouse_position = (0, 0)
active_app = None
app_start_time = time.time()

# Ensure screenshot folder exists
os.makedirs(SCREENSHOT_FOLDER, exist_ok=True)

def log_system_usage():
    while True:
        try:
            cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
            memory = psutil.virtual_memory()
            total, used, free = shutil.disk_usage("/")
            net = psutil.net_io_counters()

            log_data = {
                "timestamp": datetime.now().isoformat(),
                "cpu_usage": cpu_percent,
                "memory_used": f"{memory.used / 1024 ** 3:.2f} GB",
                "memory_percent": memory.percent,
                "disk_usage": f"Total: {total / 1024 ** 3:.2f} GB, Used: {used / 1024 ** 3:.2f} GB, Free: {free / 1024 ** 3:.2f} GB",
                "network_sent": f"{net.bytes_sent / 1024 ** 2:.2f} MB",
                "network_received": f"{net.bytes_recv / 1024 ** 2:.2f} MB"
            }

            with open(LOG_SYSTEM, "a") as log_file:
                log_file.write(json.dumps(log_data, indent=4) + "\n")

        except Exception as e:
            print(f"Error logging system usage: {e}")

        time.sleep(10)  # Log every 10 seconds

# Function to get the active window title (Ubuntu compatible)
def get_active_window():
    try:
        win_id = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True).stdout.strip()
        if not win_id:
            return "Unknown"

        output = subprocess.run(["xprop", "-id", win_id, "WM_NAME"], capture_output=True, text=True).stdout
        if 'WM_NAME' in output:
            return output.split("=", 1)[1].strip().strip('"')

        return "Unknown"
    except Exception as e:
        print(f"Error getting active window: {e}")
        return "Unknown"


# Function to track time spent on each application
def update_application_usage():
    global active_app, app_start_time, app_usage
    current_app = get_active_window()

    if active_app != current_app:
        elapsed_time = time.time() - app_start_time
        if active_app and active_app != "Unknown":
            app_usage[active_app] = app_usage.get(active_app, 0) + elapsed_time

        active_app = current_app
        app_start_time = time.time()


# Function to log user activity every minute
def log_user_activity():
    global mouse_activity, keyboard_activity, app_usage
    while True:
        try:
            update_application_usage()
            uptime = time.time() - psutil.boot_time()

            log_data = {
                "timestamp": datetime.now().isoformat(),
                "mouse_activity": mouse_activity,
                "keyboard_activity": {
                    "total_key_presses": keyboard_activity["key_presses"],
                    "keys": keyboard_activity["keys"][-10:]  # Last 10 keys pressed
                },
                "system_uptime": f"{uptime:.2f} seconds",
                "application_usage": {app: f"{time_spent:.2f} seconds" for app, time_spent in app_usage.items()}
            }

            with open(LOG_FILE, "a") as log_file:
                log_file.write(json.dumps(log_data, indent=4) + "\n")

            # Reset counts
            mouse_activity = {"clicks": 0, "scrolls": 0, "movements": 0}
            keyboard_activity = {"key_presses": 0, "keys": []}

        except Exception as e:
            print(f"Error logging user activity: {e}")

        time.sleep(60)  # Log every minute


# Function to take screenshots
def take_screenshot(reason="Periodic"):
    global last_screenshot_time
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    screenshot_path = os.path.join(SCREENSHOT_FOLDER, f"{reason}_screenshot_{timestamp}.png")
    pyautogui.screenshot(screenshot_path)
    last_screenshot_time = time.time()
    print(f"📸 Screenshot taken ({reason}): {screenshot_path}")


# Function to monitor inactivity
def track_inactivity():
    global last_activity_time
    while True:
        time.sleep(10)
        inactive_time = time.time() - last_activity_time

        if inactive_time > INACTIVITY_THRESHOLD:
            take_screenshot("Inactive")
            last_activity_time = time.time()


# Function to take periodic screenshots every 10 minutes
def periodic_screenshots():
    while True:
        time.sleep(SCREENSHOT_INTERVAL)
        take_screenshot("Periodic")


# Event listeners
def on_key_press(key):
    global keyboard_activity, last_activity_time
    try:
        keyboard_activity["key_presses"] += 1
        keyboard_activity["keys"].append(str(key))
        last_activity_time = time.time()
    except Exception as e:
        print(f"Error in key press event: {e}")


def on_mouse_click(x, y, button, pressed):
    global mouse_activity, last_activity_time
    if pressed:
        mouse_activity["clicks"] += 1
        last_activity_time = time.time()


def on_mouse_scroll(x, y, dx, dy):
    global mouse_activity, last_activity_time
    mouse_activity["scrolls"] += 1
    last_activity_time = time.time()


def on_mouse_move(x, y):
    global mouse_activity, last_activity_time
    mouse_activity["movements"] += 1
    last_activity_time = time.time()

# Start system usage tracking
system_usage_thread = Thread(target=log_system_usage)
system_usage_thread.daemon = True
system_usage_thread.start()

# Start user activity logging thread
activity_thread = Thread(target=log_user_activity, daemon=True)
activity_thread.start()

# Start inactivity tracking thread
inactivity_thread = Thread(target=track_inactivity, daemon=True)
inactivity_thread.start()

# Start periodic screenshot thread
screenshot_thread = Thread(target=periodic_screenshots, daemon=True)
screenshot_thread.start()

# Start event listeners
keyboard_listener = keyboard.Listener(on_press=on_key_press)
mouse_listener = mouse.Listener(
    on_click=on_mouse_click, on_scroll=on_mouse_scroll, on_move=on_mouse_move
)

if __name__ == "__main__":
    try:
        print("✅ Activity tracker started. Logging user activity and taking screenshots.")
        keyboard_listener.start()
        mouse_listener.start()

        keyboard_listener.join()
        mouse_listener.join()
    except Exception as e:
        print(f"Error in main loop: {e}")
        traceback.print_exc()
