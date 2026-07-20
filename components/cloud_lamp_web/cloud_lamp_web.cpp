#include "cloud_lamp_web.h"

#ifdef USE_NETWORK

#include "esphome/core/application.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

#ifdef USE_CAPTIVE_PORTAL
#include "esphome/components/captive_portal/captive_portal.h"
#endif

namespace esphome {
namespace cloud_lamp_web {

static const char *const TAG = "cloud_lamp_web";

// Serial = last two MAC bytes, uppercase hex -> 4 characters, e.g. "3F2A".
static std::string device_serial() {
  std::string mac = get_mac_address();  // 12 lowercase hex chars
  std::string serial = mac.substr(mac.size() - 4);
  for (auto &c : serial)
    c = ::toupper(c);
  return serial;
}

void CloudLampWeb::setup() {
  this->base_->init();
  this->base_->add_handler(this);
}

void CloudLampWeb::dump_config() {
  ESP_LOGCONFIG(TAG,
                "Cloud-Lamp web app:\n"
                "  HTML: %u bytes (gzip)\n"
                "  Icon: %u bytes\n"
                "  Logo: %u bytes\n"
                "  Serial: %s",
                (unsigned) this->html_size_, (unsigned) this->icon_size_, (unsigned) this->logo_size_,
                device_serial().c_str());
}

// Just above the stock web_server (WIFI - 1.0) so our handler is registered
// first and wins the "/" route; all other routes fall through to web_server.
float CloudLampWeb::get_setup_priority() const { return setup_priority::WIFI - 0.5f; }

bool CloudLampWeb::canHandle(AsyncWebServerRequest *request) const {
  if (request->method() != HTTP_GET)
    return false;
#ifdef USE_CAPTIVE_PORTAL
  // Never shadow the Wi-Fi onboarding portal.
  if (captive_portal::global_captive_portal != nullptr && captive_portal::global_captive_portal->is_active())
    return false;
#endif
  const auto &url = request->url();
  return url == F("/") || url == F("/app") || url == F("/manifest.json") || url == F("/icon.png") ||
         url == F("/logo.png") || url == F("/device.json");
}

void CloudLampWeb::handleRequest(AsyncWebServerRequest *request) {
  const auto &url = request->url();
  if (url == F("/") || url == F("/app")) {
    this->handle_app_(request);
  } else if (url == F("/manifest.json")) {
    this->handle_manifest_(request);
  } else if (url == F("/icon.png")) {
    this->handle_png_(request, this->icon_, this->icon_size_);
  } else if (url == F("/logo.png")) {
    this->handle_png_(request, this->logo_, this->logo_size_);
  } else if (url == F("/device.json")) {
    this->handle_device_info_(request);
  } else {
    request->send(404);
  }
}

void CloudLampWeb::handle_app_(AsyncWebServerRequest *request) {
  if (this->html_ == nullptr) {
    request->send(404);
    return;
  }
  AsyncWebServerResponse *response = request->beginResponse_P(200, "text/html", this->html_, this->html_size_);
  response->addHeader("Content-Encoding", "gzip");
  // Always revalidate so firmware updates show the new UI immediately.
  response->addHeader("Cache-Control", "no-cache");
  // Never advertise HTTPS. Clears any accidental HSTS for this host and
  // avoids Safari "upgrading" the home-screen shortcut to https://…
  response->addHeader("Strict-Transport-Security", "max-age=0");
  request->send(response);
}

void CloudLampWeb::handle_manifest_(AsyncWebServerRequest *request) {
  std::string name = App.get_friendly_name();
  if (name.empty())
    name = "Cloud Lamp";
  // start_url stays relative ("/") so the home-screen shortcut keeps the
  // scheme the user typed (must be http:// — see design doc / iOS tip).
  std::string manifest = "{\"name\":\"" + name +
                         "\",\"short_name\":\"" + name +
                         "\",\"start_url\":\"/\",\"scope\":\"/\",\"display\":\"standalone\","
                         "\"display_override\":[\"standalone\",\"fullscreen\"],"
                         "\"background_color\":\"#0b0f18\",\"theme_color\":\"#0b0f18\"";
  if (this->icon_ != nullptr) {
    manifest += ",\"icons\":[{\"src\":\"/icon.png\",\"sizes\":\"256x256\",\"type\":\"image/png\",\"purpose\":\"any\"}]";
  }
  manifest += "}";
  AsyncWebServerResponse *response = request->beginResponse(200, "application/manifest+json", manifest.c_str());
  response->addHeader("Cache-Control", "no-cache");
  response->addHeader("Strict-Transport-Security", "max-age=0");
  request->send(response);
}

void CloudLampWeb::handle_png_(AsyncWebServerRequest *request, const uint8_t *data, size_t size) {
  if (data == nullptr) {
    request->send(404);
    return;
  }
  AsyncWebServerResponse *response = request->beginResponse_P(200, "image/png", data, size);
  response->addHeader("Cache-Control", "max-age=86400");
  request->send(response);
}

void CloudLampWeb::handle_device_info_(AsyncWebServerRequest *request) {
  std::string json = "{\"name\":\"" + App.get_name() +
                     "\",\"friendly_name\":\"" + App.get_friendly_name() +
                     "\",\"serial\":\"" + device_serial() +
                     "\",\"mac\":\"" + get_mac_address_pretty() +
                     "\",\"version\":\"" +
#ifdef ESPHOME_PROJECT_VERSION
                     ESPHOME_PROJECT_VERSION
#else
                     "unknown"
#endif
                     "\"}";
  request->send(200, "application/json", json.c_str());
}

}  // namespace cloud_lamp_web
}  // namespace esphome

#endif  // USE_NETWORK
