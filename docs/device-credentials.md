# Cloud-Lamp — Device Credentials & Sticker Reference

This file documents how credentials are handled across all cloud-lamp builds and what
goes on the product sticker. Only deliberately public values (the sticker AP password)
appear literally in this document; everything else lives in the git-ignored
`secrets.yaml` (template: `secrets.example.yaml`).

---

## Product sticker (back of every lamp)

Each lamp gets a sticker with everything the recipient needs for Wi-Fi setup:

| Field | Value | Where it comes from |
|---|---|---|
| Device name | `Cloud-Lamp` | Generic on purpose — lamps are personalised only by the physical front text |
| Setup Wi-Fi | `Cloud-Lamp-XXXX` | Generated at runtime; XXXX = last 4 hex digits of the chip MAC, uppercase |
| Wi-Fi password | `cloud-lamp` | Shared across all devices (see below) |

To read the serial for the sticker before assembly: boot the device once and check the log
line `Setup hotspot SSID: Cloud-Lamp-XXXX`, or open `http://<lamp-ip>/device.json` (field
`serial`). The same serial is shown in the web app under Settings → About.

---

## Setup hotspot (captive portal)

If the lamp cannot connect to any known Wi-Fi network, it opens its own access point:

- **SSID:** `Cloud-Lamp-XXXX` (per-device, printed on the sticker)
- **Password:** `cloud-lamp` (same on every device, printed on the sticker)

**Setup / recovery steps for the end user:**

1. Wait ~1 minute after powering on (or after the home Wi-Fi password changed)
2. Connect a phone to the lamp's Wi-Fi using the password from the sticker
3. A configuration page opens automatically (or go to `192.168.4.1`)
4. Enter the home Wi-Fi credentials and save
5. The lamp connects; the web app is then reachable at the lamp's IP (or via
   `http://<device_name>.local/`)

The lamp keeps working as a normal lamp (button control) the entire time — it never
reboots or blocks because Wi-Fi is unavailable.

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
