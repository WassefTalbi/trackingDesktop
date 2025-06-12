import time
from collections import deque
from evdev import InputDevice, ecodes, list_devices
from Xlib import display, X
from Xlib.ext import record
from Xlib.protocol import rq
import threading

# === Global Buffers ===
scroll_events = deque()
click_events = deque()
scripted_events = deque()

def find_device(keywords):
    devices = [InputDevice(path) for path in list_devices()]
    for dev in devices:
        if any(keyword in dev.name.lower() for keyword in keywords):
            return dev
    return None

def get_mouse_position():
    data = display.Display().screen().root.query_pointer()._data
    return data["root_x"], data["root_y"]

def monitor_device(device, event_buffer, key):
    for event in device.read_loop():
        if event.type in {ecodes.EV_REL, ecodes.EV_ABS, ecodes.EV_KEY}:
            event_buffer[key].append((time.time(), event))

def record_x11_events(event_buffer):
    record_dpy = display.Display()

    def callback(reply):
        if reply.category != record.FromServer or reply.client_swapped or not len(reply.data):
            return
        if reply.data[0] < 2:
            return
        data = reply.data
        while len(data):
            event, data = rq.EventField(None).parse_binary_value(data, record_dpy.display, None, None)
            now = time.time()
            if event.type in (X.KeyPress, X.KeyRelease):
                event_buffer['scripted_keyboard'].append((now, event))
            elif event.type in (X.ButtonPress, X.ButtonRelease):
                # Log all button events for debugging
                event_buffer['scripted_mouse'].append((now, event))
                print(f"DEBUG: Xlib captured button event: type={event.type}, detail={event.detail}")
            elif event.type == X.MotionNotify:
                event_buffer['scripted_motion'].append((now, event))

    ctx = record_dpy.record_create_context(
        0,
        [record.AllClients],
        [dict(
            core_requests=(0, 0),
            core_replies=(0, 0),
            ext_requests=(0, 0, 0, 0),
            ext_replies=(0, 0, 0, 0),
            delivered_events=(X.KeyPress, X.KeyRelease, X.ButtonPress, X.ButtonRelease, X.MotionNotify),
            device_events=(X.KeyPress, X.KeyRelease, X.ButtonPress, X.ButtonRelease, X.MotionNotify),
            errors=(0, 0),
            client_started=False,
            client_died=False,
        )]
    )
    record_dpy.record_enable_context(ctx, callback)
    record_dpy.record_free_context(ctx)

def monitor_scroll_devices():
    devices = [InputDevice(path) for path in list_devices()]
    def handle(device):
        for event in device.read_loop():
            if event.type == ecodes.EV_REL and event.code in (ecodes.REL_WHEEL, ecodes.REL_HWHEEL):
                scroll_events.append((time.time(), device.name, event.code, event.value))
    for dev in devices:
        threading.Thread(target=handle, args=(dev,), daemon=True).start()

def detect_non_scripted_inputs(poll_interval=0.05, event_window=0.15):
    print("🔍 Starting input detection...")

    mouse_device = find_device(["mouse", "touchpad"])
    keyboard_device = find_device(["keyboard"])

    if mouse_device is None or keyboard_device is None:
        print("❌ Input devices not found.")
        return

    event_buffer = {
        'mouse': deque(),
        'keyboard': deque(),
        'scripted_keyboard': deque(),
        'scripted_mouse': deque(),
        'scripted_motion': deque()
    }

    threading.Thread(target=monitor_device, args=(mouse_device, event_buffer, 'mouse'), daemon=True).start()
    threading.Thread(target=monitor_device, args=(keyboard_device, event_buffer, 'keyboard'), daemon=True).start()
    threading.Thread(target=record_x11_events, args=(event_buffer,), daemon=True).start()

    monitor_scroll_devices()

    last_mouse_pos = get_mouse_position()

    last_print = {}

    def should_print(key, cooldown=0.3):
        now = time.time()
        if key not in last_print or now - last_print[key] > cooldown:
            last_print[key] = now
            return True
        return False

    while True:
        start_time = time.time()
        now = time.time()
        current_mouse_pos = get_mouse_position()

        # === Cursor Movement ===
        if current_mouse_pos != last_mouse_pos:
            if event_buffer['mouse']:
                if should_print('cursor_real'):
                    print(f"✅ Cursor moved from {last_mouse_pos} to {current_mouse_pos} (real)")
            else:
                if should_print('cursor_scripted'):
                    print(f"⚠️ Cursor moved from {last_mouse_pos} to {current_mouse_pos} (scripted)")
            last_mouse_pos = current_mouse_pos

        # === Clicks ===
        for _, event in list(event_buffer['mouse']):
            if event.type == ecodes.EV_KEY and event.code in [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE]:
                if event.value == 1:
                    if should_print('click_real'):
                        print("✅ Mouse click detected (real)")
        for _, event in list(event_buffer['scripted_mouse']):
            if event.type == X.ButtonPress:
                if event.detail in (1, 2, 3):  # Left, Middle, Right buttons
                    if should_print('click_scripted'):
                        print(f"⚠️ Scripted mouse click detected (button {event.detail})")
                elif event.detail in (4, 5):  # Scroll up/down
                    if should_print('scroll_scripted'):
                        print(f"⚠️ Scripted scroll detected (direction: {'↑' if event.detail == 4 else '↓'})")

        # === Scrolls ===
        had_real_scroll = False
        while scroll_events and now - scroll_events[0][0] <= event_window:
            _, dev_name, code, value = scroll_events.popleft()
            had_real_scroll = True
            if should_print('scroll_real'):
                direction = {
                    ecodes.REL_WHEEL: "↑" if value > 0 else "↓",
                    ecodes.REL_HWHEEL: "→" if value > 0 else "←"
                }.get(code, "?")
                print(f"🖱️ Scroll on {dev_name}: {direction} (passive device)")

        # === Keyboard ===
        if event_buffer['keyboard']:
            if should_print('keyboard_real'):
                print("✅ Keyboard input detected (real)")
        elif event_buffer['scripted_keyboard']:
            if should_print('keyboard_scripted'):
                print("⚠️ Scripted keyboard input detected")

        # === Cleanup ===
        for key in event_buffer:
            while event_buffer[key] and now - event_buffer[key][0][0] > event_window:
                event_buffer[key].popleft()
        time.sleep(max(0, poll_interval - (time.time() - start_time)))

if __name__ == "__main__":
    detect_non_scripted_inputs()

