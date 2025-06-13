
# 🧠 Integrated Employee Activity Tracker

**This script monitors real-time keyboard and mouse input, tracks active applications and visited websites, and integrates with Odoo to report daily activity and detect scripted (anomalous) input behavior.**

---

## 🚀 Features

- ✅ **Detects real vs. scripted keyboard & mouse inputs**
- 🖱️ **Tracks cursor movement, clicks, and scrolls**
- 🌐 **Logs websites visited in Firefox, Chrome, Brave, and Edge**
- 🗂️ **Reports GUI app usage duration**
- 🔒 **Alerts administration via Odoo if automation is detected**
- 📅 **Sends daily summary to** `/api/employee_daily_work`

---

## 📦 Requirements

Install required Python libraries:

```bash
pip install evdev lz4 psutil requests beautifulsoup4 python-xlib
```
Also required system packages:
```bash
sudo apt install xdotool wmctrl libx11-dev libxtst-dev libxrandr-dev
```

# 🔐 Odoo Integration

**The script uses Bearer Token Authentication to communicate with Odoo.**

### ✅ Setup

Ensure your Odoo backend supports the following endpoints:

- `POST /api/script_alert` – for reporting scripted/anomalous input
- `POST /api/employee_daily_work` – for sending daily work summaries

**Token Authentication:**

Place your Odoo authentication token in the following file:




# 🏃 How to Run

Because input detection requires root privileges, and browser data requires access to your user environment, you must preserve the environment when running:

```bash
sudo --preserve-env=HOME,DISPLAY,XAUTHORITY python3 integrated.py
```
✅ This gives the script both root access and access to your user GUI session and browser data.


# 📋 Example Output

✅ Cursor moved (real): (100, 200) -> (105, 210)

⚠️ Scripted keyboard input detected

✅ Mouse click detected (real)

🖱️ Scroll on Logitech USB Mouse: ↑ (real)

**And this display after stopping the script:**

📊 Application usage report:
 - firefox: 1225.80 seconds

🌐 Website usage report:
 - Wikipedia (https://en.wikipedia.org): 450.20 seconds

⚠️ Scripted input was detected during this session.