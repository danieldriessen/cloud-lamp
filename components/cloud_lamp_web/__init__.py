"""Cloud-Lamp web app component.

Serves the single-file iOS-style web app (gzipped, from PROGMEM) at `/` and
`/app`, plus the PWA manifest at `/manifest.json`, the home-screen icon at
`/icon.png`, the in-app header brand mark at `/brand.png`, and the maker logo
at `/logo.png`. Registers before the standard `web_server` component so it
wins the `/` route while leaving the whole REST + /events API untouched.

While the captive portal (Wi-Fi setup) is active, the branded onboarding page
(`setup_file`, web/setup.html) replaces ESPHome's stock portal page; the stock
`/config.json` + `/wifisave` endpoints keep doing the actual scan/save work.

The HTML files are read and gzip-compressed at compile time; changing
`web/app.html` / `web/setup.html` therefore requires a recompile.
"""

import gzip
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
CONF_HTML_DATA_ID = "html_data_id"
CONF_SETUP_DATA_ID = "setup_data_id"
CONF_ICON_DATA_ID = "icon_data_id"
CONF_BRAND_DATA_ID = "brand_data_id"
CONF_LOGO_DATA_ID = "logo_data_id"

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
        cv.GenerateID(CONF_HTML_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_SETUP_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_ICON_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_BRAND_DATA_ID): cv.declare_id(cg.uint8),
        cv.GenerateID(CONF_LOGO_DATA_ID): cv.declare_id(cg.uint8),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])
    var = cg.new_Pvariable(config[CONF_ID], base)
    await cg.register_component(var, config)

    html_path = Path(CORE.relative_config_path(config[CONF_HTML_FILE]))
    html_gz = gzip.compress(html_path.read_bytes(), compresslevel=9)
    html_arr = cg.progmem_array(config[CONF_HTML_DATA_ID], list(html_gz))
    cg.add(var.set_html(html_arr, len(html_gz)))

    if CONF_SETUP_FILE in config:
        setup_path = Path(CORE.relative_config_path(config[CONF_SETUP_FILE]))
        setup_gz = gzip.compress(setup_path.read_bytes(), compresslevel=9)
        setup_arr = cg.progmem_array(config[CONF_SETUP_DATA_ID], list(setup_gz))
        cg.add(var.set_setup(setup_arr, len(setup_gz)))

    if CONF_ICON_FILE in config:
        icon_path = Path(CORE.relative_config_path(config[CONF_ICON_FILE]))
        icon_data = icon_path.read_bytes()
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
