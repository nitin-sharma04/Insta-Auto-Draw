# 🎨 Instagram Auto Draw

Automatically draw any image on Instagram DM's drawing canvas using your Android phone.

Upload an image → the tool converts it to strokes → draws it on Instagram via ADB.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Features

- **Contour-based drawing** — uses OpenCV edge detection + contour extraction for accurate strokes
- **Catmull-Rom curve interpolation** — smooth, natural-looking curves instead of jagged lines
- **Adaptive sampling** — hybrid uniform + curvature-based point selection for optimal detail
- **Persistent ADB shell** — fast drawing with minimal latency (no subprocess spawn per stroke)
- **Real-time edge preview** — see exactly what will be drawn before starting
- **Dark themed GUI** — clean Tkinter interface with live settings

---

## 📋 Requirements

- **Python 3.8+**
- **Android phone** with USB Debugging enabled
- **USB cable** (data-capable, not charge-only)
- **ADB (Android Debug Bridge)** — see setup below

### Python Packages

```bash
pip install opencv-python Pillow numpy
```

---

## 🔧 Setup

### 1. Install ADB

**Windows:**
1. Download [Android Platform Tools](https://developer.android.com/studio/releases/platform-tools)
2. Extract the zip
3. Place the `platform-tools` folder in the same directory as `auto_draw.py` — the tool detects it automatically

**macOS:**
```bash
brew install android-platform-tools
```

**Linux:**
```bash
sudo apt install adb
```

### 2. Enable USB Debugging on Phone

1. Go to **Settings → About Phone**
2. Tap **Build Number** 7 times → Developer Options will be unlocked
3. Go to **Settings → Developer Options**
4. Enable **USB Debugging**
5. *(Xiaomi/MIUI/HyperOS only)* Also enable **USB Debugging (Security settings)** — this is required for input injection on Xiaomi devices

### 3. Connect Phone to PC

1. Connect via USB cable
2. On the phone, tap **Allow** on the "Allow USB debugging?" popup
3. Set USB mode to **File Transfer (MTP)**

### 4. Verify Connection

```bash
adb devices
```

You should see your device with status `device` (not `offline` or `unauthorized`).

---

## 🚀 Usage

### Step 1 — Launch the tool

```bash
python auto_draw.py
```

### Step 2 — Connect device

- Click **Refresh** to detect your phone
- Select it from the dropdown
- Click **Connect** — status turns green ✓

### Step 3 — Upload image

- Click **Upload Image** and select any image (PNG, JPG, BMP, WebP)
- The edge preview appears on the right — adjust **Edge Threshold** to control detail level
- **Best results:** use line art / sketch images with clear black lines on white background

### Step 4 — Prepare Instagram

1. Open **Instagram** on your phone
2. Go to a **DM conversation**
3. Tap the **+** button → select **Draw**
4. The drawing canvas should be open and ready

### Step 5 — Start drawing

- Click **▶ Start Drawing** in the tool
- You get a **3-second countdown** — make sure Instagram's draw canvas is visible
- The tool draws automatically stroke by stroke
- Click **■ Stop** anytime to cancel

---

## ⚙️ Settings

| Setting | Range | Description |
|---|---|---|
| **Edge Threshold** | 20–200 | Controls edge detection sensitivity. Lower = more detail, Higher = only strong edges. Sweet spot: 60–100 |
| **Smoothing** | 0–10 | Gaussian blur before edge detection. Higher = smoother, less noise |
| **Curve Interpolation** | On/Off | Enables Catmull-Rom spline smoothing for natural curves |
| **Curve Smoothness** | 2–8 | Number of interpolation points between control points |
| **Max Points/Stroke** | 50–1000 | Maximum points per contour. Higher = more detail but slower |
| **Draw Speed (ms)** | 30–300 | Time per swipe in milliseconds. Lower = faster drawing |
| **Draw Region (%)** | 0–100 | Left, Top, Right, Bottom — defines the drawing area on screen as percentage |

### Recommended Settings

| Use Case | Threshold | Max Points | Speed |
|---|---|---|---|
| Simple logo | 80–120 | 200–300 | 50–80ms |
| Detailed sketch | 40–70 | 400–600 | 80–120ms |
| Portrait/complex | 30–60 | 600–1000 | 100–150ms |

---

## 🗂️ Project Structure

```
insta_auto_draw/
├── auto_draw.py        # Main application (GUI + image processing + ADB control)
├── platform-tools/     # ADB binaries (download and place here)
│   └── adb.exe
└── README.md
```

---

## ❗ Troubleshooting

### Device not detected
- Make sure USB cable supports data transfer (not charge-only)
- Accept "Allow USB debugging?" popup on phone
- Run `adb devices` in terminal — device should show as `device`
- Try `adb kill-server` then `adb devices` to restart ADB

### Device shows as "offline"
- Unlock your phone screen
- Reconnect the USB cable
- Re-accept the USB debugging authorization popup
- Set USB mode to File Transfer (MTP)

### Device shows as "unauthorized"
- Check your phone for the USB debugging permission popup and tap **Allow**
- Check "Always allow from this computer" for convenience

### Drawing not working / permission error
- **Xiaomi/MIUI/HyperOS:** Enable **Settings → Developer Options → USB Debugging (Security settings)**
- This is required for `input` command injection on Android 12+ Xiaomi devices

### Drawing is inaccurate
- Use clear line art images (black lines on white background)
- Adjust **Edge Threshold** — use the preview to check before drawing
- Adjust **Draw Region %** to match Instagram's canvas area on your screen
- Increase **Max Points/Stroke** for more detail

### Drawing is too slow
- Reduce **Max Points/Stroke**
- Lower **Draw Speed** value (ms per swipe)
- Use a simpler image with fewer strokes

---

## 📝 How It Works

1. **Edge Detection** — OpenCV's Canny edge detector finds edges in your image
2. **Contour Extraction** — `findContours` with `CHAIN_APPROX_NONE` preserves all contour points
3. **Adaptive Sampling** — Hybrid algorithm: 2/3 uniform sampling + 1/3 curvature-based for curves
4. **Curve Smoothing** — Optional Catmull-Rom spline interpolation for smooth natural curves
5. **ADB Drawing** — Persistent ADB shell sends `input swipe` commands to draw each stroke
6. **Point Merging** — Skips sub-2px movements to reduce redundant commands

---

## ⚠️ Disclaimer

This tool is for **educational and personal use only**. Use it responsibly and respect Instagram's Terms of Service. The author is not responsible for any misuse or account actions resulting from the use of this tool.

---

## 📄 License

MIT License — free to use, modify, and distribute.
