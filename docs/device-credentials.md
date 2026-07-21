# Cloud-Lamp — Device Credentials & Sticker Reference

This file documents how credentials are handled across all cloud-lamp builds and what
goes on the product sticker. Only deliberately public values (the sticker AP password)
appear literally in this document; everything else lives in the git-ignored
`secrets.yaml` (template: `secrets.example.yaml`).

---

## Product sticker (back of every lamp)

The printable label is maintained in [`Label.lbx`](./Label.lbx) (Brother P-Touch Editor
file). Keep it in sync with the field lists below; the user manual's sticker table
(user-manual.md §2) must match whatever the printed label actually contains.

**Final layout** (as printed): a `DD Productions` / cloud-lamp wordmark header, then
`Model: CL-1`, `S/N: <serial>`, `Hostname: http://cloud-lamp-<serial>.local`,
`WiFi-Passw.: cloud-lamp`, `Power-Supply: 5V ⎓ 2A` with a centre-positive barrel-jack
polarity icon, and a QR code captioned `Manual`. `Hostname` is printed with the `http://`
scheme already included, so the recipient can type or read it straight off the sticker —
required for iOS Safari to treat it as an address instead of a search, and one less thing
to explain in the manual. One consequence of this exact layout that the user manual has
to compensate for (see user-manual.md §2 and §5):

- **No separate setup-hotspot line.** The setup Wi-Fi network name (`Cloud-Lamp-XXXXXX`)
  is not printed literally — only the bare serial (`S/N`). The manual instructs the
  recipient to prefix `Cloud-Lamp-` to the printed `S/N` themselves.

### Required — without these a recipient cannot recover the lamp

| Field on the sticker | Value | Why it must be printed |
|---|---|---|
| `S/N` | last 6 hex digits of the chip MAC, uppercase (e.g. `CFB911`) | Doubles as the setup-hotspot SSID suffix (`Cloud-Lamp-CFB911`) and the `Hostname` suffix — the one parent code recipients need for onboarding and recovery |
| `WiFi-Passw.` | `cloud-lamp` | Password for the setup hotspot; shared across all devices — not discoverable anywhere else |
| `Hostname` | `http://cloud-lamp-<serial>.local` | The lamp's remote-control address once it's on the home Wi-Fi, printed with the `http://` scheme so recipients can type it exactly as shown — required for iOS Safari to treat it as an address instead of a search |
| `Manual` QR code | `https://danieldriessen.github.io/cloud-lamp/user-manual.pdf` | Safety information, button gestures and troubleshooting when the web app is unreachable. Same URL on every lamp; the manual (PDF) always describes the latest firmware. GitHub Pages serves the PDF directly in the browser with a real `application/pdf` type (GitHub's own blob/raw URLs either download it or wrap it in the GitHub UI) |

### Recommended

| Field on the sticker | Value | Why |
|---|---|---|
| `Model` | `CL-1` | Model designation for this product line; useful for support / future variants |
| `DD Productions` header | wordmark + `© 2026 DD Productions` | Identifies the maker; the manual says "contact the builder" |
| `Power-Supply` | `5V ⎓ 2A` + centre-positive barrel-jack polarity icon | Prevents a recipient from using the wrong replacement adapter (see the corrected power-supply description below — it is a DC barrel-jack adapter, not USB) |

### Optional (nice to have, all recoverable elsewhere)

- Production date or lamp number
- Full MAC address — visible in the web app under Settings → About

### Leave off

- **Firmware version** — goes stale with the first OTA update (the web app shows it)
- **Any non-public credential** (OTA password, MQTT, builder Wi-Fi)

To read the serial for the sticker before assembly: boot the device once and check the log
line `Setup hotspot SSID: Cloud-Lamp-XXXXXX`, or open `http://<lamp-ip>/device.json` (field
`serial`). The same serial is shown in the web app header and under Settings → About. The
hostname is in the same JSON (`hostname`) and under Settings → About → Hostname.

**One parent code:** sticker AP, web-app header and `.local` address all use the same last
six MAC hex digits (e.g. `Cloud-Lamp-CFB911` ↔ `cloud-lamp-cfb911.local`). That is
16 777 216 values — enough that multiple lamps on one network do not collide. The full MAC
(Settings → About) remains the definitive unique ID. Captive-portal onboarding still uses
the sticker hotspot / `192.168.4.1`.

---

## Setup hotspot (captive portal)

If the lamp cannot connect to any known Wi-Fi network, it opens its own access point:

- **SSID:** `Cloud-Lamp-XXXXXX` (per-device; `XXXXXX` = the `S/N` printed on the sticker,
  with `Cloud-Lamp-` prefixed — the sticker does not print the full SSID as its own line)
- **Password:** `cloud-lamp` (same on every device, printed on the sticker as `WiFi-Passw.`)

**Setup / recovery steps for the end user:**

1. Wait ~1 minute after powering on (or after the home Wi-Fi password changed)
2. Connect a phone to the lamp's Wi-Fi — `Cloud-Lamp-` followed by the `S/N` on the
   sticker — using the `WiFi-Passw.` from the sticker
3. A configuration page opens automatically (or go to `192.168.4.1`)
4. Enter the home Wi-Fi credentials and save
5. The lamp connects; the web app is then reachable at the lamp's IP (or via
   `http://cloud-lamp-<mac6>.local/`, same serial as the sticker)

