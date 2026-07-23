"""Cloud-Lamp web app component.

Serves the single-file iOS-style web app (gzipped, from PROGMEM) at `/` and
`/app`, plus the PWA manifest at `/manifest.json`, the home-screen icon at
`/icon.png`, the firmware-update-overlay brand mark at `/brand.png`, the
maker logo at `/logo.png`, and the app.html header's own logo at
`/header.png` (kept separate from `/brand.png` so the header's asset can use
a different resolution/aspect ratio without affecting the overlay icon).
Registers before the standard `web_server` component so it wins the `/`
route while leaving the whole REST + /events API untouched.

While the captive portal (Wi-Fi setup) is active, the branded onboarding page
(`setup_file`, web/setup.html) replaces ESPHome's stock portal page; the stock
`/config.json` + `/wifisave` endpoints keep doing the actual scan/save work.

The HTML files are read and gzip-compressed at compile time; changing
`web/app.html` / `web/setup.html` therefore requires a recompile.
"""

import gzip
import hashlib
from pathlib import Path

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import web_server_base
from esphome.components.web_server_base import CONF_WEB_SERVER_BASE_ID
from esphome.const import CONF_ID
from esphome.core import CORE

AUTO_LOAD = ["web_server_base"]
DEPENDENCIES = ["network"]
CODEOWNERS = ["@danieldriessen"]

cloud_lamp_web_ns = cg.esphome_ns.namespace("cloud_lamp_web")
CloudLampWeb = cloud_lamp_web_ns.class_("CloudLampWeb", cg.Component)

CONF_HTML_FILE = "html_file"
CONF_SETUP_FILE = "setup_file"
CONF_ICON_FILE = "icon_file"
CONF_BRAND_FILE = "brand_file"
CONF_LOGO_FILE = "logo_file"
CONF_HEADER_FILE = "header_file"
CONF_HTML_DATA_ID = "html_data_id"
CONF_SETUP_DATA_ID = "setup_data_id"
CONF_ICON_DATA_ID = "icon_data_id"
CONF_BRAND_DATA_ID = "brand_data_id"
CONF_LOGO_DATA_ID = "logo_data_id"
CONF_HEADER_DATA_ID = "header_data_id"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(CloudLampWeb),
        cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
            web_server_base.WebServerBase
        ),
        cv.Required(CONF_HTML_FILE): cv.file_,
        cv.Optional(CONF_SETUP_FILE): cv.file_,
        cv.Optional(CONF_ICON_FILE): cv.file_,
        cv.Optional(CONF_BRAND_FILE): cv.file_,
        cv.Optional(CONF_LOGO_FILE): cv.file_,
        cv.Optional(CONF_HEADER_FILE): cv.file_,
        cv.GenerateID(CONF_HTML_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_SETUP_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_ICON_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_BRAND_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_LOGO_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_HEADER_DATA_ID): cv.declare_id(cg.uint8),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])
    var = cg.new_Pvariable(config[CONF_ID], base)
    await cg.register_component(var, config)

    # Read the icon first (if any) so its content hash is ready before the
    # HTML is processed below — both /icon.png references in the HTML and
    # the manifest's icon entry get a "?v=<hash>" cache-buster derived from
    # it. iOS Safari's site-icon cache is known to ignore Cache-Control on
    # /icon.png (favicon + apple-touch-icon / "Add to Home Screen"), so a
    # same-URL refresh can get stuck showing a stale icon indefinitely; a
    # URL that actually changes whenever the icon's bytes change is the only
    # reliable way to bust that cache. The hash is deterministic from the
    # file content, so it updates itself automatically — no manual version
    # bump needed when the artwork changes.
    icon_data = b""
    if CONF_ICON_FILE in config:
        icon_path = Path(CORE.relative_config_path(config[CONF_ICON_FILE]))
        icon_data = icon_path.read_bytes()
    icon_version = hashlib.md5(icon_data).hexdigest()[:8] if icon_data else "0"
    cg.add(var.set_icon_version(icon_version))

    html_path = Path(CORE.relative_config_path(config[CONF_HTML_FILE]))
    html_bytes = html_path.read_bytes().replace(b"__ICON_VERSION__", icon_version.encode())
    html_gz = gzip.compress(html_bytes, compresslevel=9)
    html_arr = cg.progmem_array(config[CONF_HTML_DATA_ID], list(html_gz))
    cg.add(var.set_html(html_arr, len(html_gz)))

    if CONF_SETUP_FILE in config:
        setup_path = Path(CORE.relative_config_path(config[CONF_SETUP_FILE]))
        setup_gz = gzip.compress(setup_path.read_bytes(), compresslevel=9)
        setup_arr = cg.progmem_array(config[CONF_SETUP_DATA_ID], list(setup_gz))
        cg.add(var.set_setup(setup_arr, len(setup_gz)))

    if icon_data:
        icon_arr = cg.progmem_array(config[CONF_ICON_DATA_ID], list(icon_data))
        cg.add(var.set_icon(icon_arr, len(icon_data)))

    if CONF_BRAND_FILE in config:
        brand_path = Path(CORE.relative_config_path(config[CONF_BRAND_FILE]))
        brand_data = brand_path.read_bytes()
        brand_arr = cg.progmem_array(config[CONF_BRAND_DATA_ID], list(brand_data))
        cg.add(var.set_brand(brand_arr, len(brand_data)))

    if CONF_LOGO_FILE in config:
        logo_path = Path(CORE.relative_config_path(config[CONF_LOGO_FILE]))
        logo_data = logo_path.read_bytes()
        logo_arr = cg.progmem_array(config[CONF_LOGO_DATA_ID], list(logo_data))
        cg.add(var.set_logo(logo_arr, len(logo_data)))

    # Separate from brand_file: a dedicated, correctly-proportioned @2x asset
    # for just the app.html header mark, so it can be swapped/resized without
    # affecting /brand.png's other use (the firmware-update overlay icon).
    if CONF_HEADER_FILE in config:
        header_path = Path(CORE.relative_config_path(config[CONF_HEADER_FILE]))
        header_data = header_path.read_bytes()
        header_arr = cg.progmem_array(config[CONF_HEADER_DATA_ID], list(header_data))
        cg.add(var.set_header(header_arr, len(header_data)))
