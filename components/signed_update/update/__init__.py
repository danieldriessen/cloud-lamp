# ==============================================================================
#  components/signed_update — Ed25519-signed OTA manifest checker over plain HTTP
#
#  Why this exists: see docs/cloud-lamp-design.md ("Signed OTA over plain
#  HTTP") and docs/firmware-updates.md. Short version — the ESP8266's ~25KB
#  of usable heap cannot reliably complete a BearSSL TLS handshake against
#  GitHub's CDN (needs ~16-20KB contiguous) while other components (web
#  server, MQTT) hold onto memory. Fetching the manifest over plain HTTP
#  removes that requirement entirely; an Ed25519 signature over the
#  version/path/md5 tuple gives the update integrity guarantees that are at
#  least as strong as the `verify_ssl: false` HTTPS this replaces (which
#  trusted the transport but not any particular certificate).
#
#  This is a drop-in replacement for http_request's `update:` platform: same
#  manifest shape (see tools/release.sh / docs/firmware-dist/*/manifest.json),
#  plus one additional required field, `builds[].ota.signature` — a 128-hex
#  character (64-byte) Ed25519 signature over the ASCII string
#  "<version>|<path>|<md5>", produced by tools/release.sh at publish time
#  and verified on-device against the public key baked in below before any
#  update is ever considered "available".
#
#  The signing PRIVATE key never leaves the release machine (see
#  docs/firmware-updates.md); only the PUBLIC key (not a secret) is compiled
#  into the firmware via the `public_key` option.
# ==============================================================================
import esphome.codegen as cg
from esphome.components import ota, update
from esphome.components.http_request import CONF_HTTP_REQUEST_ID, HttpRequestComponent
from esphome.components.http_request.ota import OtaHttpRequestComponent
import esphome.config_validation as cv
from esphome.const import CONF_SOURCE

CODEOWNERS = ["@danieldriessen"]
DEPENDENCIES = ["ota.http_request"]

signed_update_ns = cg.esphome_ns.namespace("signed_update")
SignedHttpRequestUpdate = signed_update_ns.class_(
    "SignedHttpRequestUpdate", update.UpdateEntity, cg.PollingComponent
)

CONF_OTA_ID = "ota_id"
CONF_PUBLIC_KEY = "public_key"


def validate_public_key(value):
    value = cv.string_strict(value)
    if len(value) != 64:
        raise cv.Invalid(
            f"public_key must be exactly 64 hex characters (32 bytes), got {len(value)}"
        )
    try:
        bytes.fromhex(value)
    except ValueError as e:
        raise cv.Invalid(f"public_key must be valid hex: {e}") from e
    return value.lower()


CONFIG_SCHEMA = (
    update.update_schema(SignedHttpRequestUpdate)
    .extend(
        {
            cv.GenerateID(CONF_OTA_ID): cv.use_id(OtaHttpRequestComponent),
            cv.GenerateID(CONF_HTTP_REQUEST_ID): cv.use_id(HttpRequestComponent),
            cv.Required(CONF_SOURCE): cv.url,
            cv.Required(CONF_PUBLIC_KEY): validate_public_key,
        }
    )
    .extend(cv.polling_component_schema("6h"))
)


async def to_code(config):
    # Vendored, audited Ed25519 implementation (rweather/arduinolibs' Crypto
    # library, tested on ESP8266 — see its crypto-esp.dox for watchdog notes
    # this component's verify_signature_() already accounts for). Pulled via
    # PlatformIO's library registry rather than hand-copied into this repo so
    # the exact, unmodified upstream sources are what actually gets compiled.
    cg.add_library("operatorfoundation/Crypto", "0.4.0")

    var = await update.new_update(config)
    ota_parent = await cg.get_variable(config[CONF_OTA_ID])
    cg.add(var.set_ota_parent(ota_parent))
    request_parent = await cg.get_variable(config[CONF_HTTP_REQUEST_ID])
    cg.add(var.set_request_parent(request_parent))

    cg.add(var.set_source_url(config[CONF_SOURCE]))
    cg.add(var.set_public_key(config[CONF_PUBLIC_KEY]))

    ota.request_ota_state_listeners()

    await cg.register_component(var, config)