The lamp keeps working as a normal lamp (button control) the entire time — it never
reboots or blocks because Wi-Fi is unavailable.

> **iOS / iPadOS note (required once per device):** before *Add to Home Screen*, disable
> *Settings → Apps → Safari → Not Secure Connection Warning*, then open the lamp by
> typing its `http://cloud-lamp-….local/` address (with `http://`) in Safari and add it
> from there. Leaving that Safari setting on makes iOS refuse the home-screen app with an
> "HTTPS-Only" / "HTTP is only" error — the lamp cannot serve HTTPS (see the design doc).

The AP password is stored in the `wifi_ap_password` substitution in `cloud-lamp.yaml`
(deliberately not in `secrets.yaml` — it is public on every sticker).

---

## OTA update password (builder push updates)

The same OTA password is used on every cloud-lamp device, so the builder can push firmware
to any device without per-device bookkeeping. The value lives **only in `secrets.yaml`**
(key `ota_password`, referenced via `!secret ota_password`) — it is deliberately not
written down in this public document. End users never need it; they update via the web app
instead (see [firmware-updates.md](./firmware-updates.md)).

> Threat-model note: the OTA password is embedded in the published firmware binaries and
> is therefore extractable by a determined attacker. It only gates push-flashing from
> inside the lamp's own Wi-Fi network and exists mainly to prevent accidental
> cross-flashing between own projects — it is not a hard security boundary, and nothing
> else relies on it.

---

## Builder hotspot (dev builds only)

**Gift lamps (public `cloud-lamp.yaml` build) contain NO compiled-in Wi-Fi networks at
all** — their binaries are published in the public repo, so no credentials may be embedded.
Recipients connect them exclusively via the captive portal; those credentials are stored in
the preferences flash area and survive every OTA update.

The builder's dev build (`cloud-lamp-dev.yaml`) additionally compiles in two networks from
`secrets.yaml`:

1. `wifi_ssid_user` / `wifi_password_user` — the home network of the current bench setup.
2. `wifi_ssid_builder` / `wifi_password_builder` — the builder's own Wi-Fi, usable as an
   OTA rescue: bring a hotspot with these credentials into range and the lamp connects.

These credentials are **never shared with the end user** and dev binaries are **never
published** (`tools/release.sh` enforces this with a binary scan).

---

## MQTT broker

Only relevant when `packages/mqtt.yaml` is enabled (never for gift lamps). Broker address,
port, username and password are set per-installation in `secrets.yaml`. There is no shared
default.
