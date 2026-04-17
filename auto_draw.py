"""
Instagram Auto Draw Tool
========================
Ek image do → tool usse Instagram DM pe automatically draw karta hai
ADB se Android phone ko control karta hai

Requirements:
    pip install opencv-python Pillow numpy
    ADB installed hona chahiye (Android Debug Bridge)

Usage:
    python auto_draw.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
import subprocess
import threading
import time
import os
import sys


# ─────────────────────────────────────────────
# ADB Helper Functions
# ─────────────────────────────────────────────

def _find_adb():
    """Find adb executable — check local platform-tools first."""
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platform-tools", "adb.exe")
    if os.path.isfile(local):
        return local
    return "adb"

ADB_PATH = _find_adb()

def adb(cmd, capture=True):
    """Run an ADB command."""
    full = f'"{ADB_PATH}" {cmd}'
    try:
        result = subprocess.run(
            full, shell=True,
            capture_output=capture,
            text=True, timeout=15
        )
        return result.stdout.strip() if capture else None
    except subprocess.TimeoutExpired:
        return ""


class ADBShell:
    """Persistent ADB shell — ek process, saare commands pipe through.
    Har swipe ke liye naya subprocess nahi spawn hota = 10x fast."""

    def __init__(self):
        self.proc = None

    def open(self):
        if self.proc and self.proc.poll() is None:
            return True
        try:
            self.proc = subprocess.Popen(
                f'"{ADB_PATH}" shell',
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True,
            )
            return True
        except Exception:
            return False

    def cmd(self, command):
        """Send command through persistent shell."""
        for attempt in range(3):
            if not self.proc or self.proc.poll() is not None:
                self.open()
                import time; time.sleep(0.3)
            try:
                self.proc.stdin.write((command + "\n").encode())
                self.proc.stdin.flush()
                return
            except (BrokenPipeError, OSError):
                self.proc = None
                if attempt == 2:
                    # Fallback: run as individual adb command
                    subprocess.run(
                        f'"{ADB_PATH}" shell {command}',
                        shell=True, timeout=10,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

    def swipe(self, x1, y1, x2, y2, duration_ms=100):
        self.cmd(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {duration_ms}")

    def tap(self, x, y):
        self.cmd(f"input tap {int(x)} {int(y)}")

    def close(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception:
                pass
            self.proc = None


# Global persistent shell (used during drawing)
_adb_shell = ADBShell()


def get_connected_devices():
    out = adb("devices")
    lines = out.strip().split("\n")[1:]
    devices = [l.split("\t")[0] for l in lines if "device" in l and "offline" not in l]
    return devices


def get_screen_size():
    out = adb("shell wm size")
    try:
        size = out.split(":")[-1].strip()
        w, h = size.split("x")
        return int(w), int(h)
    except:
        return 1080, 1920


def tap(x, y):
    adb(f"shell input tap {int(x)} {int(y)}", capture=False)


def swipe(x1, y1, x2, y2, duration_ms=150):
    adb(f"shell input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {duration_ms}", capture=False)


# ─────────────────────────────────────────────
# Image Processing — Contour-based with Curves
# ─────────────────────────────────────────────

def _adaptive_sample(points, max_points=200):
    """
    Hybrid sampling: uniform base + extra points on curves.
    Ensures no gaps in straight sections while preserving curves.
    """
    if len(points) <= max_points:
        return points

    # Step 1: Uniform base — keep every Nth point (ensures coverage)
    uniform_budget = max_points * 2 // 3  # 2/3 budget for uniform
    curve_budget = max_points - uniform_budget  # 1/3 for curves

    step = max(1, len(points) // uniform_budget)
    keep = set(range(0, len(points), step))
    keep.add(0)
    keep.add(len(points) - 1)

    # Step 2: Add high-curvature points from remaining budget
    if curve_budget > 0:
        curvatures = [0.0]
        for i in range(1, len(points) - 1):
            x0, y0 = points[i - 1]
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            dx1, dy1 = x1 - x0, y1 - y0
            dx2, dy2 = x2 - x1, y2 - y1
            cross = abs(dx1 * dy2 - dy1 * dx2)
            curvatures.append(cross)
        curvatures.append(0.0)

        ranked = sorted(range(len(points)), key=lambda i: curvatures[i], reverse=True)
        for idx in ranked:
            if len(keep) >= max_points:
                break
            keep.add(idx)

    sampled = [points[i] for i in sorted(keep)]
    return sampled


def _catmull_rom(p0, p1, p2, p3, num_pts=4):
    """Catmull-Rom spline interpolation between p1 and p2."""
    pts = []
    for t in np.linspace(0, 1, num_pts, endpoint=False):
        t2 = t * t
        t3 = t2 * t
        x = 0.5 * ((2 * p1[0]) +
                    (-p0[0] + p2[0]) * t +
                    (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                    (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
        y = 0.5 * ((2 * p1[1]) +
                    (-p0[1] + p2[1]) * t +
                    (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                    (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
        pts.append((x, y))
    return pts


def _interpolate_contour(points, smoothness=3):
    """Catmull-Rom se contour points ke beech smooth curves generate karo."""
    if len(points) < 3:
        return points

    result = []
    pts = list(points)
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[max(i - 1, 0)]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[min(i + 2, n - 1)]
        interp = _catmull_rom(p0, p1, p2, p3, num_pts=smoothness)
        result.extend(interp)
    result.append(pts[-1])
    return result


def extract_contours(image_path, threshold=80, smooth=3, min_contour_len=5,
                     use_curves=True, curve_smoothness=3, max_pts=200):
    """
    Image se contours extract karo with optional curve interpolation.
    Returns list of contours (each contour = list of (x, y) normalized 0.0–1.0),
    and edge image for preview.
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError("Image load nahi hui.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Gaussian blur for smoothing
    ksize = smooth * 2 + 1
    if ksize >= 3:
        gray = cv2.GaussianBlur(gray, (ksize, ksize), 0)

    # Edge detection
    edges = cv2.Canny(gray, threshold, threshold * 2)

    # Dilate slightly for better strokes
    kernel = np.ones((2, 2), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)

    # CHAIN_APPROX_NONE — ALL contour points preserve karo (curves ke liye zaroori)
    contours_raw, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

    contours = []
    for cnt in contours_raw:
        if len(cnt) < min_contour_len:
            continue

        # Normalize raw points to 0.0–1.0
        raw_pts = [(float(p[0][0]) / w, float(p[0][1]) / h) for p in cnt]

        # Adaptive sample — keep more points on curves, less on straight
        sampled = _adaptive_sample(raw_pts, max_points=max_pts)

        if len(sampled) < 2:
            continue

        # Catmull-Rom interpolation for smooth curves
        if use_curves and len(sampled) >= 3:
            sampled = _interpolate_contour(sampled, smoothness=max(2, curve_smoothness))

        contours.append(sampled)

    # Sort: bigger contours first
    contours.sort(key=lambda c: len(c), reverse=True)

    return contours, edges


# ─────────────────────────────────────────────
# Main GUI Application
# ─────────────────────────────────────────────

class AutoDrawApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Instagram Auto Draw")
        self.geometry("780x680")
        self.resizable(True, True)
        self.configure(bg="#0F0F0F")

        # Cleanup on window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # State
        self.image_path = None
        self.contours = []
        self.edge_preview = None
        self.is_drawing = False
        self.draw_thread = None

        # Default draw region (will be calibrated)
        # These are fractions of screen: (left%, top%, right%, bottom%)
        self.region = (0.05, 0.15, 0.95, 0.85)

        self._build_ui()

    # ── UI Layout ──────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg="#0F0F0F")
        hdr.pack(fill="x", padx=20, pady=(20, 0))

        tk.Label(
            hdr, text="Instagram Auto Draw",
            font=("SF Pro Display", 22, "bold"),
            fg="#FFFFFF", bg="#0F0F0F"
        ).pack(side="left")

        self.status_dot = tk.Label(hdr, text="●", font=("Arial", 14),
                                   fg="#FF4444", bg="#0F0F0F")
        self.status_dot.pack(side="right", padx=4)
        self.status_lbl = tk.Label(hdr, text="Not connected",
                                   font=("SF Pro Text", 12),
                                   fg="#888888", bg="#0F0F0F")
        self.status_lbl.pack(side="right")

        # Separator
        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=20, pady=12)

        # Main columns
        cols = tk.Frame(self, bg="#0F0F0F")
        cols.pack(fill="both", expand=True, padx=20, pady=0)

        self._build_left(cols)
        self._build_right(cols)

        # Bottom bar
        self._build_bottom()

    def _build_left(self, parent):
        left = tk.Frame(parent, bg="#0F0F0F", width=340)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # ── Device section ──
        self._section(left, "1  Device")

        dev_row = tk.Frame(left, bg="#0F0F0F")
        dev_row.pack(fill="x", pady=(0, 8))

        self.device_var = tk.StringVar(value="No device found")
        self.device_menu = ttk.Combobox(dev_row, textvariable=self.device_var,
                                        state="readonly", width=22)
        self.device_menu.pack(side="left")

        tk.Button(dev_row, text="Refresh", command=self._refresh_devices,
                  bg="#1E1E1E", fg="#CCCCCC", relief="flat",
                  padx=10, pady=4, cursor="hand2"
                  ).pack(side="left", padx=8)

        tk.Button(dev_row, text="Connect ↗", command=self._connect_device,
                  bg="#E1306C", fg="#FFFFFF", relief="flat",
                  padx=12, pady=4, cursor="hand2",
                  font=("SF Pro Text", 11, "bold")
                  ).pack(side="left")

        # ── Image section ──
        self._section(left, "2  Image")

        img_row = tk.Frame(left, bg="#0F0F0F")
        img_row.pack(fill="x", pady=(0, 8))

        tk.Button(img_row, text="Upload Image",
                  command=self._upload_image,
                  bg="#1E1E1E", fg="#CCCCCC", relief="flat",
                  padx=12, pady=5, cursor="hand2"
                  ).pack(side="left")

        self.img_name_lbl = tk.Label(img_row, text="No image selected",
                                     font=("SF Pro Text", 11),
                                     fg="#666666", bg="#0F0F0F")
        self.img_name_lbl.pack(side="left", padx=10)

        # ── Settings section ──
        self._section(left, "3  Settings")

        # Edge threshold
        self._slider_row(left, "Edge Threshold",
                         "thresh_var", 20, 200, 80,
                         lambda v: self._update_preview())

        # Smoothing
        self._slider_row(left, "Smoothing",
                         "smooth_var", 0, 10, 3,
                         lambda v: self._update_preview())

        # Curve interpolation checkbox
        curve_row = tk.Frame(left, bg="#0F0F0F")
        curve_row.pack(fill="x", pady=3)
        self.curve_var = tk.BooleanVar(value=True)
        tk.Checkbutton(curve_row, text="Curve Interpolation",
                       variable=self.curve_var,
                       bg="#0F0F0F", fg="#AAAAAA",
                       selectcolor="#1E1E1E",
                       activebackground="#0F0F0F",
                       activeforeground="#FFFFFF",
                       font=("SF Pro Text", 11),
                       command=self._update_preview
                       ).pack(side="left")

        # Curve smoothness
        self._slider_row(left, "Curve Smoothness",
                         "curve_smooth_var", 2, 8, 3,
                         lambda v: self._update_preview())

        # Max points per stroke
        self._slider_row(left, "Max Points/Stroke",
                         "max_pts_var", 50, 1000, 400,
                         lambda v: self._update_preview())

        # Speed
        self._slider_row(left, "Draw Speed (ms/swipe)",
                         "speed_var", 30, 300, 80)

        # Draw region
        self._section(left, "4  Draw Region  (% of screen)")
        grid = tk.Frame(left, bg="#0F0F0F")
        grid.pack(fill="x")

        labels = ["Left %", "Top %", "Right %", "Bottom %"]
        defaults = [5, 15, 95, 85]
        self.region_vars = []
        for i, (lbl, val) in enumerate(zip(labels, defaults)):
            row = tk.Frame(grid, bg="#0F0F0F")
            row.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 20), pady=2)
            tk.Label(row, text=lbl, font=("SF Pro Text", 11),
                     fg="#888888", bg="#0F0F0F", width=8, anchor="w").pack(side="left")
            v = tk.IntVar(value=val)
            self.region_vars.append(v)
            tk.Spinbox(row, from_=0, to=100, textvariable=v,
                       width=5, bg="#1E1E1E", fg="#FFFFFF",
                       insertbackground="#FFFFFF",
                       relief="flat"
                       ).pack(side="left")

    def _build_right(self, parent):
        right = tk.Frame(parent, bg="#0F0F0F", width=360)
        right.pack(side="left", fill="both", expand=True)

        self._section(right, "Preview")

        self.canvas = tk.Canvas(right, width=320, height=320,
                                bg="#1A1A1A", highlightthickness=1,
                                highlightbackground="#333333")
        self.canvas.pack(pady=(0, 10))

        self.preview_lbl = tk.Label(right,
                                    text="Upload an image to see edge preview",
                                    font=("SF Pro Text", 11),
                                    fg="#555555", bg="#0F0F0F")
        self.preview_lbl.pack()

        # Log
        self._section(right, "Log")
        self.log_text = tk.Text(right, height=8, bg="#1A1A1A",
                                fg="#00FF88", font=("Menlo", 10),
                                relief="flat", state="disabled",
                                insertbackground="#00FF88")
        self.log_text.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(right, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)

    def _build_bottom(self):
        bar = tk.Frame(self, bg="#0F0F0F")
        bar.pack(fill="x", padx=20, pady=15)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=20, pady=(0, 12))

        self.draw_btn = tk.Button(
            bar, text="▶  Start Drawing",
            command=self._start_drawing,
            bg="#E1306C", fg="#FFFFFF",
            font=("SF Pro Text", 13, "bold"),
            relief="flat", padx=24, pady=10,
            cursor="hand2", state="disabled"
        )
        self.draw_btn.pack(side="left")

        tk.Button(
            bar, text="■  Stop",
            command=self._stop_drawing,
            bg="#333333", fg="#FFFFFF",
            font=("SF Pro Text", 13),
            relief="flat", padx=16, pady=10,
            cursor="hand2"
        ).pack(side="left", padx=10)

        self.progress = ttk.Progressbar(bar, length=200, mode="determinate")
        self.progress.pack(side="left", padx=10)

        self.pct_lbl = tk.Label(bar, text="0%",
                                font=("SF Pro Text", 11),
                                fg="#888888", bg="#0F0F0F")
        self.pct_lbl.pack(side="left")

    # ── Section header ─────────────────────────

    def _section(self, parent, title):
        f = tk.Frame(parent, bg="#0F0F0F")
        f.pack(fill="x", pady=(14, 6))
        tk.Label(f, text=title.upper(),
                 font=("SF Pro Text", 10, "bold"),
                 fg="#E1306C", bg="#0F0F0F").pack(side="left")
        tk.Frame(f, bg="#2A2A2A", height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

    def _slider_row(self, parent, label, attr, mn, mx, default, cmd=None):
        row = tk.Frame(parent, bg="#0F0F0F")
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, font=("SF Pro Text", 11),
                 fg="#AAAAAA", bg="#0F0F0F", width=18, anchor="w"
                 ).pack(side="left")
        v = tk.IntVar(value=default)
        setattr(self, attr, v)
        val_lbl = tk.Label(row, textvariable=v,
                           font=("SF Pro Mono", 11),
                           fg="#FFFFFF", bg="#0F0F0F", width=4)
        val_lbl.pack(side="right")
        s = tk.Scale(row, from_=mn, to=mx, variable=v,
                     orient="horizontal", bg="#0F0F0F",
                     fg="#FFFFFF", troughcolor="#2A2A2A",
                     highlightthickness=0, showvalue=False,
                     command=cmd)
        s.pack(side="left", fill="x", expand=True)

    # ── Actions ────────────────────────────────

    def _refresh_devices(self):
        self._log("ADB devices dhundh raha hai...")
        devices = get_connected_devices()
        if devices:
            self.device_menu["values"] = devices
            self.device_var.set(devices[0])
            self._log(f"Mila: {', '.join(devices)}")
        else:
            self.device_menu["values"] = []
            self.device_var.set("No device found")
            self._log("Koi device nahi mila. USB debugging on hai?")

    def _connect_device(self):
        device = self.device_var.get()
        if "No device" in device or not device:
            messagebox.showwarning("Device", "Pehle device select karo.")
            return
        out = adb("get-state")
        if "device" in out:
            self.status_dot.config(fg="#00FF88")
            self.status_lbl.config(text=f"Connected: {device}", fg="#00FF88")
            self._log(f"✓ Connected to {device}")
            if self.image_path:
                self.draw_btn.config(state="normal")
        else:
            self.status_dot.config(fg="#FF4444")
            self.status_lbl.config(text="Connection failed", fg="#FF4444")
            self._log("✗ Connection fail. ADB aur USB debugging check karo.")

    def _upload_image(self):
        path = filedialog.askopenfilename(
            title="Image select karo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp")]
        )
        if not path:
            return
        self.image_path = path
        name = os.path.basename(path)
        self.img_name_lbl.config(text=name, fg="#FFFFFF")
        self._log(f"Image loaded: {name}")
        self._update_preview()
        if "Connected" in self.status_lbl.cget("text"):
            self.draw_btn.config(state="normal")

    def _update_preview(self, *_):
        if not self.image_path:
            return
        try:
            thresh = self.thresh_var.get()
            smooth = self.smooth_var.get()
            use_curves = self.curve_var.get()
            curve_sm = self.curve_smooth_var.get()
            max_pts = self.max_pts_var.get()
            contours, edges = extract_contours(
                self.image_path,
                threshold=thresh,
                smooth=smooth,
                use_curves=use_curves,
                curve_smoothness=curve_sm,
                max_pts=max_pts,
            )
            total_pts = sum(len(c) for c in contours)
            # Show edges on canvas
            edge_img = Image.fromarray(edges).resize((320, 320))
            self.edge_preview = ImageTk.PhotoImage(edge_img)
            self.canvas.create_image(0, 0, anchor="nw", image=self.edge_preview)
            self.preview_lbl.config(
                text=f"{len(contours)} strokes, {total_pts} points",
                fg="#888888")
        except Exception as e:
            self._log(f"Preview error: {e}")

    def _start_drawing(self):
        if not self.image_path:
            messagebox.showwarning("Image", "Pehle image upload karo.")
            return
        if self.is_drawing:
            return

        # Extract contours
        try:
            thresh = self.thresh_var.get()
            smooth = self.smooth_var.get()
            use_curves = self.curve_var.get()
            curve_sm = self.curve_smooth_var.get()
            max_pts = self.max_pts_var.get()
            self.contours, _ = extract_contours(
                self.image_path,
                threshold=thresh,
                smooth=smooth,
                use_curves=use_curves,
                curve_smoothness=curve_sm,
                max_pts=max_pts,
            )
            total_pts = sum(len(c) for c in self.contours)
            self._log(f"Contours ready: {len(self.contours)} strokes, {total_pts} points")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        if not self.contours:
            messagebox.showwarning("No strokes", "Koi strokes nahi mili. Threshold adjust karo.")
            return

        # Build draw region from spinboxes
        sw, sh = get_screen_size()
        l, t, r, b = [v.get() / 100.0 for v in self.region_vars]
        self.draw_region = (l * sw, t * sh, r * sw, b * sh)
        self._log(f"Screen: {sw}x{sh}, Draw region: {self.draw_region}")

        self.is_drawing = True
        self.draw_btn.config(state="disabled")
        self.draw_thread = threading.Thread(target=self._draw_worker, daemon=True)
        self.draw_thread.start()

    def _stop_drawing(self):
        self.is_drawing = False
        _adb_shell.close()  # Kill shell immediately — buffered commands bhi band
        self._log("Drawing roka gaya.")
        self.draw_btn.config(state="normal")

    def _draw_worker(self):
        """Background thread — persistent ADB shell se fast drawing."""
        speed = self.speed_var.get()
        region = self.draw_region
        x1r, y1r, x2r, y2r = region

        total_contours = len(self.contours)
        total_pts = sum(len(c) for c in self.contours)
        done_pts = 0

        # Open persistent ADB shell — no subprocess spawn per swipe
        if not _adb_shell.open():
            self._log("✗ ADB shell open nahi hua!")
            self.after(0, self._drawing_done)
            return

        self._log("Drawing shuru ho rahi hai 3 sec mein...")
        self._log("Instagram DM pe Draw mode open karo!")
        time.sleep(3)

        # Precompute all screen coordinates for speed
        def to_screen(nx, ny):
            return int(x1r + nx * (x2r - x1r)), int(y1r + ny * (y2r - y1r))

        # Min delay between swipes (persistent shell is fast, so we need some pacing)
        swipe_delay = speed / 2000.0  # much less delay needed with persistent shell
        swipe_dur = max(speed, 50)

        for ci, contour in enumerate(self.contours):
            if not self.is_drawing:
                break

            if len(contour) < 2:
                done_pts += len(contour)
                continue

            # Convert all points to screen coords
            screen_pts = [to_screen(nx, ny) for nx, ny in contour]

            # Merge nearby points: skip swipes smaller than 3px (invisible)
            merged = [screen_pts[0]]
            for pt in screen_pts[1:]:
                dx = pt[0] - merged[-1][0]
                dy = pt[1] - merged[-1][1]
                if dx * dx + dy * dy >= 4:  # 2px threshold
                    merged.append(pt)
            if len(merged) < 2:
                done_pts += len(contour)
                continue

            # Draw merged points via persistent shell
            for j in range(len(merged) - 1):
                if not self.is_drawing:
                    break
                sx1, sy1 = merged[j]
                sx2, sy2 = merged[j + 1]
                _adb_shell.swipe(sx1, sy1, sx2, sy2, duration_ms=swipe_dur)
                time.sleep(swipe_delay)

            done_pts += len(contour)
            pct = min(int(done_pts / total_pts * 100), 100)
            self.after(0, self._update_progress, pct)

            # Tiny pause between contours (pen lift)
            time.sleep(0.02)

            if (ci + 1) % 30 == 0:
                self._log(f"  {ci + 1}/{total_contours} strokes done...")

        _adb_shell.close()
        self.after(0, self._drawing_done)

    def _update_progress(self, pct):
        self.progress["value"] = pct
        self.pct_lbl.config(text=f"{pct}%")

    def _drawing_done(self):
        self.is_drawing = False
        self.draw_btn.config(state="normal")
        self._log("✓ Drawing complete!")
        messagebox.showinfo("Done!", "Drawing complete ho gayi!\nAbhi send kar do DM mein.")

    def _log(self, msg):
        def _write():
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"› {msg}\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.after(0, _write)

    def _on_close(self):
        """Window close pe sab kuch clean band karo."""
        self.is_drawing = False
        _adb_shell.close()
        self.destroy()


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = AutoDrawApp()
    app.mainloop()
