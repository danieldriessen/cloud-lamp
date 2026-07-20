# Cloud-Lamp — Firmware Updates

How updates reach a lamp that lives in someone else's home, and how the builder publishes
them. Configured in `packages/updates.yaml`; user-facing UI in the web app's settings sheet.

---

## The three update paths

| Path | Who | How |
|---|---|---|
| **Online update** (primary) | End user, one tap | Web app → Settings → Firmware → *Install update* |
| Browser upload | Builder / power user | `http://<lamp-ip>/update` (stock ESPHome page), upload a `.bin` |
| Push OTA | Builder, same network | `esphome run cloud-lamp.yaml` (uses the shared OTA password) |

## How the online update works

Releases are hosted **in this GitHub repository** (`danieldriessen/cloud-lamp`, public)
inside the tracked `firmware-dist/` folder and served via `raw.githubusercontent.com` — no
GitHub Pages setup or separate repo needed.

**Public-safety rule:** released binaries are built exclusively from `cloud-lamp.yaml`
(the generic gift build) — no personal names, no Wi-Fi networks, no MQTT credentials.
`tools/release.sh` refuses dev configs and additionally scans every binary for values from
`secrets.yaml` before packaging. Never publish a `cloud-lamp-dev.yaml` build.

1. Every 6 hours (and shortly after boot) the lamp downloads its manifest from
   `https://raw.githubusercontent.com/danieldriessen/cloud-lamp/main/firmware-dist/cloud-lamp/manifest.json`
   (the `update_manifest_url` substitution).
2. If the manifest version differs from the installed `${project_version}`, the web app
   shows an **Update available** badge and an **Install** button.
3. On install, the lamp downloads the firmware image (the `path` in the manifest is
   resolved relative to the manifest URL, so the `.bin` sits next to it), verifies its
   **MD5 checksum**, writes it to the inactive flash area, and reboots into it. The lamp
   keeps working during the download.

An unreachable manifest URL is harmless — the check fails silently and the lamp keeps
running (relevant for lamps in homes without internet, or before a device's first release
is published).

## Why an update cannot brick the lamp

- Download or power failure mid-update → the old firmware still boots (the new image only
  replaces the old one after complete, verified reception).
- Corrupted download → MD5 mismatch, image discarded, old firmware keeps running.
- New firmware boot-loops → `safe_mode` catches it after 5 attempts and keeps Wi-Fi + OTA
  alive so a fixed image can be pushed.
- User settings (Wi-Fi credentials from the captive portal, brightness, effect, power
  behaviour, MQTT switch) live in the preferences area, **outside** the firmware image, and
  survive every update. Global/entity IDs are kept stable across versions so stored values
  stay attached.

## Publishing a release (builder workflow)

1. Bump `project_version` in the `substitutions` block of the device's config.
2. Run `tools/release.sh` — it compiles the public build, verifies the binary contains no
   secrets, and writes `firmware-dist/cloud-lamp/` with the binary and `manifest.json`
   (with MD5).
3. Commit and push:
   `git add firmware-dist/cloud-lamp && git commit -m "Release cloud-lamp vX.Y.Z" && git push`

The firmware is generic (lamps are personalised only by the physical front text), so **one
release channel serves every lamp**. Builder/dev lamps running `cloud-lamp-dev.yaml` should
be updated via push OTA instead — installing the public update on them would remove the
compiled-in Wi-Fi networks and MQTT.

> Note: publishing the same version string twice is not offered to devices — always bump
> `project_version` first.

### Manifest format

```json
{
  "name": "Cloud Lamp (cloud-lamp)",
  "version": "2.1.0",
  "builds": [
    {
      "chipFamily": "ESP8266",
      "ota": {
        "path": "cloud-lamp-2.1.0.bin",
        "md5": "<md5 of the bin>",
        "summary": "Cloud-Lamp firmware 2.1.0"
      }
    }
  ]
}
```

`path` is resolved relative to the manifest URL. `release_url` and `summary` are optional
and shown by the update entity where supported.

## TLS note

The ESP8266's BearSSL stack has no CA certificate store, so the manifest/firmware download
uses `verify_ssl: false`: transport is TLS-encrypted but the server certificate is not
validated. Integrity of the installed firmware is enforced end-to-end by the manifest MD5;
an attacker able to spoof GitHub DNS could at worst offer a manifest the user must still
manually install. Accepted trade-off for this device class.
