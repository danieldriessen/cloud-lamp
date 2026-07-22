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
#   3. Copies the OTA binary into  firmware-dist/<device_name>/  and writes
#      the update manifest (version, path, MD5, Ed25519 signature) next to it.
#   4. Publishes the release as ONE atomic step, both halves required:
#        a) commits + pushes firmware-dist/<device_name>/ to GitHub, and
#        b) uploads manifest.json + the .bin to the plain-HTTP host the lamp
#           actually checks (${update_manifest_url} in cloud-lamp.yaml).
#      If either half fails, the release is reported as NOT published — see
#      "Publishing" below. Re-running the script is safe (same version/MD5/
#      signature) until both halves succeed.
#
# Why signed + plain HTTP instead of HTTPS (see docs/firmware-updates.md for
# the full writeup): the ESP8266 can't reliably complete a BearSSL TLS
# handshake against GitHub's CDN within its free contiguous heap. Moving to
# plain HTTP removes that ceiling entirely; the Ed25519 signature this script
# adds to the manifest is what keeps the update trustworthy without TLS.
#
# Publishing (see docs/firmware-updates.md):
#   The lamp checks ${update_manifest_url} (the HTTP host, set in
#   cloud-lamp.yaml) every 6 hours and offers the update in its web app when
#   the manifest version differs from the installed one. GitHub's copy of
#   firmware-dist/ is the source-of-truth history and a manual-download
#   fallback — the lamp itself never fetches from GitHub.
#
# Signing key (see docs/firmware-updates.md):
#   The Ed25519 PRIVATE key lives OUTSIDE this repo — by default at
#   ~/.cloud-lamp-release-secrets/ota-ed25519-private.key (override with
#   RELEASE_SIGNING_KEY). Only its matching PUBLIC key is compiled into the
#   firmware (cloud-lamp.yaml's ota_ed25519_pubkey substitution).
#
# HTTP host upload (see docs/firmware-updates.md):
#   Configured via the git-ignored tools/release.local.env — copy
#   tools/release.local.env.example and fill in your host's FTP(S) credentials.
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

# --- Publish: GitHub AND the HTTP host, atomically --------------------------
# The lamp only ever fetches from the HTTP host — GitHub is history / manual
# fallback. If one side is updated without the other, the lamp could
# silently keep serving a stale or mismatched build. Both steps below count
# as ONE release: either both succeed, or nothing is reported as published.
echo
echo "==> Publishing release (GitHub + HTTP host)"

publish_github() {
  git add "$OUT_DIR"
  if git diff --cached --quiet -- "$OUT_DIR"; then
    echo "    github: no changes to commit (already up to date), pushing anyway"
  else
    git commit -m "Release $DEVICE_NAME v$VERSION"
  fi
  git push
}

publish_http_host() {
  local env_file="tools/release.local.env"
  if [[ ! -f "$env_file" ]]; then
    echo "    http-host: ERROR — $env_file not found." >&2
    echo "               Copy tools/release.local.env.example to $env_file and fill it in." >&2
    return 1
  fi
  # shellcheck disable=SC1090
  source "$env_file"
  if [[ -z "${RELEASE_HTTP_FTP_HOST:-}" || -z "${RELEASE_HTTP_FTP_USER:-}" || -z "${RELEASE_HTTP_FTP_PASSWORD:-}" ]]; then
    echo "    http-host: ERROR — RELEASE_HTTP_FTP_HOST / _USER / _PASSWORD not set in $env_file" >&2
    return 1
  fi
  local ftp_dir="${RELEASE_HTTP_FTP_PATH:-/firmware-dist/cloud-lamp/}"

  # Password goes into a short-lived, 0600 netrc file — never on the command
  # line, in shell history, or visible via `ps`.
  local netrc rc=0
  netrc="$(mktemp)"
  chmod 600 "$netrc"
  printf 'machine %s\nlogin %s\npassword %s\n' \
    "$RELEASE_HTTP_FTP_HOST" "$RELEASE_HTTP_FTP_USER" "$RELEASE_HTTP_FTP_PASSWORD" > "$netrc"

  # Upload the binary under its final name first — no manifest points to it
  # yet, so this is harmless even mid-transfer. Then upload the manifest to a
  # temp name and FTP-rename it into place (RNFR/RNTO), so a lamp polling
  # mid-publish never sees a half-written manifest.json.
  curl --ssl-reqd --netrc-file "$netrc" --ftp-create-dirs \
    -T "$OUT_DIR/$OUT_BIN" "ftp://${RELEASE_HTTP_FTP_HOST}${ftp_dir}${OUT_BIN}" \
    || rc=1
  if [[ "$rc" == 0 ]]; then
    curl --ssl-reqd --netrc-file "$netrc" --ftp-create-dirs \
      -T "$OUT_DIR/manifest.json" "ftp://${RELEASE_HTTP_FTP_HOST}${ftp_dir}.manifest.json.tmp" \
      -Q "-RNFR .manifest.json.tmp" -Q "-RNTO manifest.json" \
      || rc=1
  fi
  rm -f "$netrc"
  return "$rc"
}

GITHUB_OK=0
HTTP_OK=0
publish_github && GITHUB_OK=1 || true
publish_http_host && HTTP_OK=1 || true

if [[ "$GITHUB_OK" != 1 || "$HTTP_OK" != 1 ]]; then
  echo >&2
  echo "ERROR: Release v$VERSION NOT fully published." >&2
  [[ "$GITHUB_OK" != 1 ]] && echo "       - GitHub push FAILED." >&2
  [[ "$HTTP_OK" != 1 ]] && echo "       - HTTP host upload FAILED." >&2
  echo "       Devices only ever trust the HTTP host, and the two copies must" >&2
  echo "       never drift out of sync — fix the failing half above and" >&2
  echo "       re-run this script (safe: same version/MD5/signature each time)." >&2
  exit 1
fi

echo
echo "==> Release v$VERSION published: GitHub + HTTP host both updated."
