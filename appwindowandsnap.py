import os
import time
import subprocess
import psutil
import json
import lz4.block
from collections import defaultdict

# === CONFIG ===
FIREFOX_PROFILE_PATH = "/home/wassef/snap/firefox/common/.mozilla/firefox/3afnh5rk.default"
RECOVERY_FILE = os.path.join(FIREFOX_PROFILE_PATH, "sessionstore-backups", "recovery.jsonlz4")
IGNORED_PROCESSES = {"Xwayland", "Xorg", "gnome-shell", "gnome-shell-calendar-server", "pipewire"}

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

# === FIREFOX TAB DETECTION ===
def get_current_firefox_tab_url():
    """Return (title, url) of the active tab in Firefox from recovery.jsonlz4."""
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

# === TRACKING LOGIC ===
def track_gui_app_and_web_usage(duration=60, interval=2):
    app_usage = defaultdict(float)
    site_usage = defaultdict(float)
    active_app = None
    active_site = None
    app_start_time = time.time()
    end_time = app_start_time + duration

    while time.time() < end_time:
        now = time.time()
        current_app = get_best_gui_app()

        current_site = None
        if current_app == "firefox":
            title, url = get_current_firefox_tab_url()
            if url:
                current_site = f"{title} ({url})"

        if current_app != active_app or current_site != active_site:
            if active_app and active_app != "Unknown":
                delta = now - app_start_time
                app_usage[active_app] += delta
                if active_app == "firefox" and active_site:
                    site_usage[active_site] += delta
            active_app = current_app
            active_site = current_site
            app_start_time = now

        time.sleep(interval)

    # Final update
    if active_app and active_app != "Unknown":
        delta = time.time() - app_start_time
        app_usage[active_app] += delta
        if active_app == "firefox" and active_site:
            site_usage[active_site] += delta

    return dict(app_usage), dict(site_usage)


# === MAIN ===
def main():
    print("🟢 Robust GUI + Website Tracker (Snap & Wayland Friendly)")
    print("⏳ Tracking... please wait 60 seconds...\n")
    app_results, site_results = track_gui_app_and_web_usage(duration=60, interval=2)

    print("\n📊 Application usage report:")
    for app, seconds in sorted(app_results.items(), key=lambda x: -x[1]):
        print(f" - {app}: {seconds:.2f} seconds")

    print("\n🌐 Website usage report (Firefox):")
    for site, seconds in sorted(site_results.items(), key=lambda x: -x[1]):
        print(f" - {site}: {seconds:.2f} seconds")

if __name__ == "__main__":
    main()
