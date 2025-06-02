import time
from collections import deque
from evdev import InputDevice, categorize, ecodes, list_devices
from Xlib import display, X
from Xlib.ext import record
from Xlib.protocol import rq
import threading

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

def record_keyboard_events(event_buffer):
    local_dpy = display.Display()
    record_dpy = display.Display()

    def callback(reply):
        if reply.category != record.FromServer:
            return
        if reply.client_swapped:
            return
        if not len(reply.data) or reply.data[0] < 2:
            return

        data = reply.data
        while len(data):
            event, data = rq.EventField(None).parse_binary_value(data, record_dpy.display, None, None)
            if event.type == X.KeyPress or event.type == X.KeyRelease:
                event_buffer['scripted_keyboard'].append((time.time(), event))

    ctx = record_dpy.record_create_context(
        0,
        [record.AllClients],
        [{
            'core_requests': (0, 0),
            'core_replies': (0, 0),
            'ext_requests': (0, 0, 0, 0),
            'ext_replies': (0, 0, 0, 0),
            'delivered_events': (X.KeyPress, X.KeyRelease),
            'device_events': (X.KeyPress, X.KeyRelease),
            'errors': (0, 0),
            'client_started': False,
            'client_died': False,
        }]
    )

    record_dpy.record_enable_context(ctx, callback)
    record_dpy.record_free_context(ctx)

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
        'scripted_keyboard': deque()
    }

    threading.Thread(target=monitor_device, args=(mouse_device, event_buffer, 'mouse'), daemon=True).start()
    threading.Thread(target=monitor_device, args=(keyboard_device, event_buffer, 'keyboard'), daemon=True).start()
    threading.Thread(target=record_keyboard_events, args=(event_buffer,), daemon=True).start()

    last_mouse_pos = get_mouse_position()

    last_print = {
        'mouse_move': None,
        'mouse_click': None,
        'mouse_scroll': None,
        'keyboard_real': None,
        'keyboard_scripted': None,
        'cursor_scripted_move': None,
    }

    def should_print(key, cooldown=0.3):
        now = time.time()
        last = last_print.get(key)
        if last is None or now - last > cooldown:
            last_print[key] = now
            return True
        return False

    while True:
        start_time = time.time()
        now = time.time()

        for key in ['mouse', 'keyboard', 'scripted_keyboard']:
            while event_buffer[key] and now - event_buffer[key][0][0] > event_window:
                event_buffer[key].popleft()

        current_mouse_pos = get_mouse_position()

        if current_mouse_pos != last_mouse_pos:
            if event_buffer['mouse']:
                if should_print('mouse_move'):
                    print(f"✅ Cursor moved from {last_mouse_pos} to {current_mouse_pos} (real)")
            else:
                if should_print('cursor_scripted_move'):
                    print(f"⚠️ Cursor moved from {last_mouse_pos} to {current_mouse_pos} (scripted)")
            last_mouse_pos = current_mouse_pos
        for _, event in list(event_buffer['mouse']):
            if event.type == ecodes.EV_KEY and event.code in [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE]:
                if event.value == 1 and should_print('mouse_click'):
                    print("✅ Mouse click detected (real)")
            elif event.type == ecodes.EV_REL and event.code == ecodes.REL_WHEEL:
                if should_print('mouse_scroll'):
                    print("✅ Mouse scroll detected (real)")

        if not event_buffer['mouse']:
            pos_now = get_mouse_position()
            if pos_now != last_mouse_pos and should_print('cursor_scripted_move'):
                print("⚠️ Cursor movement or activity detected without hardware event (scripted)")
        real_kbd = len(event_buffer['keyboard']) > 0
        scripted_kbd = len(event_buffer['scripted_keyboard']) > 0
        if real_kbd:
            if should_print('keyboard_real'):
                print("✅ Keyboard input detected (real)")
        elif scripted_kbd:
            if should_print('keyboard_scripted'):
                print("⚠️ Scripted keyboard input detected")

        elapsed = time.time() - start_time
        time.sleep(max(0, poll_interval - elapsed))


if __name__ == "__main__":
    detect_non_scripted_inputs()
