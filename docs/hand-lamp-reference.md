# Hand-Lamp — Reference Documentation

This document describes the completed **hand-lamp** project in full. It serves as the reference baseline for the new cloud-lamp project.

Source: `/ESPHome/config/hand-lamp/hand-lamp.yaml`

---

## Hardware

| Component | Specification |
|---|---|
| Microcontroller | Wemos D1 Mini (ESP8266), ESPHome board: `d1_mini` |
| LED rings | 2× WS2812x rings, daisy-chained, 16 LEDs total (GRB colour order) |
| LED data pin | GPIO03 (hardware RX pin) |
| Signal resistor | 330 Ω in series between GPIO03 and DI of the first LED ring |
| Decoupling capacitor | ~220 µF electrolytic, in parallel with the 5 V supply rail |
| Power supply | External 5 V / 2 A |
| Touch input | Capacitive touch board (B09VPK9N7F) on GPIO12 (D6), active-high, internal pull-up enabled |
| Temperature sensors | 2× DS18B20 on GPIO4 (D2) via OneWire protocol |

### Wiring notes

- The **330 Ω resistor** on the data line protects against signal integrity issues. WS2812 LEDs expect a 5 V logic level; the resistor helps reduce ringing on the line from the 3.3 V ESP output.
- The **220 µF capacitor** absorbs the large inrush current spike when the LED rings first receive power, protecting the ESP and the power supply.
- The two LED rings are **daisy-chained**: DO (data-out) of ring 1 connects to DI (data-in) of ring 2. ESPHome treats the entire chain as a single 16-LED strip.

---

## Software Features

### Light effects (17 total)

The LED strip is declared as an `internal` light entity — ESPHome does not auto-publish its state via MQTT. All state reporting is handled by explicit `mqtt.publish` calls in scripts.

The active effect index is persisted to flash (`restore_value: yes`) so the lamp remembers its last colour across reboots.

#### Solid colours (10)

| Name | RGB |
|---|---|
| White | 255, 255, 255 |
| Red | 255, 0, 0 |
| Orange | 255, 128, 0 |
| Yellow | 255, 255, 0 |
| Green | 0, 255, 0 |
| Cyan | 0, 255, 255 |
| Blue | 0, 0, 255 |
| Indigo | 75, 0, 130 |
| Violet | 138, 43, 226 |
| Pink | 255, 105, 180 |

#### Animated effects (7)

| Name | Description |
|---|---|
| Rainbow | Scrolling rainbow across all 16 LEDs, speed 3, width 100 |
| Color Wipe | ESPHome built-in colour wipe animation |
| Scanner | Larson scanner (back-and-forth sweep) |
| Twinkle | Random LED twinkle |
| Fireworks | ESPHome built-in fireworks |
| Flicker | ESPHome built-in flicker |
| Pulse | Slow brightness breathing: 30–100%, 8 s transition, 3 s update interval |

---

### Touch button behaviour

The capacitive touch board is read as a `gpio` binary sensor with internal pull-up. Timing is measured manually in milliseconds; the long-press threshold is 1500 ms.

| Interaction | Condition | Action |
|---|---|---|
| Short press (< 1500 ms) | LEDs are **off**, no emergency lockout | Turn LEDs on, restore last effect |
| Short press (< 1500 ms) | LEDs are **on** | Advance to next effect (wraps around) |
| Long press (≥ 1500 ms) | Any state | Turn LEDs off |
| Any press | During boot (`boot_completed == false`) | Ignored entirely |
| Short press | Emergency lockout active | Ignored, warning logged |

The long-press action is implemented via a `restart`-mode script (`long_press_shutdown`) that runs a 1500 ms delay; if the button is released before the delay expires, the script is cancelled on the next press, which prevents a false long-press.

---

### Temperature monitoring and emergency shutdown

Two DS18B20 sensors are polled every 15 s. A 3-sample sliding moving average is applied; the filtered value is published every 2 readings (≈ every 30 s).

| Sensor | Shutdown threshold | Auto-recovery threshold |
|---|---|---|
| Case temperature | ≥ 40 °C | ≤ 35 °C |
| Hands temperature | ≥ 36 °C | ≤ 32 °C |

When either threshold is exceeded:
- LEDs are turned off immediately.
- `led_emergency_off` flag is set.
- `emergency_shutdown_reason` is set to `"Case-Temperature"` or `"Hands-Temperature"`.
- All MQTT on/effect commands and short button presses are blocked.

The lockout lifts automatically only when **both** sensors are simultaneously below their respective recovery thresholds (hysteresis prevents oscillation).

---

### MQTT interface

Broker connection uses keepalive 8 s and a 10-minute reboot timeout. All topics are under `Devices/Hand-Lamp/`.

| Topic | Direction | Payload | Notes |
|---|---|---|---|
| `.../Control/On` | in + out | `"true"` / `"false"` | Accepts `true/True/TRUE/on/On/ON/1` for on |
| `.../Control/Effect` | in + out | Effect name string | Invalid names are rejected; current effect is re-published |
| `.../Control/Reboot` | in | `"true"` | Triggers reboot after 3 s delay |
| `.../Info/Reachable` | out | `"online"` / `"offline"` | LWT; QoS 2 |
| `.../Info/IP` | out | IP address string | Published on boot and every 60 s |
| `.../Info/Emergency_Shutdown` | out | `"true"` / `"false"` | Published every 5 s and on every temp reading |
| `.../Info/Emergency_Shutdown_Reason` | out | `"NONE"` / `"Case-Temperature"` / `"Hands-Temperature"` | Published with emergency flag |
| `.../Temperatures/Case_Temperature` | out | Temperature in °C | Published on each filtered sensor reading |
| `.../Temperatures/Hands_Temperature` | out | Temperature in °C | Published on each filtered sensor reading |
| `.../Logging/Log` | out | Log line | ESPHome log forwarding |
| `.../Logging/Last_Reboot` | out | `"YYYY-MM-DD HH:MM:SS"` | Published on boot if SNTP time is valid |
| `.../Logging/Last_Reboot_Reason` | out | ESP reset reason string | Published on every boot |

Periodic re-publish intervals: emergency status every **5 s**, on/effect every **10 s**, IP every **60 s**.

---

### Boot sequence

Runs at priority −10 (after all components have initialised):

1. Force `light_enabled = false` (overrides restored flash value).
2. Execute `all_leds_off` (sets all 16 LEDs to black).
3. Wait 3 s for WiFi and MQTT to stabilise.
4. Publish: IP address, reboot flag (`false`), on/off state, current effect, emergency state and reason, last reboot timestamp (if SNTP valid), reset reason.
5. Initialise `button_press_time = millis()` (prevents false long-press on boot).
6. Set `boot_completed = true` — MQTT commands and button presses are now accepted.
