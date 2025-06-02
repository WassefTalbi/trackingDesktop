import time
import os
from pynput.mouse import Controller, Button
from pynput.keyboard import Controller as KeyboardController, Key

mouse = Controller()
keyboard = KeyboardController()


def simulate_activity():
    print("🎯 Starting simulation of mouse, keyboard, and file operations...")

    try:
        # Create a file (like 'touch' command)
        filename = "simulation_test.txt"
        with open(filename, 'w') as f:
            f.write("This file was created by the simulation script\n")
        print(f"📄 Created file: {filename}")
        time.sleep(0.5)

        # Mouse movements (original logic)
        mouse.move(50, 0)
        print("🖱️ Moved right")
        time.sleep(0.5)

        mouse.move(-50, 0)
        print("🖱️ Moved left")
        time.sleep(0.5)

        # Mouse scroll
        mouse.scroll(0, 2)
        print("🖱️ Scrolled up")
        time.sleep(0.5)

        mouse.scroll(0, -2)
        print("🖱️ Scrolled down")
        time.sleep(0.5)

        # Mouse click
        #mouse.click(Button.left, 1)
        #print("🖱️ Left clicked")
        #time.sleep(0.5)

        # Keyboard input
        keyboard.type("Hello from simulation script!")
        print("⌨️ Typed text")
        time.sleep(0.5)

        # Press Enter key
        keyboard.press(Key.enter)
        keyboard.release(Key.enter)
        print("⌨️ Pressed Enter")
        time.sleep(0.5)

        # Double click
        mouse.click(Button.left, 2)
        print("🖱️ Double clicked")
        time.sleep(0.5)

    except KeyboardInterrupt:
        print("🛑 Simulation interrupted")
    except Exception as e:
        print(f"⚠️ Error occurred: {str(e)}")

    print("✅ Simulation completed")


if __name__ == "__main__":
    while True:
        simulate_activity()

