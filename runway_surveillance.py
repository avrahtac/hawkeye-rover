import cv2
import socket
import time
import threading
import numpy as np
import requests
from ultralytics import YOLO

# ═══════════════════════════════════════════════════════
#  SYSTEM CONFIGURATION
# ═══════════════════════════════════════════════════════
ESP32_IP = "192.168.1.8"  #esp32 ip address
UDP_PORT = 8888

PHONE_IP_PORT = "192.168.1.6:8080" #phone ip
STREAM = f"http://{PHONE_IP_PORT}/shot.jpg" 

MODEL_PATH = "yolov8n.pt"
CONFIDENCE = 0.45

# Shared data structures across threads
latest_frame = None
live_gps = "Locating over Network..."
live_maps_url = "Generating Link..."
network_provider = "Detecting ISP..."
running = True

# --- NEW HEARTBEAT VARIABLES ---
current_command = 'F' 
last_sent_cmd = None

# ═══════════════════════════════════════════════════════
#  BACKGROUND DATA WORKERS
# ═══════════════════════════════════════════════════════
def internet_telemetry_worker():
    global live_gps, live_maps_url, network_provider, running
    try:
        response = requests.get("http://ip-api.com/json/", timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data["status"] == "success":
                lat, lon, isp = data["lat"], data["lon"], data["isp"]
                live_gps = f"{lat:.4f} N, {lon:.4f} E"
                live_maps_url = f"https://maps.google.com/?q={lat},{lon}"
                network_provider = f"LINK: {isp.split()[0]}" 
    except Exception:
        live_gps = "Offline / No Internet"

def video_stream_worker():
    global latest_frame, running
    while running:
        try:
            img_resp = requests.get(STREAM, timeout=0.5)
            if img_resp.status_code == 200:
                img_arr = np.array(bytearray(img_resp.content), dtype=np.uint8)
                decoded = cv2.imdecode(img_arr, -1)
                if decoded is not None: latest_frame = decoded
        except Exception:
            pass
        time.sleep(0.01)

# ═══════════════════════════════════════════════════════
#  HIGH-SPEED TELEMETRY HEARTBEAT (THE FIX!)
# ═══════════════════════════════════════════════════════
try:
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.settimeout(0.05)
except Exception:
    udp_socket = None

def telemetry_heartbeat_worker():
    global running, current_command, last_sent_cmd, udp_socket
    while running:
        if udp_socket:
            try:
                # Blast the current command 10 times a second!
                udp_socket.sendto(current_command.encode(), (ESP32_IP, UDP_PORT))
                
                # Only print to terminal if the command actually changed
                if current_command != last_sent_cmd:
                    print(f"[TX] Command Transmitted: [ {current_command} ]")
                    last_sent_cmd = current_command
            except Exception:
                pass
        time.sleep(0.1) # 100ms delay = 10 packets per second

# ═══════════════════════════════════════════════════════
#  MAIN GRAPHICAL INTERFACE ENGINE
# ═══════════════════════════════════════════════════════
def main():
    global latest_frame, running, current_command
    model = YOLO(MODEL_PATH)
    
    # Start all three background engines
    threading.Thread(target=video_stream_worker, daemon=True).start()
    threading.Thread(target=internet_telemetry_worker, daemon=True).start()
    threading.Thread(target=telemetry_heartbeat_worker, daemon=True).start() # The new heartbeat thread!

    manual_override = False
    cv2.namedWindow("RUNWAY SURVEILLANCE & TELEMETRY STATION", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("RUNWAY SURVEILLANCE & TELEMETRY STATION", 1280, 800)

    while True:
        if latest_frame is None:
            time.sleep(0.1)
            continue

        base_frame = cv2.resize(latest_frame.copy(), (1280, 720))
        results = model(base_frame, conf=CONFIDENCE, verbose=False)
        annotated = results[0].plot()
        debris_found = results[0].boxes is not None and len(results[0].boxes) > 0

        # Update the global command based on AI (The heartbeat thread handles the actual sending)
        if not manual_override:
            if debris_found:
                current_command = 'S'
                cv2.rectangle(annotated, (0, 0), (1280, 60), (0, 0, 180), -1)
                cv2.putText(annotated, "ALERT: DEBRIS DETECTED - HALTED", (20, 42), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 255, 255), 2)
            else:
                current_command = 'F'
                cv2.rectangle(annotated, (0, 0), (1280, 60), (0, 120, 0), -1)
                cv2.putText(annotated, "STATUS: ACTIVE PATROL", (20, 42), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 255, 255), 2)
        else:
            current_command = 'S'
            cv2.rectangle(annotated, (0, 0), (1280, 60), (0, 100, 200), -1)
            cv2.putText(annotated, "MANUAL OVERRIDE ENGAGED", (20, 42), cv2.FONT_HERSHEY_DUPLEX, 0.9, (255, 255, 255), 2)

        # UI Dashboard Rendering
        telemetry_tray = np.zeros((100, 1280, 3), dtype=np.uint8)
        cv2.putText(telemetry_tray, f"TX PACKET: [ {current_command} ]", (870, 70), cv2.FONT_HERSHEY_DUPLEX, 0.7, (0, 255, 0) if current_command == 'F' else (0, 0, 255), 1)
        final_dashboard = np.vstack((annotated, telemetry_tray))
        cv2.imshow("RUNWAY SURVEILLANCE & TELEMETRY STATION", final_dashboard)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            current_command = 'S'
            time.sleep(0.2) # Give heartbeat time to send the final stop
            running = False
            break
        elif key == ord('s'): 
            manual_override = True
        elif key == ord('g'): 
            manual_override = False

    if udp_socket: udp_socket.close()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()