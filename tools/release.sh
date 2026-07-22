#!/usr/bin/env bash
# ==============================================================================
# tools/release.sh — Build and publish a firmware release for the online updater
#
# Usage:
#   tools/release.sh [config.yaml]     (default: cloud-lamp.yaml)
#
# What it does:
#   1. Reads device_name and project_version from the config's substitutions.
#   2. Compiles the firmware with ESPHome.
#   3. Copies the OTA binary into  docs/firmware-dist/<device_name>/  and writes
#      the update manifest (version, path, MD5, Ed25519 signature) next to it.
#   4. Commits + pushes docs/firmware-dist/<device_name>/ to GitHub. That single
#      push both records release history AND republishes the live update
#      channel — GitHub Pages serves docs/ directly at the custom domain the
#      lamp actually checks (${update_manifest_url} in cloud-lamp.yaml), so
#      there is no separate upload step to keep in sync.
#
# Why signed + plain HTTP instead of HTTPS (see docs/firmware-updates.md for
# the full writeup): the ESP8266 can't reliably complete a BearSSL TLS
# handshake against GitHub's CDN within its free contiguous heap. Moving to
# plain HTTP removes that ceiling entirely; the Ed25519 signature this script
# adds to the manifest is what keeps the update trustworthy without TLS.
#
# Publishing (see docs/firmware-updates.md):
#   The lamp checks ${update_manifest_url} — a GitHub Pages custom domain,
#   with "Enforce HTTPS" deliberately left off so it stays plain HTTP — every
#   6 hours and offers the update in its web app when the manifest version
#   differs from the installed one.
#
# Signing key (see docs/firmware-updates.md):
#   The Ed25519 PRIVATE key lives OUTSIDE this repo — by default at
#   ~/.cloud-lamp-release-secrets/ota-ed25519-private.key (override with
#   RELEASE_SIGNING_KEY). Only its matching PUBLIC key is compiled into the
#   firmware (cloud-lamp.yaml's ota_ed25519_pubkey substitution).
#
# IMPORTANT: bump project_version in the config's substitutions BEFORE
# releasing — the updater compares version strings, and publishing the same
# version twice will not be offered to devices.
# ==============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

CONFIG="${1:-cloud-lamp.yaml}"

get_sub() {
  # Extracts a quoted substitution value: get_sub key
  sed -n "s/^[[:space:]]*$1:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$CONFIG" | head -n 1
}

DEVICE_NAME="$(get_sub device_name)"
VERSION="$(get_sub project_version)"

if [[ -z "$DEVICE_NAME" || -z "$VERSION" ]]; then
  echo "ERROR: could not read device_name / project_version from $CONFIG" >&2
  exit 1
fi

if [[ "$CONFIG" == *dev* ]]; then
  echo "ERROR: refusing to release a dev build ($CONFIG embeds credentials from secrets.yaml)." >&2
  echo "       Releases are built from cloud-lamp.yaml only." >&2
  exit 1
fi

echo "==> Building $DEVICE_NAME v$VERSION from $CONFIG"
esphome compile "$CONFIG"

BIN=".esphome/build/$DEVICE_NAME/.pioenvs/$DEVICE_NAME/firmware.bin"
if [[ ! -f "$BIN" ]]; then
  echo "ERROR: build output not found: $BIN" >&2
  exit 1
fi

# --- Secret-leak guard: the published binary must not contain any value from
# secrets.yaml (except the shared, deliberately public AP + OTA passwords).
echo "==> Verifying the binary contains no secrets"
python3 - "$BIN" <<'PYEOF'
import sys, yaml
data = open(sys.argv[1], "rb").read()
allowed = {"ap_password", "ota_password"}  # shared + documented on sticker/docs
leaked = [k for k, v in yaml.safe_load(open("secrets.yaml")).items()
          if k not in allowed and len(str(v)) >= 4 and str(v).encode() in data]
if leaked:
    print(f"ERROR: secrets found in binary: {', '.join(leaked)} — NOT publishing.", file=sys.stderr)
    sys.exit(1)
print("    OK — no secrets embedded.")
PYEOF

OUT_DIR="docs/firmware-dist/$DEVICE_NAME"
OUT_BIN="$DEVICE_NAME-$VERSION.bin"
mkdir -p "$OUT_DIR"
cp "$BIN" "$OUT_DIR/$OUT_BIN"

MD5="$(md5 -q "$OUT_DIR/$OUT_BIN" 2>/dev/null || md5sum "$OUT_DIR/$OUT_BIN" | cut -d' ' -f1)"

# --- Sign the manifest ------------------------------------------------------
# Canonical message is "<version>|<path>|<md5>" — see
# components/signed_update/__init__.py for the matching on-device check.
SIGNING_KEY="${RELEASE_SIGNING_KEY:-$HOME/.cloud-lamp-release-secrets/ota-ed25519-private.key}"
if [[ ! -f "$SIGNING_KEY" ]]; then
  echo "ERROR: Ed25519 signing key not found at $SIGNING_KEY" >&2
  echo "       See docs/firmware-updates.md for how to generate one." >&2
  echo "       (Set RELEASE_SIGNING_KEY to use a different path.)" >&2
  exit 1
fi

echo "==> Signing manifest"
SIGNATURE="$(python3 - "$SIGNING_KEY" "$VERSION" "$OUT_BIN" "$MD5" <<'PYEOF'
import sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key_path, version, path, md5 = sys.argv[1:5]
with open(key_path, "rb") as f:
    raw = f.read()
if len(raw) != 32:
    print(f"ERROR: signing key at {key_path} must be 32 raw bytes, got {len(raw)}", file=sys.stderr)
    sys.exit(1)
key = Ed25519PrivateKey.from_private_bytes(raw)
message = f"{version}|{path}|{md5}".encode()
print(key.sign(message).hex())
PYEOF
)"

cat > "$OUT_DIR/manifest.json" <<EOF
{
  "name": "Cloud Lamp ($DEVICE_NAME)",
  "version": "$VERSION",
  "builds": [
    {
      "chipFamily": "ESP8266",
      "ota": {
        "path": "$OUT_BIN",
        "md5": "$MD5",
        "signature": "$SIGNATURE",
        "summary": "Cloud-Lamp firmware $VERSION"
      }
    }
  ]
}
EOF

echo
echo "==> Release built: $OUT_DIR/"
echo "    $OUT_BIN  (md5 $MD5)"
echo "    manifest.json (signed)"

# --- Publish: a single push to GitHub -----------------------------------
# docs/ is served directly by GitHub Pages at the custom domain the lamp
# checks, so committing + pushing docs/firmware-dist/<device_name>/ both
# records release history AND republishes the live update channel in one
# step — no separate upload target to keep in sync.
echo
echo "==> Publishing release (git push)"

git add "$OUT_DIR"
if git diff --cached --quiet -- "$OUT_DIR"; then
  echo "    no changes to commit (already up to date), pushing anyway"
else
  git commit -m "Release $DEVICE_NAME v$VERSION"
fi
git push

echo
echo "==> Release v$VERSION published."
echo "    GitHub Pages will pick it up shortly at \${update_manifest_url}."
