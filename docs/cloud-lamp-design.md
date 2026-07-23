# Cloud-Lamp — Design Document

This document describes the design of the **cloud-lamp** firmware (v2). It covers the
architecture, the button and boot behaviour, the web app, the MQTT integration (always
included, OFF by default), and the hardware. Historical context from the predecessor project lives in
[hand-lamp-reference.md](./hand-lamp-reference.md); the v1 → v2 rewrite rationale is
summarised in [the changelog section](#v1--v2-changelog) at the end.

Related documents:

- [README.md](../README.md) — public project overview, features, getting started
- [user-manual.pdf](./user-manual.pdf) — end-user manual, PDF (permanent URL: sticker QR code + web-app book icon); source: [user-manual.md](./user-manual.md), rebuilt with `tools/build-manual.py`
- [device-credentials.md](./device-credentials.md) — shared passwords, AP naming, sticker contents
- [firmware-updates.md](./firmware-updates.md) — online update workflow and release process

---

## Project status

> **Phase:** v2.6.0 — a batch of captive-portal fixes/polish plus interim mitigations and
> tuning, no architecture changes. Highlights (each has its own detailed entry further
> down this section): **(1)** a real bug fix — the branded Wi-Fi onboarding page
> (`web/setup.html`) was silently being shadowed by ESPHome's own unbranded stock captive
> portal on some boots, due to a handler-registration race; `cloud_lamp_web`'s setup
> priority raised above both `wifi` and `captive_portal` so it always wins. **(2)** the
> captive portal now has its own language dropdown (same 10 languages as the app, English
> default) instead of silently auto-detecting the phone's OS language. **(3)** an interim
> mitigation for a real-hardware OTA update failure (v2.4.0 → v2.5.1): the update itself
> succeeds, but the lamp can lose its Wi-Fi pairing and fall back to its own setup hotspot
> on that specific version jump (root cause not fully confirmed, suspected first-ever
> `restore_from_flash` write) — the in-app failure message now explains how to recover via
> the captive portal. **(4)** Ring Ripple's inter-ripple pause shortened (was reading as
> "did it turn off?") and Candlelight's flicker amplitude restored (had become an
> almost-static colour after the previous tuning pass). **(5)** three small web-app fixes:
> mobile header badge order (Connected always above Update available), title/serial
> truncation when the update badge is shown, and the update-available badge not appearing
> until a manual check (delayed the first automatic check past boot-time Wi-Fi/MQTT
> contention). Verified: (1)-(2) live on real hardware; (3)-(5) browser/compile-verified
> only, not yet re-tested on real hardware as this exact release build. See
> [Behaviour reference](#behaviour-reference) and [Effects](#effects-effectsyaml) for the
> resulting current-state reference; the entries below are the as-built record.
>
> **Phase:** v2.6.1 — real-hardware report right after publishing v2.6.0: the
> update *did* succeed (the lamp reconnected to the home Wi-Fi normally, no AP-fallback,
> and correctly reports `2.6.0` afterwards) but the web app's install coach (`web/app.html`)
> showed **"Update failed"** anyway and offered "Try again". Root cause: `FW_TIMEOUT_MS`
> (180000, 3 min) is a single hard deadline covering the *entire* install+reboot+Wi-Fi-
> reassociation journey from the moment Install is tapped; `tickFwCoach()` checks it first
> on every 1 s tick and declares failure unconditionally once it elapses, with no final
> reachability check first. This is a **different** bug from the v2.4.0 → v2.5.1
> AP-fallback failure documented below — here the lamp reconnects to the *correct* network
> the whole time, it just occasionally takes longer than 3 minutes end-to-end on real
> hardware, and the coach had already given up (and stopped polling) by the time it came
> back. Fix: raised `FW_TIMEOUT_MS` to 300000 (5 min) — cheap and safe, since a genuinely
> stuck lamp still times out, just later. Also reworded `fw_hint_fail` (all 10 languages)
> to stop asserting "the previous firmware is still running" (which this incident showed
> can be flat wrong) and instead point at Settings → Firmware's "Installed version" first,
> since that's now a known way for this exact failure mode to resolve itself. JS syntax-
> checked; not yet re-tested against an update slow enough to exercise the new 5 min
> ceiling on real hardware.
>
> **Phase:** v2.6.0 — found and fixed the real cause of a report that the
> captive-portal Wi-Fi onboarding page "looks basic" when opened via the setup hotspot.
> Ruled out CSS/CNA-sandbox theories first (the page renders fully styled in
> `tools/mock-device.py`, and identically in real Safari and in the iOS setup-hotspot
> popup — so it's not a rendering-environment issue). Live `curl` against a real lamp
> stuck in AP-fallback proved it conclusively: **every** path (`/`, `/app`,
> `/manifest.json`, `/device.json`, `/brand.png`) returned the exact same bytes — a
> byte-for-byte match (verified by decompressing ESPHome's own `captive_index.h`) for the
> **stock, unbranded** ESPHome captive-portal page. `web/setup.html` wasn't being served at
> all. Root cause: `cloud_lamp_web`'s `AsyncWebHandler` and ESPHome's stock
> `captive_portal` handler share one `AsyncWebServer`; whichever registers first wins for
> *every* matching request (`AsyncWebServer::_attachHandler` stops at the first
> `canHandle()==true`, in registration order) — captive_portal's own `canHandle()` matches
> any GET unconditionally while active, so if it registers before `cloud_lamp_web`, it
> shadows it completely, not just for `/`. `cloud_lamp_web::setup()` normally *does* run
> first (its priority `WIFI - 0.5` vs. captive_portal's `WIFI + 1.0` — higher runs later —
> only matters when captive_portal starts the *usual* way: dynamically, from `loop()`,
> long after every component's `setup()` has already run, if the STA connection fails).
> But `WiFiComponent::setup()` has a second, synchronous path: if it finds no usable saved
> STA credentials (`has_sta()` false right after trying to load them from flash), it calls
> `captive_portal::start()` **immediately**, still inside `setup()`, at priority `WIFI`
> (250) — *before* `cloud_lamp_web` (`WIFI - 0.5` = 249.5) ever gets a chance to register.
> This is exactly the boot state this lamp was in (still recovering from the original
> post-OTA Wi-Fi-loss incident above), which is why it was reproducible. Confirmed the
> same mechanism plausibly explains that *original* incident too: `wifi:`'s own saved-STA
> preference has always been explicitly flash-backed
> (`make_preference<SavedWifiSettings>(hash, true)`, independent of
> `esp8266: restore_from_flash`) — but flash preference *offsets* are handed out
> sequentially, in whatever order each component's `make_preference(..., in_flash=true)`
> call happens to run at boot; turning on `esp8266: restore_from_flash: true` (v2.5.0) made
> many *other* previously-RTC-only preferences flash-backed for the first time, which can
> shift where Wi-Fi's own preference lands relative to the one it was written at under the
> older firmware — landing on stale/foreign bytes fails the stored CRC, `has_sta()` comes
> back false, and the cascade above begins. This second half remains a plausible, evidence-
> consistent theory rather than a fully proven one (would need flash-offset instrumentation
> to nail down definitively) — but it's no longer a shot in the dark either.
> **Fix shipped:** `CloudLampWeb::get_setup_priority()` raised from `WIFI - 0.5` to
> `WIFI + 2.0` — strictly above *both* `captive_portal` (`WIFI + 1.0`) and `wifi`
> (`WIFI`) itself, so `cloud_lamp_web` always registers first regardless of which of the
> two startup paths triggers the portal. Verified on the real, still-affected lamp: pushed
> the fixed build via the browser-upload OTA endpoint (`http://192.168.4.1/update`, reachable
> even mid-portal since it's a `POST`, which the portal's GET-only catch-all doesn't shadow)
> and re-ran the same `curl` probes — all now return the actual branded `web/setup.html`
> (`Content-Length: 11094`, matching its content, not the stock page's `1462`). Separately
> confirmed via `esphome compile` + inspecting the generated `main.cpp` that
> `web/setup.html` has always been correctly compiled in (`set_setup(..., 11041)` bytes
> gzipped) — so this was never a missing-content bug, only a handler-race one. Two earlier,
> low-risk hardening tweaks shipped alongside this (harmless either way, kept for
> consistency): `-webkit-backdrop-filter` alongside the unprefixed property on `.card` in
> both `web/setup.html` and `web/app.html`, and the success screen's
> `http://cloud-lamp-xxxxxx.local/` reconnect address is now a tappable `<a>` link instead
> of inert text. Separately, confirmed the "how do I get back to the lamp" ask was already
> covered end-to-end (success screen's numbered steps, `user-manual.md` §5,
> `firmware-updates.md`'s troubleshooting section — all point at the mDNS hostname); a true
> instant hand-off to the lamp's real IP isn't possible from inside a locked-down portal
> webview, so that's the practical ceiling, not a gap. Also confirmed (real device, real
> iPhone) that the setup-hotspot popup sometimes not appearing automatically is iOS's own
> "seen this SSID before" heuristic, not a device-side delay — the device responds
> instantly once a real navigation is attempted; nothing to fix there. Not yet
> re-verified end-to-end from a genuine factory-reset boot (only from the specific
> already-broken state this lamp was already in) or folded into an official release build.
> Follow-up in the same session: added a language-selector dropdown to `web/setup.html`
> itself (same 10 languages as the app, English default). Previously the page
> auto-detected from `navigator.languages` — exactly why a German-language phone saw the
> *whole* onboarding page in German even though the main app defaults to English; the
> dropdown replaces that auto-detect entirely, matching the app's own policy that English
> is the default and every other language is an explicit user choice. Deliberately not
> persisted via `localStorage` — some captive-portal webviews (notably iOS's Captive
> Network Assistant) run in a restricted context where storage APIs can be unavailable,
> and the page is only ever seen once per onboarding anyway — so the choice lives in a
> page-local JS variable, with a new `applyI18n()` re-rendering every static label plus
> the live network list (so "Other network…" / the empty-state text follow the selection
> too). Browser-verified against `tools/mock-device.py` (English → German → English,
> including the network list); not yet tested on real hardware. Also dug further into the
> "auto-popup sometimes doesn't appear / is slow" heuristic noted just above, by reading
> ESPHome's actual `captive_portal.cpp`: confirmed the wildcard DNS server
> (`dns_server_->start(53, "*", ip)`, both the ESP32 and the Arduino/ESP8266 build this
> project uses) and our own `canHandle()` (`url != "/config.json" && url != "/wifisave"`
> while the portal is active — i.e. *every other* GET, including OS captive-detection
> probes like `/hotspot-detect.html`, `/generate_204`, `/ncsi.txt`) were already correct
> before today; the branded page is already served for those probe paths too, not just
> `/`. No code-level bug found — the remaining unreliability lines up with well-documented,
> device-independent iOS behaviour beyond the SSID-seen-before heuristic already noted:
> (1) the very first captive-check probe can race and lose if a phone joins the AP in the
> brief window before its DNS/HTTP stack has finished starting inside
> `captive_portal::start()`; (2) an active VPN or encrypted DNS (DoH) profile on the phone
> bypasses the local DNS interception the whole mechanism depends on. The standard,
> Apple-acknowledged workaround — manually opening Safari and navigating to any address
> (the lamp's own, or a throwaway one like `1.1.1.1`) — always triggers it instantly,
> matching what was already observed. Nothing changed on the device side; there is no safe
> device-side fix for OS-level caching/heuristics.
>
> **Phase:** v2.6.0 — second real-hardware tuning pass on two effects from the
> v2.5.0 batch, both confirmed too subtle on the bench lamp rather than "final calibration"
> (as flagged at the time). **Ring Ripple:** the 3 s pause between ripples (plus the
> ripple's own soft fade-in/out runout either side of it) added up to a stretch long enough
> to read as "did it turn off?" rather than a deliberate calm beat between waves;
> `ring_ripple_pause_ms` `3000` → `1200` (substitution only, lambda unchanged).
> **Candlelight:** now reads as a fixed warm-orange colour with no visible flicker at all —
> confirmed as amplitude, not the snap/jumpiness the *previous* pass fixed. The v2.5.0
> rewrite fixed two separate, previously-conflated bugs at once: (1) each ring **snapped**
> to a fresh random target every 90 ms (the actual "disco" cause, fixed by the continuous
> `dip[r] += (target - dip) * ease` glide), and (2) `candle_depth` wasn't a real cap at all
> (the old normalisation divided by the same constant it multiplied by, so depth changes
> had ~no effect on range) — fixing *that* into a genuine cap, while keeping the same
> default (`60`) chosen for the old, non-functional-cap formula, made the reachable dip a
> mere ~0-24% of the full base→ember shift instead of the old ~0-100% — calm turned into
> practically invisible. Only the snap needed fixing, not the range: `candle_depth` `60` →
> `150` restores a visible ember dip while the (unrelated, already-fixed) glide keeps it
> smooth; also nudged the ease factor `0.05` → `0.07` so the glide keeps up with each new
> target (re-rolled every `candle_interval_ms` = 320 ms) a bit better instead of mostly
> averaging itself out. Both changes are substitution/constant tweaks verified with a clean
> `esphome compile`; **not yet re-tested on real hardware** after this second pass.
>
> **Phase:** v2.6.0 — reproduced a real OTA failure on real hardware and shipped
> an interim mitigation; root cause not yet fully confirmed. Repro method: checked out the
> exact `v2.4.0` git tag into a throwaway worktree, added `api:` for live Wi-Fi log
> streaming (the same method as the `cloud-lamp-dev.yaml` diagnostic builds described
> below), push-OTA'd it to a real lamp, then triggered the real pull-OTA update to the
> currently-published v2.5.1 via the device's own REST API while watching logs live.
> Result: the download, MD5 check, and flash write all completed cleanly (100% in 14s,
> "Update complete") — but the freshly-flashed v2.5.1 image never reconnected to the home
> Wi-Fi network afterwards, falling back to its own setup hotspot instead; it stayed that
> way for **hours**, and a power cycle did not recover it — only manually re-pairing Wi-Fi
> via the captive portal (`192.168.4.1`) brought it back online. So the update itself
> genuinely succeeds; the lamp simply loses its Wi-Fi pairing on that specific version
> jump, which is what makes the web app's 3-minute polling window give up and show
> "previous firmware still running" — a real but *secondary* symptom, not the cause.
> Leading (unconfirmed) suspect: this is the first time this physical unit ever exercises
> `esp8266: restore_from_flash: true` (new in v2.5.0), which starts writing to a flash
> sector never touched by any earlier version — but this has not been proven at the flash
> level, and an unrelated toolchain/partition difference between when v2.4.0 was
> originally built and today's rebuild can't be ruled out either. Side effect observed:
> all persisted settings (Power Behavior, MQTT config, on/off state) reset to defaults
> after the incident, consistent with a genuinely first-ever flash-preferences write.
> **Interim mitigation shipped now** (doesn't require knowing the exact root cause):
> `fw_hint_fail` (`web/app.html`, all 10 languages) now tells the user to check whether the
> lamp re-created its own Wi-Fi network and, if so, reconnect it the same way as initial
> setup — turning a "looks bricked" dead end into a known, documented recovery path for
> anyone (including other gift recipients on pre-v2.5.0 firmware) who hits this. Proper
> root-causing (and, ideally, a real fix or a guarded/staged rollout for the
> `restore_from_flash` transition) remains open.
>
> **Phase:** v2.6.0 — three small web-app fixes. **(1)** On the mobile header
> layout, the "Update available" badge used to wrap onto its own line *above* the
> "Connected" pill when both couldn't fit on one line (pure DOM-order artifact of
> `flex-wrap`); swapped so Connected is always the top line and the badge (only shown when
> relevant) wraps below it. **(2)** The "Cloud-Lamp" title and serial-number subtitle in
> the header were getting ellipsis-truncated whenever the update badge appeared, even with
> visually obvious room to spare — a flexbox quirk where a wrapping flex item's un-wrapped
> (max-content) width is used for shrink-distribution purposes, so the brand name shrank
> too even though the badge/pill group had room to wrap instead. Fixed with
> `.brand{flex-shrink:0}`, so all squeeze pressure lands on the badge/pill group (which can
> absorb it by wrapping) and the brand text is never truncated. **(3)** The "Update
> available" badge sometimes didn't appear until the user manually pressed "Check for New
> Updates" in Settings, even though the manifest genuinely had a newer version — traced to
> `packages/updates.yaml`'s periodic manifest check firing its *first* automatic check
> within a few seconds of boot (ESPHome's default `PollingComponent` startup behaviour),
> often before Wi-Fi has even finished associating and right as MQTT's own connect burst is
> competing for heap; that first check would silently fail with no retry until the next
> full 6h tick. Added `startup_delay: 90s` to that `interval:` so the first automatic check
> happens well after boot-time Wi-Fi/MQTT contention has settled, instead of racing it.
> Verified: (1) and (2) browser-verified against `tools/mock-device.py`; (3) is an ESPHome
> config change confirmed with `esphome config`, not yet tested on real hardware.
>
> **Phase:** v2.5.1 — MQTT settings save behaviour changed from silent auto-commit
> (on blur/change) to an explicit **Save** button: the four broker fields (Broker/Port/
> Username/Password) now only stage edits locally — nothing is sent to the device, and no
> broker reconnect is triggered, until Save is clicked (Enter in any field triggers the
> same save). Fixes user-reported confusion that changes might not be taking effect
> (there was previously no positive confirmation on a successful auto-save, only a toast
> on failure). `web/app.html`: added `mqttDirty` state gating both the Save button and the
> SSE `ingest()` handlers (so an incoming state update never clobbers an unsaved edit),
> and `mqtt_save`/`mqtt_saving`/`mqtt_saved` i18n keys across all 10 languages. Also this
> release: git-tagged and backfilled GitHub Releases for all versions back to v2.1.2 (see
> [Firmware updates → GitHub Releases](./firmware-updates.md#github-releases-human-facing-downloads));
> `tools/release.sh` now creates one automatically for every future release too — purely a
> human-facing download page, unrelated to the OTA mechanism below. JS syntax-checked and
> browser-verified against `tools/mock-device.py`; not yet tested on real hardware.
>
> **Phase:** v2.5.0 — a batch of correctness fixes and web-app/effects polish, no
> architecture changes. Highlights (each has its own detailed entry further down this
> section): **(1)** a real power-loss bug fix — every persisted setting (on/off,
> brightness, effect, Power Behavior itself) defaulted to ESP8266 RTC memory, which does
> not survive an actual power cut; now flash-backed (`esp8266: restore_from_flash: true`)
> so "Restore Last State" genuinely works. **(2)** boot logic now tells a deliberate
> reboot (a successful update, the Restart button, MQTT `Set/Reboot`) apart from a real
> power cut, and always resumes the pre-reboot on/off state for the former, regardless of
> the Power Behavior setting. **(3)** a new effect, **Ring Ripple**, plus a tuning pass
> across four existing effects (Candlelight calmed down for nursery use; Spectrum Fade
> slowed; Sky Breathing's trough brightened; Blue Color Wipe smoothed and slightly sped
> up; Pulse's floor raised and slowed further). **(4)** several web-app fixes: header/
> footer logo images now retry instead of silently falling back, the brightness icon is
> now a light bulb, the Custom Color button no longer looks permanently "selected", the
> Speed slider now shows its `%` unit, and the power on/off toggle's knob is now exactly
> vertically centred (was 1px off due to a border/box-sizing interaction). All verified
> with `esphome compile`; not yet tested on real hardware except the UI-only web-app
> changes (checked against the mock device server). See
> [Behaviour reference](#behaviour-reference) and [Effects](#effects-effectsyaml) for the
> resulting current-state reference; the entries below are the as-built record.
>
> **Phase:** v2.4.0 — root-caused and fixed the OTA install/check failures that had been
> "still investigating" since v2.3.2: **BearSSL's HTTPS handshake against GitHub's CDN
> needs roughly 16-20 KB of *contiguous* free heap** — confirmed directly on hardware with
> heap instrumentation (`ESP.getFreeHeap()`/`getMaxFreeBlockSize()`/`getHeapFragmentation()`
> logged immediately around the failing allocation), which showed 12-17 KB free contiguous
> heap *still* wasn't enough. That's more than this device reliably has alongside the web
> server and MQTT, no matter how the TLS buffers were tuned (raising them further OOMs even
> sooner on the MQTT-enabled bench build; GitHub/Fastly's CDN doesn't honor MFLN at the
> sizes tried) — so every fix through v2.3.3 (closing the web app's SSE connection,
> suspending MQTT) reduced *contention* for that budget but could never make the budget
> itself sufficient. **Fix: drop TLS for OTA entirely.** Both the manifest and the firmware
> binary are now fetched over **plain HTTP** — removing BearSSL's memory requirement
> completely — and a new **Ed25519 signature** on the manifest (verified on-device before
> anything is trusted as an update) replaces TLS as the source of integrity/authenticity,
> which is strictly *stronger* than the previous `verify_ssl: false` HTTPS ever provided
> (an on-path attacker had exactly as much power then — no certificate was ever validated —
> just with TLS overhead and none of the memory cost). New custom component
> [`components/signed_update/`](../components/signed_update/) (an `update:` platform,
> drop-in for `http_request`'s own) fetches, parses and verifies the manifest, then calls
> straight into the existing, unchanged `ota: platform: http_request` entity to flash —
> so the web app, MQTT discovery and the update coach UI all keep working with no changes.
> `tools/release.sh` now signs every manifest with an Ed25519 private key kept **outside
> this repository** (never committed — see
> [firmware-updates.md](./firmware-updates.md#key-custody)). The plain-HTTP host is this
> repo's own **GitHub Pages** site: `docs/` moved to also hold `docs/firmware-dist/`
> (published releases), and a custom domain — `cloud-lamp.ddproductions.de`, DNS pointed at
> GitHub Pages via CNAME, "Enforce HTTPS" deliberately left off — serves it as plain HTTP.
> That collapses "publish" back down to a single `git push`: there is no second upload
> target to keep in sync, since GitHub *is* the plain-HTTP host. (All-inkl.com, the
> project's other webspace, was considered and set up first, but every HTTP request to a
> subdomain there was unexpectedly 301-redirected to HTTPS by the host regardless of KAS
> panel settings — an Apache-level behavior outside our control — which defeats the entire
> point; GitHub Pages doesn't have that problem.) `cloud-lamp.yaml` gained an
> `ota_ed25519_pubkey` substitution (the public half, not a secret) and
> `update_manifest_url` now points at that custom domain instead of
> `raw.githubusercontent.com`. Verified: full `esphome compile` succeeds with the new
> component and its vendored Ed25519 dependency
> ([operatorfoundation/Crypto](https://registry.platformio.org/libraries/operatorfoundation/Crypto),
> a PlatformIO-registry mirror of rweather/arduinolibs' audited Crypto library, pulled
> as-is rather than hand-copied) linked in, adding only ~8 KB to the final binary thanks to
> linker dead-code elimination; a standalone Python sign/verify round-trip against both the
> real production keypair and `tools/mock-device.py`'s throwaway test keypair. **DNS
> propagation for the custom domain is now confirmed** — `curl
> http://cloud-lamp.ddproductions.de/firmware-dist/cloud-lamp/manifest.json` returns `200`
> over plain HTTP with no redirect, serving the live, signed manifest. Still pending: a
> confirmed on-hardware test of the actual online-updater's check+install cycle against
> this endpoint end-to-end (the public build has been pushed to the bench lamp via push-OTA
> with the new `update_manifest_url` compiled in, but push-OTA bypasses
> `components/signed_update/` entirely, so it doesn't exercise the code path being tested).
>
> **Phase:** v2.3.4 — fixed the web app's REST calls to use ESPHome's new entity-Name-based
> URL format (e.g. `/light/Cloud Light`) instead of the legacy object_id form
> (`/light/cloud_light`). The object_id form still works today but logs a
> `[W][web_server]: Deprecated URL format: ...` warning on every request and is removed
> entirely in ESPHome 2026.7.0 — left unfixed, the web app would have stopped working
> outright on the next ESPHome upgrade. Every REST call the app makes (light, MQTT
> switch/text/number fields, Power Behavior select, Effect Speed, Firmware
> check/install, and the maintenance buttons) now builds its path from the entity's
> display Name via a small `restPath()`/`P_*` constant table in `web/app.html`, matching
> each entity's `name:` in the YAML. `tools/mock-device.py` was updated to accept both
> the new Name-based paths and the legacy object_id ones (see its `NAME_TO_ID` table), so
> it keeps working for anyone testing against an older bookmark/script. No user-visible
> change — this is a backend/API-format fix only. See the **API** bullet under
> [Web app](#web-app-packagesweb-remoteyaml--componentscloud_lamp_web--webapphtml) for the
> parallel (later, 2026.8.0) deprecation of the SSE/REST JSON `id` field, which is not yet
> addressed.
>
> **Phase:** v2.3.3 — three web-app UX improvements, no firmware/backend logic changes:
> (1) the "Connected" pill moves back into the header's top row, pinned to the top-right
> corner next to the logo (it had been moved into a second row in v2.3.0); (2) a new
> **"Update available" badge** sits next to it, visible on the main screen itself —
> previously the only indicator was the same-styled badge inside Settings → Firmware,
> easy to miss for anyone who rarely opens Settings. Tapping the new badge opens Settings
> and scrolls straight to the Firmware section. Both badges are driven by the same
> `hasUpd` check in `renderUpdate()`, so any future fix to that logic (see the "Latest
> version" detection work still open elsewhere) automatically applies to both; (3) a
> **loading overlay** (spinner + "Loading…") now covers the app until the lamp's real
> on/off/brightness/effect state has actually arrived over `/events` or the initial REST
> fetch — before this, the UI briefly rendered its JS defaults (e.g. "Off") which could be
> flatly wrong if the lamp was actually on, right as the "Connected" pill was still
> showing its own "…" placeholder. The overlay always clears within 12 s even if the lamp
> is unreachable, falling back to the existing "Offline" badge rather than spinning
> forever. Also fixed an ESPHome deprecation warning (`select::state` → `current_option()`,
> `cloud-lamp.yaml`'s `power_behavior` boot lambda) that would have broken the build in
> ESPHome 2026.7.0.
>
> **Still investigating (carried over from v2.3.2):** the OTA *install* failing outright on
> real hardware. Diagnostic build tooling only, this release: an OTA-push-only,
> gitignored `esphome run`-time copy of `cloud-lamp.yaml` with `api:` added is used to
> stream live logs over Wi-Fi during a failed install (no case-opening/USB required —
> `esphome logs <file> --device <lamp-ip>`), since MQTT-based log viewing goes silent for
> the exact window under investigation (MQTT is intentionally suspended during OTA to
> free heap — see `packages/mqtt.yaml`). Nothing diagnostic-only ships in this release.
>
> **Phase:** v2.3.2 — the update-failed screen had no way out except retrying. In
> `setFwCoachPhase()`, the "Continue" button was hidden with `cont.hidden = phase ===
> "fail"` — inverted: it hid Continue *specifically* on failure, the one phase where a
> dismiss action is most needed, leaving only "Try again" with no way to back out of a
> failed update without immediately retrying it. Found while testing the v2.3.1 check fix
> on real hardware (the check now correctly found v2.3.1, but the *install* itself then
> failed — separate, still-open issue, see below — and the coach's failure screen trapped
> the user). Fixed by adding a dedicated **Cancel** button, shown only on `fail` (alongside
> "Try again"), and correcting `cont.hidden` so **Continue** now only shows on `done`
> (`web/app.html`, all 10 languages). `fw_hint_fail` was already accurate ("the previous
> firmware is still running") — the modal itself just had no way out.
>
> **Still investigating:** the *install* failing outright (not just the check) on the same
> real device, now running a much larger binary (~845 KB vs. 766 KB at v2.2.5 — the new
> MQTT entities and expanded effect list). Likely the same heap-contention family as the
> v2.2.5/v2.3.1 fixes, just a bigger download holding the TLS buffer open for longer, but
> not yet confirmed without device logs. Recovery in the meantime: browser-upload OTA
> bypasses the online updater entirely (see
> [firmware-updates.md](./firmware-updates.md#stuck-on-an-old-version-with-up-to-date-showing)).
>
> **Phase:** v2.3.1 — a real device stayed on "Up to date" / 2.2.5 shortly after v2.3.0
> went live, even after explicitly pressing "Check for updates now". Root cause: the exact
> same ESP8266 heap-contention bug already fixed for OTA **installs** in v2.2.5 was also
> silently affecting the manifest **check** — never noticed before because nobody had
> pressed "Check for updates now" from the web app (which necessarily has an SSE connection
> open) since that fix went in. `http_request`'s update platform only republishes its state
> on a *successful* check; a failed one (heap too fragmented for BearSSL's ~8.7 KB
> contiguous TLS buffer, with the web app's own held-open `/events` connection as the
> single biggest avoidable contributor) leaves the entity exactly as it was — current
> version, latest version, everything — with no error exposed anywhere the web app can see.
> So the app kept confidently showing the result of whatever check last happened to
> succeed, which was before v2.3.0 was published. Fixed the same way as the install: (1)
> `web/app.html`'s "Check for updates now" handler now closes its `EventSource` before
> POSTing the button press and reconnects immediately after (the press blocks server-side
> until the check finishes, so there's nothing to wait for in between — see
> `packages/updates.yaml`'s reliability note); (2) `check_for_updates_btn` now also
> suspends/resumes MQTT around `update.check`, in that exact order in one `on_press` list
> (unlike the OTA install hooks, this can't be added via a second `on_press` merged in from
> `packages/mqtt.yaml` with `!extend` — that wouldn't guarantee running before/after the
> existing step). **A device already stuck on a stale "Up to date" cannot self-heal via
> this fix alone**, since it is still running the old, unfixed web app until it updates —
> see [firmware-updates.md](./firmware-updates.md#stuck-on-an-old-version-with-up-to-date-showing)
> for the recovery steps (power-cycle without opening the web app, or manual browser-upload
> OTA as a last resort).
>
> **Phase:** v2.3.0 — MQTT is now always compiled in (public build too) but OFF by
> default on every new device (`RESTORE_DEFAULT_OFF`; previously the "MQTT Enabled" switch
> itself defaulted to ON on the dev-only bench build). Broker address/port/username/password
> are no longer compile-time `!secret`s — they're `text`/`number` template entities in the
> web app's settings sheet (Settings → MQTT), only shown once enabled, persisted in flash
> independently of the switch (turning MQTT off never loses what was typed in), and applied
> live via `MQTTClientComponent::set_broker_address()`/`set_broker_port()`/`set_username()`/
> `set_password()` — no reflash needed to (re)configure a broker. `cloud-lamp-dev.yaml` no
> longer needs its own `mqtt: !include packages/mqtt.yaml` line since the base config already
> includes it; `secrets.example.yaml`'s `mqtt_broker_*` keys are gone (configure from the web
> UI instead). See [MQTT design](#mqtt-design-packagesmqttyaml-always-included-off-by-default)
> below. v2.2.5: OTA reliability fix: a real "Update failed — previous firmware
> still running" was traced to ESP8266 heap pressure during the download, not a bad
> binary (committed binaries were verified byte-for-byte against their manifest MD5).
> The web app now closes its SSE (`/events`) connection before POSTing
> `/update/Firmware/install` and only reconnects once the update coach reaches
> done/fail; on the MQTT-enabled bench build, the MQTT client is suspended for the OTA's
> duration via `ota_via_http`'s `on_begin`/`on_error`/`on_abort` hooks (added to
> `packages/mqtt.yaml` with the `!extend` package syntax, which merges automation
> triggers into an existing entity declared in another package by matching `id:`).
> Respects the persisted MQTT kill switch — it won't re-enable MQTT on failure if the
> user had already turned it off. See `packages/updates.yaml`'s "Reliability note" for
> the full explanation. v2.2.4: the permanent manual URL moved from the jsDelivr CDN to GitHub
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
> **Header layout (no firmware change):** the header is now two rows instead of one —
> row 1 keeps the wordmark + device name/serial; row 2 holds the connection pill
> (left-aligned) and the Manual/Settings icon buttons (right-aligned, unchanged), split
> via a new `.hdr-row2` flex row (`justify-content:space-between`). Gives the connection
> pill more breathing room next to the two icon buttons on narrow phones.
> **iOS icon-caching fix:** `/icon.png` (favicon + `apple-touch-icon`, i.e. the "Add to
> Home Screen" icon) now gets a `?v=<hash>` cache-buster derived from the icon file's own
> content (`components/cloud_lamp_web/__init__.py` hashes it at compile time and
> substitutes `web/app.html`'s `__ICON_VERSION__` placeholder; `tools/mock-device.py`
> mirrors the same substitution for local dev). Root cause: iOS Safari's site-icon cache
> ignores `Cache-Control` for favicon/apple-touch-icon requests and can get stuck serving
> a stale icon from an earlier visit indefinitely (Chrome doesn't have this bug, which is
> why it always showed the current icon while Safari on iPhone kept showing an old one);
> the fix is self-maintaining — any future icon-artwork change gets a new hash and a new
> URL automatically, no manual version bump needed. `manifest.json`'s icon entry gets the
> same cache-buster (`cloud_lamp_web.cpp`'s `handle_manifest_`). Note this only fixes
> *future* fetches — an icon already added to an iPhone's home screen before this fix
> won't retroactively update; removing and re-adding it is the only way (same as any
> apple-touch-icon change, unrelated to this bug).
> **iOS full-bleed background fix (no firmware change):** the v2.1.6 approach — a fixed
> `.app-bg` layer oversized against `100lvh`/`130vw` — still left a seam at the top/bottom
> edges on iPhone, because `html`/`body` were still natively scrollable, so Safari's
> collapsing address bar and rubber-band bounce could still move the document relative to
> that fixed layer. Fixed by locking `html`/`body` to the viewport (`height:100%;
> overflow:hidden`) and moving all real scrolling inside `.wrap` (`overflow-y:auto`)
> instead — mirroring the Bed-LEDs/Custom_WLED remote control app, which never showed this
> issue for the same reason. `.app-bg` is now a plain `inset:0` layer (oversizing is no
> longer needed since the outer page never scrolls). Applied to both `web/app.html` and
> `web/setup.html` (same design language). The settings-sheet scroll lock
> (`lockSheetScroll`/`unlockSheetScroll`) now freezes `.wrap`'s own `scrollTop` instead of
> faking a fixed `body` with a negative offset, since `.wrap` is the only scrollable
> element now.
> **Manual cover fix (no firmware change):** the v2.2.4 approach of deriving a flat,
> single-colour navy silhouette of the DD Productions icon (luminance-as-alpha mask,
> binarised, recoloured) discarded the logo's actual chrome/metallic shading, so it no
> longer read as the real mark. Replaced with a proper full-colour render (icon + text,
> correct chrome tones) supplied pre-flattened onto an opaque white background and saved
> as a JPEG — no transparency needed since the cover's footer sits on an already-white
> part of the background gradient. `assets/dd-productions-logo-on-white.jpg` is now the
> only maker-logo asset `tools/build-manual.py` uses; the superseded derived PNG
> (`dd-productions-logo-black-transparent.png`) was removed.
> **Docs correction (no firmware change):** the manual, README and this document
> previously mis-described the power supply as "5 V USB" — it is actually a 5 V/2 A DC
> barrel-jack adapter (5.5×2.1 mm, centre-positive), now corrected everywhere. The sticker
> design is finalised (docs/Label.lbx); user-manual.md §2 and device-credentials.md now
> describe its actual fields (Model/S/N/Hostname/WiFi-Passw./Power-Supply/QR) instead of
> the earlier, slightly different field set.
> **Zoom-prevention fix (no firmware change):** the viewport meta's `user-scalable=no` /
> `maximum-scale=1` alone don't stop pinch-zoom on iOS Safari 10+, which deliberately
> ignores that for accessibility — pinch-zoom is still possible even though the page has
> nowhere useful to zoom to. Added `touch-action: pan-x pan-y` on `html` in both
> `web/app.html` and `web/setup.html`: a separate mechanism iOS does honour, it drops
> pinch-zoom from the page's default gestures while leaving normal panning/scrolling
> (`.wrap`, `.sheet`) untouched. Also bumped the MQTT settings text inputs (`.row
> input.ctl`) from 14px to 16px, since iOS Safari auto-zooms the page when a focused text
> input's font is under 16px, regardless of the viewport meta.
> **Desktop mouse-wheel scroll fix (no firmware change):** the zoom-prevention fix above
> made `.wrap` (not `body`) the only scrollable element, and `.wrap` was also the centred,
> `max-width:520px` content column — so on wide desktop windows, the mouse wheel did
> nothing whenever the cursor sat in the empty margin beside that column (hit-testing
> resolves to `body`, which is intentionally `overflow:hidden`/non-scrollable). Only
> noticeable on desktop Chrome; iPhone was unaffected since its viewport width is close to
> `.wrap`'s cap, so virtually the whole screen was already "inside" it. Fixed by splitting
> the two roles: `.wrap` now spans the full viewport width and is the only element with
> `overflow-y:auto`, while a new `.inner` div (nested one level in, `max-width:520px;
> margin:0 auto`, carrying `.wrap`'s old padding) does the visual centring. Applied to both
> `web/app.html` and `web/setup.html`; no JS changes needed since `wrapEl`/`.wrap` is still
> the scrollable element the settings-sheet scroll lock reads/writes.
> **Full-bleed background fix, take 2 (no firmware change):** v2.1.6 dropped the explicit
> `theme-color` meta on the theory that iOS Safari (15+) would auto-sample the page's own
> background and tint its top/bottom bars to match, making the gradient look truly
> edge-to-edge. In practice that auto-sampling never reliably delivered — it still left a
> visible seam/cut-off at the screen edges. No page content can paint into the browser's
> native chrome either way; the only lever is `theme-color`. Restored
> `<meta name="theme-color" content="#0b0f18">` (matching `--bg1` and the PWA manifest's
> existing `background_color`/`theme_color`, both already `#0b0f18` —
> `components/cloud_lamp_web/cloud_lamp_web.cpp`) in `web/app.html`, and added the same to
> `web/setup.html` (which never had one). This mirrors the Bed-LEDs/Custom_WLED
> remote-control app (`wled00/data/remote-control.htm` + its manifest), which uses the
> identical fixed dark-navy `theme-color` and does reliably look edge-to-edge.
> **Full-bleed background fix, take 3 (no firmware change):** take 2's `theme-color` meta
> still left a solid black bar under the status bar on-device (iOS 26 Safari, confirmed via
> screenshot on the bench lamp). Root cause: Safari 26 dropped `theme-color` support
> entirely — it now tints the top/bottom bars by sampling the plain CSS `background-color`
> of a `position:fixed`/`sticky` element touching the viewport edge (≥~80% width), falling
> back to `<body>`'s `background-color`, and to plain black/white if neither exists. Our
> `.app-bg`/`.load-overlay` only ever set a gradient via the `background` shorthand, which
> carries no flat `background-color`, and `<body>` had none either — so Safari fell through
> to its black default. Fixed by giving `.app-bg` (and, as a fallback, `<body>` and
> `.load-overlay`) an explicit `background-color:var(--bg1)` alongside their existing
> gradients, in both `web/app.html` and `web/setup.html`. Left the `theme-color` meta in
> place too (harmless, and still honoured by Chrome/Android and pre-26 Safari). Source:
> WebKit's Wenson Hseih on the change's rationale, and
> https://nasedk.in/blog/ios26-safari-toolbar-colors/ / https://arpit.blog/articles/2025/11/safari-drops-support-theme-color/
> for the exact fallback chain and size thresholds.
> **Full-bleed background fix, take 4 (no firmware change):** take 3's `background-color`
> addition was confirmed deployed (byte-diffed the live `/` response) but produced zero
> visible change on-device — same solid black status-bar bar, in a fresh tab and in Private
> Browsing, ruling out tab-level toolbar-tint caching. Closed the one remaining structural
> gap versus the Bed-LEDs/Custom_WLED reference (`body::before`): added
> `transform:translateZ(0)` to `.app-bg` (and `.load-overlay`) in both `web/app.html` and
> `web/setup.html`, promoting the fixed full-bleed layer to its own GPU compositing layer.
> iOS Safari has a long history of a `position:fixed` element nested inside an
> `overflow:hidden` html/body chain mis-computing its extent under the safe-area insets
> (notch/status bar, home-indicator) without this, even though it paints correctly
> everywhere else on screen — plausible root cause given the fix was otherwise byte-for-byte
> correct. **Did not fix it** — on-device retest (regular Safari tab) showed no change.
> **Full-bleed background fix, take 5 — root cause confirmed (no firmware change):** the
> user noticed the top/bottom behaved differently between a regular Safari tab and the same
> page added-to-home-screen (standalone PWA): standalone mode fixed the *top* seam
> completely (status bar goes translucent and correctly shows the page through it in that
> mode) but left the *bottom* edge cut off by a solid black band — a different symptom from
> the plain-tab case, and the key clue. Matches a confirmed Safari 26 bug (Edoardo Lunardi,
> "Safari 26 and the Strange Case of Fixed Overlays"): a `position:fixed;inset:0` layer with
> a fully *opaque* background gets clipped short by Safari 26's new floating bottom bar,
> while the identical layer at `opacity<1` is composited on a separate layer and correctly
> covers the full viewport — `opacity:1` takes a "simple fill" fast path that gets clipped,
> anything less routes through the compositor and doesn't. Fixed by adding `opacity:.999`
> (visually indistinguishable from 1, and doubly so since `<body>` behind it already matches)
> to `.app-bg` in both `web/app.html` and `web/setup.html`. Whether this incidentally also
> fixes the still-black top bar seen in regular (non-standalone) Safari tab browsing —
> possibly the same clipping bug was breaking Safari's ability to detect `.app-bg` as a
> valid edge-bordering element for its tint-derivation — is unconfirmed pending retest of
> both modes. **Did not fix it** — retest showed both symptoms unchanged.
> **Full-bleed background fix, take 6 — structural (no firmware change):** takes 3–5 all
> tuned the *colours/compositing* of the fixed `.app-bg` layer while keeping the page's two
> structural oddities; a May-2026 field report that matches our exact symptoms
> (https://1ar.io/updates/safari-26-liquid-glass-web/, "Safari 26 Liquid Glass") identifies
> both as tint-breakers, which would explain why every colour-side fix produced zero
> change: (1) a fully `overflow:hidden`-locked `html`/`body` breaks Safari 26's
> viewport/chrome tint sampling outright ("do not lock the whole document"), leaving the
> bars at the system black/white default no matter what background-colors the page
> declares — exactly our symptom in both regular-tab (black status bar + untinted toolbar)
> and standalone mode (black home-indicator band; the top was already handled there by the
> older `black-translucent` meta, which is why standalone only showed the bottom symptom);
> and (2) full-bleed `position:fixed` layers are precisely the element class with Safari
> 26's confirmed clipping/tinting bugs (WebKit #300965/#302272, the fancyapps/MUI reports).
> Restructured both `web/app.html` and `web/setup.html` accordingly: `html`/`body` keep
> `height:100%` but drop `overflow:hidden` — the document still can't actually scroll,
> since its only content (`.wrap`) is exactly one viewport tall, so the address-bar/
> rubber-band seam the lock was protecting against can't return (overscroll is additionally
> suppressed by the existing `overscroll-behavior` rules), and `.wrap`'s internal scrolling,
> the desktop mouse-wheel fix, the pinch-zoom `touch-action` and the settings-sheet scroll
> lock are all untouched. The `.app-bg` div is deleted entirely; its full gradient +
> `background-color:var(--bg1)` moved onto `html` itself (with `background-repeat:
> no-repeat`, so any canvas beyond the root box shows the flat colour, not a tiled
> gradient). The root background is painted across the entire canvas — under the status
> bar, toolbars and home indicator with `viewport-fit=cover` — and its `background-color`
> is Safari 26's documented tint fallback, so no fixed element is needed at all and the
> whole buggy code path is sidestepped. `body` is now deliberately background-less
> (transparent) so it neither hides the root gradient nor shadows the root tint fallback.
> `.load-overlay` (still fixed, still navy — it's what Safari samples during initial load)
> is now `display:none`d via `hidden` ~400 ms after its fade-out (`markReady`), since
> Safari 26 keeps sampling `opacity:0` fixed elements; at rest the root background is the
> only tint source. Verified in a desktop browser (390px-emulated and full width): document
> has zero scrollable overflow, `.wrap`/`.sheet` scrolling and the settings sheet behave as
> before, gradient renders full-bleed.
> **On-device iOS 26 retest of take 6 — did not fix it, investigation paused:** in the
> standalone home-screen app the top edge now does stretch correctly (an improvement — the
> `black-translucent` status-bar meta was already covering that case, but the root-background
> restructure didn't regress it), but the **bottom edge still shows a blank/black band** —
> the exact same symptom take 5 already identified. In a plain Safari tab (not added to the
> home screen) the page **doesn't even stretch to the top**, so that mode is arguably no
> better off than before either. Six iterative, independently-plausible fixes in a row
> (takes 1-6: `theme-color`, a flat `background-color` fallback, GPU compositing via
> `transform:translateZ(0)`, the `opacity:.999` compositing-path workaround, and finally
> removing the `position:fixed`/`overflow:hidden` structure Safari 26's own tint-sampling
> code is documented to mishandle) have now failed to close out either symptom. **Treating
> this as a known, deferred defect rather than continuing to iterate blindly** — see the
> "Still open" note below for the summary and possible future directions. Purely
> cosmetic — the app remains fully usable either way, no functionality is affected.
> **Header logo reliability fix (no firmware change, v2.5.0):** the header brand
> mark (`/brand.png`) and footer maker logo (`/logo.png`) occasionally failed to load —
> reported mainly on desktop Chrome — falling straight through to their existing
> `onerror`-triggered fallback (removing the `<img>`, which for the header reveals the
> small SVG cloud placeholder underneath via the `:has(img)` CSS rule; the footer just goes
> blank). Root cause: on page load the app fires a burst of ~12-14 near-simultaneous HTTP
> requests (icon.png, brand.png, logo.png, manifest.json, the long-lived `/events` SSE
> stream, and a dozen initial REST state fetches for the light, MQTT fields, Power Behavior
> and Firmware) against the ESP8266's web server, which only has a handful of concurrent
> TCP connection slots; losing that race gets a request reset before the image loads.
> Desktop Chrome opens more parallel per-origin connections on page load than mobile
> Safari, which is why it surfaced there first, but the same race exists on any browser.
> Fixed in `web/app.html` and `web/setup.html`: both images now retry up to 3 times with a
> growing delay (500 ms, 1000 ms, 1500 ms) via a small `retryImgOnError()` helper before
> falling back exactly as before — by the time a retry fires, the initial request burst has
> settled and a plain refetch almost always succeeds. This does not change the root
> resource-contention issue (still only a handful of TCP slots), just makes a lost race
> self-heal instead of visibly failing. Reducing the icon/brand image file sizes was
> considered too (smaller transfers hold a connection slot for less time, marginally
> reducing contention odds) but wasn't necessary once the images reliably retry through a
> transient failure; revisit if the issue resurfaces.
> **Dedicated, smaller header logo (no version bump yet):** the issue above did
> resurface for the header specifically, so following through on "revisit if it
> resurfaces" — the app.html header now loads its own `/header.png` (224×112, a correctly
> proportioned @2x asset for its 112×56 CSS slot, losslessly optimized with `optipng`:
> 22.0 KB) instead of sharing `/brand.png` (28.7 KB, and letterboxed within that slot
> since its aspect ratio didn't match). Smaller + faster to fully transfer, so a lost
> connection race during the initial request burst is less likely. `/brand.png` itself is
> unchanged and still used by the firmware-update overlay icon and `web/setup.html`'s own
> header — this is a new, separate file/route (`header_file` in
> `packages/web-remote.yaml`, `/header.png` in `components/cloud_lamp_web`) specifically
> so those other spots are unaffected. `web/setup.html` was deliberately left on
> `/brand.png` for now (not asked for); revisit together if the header fix should extend
> there too.
> **Brightness icon (no firmware change, v2.5.0):** the icon next to the
> Brightness slider changed from a half-filled circle to a line-drawn light bulb (stroke
> style, matching the Speed slider's icon and the rest of the app's icon language) —
> clearer at a glance than the circle, which some testers read as unrelated to lighting.
> `web/app.html` only; no JS/behaviour change. **Not released yet** — bundled for the next
> version bump alongside whatever else lands before the next `tools/release.sh` run.
> **Candlelight — calmed down for nursery use (`effects.yaml`, v2.5.0):** the
> lamp is decorative — plausibly sitting right next to where a baby sleeps — not a room
> light, and the original Candlelight read as fast, jumpy, almost disco-like rather than a
> calm flame. Root cause was two-fold: (1) each ring **snapped** most of the way to a fresh
> random target every 90 ms instead of easing smoothly, so the colour visibly *stepped*
> roughly 11 times a second; (2) `candle_depth` never actually capped how deep a dip could
> go — the dip value was normalised by dividing by that same constant, so the effective
> flicker range was always ~0-100% of the full base→ember shift regardless of its value,
> despite the substitution's "higher = more nervous flame" comment implying otherwise.
> Redesigned: `dip[r]` now **eases continuously** toward a `target[r]` every 40 ms frame
> (`dip += (target - dip) * 0.05`) instead of jumping, so the glow visibly glides between
> levels; `candle_depth` (default lowered `140` → `60`) now genuinely scales the *maximum*
> reachable dip as a fraction of the full colour shift, so it's a real "how nervous" knob;
> `candle_interval_ms` (default raised `90` → `320`) re-rolls each ring's target roughly
> 3-4× less often. Net effect: a smooth, mostly-steady warm ember glow with small, soft,
> unsynchronised dips per ring "here and there" rather than a fast strobe — same warm
> orange→ember palette as before, same per-ring independence for a natural (not
> synchronised) look, same `effect_speed` slider control. Verified with `esphome compile`
> (clean build, no lambda errors); **not yet tested on real hardware** — the visual "feel"
> (glide speed `0.05`, depth `60`, interval `320 ms`) is a first pass meant to be tuned by
> eye on the bench lamp before release, not a final calibration.
> **Effect tuning pass — Spectrum Fade, Sky Breathing, Blue Color Wipe, Pulse
> (`effects.yaml`, v2.5.0):**
> - **Spectrum Fade** was a little too fast: `spectrum_fade_period_s` `36` → `48` (one full
>   18-colour lap now takes 48 s at speed 50, i.e. ~2.7 s per colour-to-colour crossfade
>   instead of ~2 s). Substitution only, lambda unchanged.
> - **Sky Breathing** looked almost off at its darkest point in a lit room — not a "not
>   using full brightness" bug (the light's Brightness slider and `color_correct` are
>   applied on top of whatever the effect renders, same as every other effect); the deep
>   ocean-blue trough colour `(15, 55, 190)` was just genuinely dark, made worse by
>   `color_correct: [100%, 75%, 60%]` (`cloud-lamp.yaml`) knocking its dominant blue
>   channel down further — a blue-heavy colour loses proportionally more perceived
>   brightness to that correction than a white/warm one does. Brightened the trough colour
>   to `(40, 110, 225)` (same hue, ~16% → ~30% perceived luminance after colour-correction;
>   the pale sky-blue peak is unchanged at ~65%) — still clearly the darker of the two ends,
>   just no longer reads as "off".
> - **Blue Color Wipe**: the moving colour boundary was an *integer* LED index, so each
>   step snapped exactly one LED from the old colour straight to the new one — visible as
>   individual LEDs "popping" on, exactly as reported. Rainbow doesn't show this because its
>   hue is a continuous per-pixel gradient with no hard edge anywhere to snap. Fixed the
>   same way: the boundary position is now a `float` that advances by real elapsed time
>   (not a fixed per-tick integer step), and only the single LED the edge is currently
>   crossing is blended smoothly between the old and new colour instead of flipping
>   outright — the edge now glides continuously across that one LED instead of stepping.
>   Also nudged `wipe_led_interval_ms` `400` → `350` (~12% faster) per the "just a little
>   bit" speed request. Verified the blend math in isolation (a standalone Python
>   simulation of the same formula): transitions land exactly on schedule and the blend
>   factor rises smoothly 0→1 across exactly one LED width every time, with no
>   off-by-one/wraparound glitches.
> - **Pulse** had already had its floor raised once before; the dimmest point still read as
>   close to off. Raised `pulse_min_level` `115` (~45%) → `150` (~59%) (max unchanged at
>   `225`/~88%) and slowed the cycle slightly further, `pulse_period_ms` `8000` → `8800`.
> All four: substitution/lambda changes in `effects.yaml` only, no entity/API changes.
> Verified with `esphome compile` (clean build); **not yet tested on real hardware** — a
> first pass meant to be tuned further by eye on the bench lamp before release.
> **Custom Color button styling (no firmware change, v2.5.0):** the full-width
> "Custom Color" tile in the Effect Presets grid had a plain white background, unlike every
> other effect tile's dark/translucent one — that made it look distractingly like it was
> always the *selected* tile even when a different effect was actually active. Now uses the
> exact same default background/border/text colour as the other tiles (via the shared
> `.fx-btn` rule, no more `.fx-custom`-specific overrides) and the same blue-tinted
> highlight as other tiles once selected (`.fx-btn.sel`), keeping only its full-width span
> (`grid-column:1/-1`) and centred label as what sets it apart. `web/app.html` CSS only; no
> JS/behaviour change.
> **Speed slider now shows its unit (no firmware change, v2.5.0):** the Speed
> slider's value used to render as a bare number ("50"), unlike the Brightness slider right
> above it ("70 %"), so it wasn't obvious what unit — if any — it was in. It's **%**: every
> animated effect's period/interval scales as `base * 50 / spd`, so the *rate* is directly
> proportional to `spd` — `100` is exactly double the default `50`'s animation rate, `1` is
> 1/50th of it — a genuine linear percentage of maximum speed, not a decorative number. See
> [Effect Speed](#effect-speed-numbereffect_speed) for the full explanation. `web/app.html`
> now appends `" %"` in `renderSpeed()` and the slider's live-drag `input` handler, mirroring
> `renderBrightness()`. Display-only change; no JS logic/behaviour change.
> **New effect: Ring Ripple (`effects.yaml`, v2.5.0):** added after a deliberate
> gap-analysis of the existing nine animated effects (see chat) — every "travelling" effect
> already here (Rainbow, Spectrum Flow, Blue Color Wipe) moves along the flattened 24-LED
> strip, and every per-ring effect (Candlelight) only randomises independently per ring, so
> none of them actually use the lamp's real 3-ring construction as a *direction of motion*.
> Ring Ripple does: a single soft brightness wave travels physically ring 1 → ring 2 → ring
> 3 (the data-wiring order — see [Hardware](#hardware)), fades out past the last ring,
> pauses briefly at the dim floor colour, then the next ripple begins — like a slow ripple
> spreading across still water. Deliberately coarse (whole-ring, not per-LED, brightness
> steps) since that's what makes it read as "ring motion" rather than another LED-strip
> effect. Stateless — every frame computed straight from `millis()`, no static variables
> needed, unlike every other travelling/flicker effect in this file. Implementation note:
> the wave position is eased in and out with an explicit `runout` margin (3.5×
> `ring_ripple_sigma`) *before* ring 1 and *after* ring 3 so the Gaussian brightness bump
> has already decayed to a negligible ~0.1% before the travel phase ends and the pause
> phase's flat floor colour takes over — without that margin the ripple would pop in/out
> abruptly right at the sweep's start/end instead of gliding all the way down smoothly (the
> same class of bug the Blue Color Wipe fix above addressed). Verified the wave/decay math
> in isolation (a standalone Python simulation): confirmed a smooth Gaussian rise and fall
> through all three rings with the pause phase, and confirmed the fix eliminates the
> discontinuity (residual brightness at the travel/pause boundary is ~0.3%, imperceptible).
> Colours (`base`/`peak` in the lambda) are a first pass — a dim, cool "resting cloud" floor
> brightening to a pale near-white crest as the ripple passes; not yet tested on real
> hardware. Added to `SPEED_FX`, `FX_SWATCH` and every `FX_NAMES` language map in
> `web/app.html`, and to `tools/mock-device.py`'s `EFFECTS` list, per the "renaming an
> effect" note above. Inserted between Candlelight and Spectrum Fade in both files' effect
> order, which — per the same note — shifts the persisted `last_effect_index` for every
> effect after it (Spectrum Fade onward) by one; harmless one-time cosmetic jump on a
> lamp's first update past this release. Verified with `esphome compile` (clean build).
> **Power-loss "Restore Last State" investigated — found a real limitation, decision
> pending (no code change yet):** checked, at the user's request, whether `saved_on` /
> `last_effect_index` / `custom_color_active` / `custom_color_rgb` / `brightness_pct` and
> the `power_behavior` select itself actually survive a genuine power cut, not just a
> reboot. **They don't, reliably** — verified by reading the installed ESPHome package's
> own C++ source, not assumed. Every `restore_value: yes` global and every
> `restore_value: true`/`restore_mode: …` entity in this whole config (globals, the
> `power_behavior` select, the MQTT enable switch and broker text/number fields — all of
> them, not just the power-related ones) calls `global_preferences->make_preference(...)`
> with no explicit "in flash" argument, which on ESP8266 defaults to `in_flash = false`
> unless the `esp8266:` block sets `restore_from_flash: true`
> (`esphome/components/esp8266/preferences.h`) — neither `cloud-lamp.yaml` nor
> `cloud-lamp-dev.yaml` sets it, so every one of these values lives in the chip's **RTC
> memory**, not flash (`esphome/components/esp8266/preferences.cpp`'s
> `save_to_rtc()`/`load_from_rtc()`; the switch component's own field for this is even
> literally named `rtc_`). ESP8266 RTC memory is well-documented (Espressif/Arduino-core;
> cross-checked against multiple independent sources) to survive a **software reset,
> watchdog reset, or deep sleep**, but **not an actual loss of VCC power** — exactly the
> "unplug the lamp" scenario "Restore Last State" exists for, per its own code comment
> ("restore the lamp after a power cut"). Practical effect: after a genuine power
> outage/unplug, `saved_on` *and* the user's own `power_behavior` choice both silently
> revert to their compiled-in defaults (`false` / `"Start Off"`) — the lamp reliably boots
> off after a real power cut no matter what was selected or showing beforehand. (Wi-Fi
> credentials are unaffected — those go through the Arduino core's own, always-flash-backed
> Wi-Fi config storage, a completely separate mechanism from ESPHome's
> `global_preferences`.) The fix is a one-line `esp8266: restore_from_flash: true` (moves
> every `restore_value` entity in the config — this and the MQTT settings — from RTC memory
> to a dedicated flash sector; ESPHome has no per-entity flash-vs-RTC override, checked in
> both the `globals` and `template`/`select` component schemas, so it's an all-or-nothing
> device-level setting), at the cost of a small, real amount of flash wear from periodic
> preference-sync writes (deduped to at most once/second per changed value, or once per
> deliberate reboot's `on_shutdown()` flush) — likely inconsequential for how rarely
> brightness/effect/on-off change on a decorative lamp over its lifetime, but a genuine
> hardware-lifespan tradeoff, not purely code, so it was put to the user rather than decided
> silently. **Resolved: `esp8266: restore_from_flash: true` added to `cloud-lamp.yaml`**
> (inherited automatically by `cloud-lamp-dev.yaml`, which packages the public build as its
> base) — accepting the small flash-wear tradeoff so "Restore Last State" genuinely survives
> a real power cut. Verified with `esphome compile` (clean build; flash usage unchanged at
> 82.0%, RAM +256 B); not yet tested on real hardware.
> **Boot logic now distinguishes a deliberate reboot from a real power cut (`cloud-lamp.yaml`,
> v2.5.0):** separately checked, per the user's request, whether a lamp that's ON
> right before a software-triggered reboot (most importantly a successful OTA update) comes
> back ON afterwards. Traced the full OTA/reboot flow in the installed ESPHome package's C++
> source: none of the three `ota:` platforms in this config (`web_server`, `http_request`/
> `ota_via_http`, `esphome`) ever touch the light, and a failed, aborted or canceled update
> never reboots at all — `ota_http_request.cpp`'s `flash()` only calls `App.safe_reboot()`
> on the `OTA_RESPONSE_OK` branch; every other outcome just clears retry state and returns,
> leaving the running firmware (and the light, mid-effect) completely untouched. So those
> three outcomes were already correct with no code change needed — there was never
> anything to "return to", because nothing was ever changed. The one real gap: a
> *successful* update calls `App.safe_reboot()` and reboots into the new firmware, where
> `apply_boot_light_state` — the same script that runs after every boot, for every reason —
> unconditionally applied the `power_behavior` select's *power-cut* policy, meaning a lamp
> with the default "Start Off" behaviour would always come back off after a successful
> update even if it had been on seconds before. Fixed by having `apply_boot_light_state`
> check `ESP.getResetReason()` first: ESP8266 reports exactly `"Software/System restart"`
> for a reboot triggered by `system_restart()` — what `App.safe_reboot()`'s `arch_restart()`
> calls under the hood (`esphome/components/esp8266/hal.cpp`) — and something else
> (`"Power On"`, `"External System"`, a watchdog/exception reason) for an actual power-on or
> crash/reset. On a software-restart boot the lamp now always resumes `saved_on` exactly as
> it was, ignoring `power_behavior` entirely; every other boot cause keeps the existing
> `power_behavior` logic unchanged (subject to the RTC-memory caveat in the entry above).
> This also correctly covers the Restart button and MQTT `Set/Reboot` (both go through the
> same `App.safe_reboot()`) and safe_mode's own retry-reboot — every deliberate software
> reboot, not just the OTA case originally asked about. `saved_on` is guaranteed current at
> this point regardless of the usual 1 s polling delay: `App.safe_reboot()` runs every
> component's `on_shutdown()` hook before actually resetting
> (`esphome/core/application.cpp`), which flushes the globals' preference immediately.
> Verified with `esphome compile` (clean build); not yet tested on real hardware.
> **Power toggle knob vertically off-centre (no firmware change, v2.5.0):** the
> big on/off toggle's circular knob sat 1 px lower than centre — 4 px gap above it, 2 px
> below. Root cause: the knob used a fixed `top:4px`, but this page's global
> `box-sizing:border-box` means the track's `height:52px` already includes its `1px`
> border, so the track's actual inner height is `50px`, not `52px` — `top:4px` on a `44px`
> knob left `50-4-44=2px` below instead of the `4px` a truly centred knob needs. (The
> smaller MQTT toggle uses the same pattern but its numbers happen to divide evenly, so it
> was already centred — only the main power toggle was affected.) Fixed by switching the
> knob to `top:50%` + `transform:translateY(-50%)`, which centres it exactly regardless of
> border width. `web/app.html` CSS only. Verified with a pixel-measurement check via CDP
> (`getBoundingClientRect()`) against the mock device server: gap above/below the knob is
> now exactly 4px/4px.
> **Still open:** the iOS Safari 26 full-bleed edge-to-edge background issue described in
> the six "Full-bleed background fix" entries above — a plain Safari tab doesn't stretch to
> the top and the standalone home-screen app doesn't stretch to the bottom, and none of the
> six independent fixes attempted (cache-busting the icon, `theme-color`, a
> `background-color` fallback, GPU compositing, the `opacity:.999` workaround, removing the
> fixed-position/`overflow:hidden` structure) resolved either symptom on a real device.
> Deferred rather than actively worked on for now; worth revisiting if a future Safari
> release changes this behaviour, or if a fundamentally different approach turns up (e.g.
> giving up on `viewport-fit=cover` edge-to-edge entirely and living with a solid-colour
> status-bar/home-indicator strip instead of chasing Safari 26's tinting quirks further).
> Per-effect user presets (store brightness + speed per effect, applied on
> selection — feasible, deferred; see Web app section); intensity slider (per-effect
> mapping); test button gestures / captive portal end-to-end; print + apply the finalised
> product sticker (docs/Label.lbx); 3D print files.
> **Firmware:** ESPHome 2026.6.0, project version 2.6.1

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
   is the generic public build — no personal names, no Wi-Fi networks, no MQTT credentials.
   MQTT itself is always included (default OFF; broker configured entirely at runtime from
   the web app, so nothing device- or person-specific is ever compiled in). The builder's
   bench lamp uses `cloud-lamp-dev.yaml`, which just layers compiled-in Wi-Fi networks on
   top. Published binaries come only from the public build (enforced by `tools/release.sh`).
4. **Settings survive everything.** Persisted values (brightness, effect, custom colour,
   power behaviour, MQTT enabled/broker/port/username/password) live in the ESP preferences
   area, outside the firmware image. They survive reboots, power cuts and OTA updates —
   `esp8266: restore_from_flash: true` (`cloud-lamp.yaml`) puts them in a dedicated flash
   sector rather than ESP8266 RTC memory, which is lost on an actual power cut (see
   [Power-loss "Restore Last State" investigated](#project-status) in the changelog for why
   that distinction matters and the flash-wear tradeoff it was chosen over). Captive-portal
   Wi-Fi credentials are handled entirely separately by the Arduino core's own Wi-Fi config
   storage. Global IDs are kept stable across firmware versions so stored values stay
   attached.

---

## File structure

```
cloud-lamp/
├── cloud-lamp.yaml               # Core firmware = public build (no secrets embedded)
├── cloud-lamp-dev.yaml           # Builder build: core + secret Wi-Fi networks
├── effects.yaml                  # Effects package + all effect tuning knobs
├── secrets.yaml                  # Per-device credentials — git-ignored, never committed
├── secrets.example.yaml          # Template for secrets.yaml (placeholders only)
├── packages/
│   ├── web-remote.yaml           # Web server + web app + diagnostics (default ON)
│   ├── updates.yaml              # Online firmware updates (default ON)
│   ├── mqtt.yaml                 # MQTT / ioBroker integration (default OFF, always included)
│   └── temperature-sensor.yaml   # Case temperature + thermal shutdown (optional)
├── components/
│   ├── cloud_lamp_web/           # Custom ESPHome component serving the web app
│   └── signed_update/            # Custom `update:` platform: plain-HTTP + Ed25519-signed
│       └── update/               #   manifest check (see firmware-updates.md)
├── web/
│   ├── app.html                  # Single-file iOS-style web app (gzipped into firmware)
│   ├── setup.html                # Branded captive-portal Wi-Fi onboarding page
│   ├── icon.png                  # Home-screen / PWA icon (wordmark, transparent)
│   ├── brand.png                 # Wordmark for the fw-update overlay + setup.html header (/brand.png)
│   ├── header.png                # Wordmark for app.html's own header, @2x for its CSS slot (/header.png)
│   └── logo.png                  # DD Productions logo (embedded, served at /logo.png)
├── assets/                       # Artwork sources (cloud-lamp-logo.png = project wordmark)
├── tools/
│   ├── release.sh                # Build, sign + git-push a firmware release for the updater
│   ├── build-manual.py           # Render docs/user-manual.md → docs/user-manual.pdf
│   └── mock-device.py            # Local mock of the device API for web app development
└── docs/                         # This folder — served as-is by GitHub Pages at the
    │                             #   cloud-lamp.ddproductions.de custom domain
    ├── user-manual.pdf           # End-user manual (permanent URL target of the sticker
    │                             #   QR code; regenerate with tools/build-manual.py)
    ├── firmware-dist/            # Published releases = the live update channel AND
    │                             #   history (see firmware-updates.md)
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

A brand-new lamp defaults to **Aurora Drift** the first time it's turned on
(`last_effect_index`'s `initial_value` in `cloud-lamp.yaml` points at Aurora Drift's
position in `effects.yaml`, which is also why it's listed first among the special
effects). Existing lamps always keep whichever effect they last had selected —
this default only applies before the very first effect change.

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
   Otherwise, `apply_boot_light_state` checks *why* the device rebooted:
   - **A deliberate software reboot** (a successful OTA update via any of the three `ota:`
     platforms, the Restart button, MQTT `Set/Reboot`, or safe_mode's own retry) is not a
     power cut — the lamp always resumes exactly how it was the instant before, on or off,
     regardless of the *Power Behavior* setting. Detected via `ESP.getResetReason() ==
     "Software/System restart"`, the reset reason the ESP8266 SDK reports only for this
     case (a failed/aborted/canceled update never reaches this point at all — it never
     reboots, so the light is simply never touched).
   - **Any other boot cause** (actual power-on, external reset, watchdog/crash) applies the
     *Power Behavior* setting: **Start switched off** (firmware option `Start Off`,
     default) or **Restore Last State** (turns back on with the saved effect and
     brightness if the lamp was on when power was cut).

   Then `boot_completed` is set; only from this point are button presses, MQTT commands
   and state mirroring active.

`restore_mode: ALWAYS_OFF` on the light plus a hard pixel-buffer clear after every turn-off
guarantee no LED can stay lit from an undefined boot state.

### Wi-Fi / provisioning

- **Public build (`cloud-lamp.yaml`): no compiled-in networks.** Its binaries are published
  publicly, so it must not embed any credentials; Wi-Fi comes exclusively from the captive
  portal (stored in flash, survives updates). The builder's dev build
  (`cloud-lamp-dev.yaml`) adds two compiled-in networks from `secrets.yaml` — see
  [device-credentials.md](./device-credentials.md).
- If no network connects, the lamp opens the setup hotspot `Cloud-Lamp-XXXXXX` (password on
  the sticker) with a captive portal for entering home Wi-Fi credentials. The lamp keeps
  working as a lamp the whole time; `reboot_timeout: 0s` means it never reboots over Wi-Fi.
- The portal shows the **branded onboarding page** (`web/setup.html`, served by
  `cloud_lamp_web`): same design language as the app, a language dropdown (same ten
  languages as the app, English default — a deliberate, explicit choice rather than
  auto-detecting the phone's OS language), network list with signal strength, password
  reveal, and a success view that tells the user to rejoin their home Wi-Fi and open the
  lamp's `.local` address. The stock
  captive-portal endpoints (`/config.json` scan, `/wifisave` save) keep doing the work
  underneath; without a compiled-in setup page the stock ESPHome page appears instead.

---

## Web app (`packages/web-remote.yaml` + `components/cloud_lamp_web/` + `web/app.html`)

A single-file iOS-style web app served by the lamp itself at `http://<lamp-ip>/`.

- **Delivery:** `web/app.html` is gzip-compressed at compile time and embedded in flash
  (PROGMEM) by the custom `cloud_lamp_web` component. The component also serves
  `/manifest.json` (PWA manifest, name = friendly name), `/icon.png` (home-screen / PWA
  icon), `/header.png` (transparent cloud mark in the app header), `/brand.png` (the same
  wordmark, used by the firmware-update overlay icon and `web/setup.html`'s own header —
  see below), `/logo.png` (DD Productions maker logo in the footer) and `/device.json`
  (name, serial, MAC, version).
- **PWA icon (`/icon.png`):** the project wordmark on a square transparent canvas
  (512×512). Used for Add to Home Screen / manifest icons. iOS may still fill
  transparent `apple-touch-icon` pixels with black — check on a real device after each
  artwork change; if it looks wrong, composite the wordmark onto the PWA
  `background_color` (`#0b0f18`) instead. Every reference to it (`app.html`'s `<link
  rel="icon">` / `<link rel="apple-touch-icon">`, the manifest's `icons` entry) carries a
  `?v=<hash>` cache-buster computed from the file's own bytes at compile time — iOS
  Safari's site-icon cache is known to ignore `Cache-Control` and can get stuck on a
  stale favicon/home-screen icon otherwise (see changelog). Changing `web/icon.png`'s
  content is enough; the hash (and therefore the URL) updates itself automatically.
- **Header brand (`/header.png`):** the same wordmark, its own dedicated file
  (224×112 — a proper @2x asset for the header's 112×56 CSS slot, `object-fit: contain`,
  no background box; not used as the home-screen icon). Deliberately a separate file
  from `/brand.png` (which still serves the firmware-update overlay icon and
  `web/setup.html`'s header) so this one spot's resolution/aspect ratio/file size can be
  tuned independently — see the changelog entry below for why.
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
  device-confirmed (no unverified optimistic UI). REST paths address entities by their
  display Name, URL-encoded (e.g. `/light/Cloud%20Light`, not the legacy object_id
  `/light/cloud_light`) — see `restPath()`/`P_*` constants in `web/app.html`. ESPHome still
  accepts object_id URLs today but logs a deprecation warning and removes them entirely in
  2026.7.0. `tools/mock-device.py` accepts both forms (see its `NAME_TO_ID` table). Note this
  is separate from the JSON payloads' `id` field (e.g. `"id":"light-cloud_light"`), which is
  still the old object_id-based format for now — ESPHome already exposes the future format in
  a parallel `name_id` field (e.g. `"light/Cloud Light"`) and `id` itself switches to it in
  2026.8.0; the app doesn't consume `name_id` yet since `id` hasn't changed shape.
- **Features:** power toggle, brightness slider, *Effect Presets* grid with colour
  swatches (grouped into *Colors* and *Special effects*) plus a *Custom color* section
  between them — a single full-width white button that opens the OS-native colour picker
  (`<input type="color">` — the iOS 14+ system spectrum/grid/slider sheet; live preview is
  throttled to ~5 requests/s while dragging). A custom colour is stored in the firmware
  like an effect (globals `custom_color_active` + `custom_color_rgb`), so it survives
  power cuts and off/on; a button double-press leaves it and re-enters the effect cycle
  at the last-used effect. There is also a header book icon that opens the
  [user manual PDF](./user-manual.pdf) in a new tab (permanent GitHub Pages URL serving
  the PDF straight from this repo — same target as the sticker QR code), settings sheet (language, power-cut behaviour, network diagnostics,
  *Change Wi-Fi network*, an MQTT section (enable switch plus broker address/port/
  username/password fields, only shown once enabled — settings persist across
  disable/re-enable), firmware version/update with
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
checks a manifest over **plain HTTP** every 6 h (or on demand via *Check for updates now*),
verifies its **Ed25519 signature** on-device (`components/signed_update/`, an `update:`
platform swapped in for `http_request`'s own) before trusting anything in it; when a newer,
validly-signed version is found the web app shows an *Install* button; the image is
downloaded (also plain HTTP), MD5-verified and written to the inactive flash area while the
lamp keeps running; `safe_mode` catches boot loops after a bad flash. Releases are published
by `tools/release.sh` with a single `git push` — this repo's `docs/firmware-dist/` is both
the release history and, via GitHub Pages' custom domain, the plain-HTTP host the lamp
actually fetches from — signing the manifest with a private key kept outside the repo.
Plain HTTP replaced HTTPS in v2.4.0
because BearSSL's TLS handshake against GitHub's CDN needs more contiguous free heap than
this device reliably has; see the [v2.4.0 changelog entry](#project-status) and
[firmware-updates.md](./firmware-updates.md#plain-http--ed25519-signing) for the full story.
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
| White / Sky Blue / Blue / Indigo / Purple / Magenta / Salmon / Red / Peach / Apricot / Orange / Amber / Honey / Gold / Vanilla / Yellow / Chartreuse / Green | solid | Static colours, 250 ms refresh. 18 colours, White first (default cycle start), then one continuous hue sweep blue → violet → pink → red → orange → yellow → green. Every hex value was tested on-device with the web app's colour picker before being locked in. Speed slider hidden. |
| Aurora Drift | animated | Slow-moving vivid teal→violet gradient with per-ring depth (saturated endpoints since v2.1.5 — the pastel pair washed out). **First special effect** and the effect a brand-new lamp shows on its very first power-on (`last_effect_index` initial value, see [Behaviour reference](#behaviour-reference)). |
| Sky Breathing | animated | Slow crossfade between a deep ocean blue and a pale sky blue — widened from the original narrow pair, which was too subtle to notice; deep-blue end later brightened too, see changelog |
| Candlelight | animated | Warm orange with a gentle, smoothly-eased per-ring flicker that dims *and* reddens slightly towards an ember tone — a calm, nursery-safe glow with small soft dips here and there, not a fast/jumpy strobe (retuned from an earlier, much more "disco-like" version — see changelog) |
| Ring Ripple | animated | A soft brightness wave that travels physically ring 1 → ring 2 → ring 3 (the data-wiring order, see [Hardware](#hardware)), fades past the last ring, pauses, then repeats — the one motion the lamp's 3-ring build supports that no other effect uses (everything else travels along the flattened LED strip instead) |
| Spectrum Fade | animated | Whole lamp crossfades through the 18-colour palette above, all rings together |
| Spectrum Flow | animated | Same 18-colour palette, but travelling — a colour gradient scrolls across the individual LEDs |
| Twinkle | animated | Quiet starfield — sparse sparks with a smooth sin() rise-and-fall envelope (never pops in/out) over a real ambient floor; kid-friendly, no flashes — reworked from the original near-invisible version |
| Blue Color Wipe | animated | Blue → violet cloud colours (Sky Blue/Blue/Indigo/Purple), very slow sweep with a smoothly-blended (not stepped) LED edge — widened and renamed from "Color Wipe" to make clear it stays in the blue/violet family |
| Rainbow | animated | Full spectrum, slow hue drift |
| Pulse | animated | Pixel-level breathing, raised to ~59–88 % so the low point never looks "off" (never overwrites saved brightness) |

### Effect Speed (`number.effect_speed`)

A persisted template number **1–100** (default **50** = substitution defaults in
`effects.yaml`). The web app shows a Speed slider only while an animated effect that
honours speed is active. Higher values shorten periods / increase spark rate; lower
values calm the motion. Solids ignore it.

**Unit:** every effect computes its period/interval as `base_value * 50 / spd` (see any
lambda in `effects.yaml`), i.e. the *rate* (1/period) is directly proportional to `spd` —
value `100` really is exactly double the animation rate of the default `50`, and `1` is
1/50th of it (practically stopped). That linear proportionality is what makes displaying
it as a plain **%** of maximum speed accurate rather than just a decorative unit, and it's
why the web app's Speed value now reads e.g. "50 %" instead of a bare "50" — matching the
Brightness slider's own "value %" display (`web/app.html`, `renderSpeed()` and the
slider's `input` handler). It is **not** a duration (not milliseconds) and not tied to any
single effect's specific timing — it's a relative multiplier every animated effect's own
substitutions (`*_period_s`, `*_interval_ms`, etc.) are scaled by.

Effect names are case-sensitive canonical identifiers used by MQTT (`Set/Effect` /
`State/Effect`) and the REST API. When renaming an effect, update the display-name maps in
`web/app.html` (`FX_NAMES`, `FX_SWATCH`, `SPEED_FX`, `SOLID_FX`) as well. The web app
groups the grid into **Colors** (names in `SOLID_FX`) and **Special effects** (everything
else, including unknown future effects), with the *Custom color* button rendered between
the two groups. Note: the last-used effect is persisted as an *index*, so reordering or
removing effects shifts which effect a lamp restores after its first update — harmless
one-time cosmetic jump.

### Deferred idea: per-effect user presets

Store brightness + speed per effect in the preferences area and apply them whenever that
effect is selected (button, web app and MQTT alike, via the shared effect scripts). UI:
adjust the live sliders, then "Save as default for this effect" + per-effect reset.
Feasible and cheap (16×2 small values); needs a decision on brightness semantics (today
brightness is global and survives effect changes). Creating entirely *new* user effects is
not possible — effect algorithms are compiled in.

---

## MQTT design (`packages/mqtt.yaml`, always included, OFF by default)

Always compiled in on every build (public and dev) but OFF on every new device
(`RESTORE_DEFAULT_OFF`) and fully runtime-configurable — no broker credentials are ever
baked into a binary. Designed to never affect lamp functionality: `reboot_timeout: 0s`,
plus a persisted runtime switch (*MQTT Enabled* in the web app settings) that silences
MQTT without a reflash.

### Runtime configuration (no reflash needed)

The web app's settings sheet exposes, in an "MQTT" section that only shows the fields
below once *MQTT Enabled* is on:

- **MQTT Broker** (`text.mqtt_broker_host`) — hostname or IP
- **MQTT Port** (`number.mqtt_broker_port`, default `1883`)
- **MQTT Username** (`text.mqtt_broker_username`) — optional
- **MQTT Password** (`text.mqtt_broker_password`, password-mode) — optional

All four are `template` entities with `restore_value: true`, so they persist in flash
independently of the enable switch — turning MQTT off never loses what was typed in.
Each has a `set_action` that calls `mqtt::global_mqtt_client->set_broker_address()` /
`set_broker_port()` / `set_username()` / `set_password()` and reconnects immediately if
MQTT is currently on; the enable switch's `turn_on_action` re-applies all four before
calling `enable()` (needed because ESPHome's `mqtt:` block only ever sees the empty
compile-time placeholders — the real values live in these entities). Note: like all
ESPHome password-mode `text` entities, the REST API's `value` field returns the
plaintext password (only the human-readable `state` field is masked) — acceptable here
since this is the lamp owner's own LAN and their own broker, not a device secret.

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
