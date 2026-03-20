"""
Runway Surveillance Rover — Autonomous Mode
============================================
Phase 1 (now):   Laptop webcam, no ESP32-CAM yet
Phase 2 (later): Swap STREAM = 0 for ESP32-CAM URL

Detection logic:
  - No debris  → rover moves FORWARD
  - Debris found → rover STOPS + green box on screen + SMS alert with GPS coords
  - Debris clears → rover resumes patrolling
"""

import cv2
import requests
import serial
import time
import threading
from ultralytics import YOLO
from datetime import datetime

# ═══════════════════════════════════════════════════════
#  CONFIGURATION — edit these before running
# ═══════════════════════════════════════════════════════

# --- Camera ---
# Phase 1 (now):   use laptop webcam
STREAM = 0
# Phase 2 (later): uncomment and set your ESP32-CAM IP
# STREAM = "http://192.168.1.42:81/stream"

# --- Rover motor ESP32 ---
# Set to None to run ML-only test without rover connected
ROVER_IP = "192.168.1.50"       # ESP32 #2 IP from Serial monitor
# ROVER_IP = None                # uncomment to disable motor commands

# --- GSM module (SIM800L) ---
# Connect SIM800L to your PC via USB-TTL for now
# Later move to ESP32 #2 via UART
GSM_PORT     = "COM5"           # Windows: COM5 etc. Linux: /dev/ttyUSB0
GSM_BAUDRATE = 9600
PHONE_NUMBER = "+91XXXXXXXXXX"  # destination phone number with country code

# --- NEO6M GPS ---
GPS_PORT     = "COM6"           # separate USB-TTL for GPS module
GPS_BAUDRATE = 9600

# --- Detection ---
CONFIDENCE       = 0.45         # 0.0–1.0, lower = more sensitive
ALERT_COOLDOWN   = 5            # seconds between repeated SMS alerts for same debris
MODEL_PATH       = "yolov8n.pt" # downloads automatically on first run

# ═══════════════════════════════════════════════════════
#  GPS READER (runs in background thread)
# ═══════════════════════════════════════════════════════

class GPSReader:
    def __init__(self):
        self.lat  = None
        self.lon  = None
        self.lock = threading.Lock()
        self._running = False

    def start(self):
        try:
            self.ser = serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1)
            self._running = True
            t = threading.Thread(target=self._read_loop, daemon=True)
            t.start()
            print(f"[GPS] Connected on {GPS_PORT}")
        except Exception as e:
            print(f"[GPS] Not connected ({e}) — using simulated coords for testing")
            self.lat = 19.0760   # Mumbai lat (placeholder for testing)
            self.lon = 72.8777   # Mumbai lon

    def _read_loop(self):
        while self._running:
            try:
                line = self.ser.readline().decode("ascii", errors="ignore").strip()
                if line.startswith("$GPRMC") or line.startswith("$GNRMC"):
                    parts = line.split(",")
                    if len(parts) > 5 and parts[2] == "A":   # A = valid fix
                        raw_lat = parts[3]
                        raw_lon = parts[5]
                        lat_dir = parts[4]
                        lon_dir = parts[6]
                        lat = self._nmea_to_decimal(raw_lat, lat_dir)
                        lon = self._nmea_to_decimal(raw_lon, lon_dir)
                        with self.lock:
                            self.lat = lat
                            self.lon = lon
            except Exception:
                pass

    def _nmea_to_decimal(self, raw, direction):
        """Convert NMEA DDDMM.MMMM format to decimal degrees."""
        if not raw:
            return None
        dot = raw.index(".")
        deg = float(raw[:dot - 2])
        mins = float(raw[dot - 2:]) / 60.0
        decimal = deg + mins
        if direction in ("S", "W"):
            decimal = -decimal
        return round(decimal, 7)

    def get_coords(self):
        with self.lock:
            return self.lat, self.lon

    def stop(self):
        self._running = False


# ═══════════════════════════════════════════════════════
#  GSM ALERT SENDER
# ═══════════════════════════════════════════════════════

class GSMAlert:
    def __init__(self):
        self.ser     = None
        self.ready   = False

    def connect(self):
        try:
            self.ser = serial.Serial(GSM_PORT, GSM_BAUDRATE, timeout=3)
            time.sleep(2)
            self.ser.write(b"AT\r")
            time.sleep(1)
            resp = self.ser.read(self.ser.in_waiting).decode(errors="ignore")
            if "OK" in resp:
                self.ser.write(b'AT+CMGF=1\r')   # set SMS text mode
                time.sleep(1)
                self.ready = True
                print(f"[GSM] SIM800L connected on {GSM_PORT}")
            else:
                print("[GSM] SIM800L not responding — SMS disabled")
        except Exception as e:
            print(f"[GSM] Not connected ({e}) — SMS disabled (will print alerts to console)")

    def send_sms(self, message):
        if not self.ready or self.ser is None:
            # Fallback: just print when GSM not connected (useful during testing)
            print(f"[GSM ALERT — no module] {message}")
            return
        try:
            self.ser.write(f'AT+CMGS="{PHONE_NUMBER}"\r'.encode())
            time.sleep(1)
            self.ser.write(message.encode() + b"\x1A")  # 0x1A = Ctrl+Z sends SMS
            time.sleep(3)
            resp = self.ser.read(self.ser.in_waiting).decode(errors="ignore")
            if "+CMGS" in resp:
                print(f"[GSM] SMS sent: {message[:40]}...")
            else:
                print(f"[GSM] SMS may have failed. Response: {resp}")
        except Exception as e:
            print(f"[GSM] Send error: {e}")


