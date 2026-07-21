#!/usr/bin/env python3
"""Mock of the Cloud-Lamp HTTP API for developing web/app.html without hardware.

Usage:  python3 tools/mock-device.py [port]     (default 8932)
Then open http://127.0.0.1:<port>/ in a browser.

Emulates the subset of the ESPHome web_server REST API + /events SSE stream
that the web app uses, plus the cloud_lamp_web endpoints (/, /device.json,
/manifest.json).

Also serves the Wi-Fi onboarding page (web/setup.html) at /setup with mock
captive-portal endpoints (/config.json, /wifisave) for styling it without
hardware.
"""

import http.server
import json
import sys
import threading
import time
import urllib.parse
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8932
ROOT = Path(__file__).resolve().parent.parent

EFFECTS = ["White", "Warm White", "Latte Brown", "Red", "Yellow", "Green",
           "Cyan", "Sky Blue", "Blue", "Violet",
           "Sky Breathing", "Aurora Drift", "Candlelight", "Night Light",
           "Twinkle", "Color Wipe", "Rainbow", "Pulse"]

state = {
    "on": False,
    "brightness": 178,   # 0-255
    "effect": "Sky Breathing",
    "color": (90, 170, 255),   # custom colour RGB (effect "None")
    "speed": 50,         # effect_speed 1–100
    "power_behavior": "Start Off",
    "mqtt": True,
    "fw_installing": False,
    "fw_progress": 0,
    "fw_current": "2.2.1",
    "fw_latest": "2.2.2",
    "fw_offline": False,   # simulate reboot blackout during OTA
}
listeners = []
lock = threading.Lock()


def light_json(detail_all=False):
    r, g, b = state["color"]
    j = {
        "id": "light-cloud_light",
        "state": "ON" if state["on"] else "OFF",
        "brightness": state["brightness"],
        "effect": state["effect"] if state["on"] else "None",
        "color": {"r": r, "g": g, "b": b},
    }
    if detail_all:
        j["effects"] = ["None"] + EFFECTS
    return j


def update_json():
    # Match ESPHome web_server shape: latest version is in `value`.
    # Note: web REST does NOT include progress — only state / value / current_version.
    latest = state["fw_latest"]
    cur = state["fw_current"]
    installing = state["fw_installing"]
    if installing:
        st = "INSTALLING"
    elif latest != cur:
        st = "UPDATE AVAILABLE"
    else:
        st = "NO UPDATE"
    return {
        "id": "update-firmware",
        "value": latest,
        "state": st,
        "current_version": cur,
        "title": "Cloud Lamp (cloud-lamp)",
        "summary": f"Cloud-Lamp firmware {latest}",
    }


