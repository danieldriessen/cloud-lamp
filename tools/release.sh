#!/usr/bin/env bash
# ==============================================================================
# tools/release.sh — Build a firmware release for the online updater
#
# Usage:
#   tools/release.sh [config.yaml]     (default: cloud-lamp.yaml)
#
# What it does:
#   1. Reads device_name and project_version from the config's substitutions.
#   2. Compiles the firmware with ESPHome.
#   3. Copies the OTA binary into  firmware-dist/<device_name>/  and writes
#      the update manifest (version, path, MD5) next to it.
#
# Publishing (see docs/firmware-updates.md):
#   firmware-dist/ is tracked in this repository. Commit and push it; each
#   lamp checks
#     https://raw.githubusercontent.com/danieldriessen/cloud-lamp/main/firmware-dist/<device_name>/manifest.json
#   every 6 hours and offers the update in its web app when the manifest
#   version differs from the installed one.
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

OUT_DIR="firmware-dist/$DEVICE_NAME"
OUT_BIN="$DEVICE_NAME-$VERSION.bin"
mkdir -p "$OUT_DIR"
cp "$BIN" "$OUT_DIR/$OUT_BIN"

MD5="$(md5 -q "$OUT_DIR/$OUT_BIN" 2>/dev/null || md5sum "$OUT_DIR/$OUT_BIN" | cut -d' ' -f1)"

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
        "summary": "Cloud-Lamp firmware $VERSION"
      }
    }
  ]
}
EOF

echo
echo "==> Release ready: $OUT_DIR/"
echo "    $OUT_BIN  (md5 $MD5)"
echo "    manifest.json"
echo
echo "Next: publish the release:"
echo "    git add firmware-dist/$DEVICE_NAME && git commit -m \"Release $DEVICE_NAME v$VERSION\" && git push"
