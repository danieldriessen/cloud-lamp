# Cloud-Lamp — Firmware Updates

How updates reach a lamp that lives in someone else's home, and how the builder publishes
them. Configured in `packages/updates.yaml`; user-facing UI in the web app's settings sheet.

---

## The three update paths

| Path | Who | How |
|---|---|---|
| **Online update** (primary) | End user | Web app → Settings → Firmware → *Check for updates now* / *Install update* |
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
   (the `update_manifest_url` substitution). The same check can be triggered on demand from
   Settings → Firmware → **Check for updates now** (REST: `POST /button/Check for Updates/press`,
   which runs `update.check` — the web-server API only exposes install, not check). REST paths use
   the entity's display Name, URL-encoded (e.g. `Check%20for%20Updates`) — the legacy object_id
   form (`check_for_updates`) still works today but is deprecated and is removed in ESPHome 2026.7.0.
2. If the manifest version differs from the installed `${project_version}`, the web app
   shows an **Update available** badge next to the "Connected" pill in the header (visible
   without opening Settings — tapping it jumps straight to Settings → Firmware), plus the
   same badge and an **Install** button inside Settings → Firmware itself.
3. On install, the web app opens a full-screen **update coach** (installing → restarting →
   waiting → done / failed). The lamp downloads the firmware image (the `path` in the
   manifest is resolved relative to the manifest URL, so the `.bin` sits next to it),
   verifies its **MD5 checksum**, writes it to the inactive flash area, and reboots into
   it. On ESP8266 the download blocks the main loop, so the web UI freezes until reboot —
   the coach treats that disconnect as the restart phase and polls until the lamp returns.
4. Important limitation: ESPHome's **web REST API does not expose download progress or
   error strings** for update entities (only the native API does). A failed install used
   to look like “nothing happened”; the coach now detects a silent return to
   `UPDATE AVAILABLE` while still online and shows **Update failed**.

An unreachable manifest URL is harmless — the check fails silently and the lamp keeps
running (relevant for lamps in homes without internet, or before a device's first release
is published). "Silently" is literal: a failed check leaves the **Firmware** entity exactly
as it was (current version, latest version, everything) — there is no error state exposed
anywhere the web app can see, so it keeps showing whatever the *last successful* check
found. Since v2.3.1, both the manual check and the periodic one guard against the one
realistic cause of a check failing while the lamp is otherwise online — see the "Reliability
note" in `packages/updates.yaml` and [below](#stuck-on-an-old-version-with-up-to-date-showing)
if you hit this on a lamp still running an older firmware.

## Why an update cannot brick the lamp

- Download or power failure mid-update → the old firmware still boots (the new image only
  replaces the old one after complete, verified reception).
- Corrupted download → MD5 mismatch, image discarded, old firmware keeps running.
- New firmware boot-loops → `safe_mode` catches it after 5 attempts and keeps Wi-Fi + OTA
  alive so a fixed image can be pushed.
- User settings (Wi-Fi credentials from the captive portal, brightness, effect, power
  behaviour, MQTT switch/broker/port/username/password) live in the preferences area,
  **outside** the firmware image, and survive every update. Global/entity IDs are kept
  stable across versions so stored values stay attached.

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
compiled-in Wi-Fi networks (MQTT is unaffected either way: it's part of the core firmware
on both builds and configured from the web app, not compiled in).

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

## Stuck on an old version with "Up to date" showing

If a lamp keeps reporting "Up to date" at an old version even though a newer release is
published (confirmed live, e.g. with `curl` against the manifest URL above) and pressing
**Check for updates now** doesn't change anything: the lamp is almost certainly running a
firmware older than **v2.3.1**, which had a real bug — the manifest *check* silently failed
due to ESP8266 heap contention with the web app's own open connection (see the v2.3.1
changelog entry in [cloud-lamp-design.md](./cloud-lamp-design.md#project-status)) — and,
critically, **a lamp already stuck like this cannot reliably fix itself via the web app**,
because it is still running that same old, unfixed check logic until it actually updates.
Recovery, in order of preference:

1. **Power-cycle the lamp and wait ~1 minute *before* opening the web app.** The firmware
   automatically checks for updates within the first minute after Wi-Fi connects — with no
   browser tab open yet, there's no competing SSE connection, which is what made the bug
   most likely to hit on a manual "Check for updates now" in the first place. Then open the
   app; if the check succeeded, **Update available** should already be showing.
2. **Browser upload OTA**, if step 1 doesn't help: download the latest `.bin` from
   [`firmware-dist/cloud-lamp/`](../firmware-dist/cloud-lamp/) in this repo (the file named
   in `manifest.json`'s `path`), then open `http://<lamp-ip-or-hostname>/update` (the stock
   ESPHome upload page) and upload it there. This bypasses the online-update check
   entirely, so it works regardless of the bug above.
3. **Push OTA** (`esphome run cloud-lamp.yaml`, builder only, same network) — also bypasses
   the check entirely.

Once the lamp is running v2.3.1 or newer, both the automatic and manual checks are
protected against this contention (see `packages/updates.yaml`) and this should not recur.

## TLS note

The ESP8266's BearSSL stack has no CA certificate store, so the manifest/firmware download
uses `verify_ssl: false`: transport is TLS-encrypted but the server certificate is not
validated. Integrity of the installed firmware is enforced end-to-end by the manifest MD5;
an attacker able to spoof GitHub DNS could at worst offer a manifest the user must still
manually install. Accepted trade-off for this device class.

`packages/updates.yaml` also sets `tls_buffer_size_rx: 8192`. Without an enlarged buffer,
fetches from `raw.githubusercontent.com` fail with BearSSL `BR_ERR_TOO_LARGE` (GitHub/Fastly
use large TLS records; the ESP8266 default 512-byte buffer is too small). 16 KiB is the
textbook size but OOMs on the MQTT-enabled bench build; 8 KiB is enough in practice here.