def broadcast(obj):
    data = f"event: state\ndata: {json.dumps(obj)}\n\n".encode()
    with lock:
        dead = []
        for w in listeners:
            try:
                w.write(data)
                w.flush()
            except Exception:
                dead.append(w)
        for w in dead:
            listeners.remove(w)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code=200, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        # Simulate lamp reboot blackout during OTA (web app coach waits for return).
        if state.get("fw_offline") and path not in ("/", "/app", "/brand.png", "/icon.png", "/logo.png", "/manifest.json"):
            self._send(503, b"{}")
            return
        if path in ("/", "/app"):
            self._send(200, (ROOT / "web" / "app.html").read_bytes(), "text/html")
        elif path == "/setup":
            # Captive-portal onboarding page (on the device it replaces "/")
            self._send(200, (ROOT / "web" / "setup.html").read_bytes(), "text/html")
        elif path == "/config.json":
            # Stock captive_portal scan endpoint (first aps element is {})
            self._send(200, json.dumps({
                "mac": "AA:BB:CC:DD:3F:2A", "name": "cloud-lamp-dd3f2a",
                "aps": [{}, {"ssid": "MyHomeWiFi", "rssi": -52, "lock": 1},
                        {"ssid": "FRITZ!Box 7590", "rssi": -61, "lock": 1},
                        {"ssid": "Guest", "rssi": -74, "lock": 0},
                        {"ssid": "Neighbor's Wi-Fi", "rssi": -85, "lock": 1}],
            }).encode())
        elif path == "/wifisave":
            time.sleep(0.8)   # feels like the real save
            self._send(200, b"Saved. Connecting...", "text/plain")
        elif path in ("/icon.png", "/brand.png", "/logo.png"):
            f = ROOT / "web" / path.lstrip("/")
            if f.exists():
                self._send(200, f.read_bytes(), "image/png")
            else:
                self._send(404, b"")
        elif path == "/device.json":
            self._send(200, json.dumps({
                "name": "cloud-lamp-dd3f2a", "friendly_name": "Cloud-Lamp-dd3f2a",
                "hostname": "cloud-lamp-dd3f2a", "serial": "DD3F2A",
                "mac": "AA:BB:CC:DD:3F:2A", "version": state["fw_current"],
            }).encode())
        elif path == "/manifest.json":
            self._send(200, json.dumps({"name": "Cloud-Lamp", "display": "standalone"}).encode())
        elif path == "/light/cloud_light":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._send(200, json.dumps(light_json(q.get("detail") == ["all"])).encode())
        elif path == "/number/effect_speed":
            self._send(200, json.dumps({"id": "number-effect_speed", "value": state["speed"],
                                        "min_value": 1, "max_value": 100, "step": 1}).encode())
        elif path == "/select/power_behavior":
            self._send(200, json.dumps({"id": "select-power_behavior", "value": state["power_behavior"]}).encode())
        elif path == "/switch/mqtt_enabled":
            self._send(200, json.dumps({"id": "switch-mqtt_enabled",
                                        "state": "ON" if state["mqtt"] else "OFF"}).encode())
        elif path == "/update/firmware":
            self._send(200, json.dumps(update_json()).encode())
        elif path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with lock:
                listeners.append(self.wfile)
            # Initial state burst, like ESPHome does
            for obj in (light_json(), update_json(),
                        {"id": "sensor-wifi_signal", "value": -58},
                        {"id": "sensor-uptime", "value": 93784},
                        {"id": "text_sensor-ip_address", "value": "192.168.2.117"},
                        {"id": "text_sensor-connected_ssid", "value": "MyHomeWiFi"},
                        {"id": "number-effect_speed", "value": state["speed"]},
                        {"id": "select-power_behavior", "value": state["power_behavior"]},
                        {"id": "switch-mqtt_enabled", "state": "ON" if state["mqtt"] else "OFF"}):
                self.wfile.write(f"event: state\ndata: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()
            while True:  # keep open; broken pipe cleans up via broadcast()
                time.sleep(60)
        else:
            self._send(404, b"{}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path, q = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path == "/light/cloud_light/turn_on":
            state["on"] = True
            if "brightness" in q:
                state["brightness"] = int(q["brightness"][0])
            if "effect" in q:
                state["effect"] = q["effect"][0]
            if all(k in q for k in ("r", "g", "b")):
                state["color"] = (int(q["r"][0]), int(q["g"][0]), int(q["b"][0]))
            self._send(200)
            broadcast(light_json())
        elif path == "/light/cloud_light/turn_off":
            state["on"] = False
            self._send(200)
            broadcast(light_json())
        elif path == "/number/effect_speed/set":
            state["speed"] = max(1, min(100, int(float(q.get("value", ["50"])[0]))))
            self._send(200)
            broadcast({"id": "number-effect_speed", "value": state["speed"]})
        elif path == "/select/power_behavior/set":
            state["power_behavior"] = q.get("option", ["Start Off"])[0]
            self._send(200)
            broadcast({"id": "select-power_behavior", "value": state["power_behavior"]})
        elif path in ("/switch/mqtt_enabled/turn_on", "/switch/mqtt_enabled/turn_off"):
            state["mqtt"] = path.endswith("turn_on")
            self._send(200)
            broadcast({"id": "switch-mqtt_enabled", "state": "ON" if state["mqtt"] else "OFF"})
        elif path == "/button/check_for_updates/press":
            self._send(200)

            def fake_check():
                time.sleep(1.2)
                broadcast(update_json())
            threading.Thread(target=fake_check, daemon=True).start()
        elif path == "/update/firmware/install":
            self._send(200)

            def fake_install():
                # Match real device: INSTALLING → (web freezes/offline) → reboot → new version.
                state["fw_installing"] = True
                broadcast(update_json())
                time.sleep(3)          # "download"
                state["fw_offline"] = True
                state["fw_installing"] = False
                time.sleep(5)          # reboot blackout
                state["fw_current"] = state["fw_latest"]
                state["fw_offline"] = False
                broadcast(update_json())
            threading.Thread(target=fake_install, daemon=True).start()
        elif path in ("/button/restart/press", "/button/factory_reset/press", "/button/reset_wifi/press"):
            self._send(200)
        else:
            self._send(404)


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Mock Cloud-Lamp on http://127.0.0.1:{PORT}/")
    server.serve_forever()
