#pragma once

#include "esphome/core/defines.h"
#ifdef USE_NETWORK

#include "esphome/core/component.h"
#include "esphome/components/web_server_base/web_server_base.h"

namespace esphome {
namespace cloud_lamp_web {

/**
 * Serves the Cloud-Lamp web app and its PWA support files:
 *
 *   GET /              -> app HTML (gzip, PROGMEM)
 *   GET /app           -> same as / (stable URL for bookmarks)
 *   GET /esphome       -> 302 redirect hint to the stock ESPHome UI is NOT
 *                         provided; the stock UI stays reachable because this
 *                         handler only claims the routes listed here.
 *   GET /manifest.json -> web app manifest (name from friendly_name)
 *   GET /icon.png      -> home screen / PWA icon (if provided at compile time)
 *   GET /brand.png     -> transparent in-app header brand mark (if provided)
 *   GET /logo.png      -> maker logo shown in the app (if provided)
 *   GET /device.json   -> device metadata (name, serial, version, mac)
 *
 * Registered with setup priority just above the stock web_server component so
 * this handler is matched first for "/", while every REST route (/light/...,
 * /select/..., /update/..., /events) still falls through to web_server.
 *
 * Captive portal (Wi-Fi onboarding): while the portal is active this handler
 * serves the BRANDED setup page (web/setup.html) for every GET except
 * /config.json and /wifisave, which fall through to the stock captive_portal
 * handlers (network scan + credential save). Claiming the whole URL space
 * also answers the OS captive-portal detection probes, exactly like the stock
 * page would. If no setup page was compiled in, the handler steps aside
 * entirely and the stock portal page is shown instead.
 */
class CloudLampWeb : public Component, public AsyncWebHandler {
 public:
  explicit CloudLampWeb(web_server_base::WebServerBase *base) : base_(base) {}

  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override;

  void set_html(const uint8_t *data, size_t size) {
    this->html_ = data;
    this->html_size_ = size;
  }
  void set_setup(const uint8_t *data, size_t size) {
    this->setup_ = data;
    this->setup_size_ = size;
  }
  void set_icon(const uint8_t *data, size_t size) {
    this->icon_ = data;
    this->icon_size_ = size;
  }
  void set_brand(const uint8_t *data, size_t size) {
    this->brand_ = data;
    this->brand_size_ = size;
  }
  void set_logo(const uint8_t *data, size_t size) {
    this->logo_ = data;
    this->logo_size_ = size;
  }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;
  bool isRequestHandlerTrivial() const override { return true; }

 protected:
  bool portal_active_() const;
  void handle_app_(AsyncWebServerRequest *request);
  void handle_setup_(AsyncWebServerRequest *request);
  void handle_manifest_(AsyncWebServerRequest *request);
  void handle_png_(AsyncWebServerRequest *request, const uint8_t *data, size_t size);
  void handle_device_info_(AsyncWebServerRequest *request);

  web_server_base::WebServerBase *base_;
  const uint8_t *html_{nullptr};
  size_t html_size_{0};
  const uint8_t *setup_{nullptr};
  size_t setup_size_{0};
  const uint8_t *icon_{nullptr};
  size_t icon_size_{0};
  const uint8_t *brand_{nullptr};
  size_t brand_size_{0};
  const uint8_t *logo_{nullptr};
  size_t logo_size_{0};
};

}  // namespace cloud_lamp_web
}  // namespace esphome

#endif  // USE_NETWORK
