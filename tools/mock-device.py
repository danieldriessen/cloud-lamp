#!/usr/bin/env python3
"""Mock of the Cloud-Lamp HTTP API for developing web/app.html without hardware.

Usage:  python3 tools/mock-device.py [port]     (default 8932)
Then open http://127.0.0.1:<port>/ in a browser.

Emulates the subset of the ESPHome web_server REST API + /events SSE stream
that the web app uses, plus the cloud_lamp_web endpoints (/, /device.json,
/manifest.json).
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

EFFECTS = ["Warm White", "White", "Sky Blue", "Cyan", "Blue", "Indigo", "Violet",
           "Sky Breathing", "Aurora Drift", "Candlelight", "Night Light",
           "Twinkle", "Color Wipe", "Rainbow", "Pulse", "Thunderstorm"]

state = {
    "on": False,
    "brightness": 178,   # 0-255
    "effect": "Sky Breathing",
    "power_behavior": "Start Off",
    "mqtt": True,
    "fw_installing": False,
    "fw_progress": 0,
}
listeners = []
lock = threading.Lock()


def light_json(detail_all=False):
    j = {
        "id": "light-cloud_light",
        "state": "ON" if state["on"] else "OFF",
        "brightness": state["brightness"],
        "effect": state["effect"] if state["on"] else "None",
    }
    if detail_all:
        j["effects"] = ["None"] + EFFECTS
    return j


def update_json():
    return {
        "id": "update-firmware",
        "state": "INSTALLING" if state["fw_installing"] else "AVAILABLE",
        "current_version": "2.0.0",
        "latest_version": "2.1.0",
        "has_progress": state["fw_installing"],
        "progress": state["fw_progress"],
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
        if path in ("/", "/app"):
            self._send(200, (ROOT / "web" / "app.html").read_bytes(), "text/html")
        elif path in ("/icon.png", "/logo.png"):
            f = ROOT / "web" / path.lstrip("/")
            if f.exists():
                self._send(200, f.read_bytes(), "image/png")
            else:
                self._send(404, b"")
        elif path == "/device.json":
            self._send(200, json.dumps({
                "name": "cloud-lamp", "friendly_name": "Cloud-Lamp",
                "serial": "3F2A", "mac": "AA:BB:CC:DD:3F:2A", "version": "2.0.0",
            }).encode())
        elif path == "/manifest.json":
            self._send(200, json.dumps({"name": "Cloud-Lamp", "display": "standalone"}).encode())
        elif path == "/light/cloud_light":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self._send(200, json.dumps(light_json(q.get("detail") == ["all"])).encode())
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
            self._send(200)
            broadcast(light_json())
        elif path == "/light/cloud_light/turn_off":
            state["on"] = False
            self._send(200)
            broadcast(light_json())
        elif path == "/select/power_behavior/set":
            state["power_behavior"] = q.get("option", ["Start Off"])[0]
            self._send(200)
            broadcast({"id": "select-power_behavior", "value": state["power_behavior"]})
        elif path in ("/switch/mqtt_enabled/turn_on", "/switch/mqtt_enabled/turn_off"):
            state["mqtt"] = path.endswith("turn_on")
            self._send(200)
            broadcast({"id": "switch-mqtt_enabled", "state": "ON" if state["mqtt"] else "OFF"})
        elif path == "/update/firmware/install":
            self._send(200)

            def fake_install():
                state["fw_installing"] = True
                for p in range(0, 101, 10):
                    state["fw_progress"] = p
                    broadcast(update_json())
                    time.sleep(0.5)
                state["fw_installing"] = False
            threading.Thread(target=fake_install, daemon=True).start()
        elif path in ("/button/restart/press", "/button/factory_reset/press"):
            self._send(200)
        else:
            self._send(404)


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Mock Cloud-Lamp on http://127.0.0.1:{PORT}/")
    server.serve_forever()
