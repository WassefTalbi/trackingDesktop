import psutil
import time
import json
import os
import re
from datetime import datetime
from collections import defaultdict
from threading import Thread
from pynput import mouse, keyboard

# Configuration
REFRESH_INTERVAL = 5  # seconds
REPORT_FILE = "activity_report.json"
CATEGORIES = {
    "work": ["word", "excel", "outlook", "teams", "slack", "pycharm", "vscode", "terminal", "code", "ssh"],
    "entertainment": ["netflix", "youtube", "spotify", "twitch", "discord"],
    "social": ["facebook", "instagram", "twitter", "tiktok", "linkedin"],
    "suspicious": ["powershell", "cmd", "bash", "script", ".sh", ".bat"]
}
BROWSERS = ["chrome", "firefox", "edge"]

# Globals
activity_log = []
last_input_time = time.time()

def categorize(name):
    lname = name.lower()
    for cat, keywords in CATEGORIES.items():
        if any(k in lname for k in keywords):
            return cat
    return "unknown"

def is_browser(proc_name):
    return any(browser in proc_name.lower() for browser in BROWSERS)

def get_browser_tabs():
    tabs = []

    # Chrome/Edge: Remote Debugging (assumes --remote-debugging-port=9222 enabled)
    try:
        import requests
        r = requests.get("http://localhost:9222/json")
        for tab in r.json():
            if tab.get("url") and not tab["url"].startswith("chrome://"):
                tabs.append((tab["title"], tab["url"]))
    except Exception:
        pass


    try:
        profile_path = os.path.expanduser("~/.mozilla/firefox")
        for profile in os.listdir(profile_path):
            path = os.path.join(profile_path, profile, "sessionstore-backups", "recovery.jsonlz4")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    f.read(8)  # skip header
                    import lz4.frame
                    data = json.loads(lz4.frame.decompress(f.read()))
                    windows = data.get("windows", [])
                    for win in windows:
                        for tab in win.get("tabs", []):
                            i = tab.get("index", 1) - 1
                            if i < len(tab["entries"]):
                                url = tab["entries"][i].get("url", "")
                                title = tab["entries"][i].get("title", "")
                                tabs.append((title, url))
    except Exception:
        pass

    return tabs

def get_active_processes():
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name']:
                name = proc.info['name']
                cmd = " ".join(proc.info['cmdline']) if proc.info['cmdline'] else ""
                category = categorize(name + " " + cmd)
                procs.append({
                    "pid": proc.info['pid'],
                    "name": name,
                    "cmdline": cmd,
                    "category": category
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs

def detect_idle():
    global last_input_time
    def on_activity(_):
        last_input_time = time.time()

    mouse.Listener(on_move=on_activity, on_click=on_activity).start()
    keyboard.Listener(on_press=on_activity).start()

def detect_auto_scripts(processes):
    auto_procs = []
    idle_threshold = 120  # seconds
    for proc in processes:
        if proc["category"] in ["suspicious", "unknown"] and (time.time() - last_input_time > idle_threshold):
            auto_procs.append(proc)
    return auto_procs

def track():
    while True:
        timestamp = datetime.now().isoformat()
        processes = get_active_processes()
        browser_tabs = get_browser_tabs()
        auto_scripts = detect_auto_scripts(processes)

        # Save each process entry
        for proc in processes:
            activity_log.append({
                "timestamp": timestamp,
                "source": "application",
                "name": proc["name"],
                "details": proc["cmdline"],
                "category": proc["category"],
                "type": "auto-script" if proc in auto_scripts else "manual",
            })

        # Save each browser tab
        for title, url in browser_tabs:
            activity_log.append({
                "timestamp": timestamp,
                "source": "browser",
                "name": title,
                "details": url,
                "category": categorize(title + " " + url),
                "type": "manual"
            })

        # Write report
        with open(REPORT_FILE, "w") as f:
            json.dump(activity_log, f, indent=2)

        time.sleep(REFRESH_INTERVAL)

if __name__ == "__main__":
    Thread(target=detect_idle, daemon=True).start()
    track()
