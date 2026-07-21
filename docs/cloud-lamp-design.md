# Cloud-Lamp — Design Document

This document describes the design of the **cloud-lamp** firmware (v2). It covers the
architecture, the button and boot behaviour, the web app, the optional MQTT integration,
and the hardware. Historical context from the predecessor project lives in
[hand-lamp-reference.md](./hand-lamp-reference.md); the v1 → v2 rewrite rationale is
summarised in [the changelog section](#v1--v2-changelog) at the end.

Related documents:

- [README.md](../README.md) — public project overview, features, getting started
- [user-manual.pdf](./user-manual.pdf) — end-user manual, PDF (permanent URL: sticker QR code + web-app book icon); source: [user-manual.md](./user-manual.md), rebuilt with `tools/build-manual.py`
- [device-credentials.md](./device-credentials.md) — shared passwords, AP naming, sticker contents
- [firmware-updates.md](./firmware-updates.md) — online update workflow and release process

---

## Project status

> **Phase:** v2.2.4 — the permanent manual URL moved from the jsDelivr CDN to GitHub
> Pages (`https://danieldriessen.github.io/cloud-lamp/user-manual.pdf`), first-party
> hosting with no third-party CDN dependency; still serves the PDF inline with a real
> application/pdf content type. This is the FINAL manual URL — it goes on printed
> stickers (see [GitHub Pages setup](#github-pages-setup) below). The PDF cover now shows
> the actual DD Productions logo (icon + wordmark) instead of plain text — derived as a
> transparent, dark-ink image from `assets/dd-productions-logo-white.png`, because
> `assets/dd-productions-logo-black.png` turned out to contain no text glyphs at all
> (icon only) despite its name. The manual cover also now shows "Describes firmware
> vX.Y.Z", read automatically from `cloud-lamp.yaml`'s `project_version` by
> `tools/build-manual.py` (never hardcoded). The final printed sticker prints `Hostname`
> WITH the `http://` scheme already included (e.g. `http://cloud-lamp-cfb911.local`) —
> user-manual.md and device-credentials.md updated accordingly (previously assumed the
> bare hostname, with the manual telling recipients to add `http://` themselves). Added
> `.cursor/rules/manual-release-check.mdc` so future releases re-verify the manual and
> sticker docs against current behaviour before publishing. v2.2.3: the permanent manual
> URL was briefly the jsDelivr CDN link. v2.2.2: branded Wi-Fi onboarding: the captive portal now serves our own
> setup page (web/setup.html, same design language as the app, ten languages) instead of
> ESPHome's stock page; scan/save still use the stock /config.json + /wifisave endpoints.
> Icons are now served with `no-cache` (a 24 h max-age kept old logos on phones after
> updates) and the wordmark is also the browser favicon. v2.2.1: user manual as designed
> PDF (docs/user-manual.pdf, built by tools/build-manual.py); the permanent manual URL
> (sticker QR code + web-app book icon) points at the PDF and must never change again.
> v2.2.0: firmware update coach (full-screen install → reboot → reconnect UI) plus longer
> HTTP OTA timeouts (60 s HTTP idle timeout); web REST has no progress %, so the coach
> uses an indeterminate bar. v2.1.9: project wordmark logo. v2.1.8: ten languages.
> v2.1.7: custom colour picker. v2.1.6: full-bleed iOS background. v2.1.5: effect list +
> manual.
> **Docs correction (no firmware change):** the manual, README and this document
> previously mis-described the power supply as "5 V USB" — it is actually a 5 V/2 A DC
> barrel-jack adapter (5.5×2.1 mm, centre-positive), now corrected everywhere. The sticker
> design is finalised (docs/Label.lbx); user-manual.md §2 and device-credentials.md now
> describe its actual fields (Model/S/N/Hostname/WiFi-Passw./Power-Supply/QR) instead of
> the earlier, slightly different field set.
> **Still open:** per-effect user presets (store brightness + speed per effect, applied on
> selection — feasible, deferred; see Web app section); intensity slider (per-effect
> mapping); test button gestures / captive portal end-to-end; print + apply the finalised
> product sticker (docs/Label.lbx); 3D print files.
> **Firmware:** ESPHome 2026.6.0, project version 2.2.4

### GitHub Pages setup

The manual PDF is hosted on GitHub Pages instead of a third-party CDN (jsDelivr, used
briefly in v2.2.3). One-time setup, already done for this repo:

1. GitHub repo → **Settings → Pages** (left sidebar, under "Code and automation").
2. **Build and deployment → Source:** "Deploy from a branch".
3. **Branch:** `main`, folder **`/docs`** → **Save**.
4. GitHub builds and publishes the site within a minute or two; the same Pages screen
   then shows the live URL (`https://danieldriessen.github.io/cloud-lamp/`).
5. `docs/.nojekyll` (committed alongside this change) tells GitHub Pages to serve the
   `/docs` folder's files as-is instead of running them through Jekyll — required so the
   PDF (and any future binary asset in `docs/`) is served byte-for-byte, unprocessed.

No further action is needed after this: every push to `main` that touches `docs/`
redeploys the Pages site automatically, so `docs/user-manual.pdf` stays current.

---

## Design principles

1. **Standalone-first.** The lamp is a lamp. On/off, effect cycling and dimming always work
   via the push-button — without Wi-Fi, without MQTT, without any network at all. Nothing
   network-related may ever block, delay or reboot the lamp (`reboot_timeout: 0s` everywhere).
2. **The light component is the single source of truth.** Button, web app and MQTT all drive
   the same `light` entity through the same scripts. State mirroring into persisted globals
   happens in one place (the light's `on_state` hook), so every control path stays consistent.
3. **Optional features are packages; the public build is secret-free.** `cloud-lamp.yaml`
   is the generic gift build — no personal names, no Wi-Fi networks, no MQTT. The builder's
   bench lamp uses `cloud-lamp-dev.yaml`, which layers compiled-in networks and the MQTT
   package on top. Published binaries come only from the public build (enforced by
   `tools/release.sh`).
4. **Settings survive everything.** Persisted values (brightness, effect, power behaviour,
   MQTT kill switch, captive-portal Wi-Fi credentials) live in the ESP preferences area,
   outside the firmware image. They survive reboots, power cuts and OTA updates. Global IDs
   are kept stable across firmware versions so stored values stay attached.

---

## File structure

```
cloud-lamp/
├── cloud-lamp.yaml               # Core firmware = public gift build (no secrets embedded)
├── cloud-lamp-dev.yaml           # Builder build: core + secret Wi-Fi networks + MQTT
├── effects.yaml                  # Effects package + all effect tuning knobs
├── secrets.yaml                  # Per-device credentials — git-ignored, never committed
├── secrets.example.yaml          # Template for secrets.yaml (placeholders only)
├── packages/
│   ├── web-remote.yaml           # Web server + web app + diagnostics (default ON)
│   ├── updates.yaml              # Online firmware updates (default ON)
│   ├── mqtt.yaml                 # MQTT / ioBroker integration (optional)
│   └── temperature-sensor.yaml   # Case temperature + thermal shutdown (optional)
├── components/
│   └── cloud_lamp_web/           # Custom ESPHome component serving the web app
├── web/
│   ├── app.html                  # Single-file iOS-style web app (gzipped into firmware)
│   ├── setup.html                # Branded captive-portal Wi-Fi onboarding page
│   ├── icon.png                  # Home-screen / PWA icon (wordmark, transparent)
│   ├── brand.png                 # Header wordmark (transparent, /brand.png)
│   └── logo.png                  # DD Productions logo (embedded, served at /logo.png)
├── assets/                       # Artwork sources (cloud-lamp-logo.png = project wordmark)
├── firmware-dist/                # Published releases (update channel, see firmware-updates.md)
├── tools/
│   ├── release.sh                # Build + package a firmware release for the updater
│   ├── build-manual.py           # Render docs/user-manual.md → docs/user-manual.pdf
│   └── mock-device.py            # Local mock of the device API for web app development
└── docs/                         # This folder
    ├── user-manual.pdf           # End-user manual (permanent URL target of the sticker
    │                             #   QR code; regenerate with tools/build-manual.py)
    ├── .nojekyll                 # Tells GitHub Pages to serve this folder's files as-is
    └── Label.lbx                 # Brother P-Touch template for the back sticker
                                  #   (required/optional fields: device-credentials.md)
```

The `packages:` block at the top of `cloud-lamp.yaml` controls which optional modules are
active. Per-build values (device name, LED count, version, manifest URL, …) all live in the
`substitutions` block — nothing requiring per-device adjustment appears anywhere else.

> **Minimum ESPHome version: 2025.x** — the config uses `!extend`, the `update` component,
> `on_multi_click`, and a local external component.

---

## Behaviour reference

### Button (single momentary switch on GPIO12)

| Gesture | Light state | Action |
|---|---|---|
| 1× click | on | Turn off |
| 1× click | off | Turn on (last effect, last brightness) |
| 2× click | on | Next effect (wraps around; order = order in `effects.yaml`) |
| 2× click | off | Turn on |
| Hold ≥ 0.5 s | on | Dim while held; direction alternates per hold, no wrap-around |
| Hold ≥ 0.5 s | off | Turn on |
| Hold while plugging in power, keep holding ~10 s | — | Factory reset (see below) |
| Anything during boot | — | Ignored (`boot_completed` guard) |

Notes on the hold-to-dim ramp: full range takes ~3 s; brightness is clamped to
`brightness_min`–100 % (default 10–100 %) so the lamp always stays visibly on — off is
only ever the explicit single-click toggle, never the end of a dim ramp. The same floor
applies to the web app slider and MQTT `Set/Brightness` (values below it are clamped).
Near a limit the direction is forced away from the limit so a hold never appears dead.
Single-click actions fire ~350 ms after release (double-click disambiguation window).

### Factory reset

Two ways, both deliberate:

- **Power-on gesture:** hold the button while plugging in power and keep holding. The rings
  pulse red for ~10 seconds as a countdown warning; releasing at any point aborts and the
  lamp boots normally. Surviving the countdown wipes all preferences (captive-portal Wi-Fi
  credentials, brightness, effect, settings) and reboots into the setup hotspot.
- **Web app:** Settings → Maintenance → Factory reset (double confirmation dialog).

### Boot sequence

1. **Priority 600:** the setup-hotspot SSID is set to `Cloud-Lamp-XXXXXX` (XXXXXX = last 6 hex
   digits of the chip MAC, uppercase) before Wi-Fi starts. This is the name printed on the
   product sticker.
2. **Priority −100 (end of boot):** if the button is held → factory-reset countdown.
   Otherwise the *Power Behavior* setting is applied: **Start switched off** (firmware
   option `Start Off`, default) or **Restore Last State** (turns back on with the saved
   effect and brightness if the lamp was on when power was cut). Then `boot_completed`
   is set; only from this point are button presses, MQTT commands and state mirroring
   active.

`restore_mode: ALWAYS_OFF` on the light plus a hard pixel-buffer clear after every turn-off
guarantee no LED can stay lit from an undefined boot state.

### Wi-Fi / provisioning

- **Gift build (`cloud-lamp.yaml`): no compiled-in networks.** Its binaries are published
  publicly, so it must not embed any credentials; Wi-Fi comes exclusively from the captive
  portal (stored in flash, survives updates). The builder's dev build
  (`cloud-lamp-dev.yaml`) adds two compiled-in networks from `secrets.yaml` — see
  [device-credentials.md](./device-credentials.md).
- If no network connects, the lamp opens the setup hotspot `Cloud-Lamp-XXXXXX` (password on
  the sticker) with a captive portal for entering home Wi-Fi credentials. The lamp keeps
  working as a lamp the whole time; `reboot_timeout: 0s` means it never reboots over Wi-Fi.
- The portal shows the **branded onboarding page** (`web/setup.html`, served by
  `cloud_lamp_web`): same design language as the app, auto-localised (same ten languages),
  network list with signal strength, password reveal, and a success view that tells the
  user to rejoin their home Wi-Fi and open the lamp's `.local` address. The stock
  captive-portal endpoints (`/config.json` scan, `/wifisave` save) keep doing the work
  underneath; without a compiled-in setup page the stock ESPHome page appears instead.

---

## Web app (`packages/web-remote.yaml` + `components/cloud_lamp_web/` + `web/app.html`)

A single-file iOS-style web app served by the lamp itself at `http://<lamp-ip>/`.

- **Delivery:** `web/app.html` is gzip-compressed at compile time and embedded in flash
  (PROGMEM) by the custom `cloud_lamp_web` component. The component also serves
  `/manifest.json` (PWA manifest, name = friendly name), `/icon.png` (home-screen / PWA
  icon), `/brand.png` (transparent cloud mark in the app header), `/logo.png` (DD
  Productions maker logo in the footer) and `/device.json` (name, serial, MAC, version).
- **PWA icon (`/icon.png`):** the project wordmark on a square transparent canvas
  (512×512). Used for Add to Home Screen / manifest icons. iOS may still fill
  transparent `apple-touch-icon` pixels with black — check on a real device after each
  artwork change; if it looks wrong, composite the wordmark onto the PWA
  `background_color` (`#0b0f18`) instead.
- **Header brand (`/brand.png`):** the same wordmark, cropped landscape, for the in-app
  header only (`object-fit: contain`, no background box; not used as the home-screen
  icon).
- **PWA:** a top-of-page button *Create a remote control app* opens a structured sheet with
  step-by-step iOS home-screen instructions (including the lamp’s own unique
  `http://cloud-lamp-<serial>.local/` address — same six-hex serial as the header). The button is shown only when
  `typeof navigator.standalone === "boolean"` (iOS / iPadOS WebKit only — desktop Chrome
  and Safari leave it undefined) and this device has not yet launched the home-screen app
  (`standalone === true` or `display-mode: standalone`, remembered in `localStorage`).
  Android, desktop browsers, and an already-installed PWA never see it. Onboarding via the
  setup hotspot is unchanged.
- **iOS "HTTPS-Only" errors:** since iOS 18.2, Safari hard-blocks *home-screen links* to
  plain-HTTP pages when *Settings → Apps → Safari → Not Secure Connection Warning* is on
  (German: *„Die Steuerung ist fehlgeschlagen… HTTP-URL mit aktiviertem Modus HTTP is
  only“*). The lamp **cannot** serve HTTPS: ESPHome's web server is HTTP-only, and an
  ESP8266 has neither the RAM for a TLS server nor a publicly trusted certificate for a
  private-network address (same limitation as FRITZ!, Shelly, WLED, …). Mitigations we
  ship: no HSTS (`Strict-Transport-Security: max-age=0`), relative PWA `start_url`, and a
  localised in-app tip that tells recipients to (1) disable that Safari setting and
  (2) type `http://cloud-lamp-<serial>.local/` explicitly before *Add to Home Screen*
  (same six-hex serial as the sticker / header). There is no firmware-only way to make
  iOS accept a local HTTP home-screen app while that setting stays enabled.
- **Safari "ᴬA" / font-size menu:** appears when the page is opened *inside Safari*. The
  app uses `role="application"`, disables text-size adjustment, and is a proper
  standalone PWA — once installed from the home screen it runs full-screen without that
  chrome. If the icon still opens Safari with the menu, delete the icon and re-add it
  after the HTTPS tip above.
- **API:** the app talks to the standard ESPHome `web_server` REST API (`/light/...`,
  `/select/...`, `/switch/...`, `/button/...`, `/update/...`) and receives live state via
  the `/events` server-sent-events stream, with a 5 s polling fallback. All state shown is
  device-confirmed (no unverified optimistic UI).
- **Features:** power toggle, brightness slider, *Effect Presets* grid with colour
  swatches (grouped into *Colors* and *Special effects*) plus a *Custom color* tile that
  opens the OS-native colour picker (`<input type="color">` — the iOS 14+ system
  spectrum/grid/slider sheet; live preview is throttled to ~5 requests/s while dragging).
  A custom colour is stored in the firmware like an effect (globals
  `custom_color_active` + `custom_color_rgb`), so it survives power cuts and off/on;
  a button double-press leaves it and re-enters the effect cycle at the last-used
  effect. There is also a header book icon that opens the
  [user manual PDF](./user-manual.pdf) in a new tab (permanent GitHub Pages URL serving
  the PDF straight from this repo — same target as the sticker QR code), settings sheet (language, power-cut behaviour, network diagnostics,
  *Change Wi-Fi network*, MQTT kill switch when present, firmware version/update with
  *Check for updates now*; Install opens a full-screen update coach through reboot/reconnect; restart, factory reset, device info). The
  settings sheet is a bottom sheet capped at the same max width
  as the main view (`520px`), locks background scroll while open, and keeps extra right /
  bottom padding so the scroll indicator and home-indicator area stay clear.
- **Change Wi-Fi:** clears saved STA credentials, re-asserts the `Cloud-Lamp-XXXXXX` AP, and
  restarts the radio into AP + captive portal. The AP password is never changed or
  cleared — the sticker always remains a way back in. Other lamp settings are kept.
- **i18n:** English (default, US flag), German, Spanish, French, Italian, Dutch, Polish,
  Portuguese, Turkish, Russian — language dropdown with flags,
  persisted in the browser's localStorage. Effect names are localised via a display-name
  map in the app; the firmware always uses the English names as canonical identifiers.
- **Handler precedence:** `cloud_lamp_web` registers just before `web_server`, so it wins
  the `/` route while all REST routes fall through. While the captive portal is active the
  component instead serves `web/setup.html` for every GET except `/config.json` and
  `/wifisave` (which fall through to the stock captive-portal handlers), replacing the
  stock portal page with the branded onboarding UI.

Web app development without hardware: `python3 tools/mock-device.py` serves the app with a
simulated device API on `http://127.0.0.1:8932/`.

---

## Online updates (`packages/updates.yaml`)

See [firmware-updates.md](./firmware-updates.md) for the full workflow. Summary: the lamp
checks a manifest hosted in this GitHub repo (`firmware-dist/`, served via
raw.githubusercontent.com) every 6 h (or on demand via *Check for updates now*); when a
newer version is published the web app shows an *Install* button; the image is downloaded,
MD5-verified and written to the inactive flash area while the lamp keeps running;
`safe_mode` catches boot loops after a bad flash.
Settings are never touched by updates. Browser-upload OTA (`/update` on the stock ESPHome
page) and push OTA from the builder's machine remain available as fallbacks.

---

## Effects (`effects.yaml`)

The `effects:` list in `effects.yaml` is the **single source of truth** — the firmware reads
registered effects from the light component at runtime (`get_effects()`), so there is no
separate name list to keep in sync (the v1 `get_effects` global is gone). Order in the file
= button cycling order. Every tuning value (speeds, colours, probabilities) is a
substitution at the top of the file.

| Effect | Type | Character |
|---|---|---|
| White / Warm White / Latte Brown / Red / Yellow / Green / Cyan / Sky Blue / Blue / Violet | solid | Static colours, 250 ms refresh. Order: neutrals first (White = default cycle start), then the spectrum red → violet. Latte Brown = case PLA (Bambu Lab Matte `#D3B7A7`; DE Milchkaffee-Braun, ES Marrón Latte, FR Café au lait). Speed slider hidden. Indigo was removed in v2.1.5 (too dark on WS2812). |
| Sky Breathing | animated | Very slow blue↔cyan crossfade — the signature calm effect |
| Aurora Drift | animated | Slow-moving vivid teal→violet gradient with per-ring depth (saturated endpoints since v2.1.5 — the pastel pair washed out) |
| Candlelight | animated | Warm white with soft per-ring flicker |
| Night Light | solid | Very dim warm glow, gentle even at 100 % brightness. Speed slider hidden. |
| Twinkle | animated | Quiet starfield — ~1 soft spark/s, long fade; baby-lamp defaults |
| Color Wipe | animated | Soft sky colours, very slow sweep |
| Rainbow | animated | Full spectrum, slow hue drift |
| Pulse | animated | Pixel-level breathing between ~20 % and ~85 % (never overwrites saved brightness) |

### Effect Speed (`number.effect_speed`)

A persisted template number **1–100** (default **50** = substitution defaults in
`effects.yaml`). The web app shows a Speed slider only while an animated effect that
honours speed is active. Higher values shorten periods / increase spark rate; lower
values calm the motion. Solids and Night Light ignore it.

Effect names are case-sensitive canonical identifiers used by MQTT (`Set/Effect` /
`State/Effect`) and the REST API. When renaming an effect, update the display-name maps in
`web/app.html` (`FX_NAMES`, `FX_SWATCH`, `SPEED_FX`, `SOLID_FX`) as well. The web app
groups the grid into **Colors** (names in `SOLID_FX`) and **Special effects** (everything
else, including Night Light and unknown future effects). Note: the last-used effect is
persisted as an *index*, so reordering or removing effects shifts which effect a lamp
restores after its first update — harmless one-time cosmetic jump.

### Deferred idea: per-effect user presets

Store brightness + speed per effect in the preferences area and apply them whenever that
effect is selected (button, web app and MQTT alike, via the shared effect scripts). UI:
adjust the live sliders, then "Save as default for this effect" + per-effect reset.
Feasible and cheap (16×2 small values); needs a decision on brightness semantics (today
brightness is global and survives effect changes). Creating entirely *new* user effects is
not possible — effect algorithms are compiled in.

---

## MQTT design (`packages/mqtt.yaml`, optional)

Enable by uncommenting one line in the `packages:` block. Designed to never affect lamp
functionality: `reboot_timeout: 0s`, plus a persisted runtime kill switch (*MQTT Enabled*
in the web app settings) that silences MQTT without a reflash.

### Topic structure

All topics follow `${mqtt_topic_root}${mqtt_topic_device}/<subtree>/<name>`
(defaults resolve to `Cloud-Lamp/<subtree>/<name>`).

| Subtree | Direction | Purpose |
|---|---|---|
| `Set/` | ioBroker → device | Commands (retain: false — a stale retained command must never re-execute) |
| `State/` | device → ioBroker | Confirmed state (retain: true — subscribers always get the current value) |
| `Info/` | device → ioBroker | Metadata and availability |
| `Logging/` | device → ioBroker | Boot history and raw log lines |

### Full topic reference

| Topic | Direction | retain | QoS | Payload |
|---|---|---|---|---|
| `…/Set/On` | in | false | 1 | `"true"`/`"false"` (accepts true/on/1, case-insensitive) |
| `…/Set/Effect` | in | false | 1 | Effect name (case-sensitive; also turns the light on) |
| `…/Set/Brightness` | in | false | 1 | Integer 1–100 (0/out-of-range ignored) |
| `…/Set/Reboot` | in | false | 1 | `"true"` (guarded, see below) |
| `…/State/On` | out | true | 1 | `"true"`/`"false"` |
| `…/State/Effect` | out | true | 1 | Effect name, or `"Custom Color"` when a picked colour is active |
| `…/State/Brightness` | out | true | 1 | Integer 1–100 |
| `…/Info/Reachable` | out | true | 1 | `"online"`/`"offline"` (birth/LWT) |
| `…/Info/IP` | out | true | 1 | IP address |
| `…/Info/Uptime` | out | false | 1 | Seconds |
| `…/Info/WiFi_Signal` | out | false | 1 | dBm |
| `…/Logging/Last_Reboot` | out | true | 1 | `"YYYY-MM-DD HH:MM:SS"` |
| `…/Logging/Last_Reboot_Reason` | out | true | 1 | ESP reset reason |
| `…/Logging/Log` | out | false | 0 | Raw log line |

With the temperature package also enabled:
`…/Temperatures/Case_Temperature` (retain, QoS 1) and `…/Info/Emergency_Shutdown`
(retain, QoS 1).

### Reliability rules

- **QoS 1 everywhere except raw logs (QoS 0); every publish specifies `qos:` explicitly**
  (ESPHome silently defaults to QoS 0 — a v1-era bug class).
- **`clean_session: false`** — the broker queues QoS 1 commands while the lamp is offline.
- **State accuracy guarantee:** the device is the single source of truth. State is published
  on MQTT connect, after every command, and re-published every 10 s (info topics every
  60 s), always guarded by `mqtt.connected` so a broker-less lamp does no pointless work.
- **`Logging/Last_Reboot`** is published from `time.on_time_sync` (first sync after boot,
  retried on MQTT connect) — v1 published it 3 s after boot when SNTP/MQTT were rarely
  ready, silently losing the timestamp.
- **`Set/Reboot` retained-loop protection:** on reception the device immediately clears the
  topic on the broker (empty retained publish) and ignores commands arriving within 15 s of
  (re)connect. A stuck retained `"true"` can therefore never cause a reboot loop.

---

## Hardware

| Component | Specification |
|---|---|
| Microcontroller | Wemos D1 Mini (ESP8266), `d1_mini` |
| LED rings | 3× WS2812x rings (B09YRHLD8W), 24 LEDs total, GRB |
| LED data pin | GPIO03 (RX) via 330 Ω series resistor |
| Decoupling capacitor | 470 µF electrolytic across the 5 V rail |
| Power supply | External 5 V / 2 A DC adapter, barrel jack 5.5×2.1 mm, centre-positive (included with the lamp) |
| User input | Momentary push-button on GPIO12 (D6), internal pull-up, to GND |
| Optional | DS18B20 temperature sensor on GPIO4 (D2) |

**Power budget:** worst case (White, 100 %) ≈ 24 × 60 mA + 200 mA ESP ≈ **1.64 A** — within
the 2 A supply with margin.

**Power injection:** with 24 LEDs, feed 5 V/GND at **both ring 1 and ring 3** to avoid a
visible voltage drop on ring 3. Data flows one way only:
`GPIO03 → 330 Ω → ring 1 → ring 2 → ring 3`.

**Push-button wiring:** one leg to GPIO12, other to GND; the internal pull-up (~30–100 kΩ)
suffices for short in-case wire runs. 10 ms software debounce on both edges.

**Why GPIO03 (RX) for LED data:** the NeoPixelBus driver uses the UART peripheral, making
GPIO03 the most stable WS2812 pin on the ESP8266. The serial monitor is unavailable while
LEDs are connected.

**Color correction:** `color_correct: [100%, 75%, 60%]` on the light compensates the blue
tint of WS2812 white. Tune per hardware batch by eye; deliberately not a substitution since
it needs physical calibration.

---

## v1 → v2 changelog

v1 was a direct port of the hand-lamp firmware (single file + MQTT mandatory). v2 is a
restructure around the standalone-first principle. Key changes:

| Area | v1 | v2 |
|---|---|---|
| MQTT | Mandatory, `reboot_timeout` default (device rebooted without broker!) | Optional package, `reboot_timeout: 0s`, runtime kill switch |
| Wi-Fi | `reboot_timeout` default | `0s` — never reboot over Wi-Fi |
| Button | 1× toggle, 1.5 s hold = next effect (manual `millis()` tracking) | 1× toggle, 2× next effect, hold = dim, power-on-hold = factory reset (`on_multi_click`) |
| Brightness | MQTT-only, `brightness_persist` substitution | Button + web + MQTT; always persisted; `Power Behavior` select replaces the substitution |
| State handling | Parallel bookkeeping in globals + scripts | Light component is the single source of truth; globals only mirror |
| Effect list | Duplicated in `get_effects` lambda (maintenance trap) | Read from the light at runtime; `effects.yaml` list is the only definition |
| Solid-colour effects | Redrawn every 16 ms | 250 ms refresh |
| `Last_Reboot` publish | 3 s after boot (usually lost) | On first time sync, retried on MQTT connect |
| `Set/Reboot` | Unguarded (retained `true` = reboot loop) | Retained-clear + 15 s connect grace period |
| Web interface | None | Full iOS-style PWA + REST/SSE |
| Updates | Push OTA from builder only | + browser-upload OTA + pull updates from GitHub Pages with MD5 verification |
| Provisioning AP | `"Cloud-Lamp Backup WiFi"` | `"Cloud-Lamp-XXXXXX"` (6-hex MAC serial, matches sticker + `.local`) |
| Factory reset | None | Power-on-hold gesture + web app button |

The old effect set (Cyan, Blue, White, Indigo, Violet, Rainbow, Color Wipe, Twinkle, Pulse)
was retuned (much slower/calmer) and extended with Warm White, Latte Brown (case PLA),
Sky Blue, Sky Breathing, Aurora Drift, Candlelight, Night Light. Thunderstorm was removed
after on-device review.
