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

Also serves a validly-signed OTA update manifest at
/firmware-dist/cloud-lamp/manifest.json (plus the referenced .bin), so this
can stand in for the real plain-HTTP host (see docs/firmware-updates.md)
when testing components/signed_update/ against real hardware without
publishing a real release. It's signed with a throwaway, dev-only
keypair (OTA_TEST_* below) — NOT the production key in
~/.cloud-lamp-release-secrets/ — so a real public-build lamp won't trust it.
To test the full accept path on real hardware, temporarily point a
diagnostic build's update_manifest_url at
http://<this-machine's-LAN-IP>:<port>/firmware-dist/cloud-lamp/manifest.json
and its ota_ed25519_pubkey at OTA_TEST_PUBLIC_KEY_HEX.
"""

import hashlib
import http.server
import json
import sys
import threading
import time
import urllib.parse
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:  # pragma: no cover - only needed for the OTA manifest route
    Ed25519PrivateKey = None

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8932
ROOT = Path(__file__).resolve().parent.parent

# Throwaway dev-only Ed25519 keypair, used ONLY to sign the local test
# manifest served below — never used for real releases (see
# tools/release.sh, which signs with the real key kept outside this repo).
# Safe to commit: it authenticates nothing on real hardware unless a
# diagnostic build is deliberately compiled with OTA_TEST_PUBLIC_KEY_HEX.
OTA_TEST_PRIVATE_KEY_HEX = "d786092d2e2ad248f3d8f24156c43d8cf5103e022099e57a532e84853a0f1282"
OTA_TEST_PUBLIC_KEY_HEX = "dfc7c2587793ff522017f8d5671b7d031d6766c6ba5026c713d3ea7417222129"


def signed_ota_manifest(device_name="cloud-lamp"):
    """Re-signs the real committed docs/firmware-dist/<device_name>/manifest.json
    with the throwaway test key, computing the MD5 live so it always matches
    whatever .bin is actually on disk."""
    manifest_dir = ROOT / "docs" / "firmware-dist" / device_name
    manifest = json.loads((manifest_dir / "manifest.json").read_text())
    build = manifest["builds"][0]["ota"]
    bin_path = manifest_dir / build["path"]
    md5 = hashlib.md5(bin_path.read_bytes()).hexdigest()
    build["md5"] = md5
    if Ed25519PrivateKey is None:
        build["signature"] = "0" * 128  # deliberately invalid — see ImportError above
    else:
        key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(OTA_TEST_PRIVATE_KEY_HEX))
        message = f"{manifest['version']}|{build['path']}|{md5}".encode()
        build["signature"] = key.sign(message).hex()
    return manifest

# Mirrors components/cloud_lamp_web/__init__.py's "?v=<hash>" cache-buster
# for /icon.png, so app.html's __ICON_VERSION__ placeholder resolves the same
# way here as on real firmware.
_icon_path = ROOT / "web" / "icon.png"
ICON_VERSION = hashlib.md5(_icon_path.read_bytes()).hexdigest()[:8] if _icon_path.exists() else "0"

EFFECTS = ["White", "Sky Blue", "Blue", "Indigo", "Purple", "Magenta", "Salmon",
           "Red", "Peach", "Apricot", "Orange", "Amber", "Honey", "Gold",
           "Vanilla", "Yellow", "Chartreuse", "Green",
           "Aurora Drift", "Sky Breathing", "Candlelight", "Ring Ripple",
           "Spectrum Fade", "Spectrum Flow", "Twinkle", "Blue Color Wipe",
           "Rainbow", "Pulse"]

state = {
    "on": False,
    "brightness": 178,   # 0-255
    "effect": "Aurora Drift",
    "color": (82, 214, 252),   # custom colour RGB (effect "None") — Sky Blue
    "speed": 50,         # effect_speed 1–100
    "power_behavior": "Start Off",
    "mqtt": False,               # OFF by default on new devices
    "mqtt_broker": "",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_pass": "",
    "fw_installing": False,
    "fw_progress": 0,
    "fw_current": "2.2.5",
    "fw_latest": "2.3.0",
    "fw_offline": False,   # simulate reboot blackout during OTA
}
listeners = []
lock = threading.Lock()

# Entity display Name -> REST object_id. Real firmware (ESPHome web_server)
# matches REST paths by entity Name first, falling back to the legacy
# object_id with a deprecation warning (removed entirely in 2026.7.0), so
# app.html now sends Name-based paths (e.g. "/light/Cloud Light"). The
# routes below are still keyed by object_id for brevity, so incoming
# requests are normalised through this table before matching.
NAME_TO_ID = {
    "Cloud Light": "cloud_light",
    "Effect Speed": "effect_speed",
    "Power Behavior": "power_behavior",
    "MQTT Enabled": "mqtt_enabled",
    "MQTT Broker": "mqtt_broker_host",
    "MQTT Username": "mqtt_broker_username",
    "MQTT Password": "mqtt_broker_password",
    "MQTT Port": "mqtt_broker_port",
    "Firmware": "firmware",
    "Restart": "restart",
    "Factory Reset": "factory_reset",
    "Reset WiFi": "reset_wifi",
    "Check for Updates": "check_for_updates",
}


def normalize_path(path):
    """Rewrite `/domain/Entity Name[/action]` to `/domain/object_id[/action]`."""
    parts = path.split("/", 3)  # ["", domain, name, action?]
    if len(parts) >= 3 and parts[2] in NAME_TO_ID:
        parts[2] = NAME_TO_ID[parts[2]]
        return "/".join(parts)
    return path


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
        path = normalize_path(urllib.parse.unquote(urllib.parse.urlparse(self.path).path))
        # Simulate lamp reboot blackout during OTA (web app coach waits for return).
        if state.get("fw_offline") and path not in ("/", "/app", "/brand.png", "/icon.png", "/logo.png", "/manifest.json"):
            self._send(503, b"{}")
            return
        if path in ("/", "/app"):
            html = (ROOT / "web" / "app.html").read_bytes().replace(b"__ICON_VERSION__", ICON_VERSION.encode())
            self._send(200, html, "text/html")
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
        elif path == "/firmware-dist/cloud-lamp/manifest.json":
            # Signed OTA update manifest — see module docstring for how to
            # point real hardware at this for a full local signed_update test.
            self._send(200, json.dumps(signed_ota_manifest()).encode())
        elif path.startswith("/firmware-dist/cloud-lamp/") and path.endswith(".bin"):
            bin_dir = (ROOT / "docs" / "firmware-dist" / "cloud-lamp").resolve()
            f = (ROOT / "docs" / path.lstrip("/")).resolve()
            if bin_dir in f.parents and f.exists():
                self._send(200, f.read_bytes(), "application/octet-stream")
            else:
                self._send(404, b"")
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
        elif path == "/text/mqtt_broker_host":
            self._send(200, json.dumps({"id": "text-mqtt_broker_host",
                                        "state": state["mqtt_broker"], "value": state["mqtt_broker"]}).encode())
        elif path == "/number/mqtt_broker_port":
            self._send(200, json.dumps({"id": "number-mqtt_broker_port", "value": state["mqtt_port"],
                                        "min_value": 1, "max_value": 65535, "step": 1}).encode())
        elif path == "/text/mqtt_broker_username":
            self._send(200, json.dumps({"id": "text-mqtt_broker_username",
                                        "state": state["mqtt_user"], "value": state["mqtt_user"]}).encode())
        elif path == "/text/mqtt_broker_password":
            # Real firmware masks `state` for password-mode texts but still
            # returns the raw value in `value` — mirror that here.
            masked = "********" if state["mqtt_pass"] else ""
            self._send(200, json.dumps({"id": "text-mqtt_broker_password",
                                        "state": masked, "value": state["mqtt_pass"]}).encode())
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
                        {"id": "switch-mqtt_enabled", "state": "ON" if state["mqtt"] else "OFF"},
                        {"id": "text-mqtt_broker_host", "value": state["mqtt_broker"]},
                        {"id": "number-mqtt_broker_port", "value": state["mqtt_port"]},
                        {"id": "text-mqtt_broker_username", "value": state["mqtt_user"]},
                        {"id": "text-mqtt_broker_password", "value": state["mqtt_pass"]}):
                self.wfile.write(f"event: state\ndata: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()
            while True:  # keep open; broken pipe cleans up via broadcast()
                time.sleep(60)
        else:
            self._send(404, b"{}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = normalize_path(urllib.parse.unquote(parsed.path))
        q = urllib.parse.parse_qs(parsed.query)
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
        elif path == "/text/mqtt_broker_host/set":
            state["mqtt_broker"] = q.get("value", [""])[0]
            self._send(200)
            broadcast({"id": "text-mqtt_broker_host", "value": state["mqtt_broker"]})
        elif path == "/number/mqtt_broker_port/set":
            try:
                state["mqtt_port"] = max(1, min(65535, int(float(q.get("value", ["1883"])[0]))))
            except ValueError:
                pass
            self._send(200)
            broadcast({"id": "number-mqtt_broker_port", "value": state["mqtt_port"]})
        elif path == "/text/mqtt_broker_username/set":
            state["mqtt_user"] = q.get("value", [""])[0]
            self._send(200)
            broadcast({"id": "text-mqtt_broker_username", "value": state["mqtt_user"]})
        elif path == "/text/mqtt_broker_password/set":
            state["mqtt_pass"] = q.get("value", [""])[0]
            self._send(200)
            broadcast({"id": "text-mqtt_broker_password", "value": state["mqtt_pass"]})
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
