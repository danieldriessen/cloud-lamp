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

Releases are published by `tools/release.sh` (see
[Publishing a release](#publishing-a-release-builder-workflow) below) with a single
`git push` to `danieldriessen/cloud-lamp` (public), into the tracked
`docs/firmware-dist/` folder. That one folder serves two roles at once:

- **Release history and a manual-download fallback** — browsable on GitHub like any other
  tracked file.
- **The live update channel** — this repo's GitHub Pages site serves `docs/` directly at a
  custom domain (`${update_manifest_url}` in `cloud-lamp.yaml`), which is what the lamp
  itself actually fetches from. Plain HTTP, not HTTPS: see
  [Plain HTTP + Ed25519 signing](#plain-http--ed25519-signing) for why, and how the
  manifest's signature keeps this trustworthy anyway.

Because both roles are the same files in the same folder, there is nothing to keep "in
sync" — a `git push` updates the live endpoint and the history simultaneously.

**Public-safety rule:** released binaries are built exclusively from `cloud-lamp.yaml`
(the generic public build) — no personal names, no Wi-Fi networks, no MQTT credentials.
`tools/release.sh` refuses dev configs and additionally scans every binary for values from
`secrets.yaml` before packaging. Never publish a `cloud-lamp-dev.yaml` build.

1. Every 6 hours (and shortly after boot) the lamp downloads its manifest over plain HTTP
   from `${update_manifest_url}` and verifies its Ed25519 **signature** against the public
   key baked into the firmware (`ota_ed25519_pubkey` substitution) — a manifest that doesn't
   verify is treated exactly like a failed fetch, so nothing untrusted is ever surfaced as
   an update. The same check can be triggered on demand from Settings → Firmware →
   **Check for updates now** (REST: `POST /button/Check for Updates/press`, which runs
   `update.check` — the web-server API only exposes install, not check). REST paths use
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
- A successful update always resumes the lamp's exact on/off state from right before it —
  a deliberate reboot is detected separately from a genuine power cut and never applies
  the *Power Behavior* power-cut policy (which only governs an actual power cut). See the
  "Boot logic now distinguishes a deliberate reboot from a real power cut" changelog entry
  in [cloud-lamp-design.md](./cloud-lamp-design.md#project-status) for the full mechanism.
  A failed, aborted or canceled update never reboots at all, so the running lamp — and its
  on/off state — is simply untouched in those cases.

## Publishing a release (builder workflow)

1. Bump `project_version` in the `substitutions` block of the device's config.
2. Run `tools/release.sh`. In order, it:
   - compiles the public build and verifies the binary contains no secrets;
   - writes `docs/firmware-dist/cloud-lamp/` with the binary and `manifest.json` (MD5 +
     version);
   - **signs** the manifest with the Ed25519 private key (see
     [Plain HTTP + Ed25519 signing](#plain-http--ed25519-signing)) and adds the
     `signature` field;
   - **publishes**: commits + pushes `docs/firmware-dist/cloud-lamp/` to GitHub. That single
     push republishes the live update channel too, since GitHub Pages serves `docs/`
     directly — there is no separate upload step that can drift out of sync. Re-running the
     script is safe (same version/MD5/signature every time) if the push needs retrying.

The firmware is generic (lamps are personalised only by the physical front text), so **one
release channel serves every lamp**. Builder/dev lamps running `cloud-lamp-dev.yaml` should
be updated via push OTA instead — installing the public update on them would remove the
compiled-in Wi-Fi networks (MQTT is unaffected either way: it's part of the core firmware
on both builds and configured from the web app, not compiled in).

> Note: publishing the same version string twice is not offered to devices — always bump
> `project_version` first.

## GitHub Releases (human-facing downloads)

Separate from everything above, `tools/release.sh` also tags the release (`vX.Y.Z`) and
creates a **GitHub Release** with the `.bin` attached, via the `gh` CLI. This exists purely
for **humans** who want a specific version's firmware to flash manually (e.g. to their own
fork's device, or to roll back) — the lamp itself never looks at GitHub's Releases feature;
it only ever polls the signed manifest described above. The two mechanisms are unrelated
and can't drift out of sync with each other in a way that matters: the Release is just a
nicer, discoverable wrapper around a `.bin` that's already sitting in
`docs/firmware-dist/cloud-lamp/` regardless.

This step is skipped (with a warning, not a build failure) if `gh` isn't installed or
authenticated on the release machine — one-time setup: `brew install gh` (or see
[cli.github.com](https://cli.github.com)), then `gh auth login`. It never blocks the actual
OTA publish, which is the part devices depend on.

All versions through v2.5.1 were tagged, and are backfilled as Releases in one batch when
this feature was added; every release from then on gets one automatically as part of
`tools/release.sh`.

### HTTP host setup (one-time): GitHub Pages custom domain

The plain-HTTP host is this repo's own **GitHub Pages** site — no separate server, upload
credentials, or publish step to maintain. `docs/` is already the Pages source folder (it's
what serves [docs/user-manual.pdf](./user-manual.pdf) today), so `docs/firmware-dist/`
piggybacks on that exact same deployment:

```
cloud-lamp.ddproductions.de/        (custom domain → GitHub Pages → this repo's docs/)
└── firmware-dist/
    └── cloud-lamp/
        ├── manifest.json
        └── cloud-lamp-<version>.bin
```

**One-time setup, on GitHub:**

1. Repo → **Settings → Pages**. Leave **Source** as the `docs/` folder on `main` (already
   configured for the manual — do *not* change it to `/ (root)`, that would require moving
   every doc and break the manual's existing URL).
2. Under **Custom domain**, enter `cloud-lamp.ddproductions.de` and save. GitHub writes a
   `docs/CNAME` file into the repo recording this.
3. Leave **Enforce HTTPS** *unchecked*. This is the one setting that matters for the
   ESP8266: checking it would make Pages 301-redirect all `http://` requests to `https://`,
   which defeats the entire point (see
   [Plain HTTP + Ed25519 signing](#plain-http--ed25519-signing)). Leaving it off still lets
   humans reach the manual over HTTPS if they type it that way — it only stops Pages from
   *forcing* the upgrade.

**One-time setup, at the DNS host (all-inkl.com/KAS, `ddproductions.de`):**

4. Add a **CNAME** record: `cloud-lamp` → `danieldriessen.github.io`. (All-inkl.com was
   originally set up to serve this itself, but every `http://` request to a subdomain there
   was unexpectedly 301-redirected to `https://` regardless of KAS panel SSL settings — an
   Apache-level behavior outside our control that defeats plain-HTTP serving. GitHub Pages
   doesn't have that problem, so hosting moved there instead; the previously-configured
   SSL/force-SSL settings on the `cloud-lamp` subdomain and the parent domain can be
   reverted to their normal, secure defaults.)
5. Wait for DNS propagation (can take anywhere from minutes to a few hours), then verify:
   `curl -v http://cloud-lamp.ddproductions.de/firmware-dist/cloud-lamp/manifest.json`
   should return `200` with no redirect, over plain HTTP. **Done and confirmed** for this
   project's domain — that exact command returns `200` over plain HTTP today.

That same path must be reachable at the `update_manifest_url` configured in
`cloud-lamp.yaml`'s substitutions (it already is — no config change needed once the domain
resolves).

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
        "signature": "<128-hex-char Ed25519 signature, see below>",
        "summary": "Cloud-Lamp firmware 2.1.0"
      }
    }
  ]
}
```

`path` is resolved relative to the manifest URL. `release_url` and `summary` are optional
and shown by the update entity where supported. `signature` is **required** —
`components/signed_update/` rejects any manifest missing it (or failing verification)
exactly as if the fetch itself had failed.

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
   [`docs/firmware-dist/cloud-lamp/`](../docs/firmware-dist/cloud-lamp/) in this repo (the file named
   in `manifest.json`'s `path`), then open `http://<lamp-ip-or-hostname>/update` (the stock
   ESPHome upload page) and upload it there. This bypasses the online-update check
   entirely, so it works regardless of the bug above.
3. **Push OTA** (`esphome run cloud-lamp.yaml`, builder only, same network) — also bypasses
   the check entirely.

Once the lamp is running v2.3.1 or newer, both the automatic and manual checks are
protected against this contention (see `packages/updates.yaml`) and this should not recur.

## Update install succeeds but the lamp goes dark / re-opens its setup Wi-Fi

Reproduced on real hardware (not yet fully root-caused — see the v2.6.0 entry in
[cloud-lamp-design.md](./cloud-lamp-design.md#project-status)): the web app
shows **"Update failed"**, but the download, verification, and flash write actually
completed successfully. What happens is the
*freshly-flashed* firmware fails to reconnect to the home Wi-Fi network and falls back to
its own setup hotspot (`Cloud-Lamp-XXXXXX`) instead — invisible to the web app, since it's
no longer on the same network, so its 3-minute wait just times out and shows the generic
failure. A power-cycle does **not** fix this on its own.

Recovery: check whether your phone can see a **`Cloud-Lamp-XXXXXX`** Wi-Fi network again
(the lamp's own setup hotspot). If so, reconnect it exactly like initial setup — connect to
it, then either wait for the configuration page to open automatically or open
`http://192.168.4.1` and re-enter your home Wi-Fi password (see
[user-manual.md §5](./user-manual.md)). The lamp should then come back online at its usual
address, already running the new firmware — no data is lost except locally-stored settings
(Power Behavior, MQTT config, on/off state), which reset to defaults if this happens on the
very first time the lamp boots a version with `esp8266: restore_from_flash: true` (v2.5.0+)
after coming from an older one — reconfigure those in Settings afterwards.

So far this has only been confirmed on a v2.4.0 → v2.5.1 jump. It's not yet known whether
it also affects smaller version jumps (e.g. any update once already running v2.5.0+).

## Update shows "Update failed" but actually succeeded (no AP-fallback)

A **different** failure mode from the one above — reported right after publishing v2.6.0
(see the "not yet released" entry right above the v2.6.0 one in
[cloud-lamp-design.md](./cloud-lamp-design.md#project-status)). Here the lamp reconnects to
the *correct* home Wi-Fi the whole time (no setup hotspot reappears), but the web app's
install coach still shows **"Update failed"** and offers "Try again" — checking
Settings → Firmware afterwards shows the new version is already installed and running.

Root cause: the coach's total budget for install + reboot + Wi-Fi reassociation
(`FW_TIMEOUT_MS` in `web/app.html`) was 3 minutes, and real-hardware reconnection has now
been observed occasionally taking a bit longer than that even on a completely normal
update — the coach had already given up and stopped polling by the time the lamp came
back online with the new version. Fixed by raising the budget to 5 minutes; a genuinely
stuck lamp (the AP-fallback case above) still times out, just a couple of minutes later.

If you see "Update failed" after an update that felt slower than usual: check
**Settings → Firmware → Installed version** before assuming anything is wrong or trying
again — it may already show the version you just installed.

## Plain HTTP + Ed25519 signing

Through v2.3.4, the manifest and firmware were fetched over HTTPS with `verify_ssl: false`
(TLS-encrypted, certificate unvalidated — the ESP8266's BearSSL stack has no CA store).
That transport turned out to be the update mechanism's real reliability problem, not just a
security trade-off:

- **The root cause, confirmed on hardware:** BearSSL needs roughly **16-20 KB of
  *contiguous* free heap** to complete a TLS handshake against GitHub's CDN — far more than
  the nominal ~8.7 KB RX/TX buffer size suggests. Direct heap instrumentation during a real
  failure showed 12-17 KB free contiguous heap *still* wasn't enough; the SSL context, X.509
  validator and I/O buffers together exceed what this device reliably has alongside the web
  server and (when enabled) MQTT. This is what caused the "update failed, previous firmware
  still running" and "stuck on an old version" issues described elsewhere in this doc — the
  safety net was always working correctly, but the underlying HTTPS transport had a memory
  ceiling this device couldn't reliably clear.
- Raising the TLS buffers further (16 KiB is ESPHome's own textbook recommendation) OOMs
  even sooner on the MQTT-enabled bench build, and GitHub/Fastly's CDN doesn't honor MFLN
  (Maximum Fragment Length Negotiation) at the buffer sizes tried, so there was no buffer
  size that reliably worked.

**Fix:** drop TLS entirely for OTA (both manifest and firmware download are plain HTTP now)
and compensate with an **Ed25519 signature** over the manifest, verified on-device
(`components/signed_update/`) before anything is ever trusted as an update. This is
strictly *stronger* authenticity than the old `verify_ssl: false` HTTPS ever provided (which
trusted the transport but validated no certificate — an on-path attacker had exactly as much
power then as with plain HTTP now, just with TLS overhead and none of the memory cost). The
firmware binary's integrity is still additionally checked by MD5 as before.

**Signed message:** the manifest's `signature` field is an Ed25519 signature (128 hex
chars / 64 bytes) over the fixed ASCII string `"<version>|<path>|<md5>"` — not the raw
manifest JSON bytes, to avoid JSON-canonicalization edge cases. Binding all three fields
together prevents replaying an old-but-validly-signed manifest entry against a different
binary or version number.

### Key custody

- **Private key** — generated once, lives **outside this repository entirely**, by default
  at `~/.cloud-lamp-release-secrets/ota-ed25519-private.key` (32 raw bytes; override the
  path with the `RELEASE_SIGNING_KEY` environment variable). Never commit it, and back it up
  somewhere durable — losing it means you can no longer publish trusted updates to devices
  already in the field without also changing their public key (i.e. flashing them, which
  defeats the purpose of online updates).
- **Public key** — not a secret; compiled into every device via `cloud-lamp.yaml`'s
  `ota_ed25519_pubkey` substitution (32 bytes, hex). Only the matching private key can
  produce a signature that verifies against it.
- To generate a new keypair (e.g. for initial setup, or a deliberate rotation), from a
  Python environment with the `cryptography` package installed (already a dependency of
  `tools/release.sh`):

  ```python
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
  from cryptography.hazmat.primitives import serialization

  key = Ed25519PrivateKey.generate()
  open("ota-ed25519-private.key", "wb").write(key.private_bytes(
      encoding=serialization.Encoding.Raw,
      format=serialization.PrivateFormat.Raw,
      encryption_algorithm=serialization.NoEncryption(),
  ))
  print(key.public_key().public_bytes(
      encoding=serialization.Encoding.Raw,
      format=serialization.PublicFormat.Raw,
  ).hex())
  ```

  Save the private key file with restrictive permissions (`chmod 600`) outside any synced
  or version-controlled folder, and put the printed public key hex into
  `ota_ed25519_pubkey` in `cloud-lamp.yaml`. **Rotating the key requires re-flashing every
  device already in the field** (via push OTA or browser upload) with a build compiled
  against the new public key before it will trust any future signed release — plan
  accordingly, this isn't something to do casually.

### Local testing without hardware

`tools/mock-device.py` serves a validly-signed test manifest (signed with a throwaway,
dev-only keypair hardcoded in that script — never the real production key) at
`/firmware-dist/cloud-lamp/manifest.json`, standing in for the plain-HTTP host. To exercise
the real on-device `components/signed_update/` logic against it (not just the web app's own
simulated update-entity behavior), point a diagnostic build's `update_manifest_url` at
`http://<this-machine's-LAN-IP>:<port>/firmware-dist/cloud-lamp/manifest.json` and its
`ota_ed25519_pubkey` at the `OTA_TEST_PUBLIC_KEY_HEX` constant in that script.
