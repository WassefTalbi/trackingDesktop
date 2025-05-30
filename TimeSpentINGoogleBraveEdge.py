import os
import sqlite3
import time
import subprocess
from datetime import datetime, timedelta
from collections import defaultdict

# Path to Chromium-based browsers history DBs
CHROMIUM_PATHS = {
    "chrome": os.path.expanduser("~/.config/google-chrome/Default/History"),
    "brave": os.path.expanduser("~/.config/BraveSoftware/Brave-Browser/Default/History"),
    "edge": os.path.expanduser("~/.config/microsoft-edge/Default/History")
}

history_cache = {}
last_history_update = datetime.min
HISTORY_UPDATE_INTERVAL = 10  # seconds

def get_active_window_title():
    try:
        title = subprocess.check_output(
            ['xdotool', 'getwindowfocus', 'getwindowname'],
            stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()
        return title
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
    for browser, path in CHROMIUM_PATHS.items():
        entries = read_history(path)
        for url, title, _ in entries:
            if url and title:
                new_cache[title] = url
    history_cache = new_cache

def find_url_by_title(title):

    if title in history_cache:
        return history_cache[title]


    for cached_title in history_cache:
        if cached_title in title or title in cached_title:
            return history_cache[cached_title]
    return None

def main(poll_interval=1):
    global last_history_update

    time_spent = defaultdict(float)
    current_key = None
    start_time = None

    print("🔍 Tracking active browser tab... (Ctrl+C to stop)")

    try:
        while True:
            now = time.time()
            if (datetime.now() - last_history_update).total_seconds() > HISTORY_UPDATE_INTERVAL:
                update_history_cache()
                last_history_update = datetime.now()
            active_title = get_active_window_title()
            if active_title:
                url = find_url_by_title(active_title)
                key = (url, active_title) if url else None
            else:
                key = None
            if key != current_key:
                if current_key and start_time:
                    duration = now - start_time
                    time_spent[current_key] += duration
                current_key = key
                start_time = now

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        # Save time on current tab
        if current_key and start_time:
            duration = time.time() - start_time
            time_spent[current_key] += duration

        print("\n📊 Time spent summary:")
        for (url, title), seconds in sorted(time_spent.items(), key=lambda x: -x[1]):
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            print(f"{mins:02}:{secs:02} | {title[:50]} | {url}")

if __name__ == "__main__":
    main()