# ═══════════════════════════════════════════════════════
#  ROVER COMMAND SENDER
# ═══════════════════════════════════════════════════════

def send_rover_cmd(action):
    """Send HTTP command to ESP32 motor controller."""
    if ROVER_IP is None:
        print(f"[ROVER] (simulated) {action}")
        return
    try:
        requests.get(f"http://{ROVER_IP}/{action}", timeout=0.4)
    except Exception:
        pass   # don't crash on WiFi blip


# ═══════════════════════════════════════════════════════
#  MAIN SURVEILLANCE LOOP
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 55)
    print("  Runway Surveillance Rover — Autonomous Mode")
    print("=" * 55)

    # Load model
    print("[ML] Loading YOLOv8 model...")
    model = YOLO(MODEL_PATH)
    print("[ML] Model ready")

    # Start GPS
    gps = GPSReader()
    gps.start()

    # Connect GSM
    gsm = GSMAlert()
    gsm.connect()

    # Open camera / stream
    print(f"[CAM] Opening {'webcam' if STREAM == 0 else STREAM}...")
    cap = cv2.VideoCapture(STREAM)
    if not cap.isOpened():
        print("[CAM] ERROR: Cannot open camera")
        return

    # State
    rover_moving     = False
    last_alert_time  = 0
    detection_log    = []

    # Start rover patrolling
    send_rover_cmd("forward")
    rover_moving = True
    print("[ROVER] Patrol started — moving forward")
    print("Press Q to quit, S to manually stop, G to go\n")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            if STREAM != 0:
                cap = cv2.VideoCapture(STREAM)
            continue

        # ── Run YOLOv8 inference ──────────────────────────
        results      = model(frame, conf=CONFIDENCE, verbose=False)
        annotated    = results[0].plot()   # draws green boxes automatically
        boxes        = results[0].boxes
        debris_found = boxes is not None and len(boxes) > 0

        # ── Autonomous decision ───────────────────────────
        if debris_found:
            # Stop rover immediately
            if rover_moving:
                send_rover_cmd("stop")
                rover_moving = False
                print("[ROVER] STOPPED — debris detected")

            # Get GPS coords
            lat, lon = gps.get_coords()
            now = time.time()

            # Send alert for every detection (with cooldown to avoid SMS spam)
            if now - last_alert_time >= ALERT_COOLDOWN:
                for box in boxes:
                    name     = model.names[int(box.cls[0])]
                    conf_val = float(box.conf[0])
                    ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # Build alert message
                    if lat and lon:
                        maps_link = f"maps.google.com/?q={lat},{lon}"
                        msg = (
                            f"RUNWAY ALERT\n"
                            f"Debris: {name} ({conf_val:.0%})\n"
                            f"Time: {ts}\n"
                            f"GPS: {lat:.6f}, {lon:.6f}\n"
                            f"Map: {maps_link}"
                        )
                    else:
                        msg = (
                            f"RUNWAY ALERT\n"
                            f"Debris: {name} ({conf_val:.0%})\n"
                            f"Time: {ts}\n"
                            f"GPS: acquiring fix..."
                        )

                    # Send SMS
                    threading.Thread(
                        target=gsm.send_sms,
                        args=(msg,),
                        daemon=True
                    ).start()

                    # Log it
                    log_entry = f"[{ts}] {name} {conf_val:.0%} @ {lat},{lon}"
                    detection_log.append(log_entry)
                    print(f"[ALERT] {log_entry}")

                last_alert_time = now

            # Red alert banner on display
            h, w = annotated.shape[:2]
            cv2.rectangle(annotated, (0, 0), (w, 44), (0, 0, 160), -1)
            cv2.putText(annotated, "DEBRIS DETECTED — ROVER STOPPED",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            # GPS coords on screen
            coord_text = f"GPS: {lat:.6f}, {lon:.6f}" if lat else "GPS: acquiring..."
            cv2.putText(annotated, coord_text,
                        (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        else:
            # No debris — keep patrolling
            if not rover_moving:
                send_rover_cmd("forward")
                rover_moving = True
                print("[ROVER] Debris cleared — resuming patrol")

            # Green status bar
            cv2.rectangle(annotated, (0, 0), (annotated.shape[1], 30), (0, 100, 0), -1)
            cv2.putText(annotated, "PATROLLING — no debris detected",
                        (10, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        # Recent detections log on screen
        for i, entry in enumerate(detection_log[-3:]):
            cv2.putText(annotated, entry,
                        (10, annotated.shape[0] - 30 - i * 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 255), 1)

        cv2.imshow("Runway Surveillance", annotated)

        # ── Keyboard controls ─────────────────────────────
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            send_rover_cmd("stop")
            break
        elif key == ord('s'):
            send_rover_cmd("stop")
            rover_moving = False
            print("[MANUAL] Stop")
        elif key == ord('g'):
            send_rover_cmd("forward")
            rover_moving = True
            print("[MANUAL] Go")

    # Cleanup
    cap.release()
    cv2.destroyAllWindows()
    gps.stop()
    print("\n[DONE] Session ended")
    print(f"Total detections logged: {len(detection_log)}")
    for entry in detection_log:
        print(f"  {entry}")


if __name__ == "__main__":
    main()
