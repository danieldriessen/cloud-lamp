#include "signed_http_request_update.h"

#include <Ed25519.h>  // operatorfoundation/Crypto (rweather/arduinolibs) — see __init__.py

#include "esphome/core/application.h"
#include "esphome/core/helpers.h"
#include "esphome/core/version.h"

#include "esphome/components/json/json_util.h"
#include "esphome/components/network/util.h"

namespace esphome::signed_update {

static const char *const TAG = "signed_update";
static const size_t MAX_READ_SIZE = 256;

void SignedHttpRequestUpdate::set_public_key(const std::string &public_key_hex) {
  if (!parse_hex(public_key_hex, this->public_key_.data(), this->public_key_.size())) {
    ESP_LOGE(TAG, "Invalid public_key (expected 64 hex chars) — signature checks will always fail");
  }
}

void SignedHttpRequestUpdate::setup() {
  this->ota_parent_->add_state_listener(this);

  // Check periodically until network is ready, same reasoning as
  // http_request's HttpRequestUpdate: only if update_interval is long enough
  // that a fixed retry window is worth it (our packages/updates.yaml sets
  // update_interval: never and drives checks from its own interval:, so this
  // mainly matters if someone reuses this component with normal polling).
  if (this->get_update_interval() != SCHEDULER_DONT_RUN &&
      this->get_update_interval() > INITIAL_CHECK_INTERVAL_MS * INITIAL_CHECK_MAX_ATTEMPTS) {
    this->initial_check_remaining_ = INITIAL_CHECK_MAX_ATTEMPTS;
    this->set_interval(INITIAL_CHECK_INTERVAL_ID, INITIAL_CHECK_INTERVAL_MS, [this]() {
      bool connected = network::is_connected();
      if (--this->initial_check_remaining_ == 0 || connected) {
        this->cancel_interval(INITIAL_CHECK_INTERVAL_ID);
        if (connected) {
          this->update();
        }
      }
    });
  }
}

void SignedHttpRequestUpdate::on_ota_state(ota::OTAState state, float progress, uint8_t error) {
  if (state == ota::OTAState::OTA_IN_PROGRESS) {
    this->state_ = update::UPDATE_STATE_INSTALLING;
    this->update_info_.has_progress = true;
    this->update_info_.progress = progress;
    this->publish_state();
  } else if (state == ota::OTAState::OTA_ABORT || state == ota::OTAState::OTA_ERROR) {
    this->state_ = update::UPDATE_STATE_AVAILABLE;
    this->status_set_error(LOG_STR("Failed to install firmware"));
    this->publish_state();
  }
}

// Verifies an Ed25519 signature (hex-encoded, 128 chars / 64 bytes) over the
// ASCII message "<version>|<path>|<md5>" using our compiled-in public key.
// Binding all three fields prevents replaying an old-but-validly-signed
// manifest entry against a different binary or version number.
bool SignedHttpRequestUpdate::verify_signature_(const std::string &version, const std::string &path,
                                                const std::string &md5, const std::string &signature_hex) const {
  if (signature_hex.size() != 128) {
    ESP_LOGE(TAG, "Manifest signature has wrong length (expected 128 hex chars, got %zu)", signature_hex.size());
    return false;
  }
  uint8_t signature[64];
  if (!parse_hex(signature_hex, signature, sizeof(signature))) {
    ESP_LOGE(TAG, "Manifest signature is not valid hex");
    return false;
  }

  std::string message = version + "|" + path + "|" + md5;
  // Feed the watchdog immediately before the EC scalar multiplication: it's
  // well under the ~3s soft-WDT window on ESP8266, but this is cheap
  // insurance (same reasoning as http_read_fully's App.feed_wdt() calls).
  App.feed_wdt();
  return Ed25519::verify(signature, this->public_key_.data(), message.data(), message.size());
}

void SignedHttpRequestUpdate::update() {
  if (!network::is_connected()) {
    ESP_LOGD(TAG, "Network not connected, skipping update check");
    return;
  }
  this->cancel_interval(INITIAL_CHECK_INTERVAL_ID);

  update::UpdateInfo info;
  const LogString *error_str = nullptr;

  auto container = this->request_parent_->get(this->source_url_);

  if (container == nullptr || container->status_code != http_request::HTTP_STATUS_OK) {
    ESP_LOGE(TAG, "Failed to fetch manifest from %s", this->source_url_.c_str());
    if (container != nullptr)
      container->end();
    error_str = LOG_STR("Failed to fetch manifest");
  } else {
    RAMAllocator<uint8_t> allocator;  // esphome::RAMAllocator (core/alloc_helpers.h)
    uint8_t *data = allocator.allocate(container->content_length);
    if (data == nullptr) {
      ESP_LOGE(TAG, "Failed to allocate %zu bytes for manifest", container->content_length);
      container->end();
      error_str = LOG_STR("Failed to allocate memory for manifest");
    } else {
      auto read_result = http_request::http_read_fully(container.get(), data, container->content_length,
                                                        MAX_READ_SIZE, this->request_parent_->get_timeout());
      if (read_result.status != http_request::HttpReadStatus::OK) {
        if (read_result.status == http_request::HttpReadStatus::TIMEOUT) {
          ESP_LOGE(TAG, "Timeout reading manifest");
        } else {
          ESP_LOGE(TAG, "Error reading manifest: %d", read_result.error_code);
        }
        allocator.deallocate(data, container->content_length);
        container->end();
        error_str = LOG_STR("Failed to read manifest");
      } else {
        size_t read_index = container->get_bytes_read();
        size_t content_length = container->content_length;
        container->end();
        container.reset();

        std::string signature_hex;
        bool sig_present = false;

        bool valid = json::parse_json(data, read_index, [&info, &signature_hex, &sig_present](JsonObject root) -> bool {
          if (!root[ESPHOME_F("name")].is<const char *>() || !root[ESPHOME_F("version")].is<const char *>() ||
              !root[ESPHOME_F("builds")].is<JsonArray>()) {
            ESP_LOGE(TAG, "Manifest does not contain required fields");
            return false;
          }
          info.title = root[ESPHOME_F("name")].as<std::string>();
          info.latest_version = root[ESPHOME_F("version")].as<std::string>();

          auto builds_array = root[ESPHOME_F("builds")].as<JsonArray>();
          for (auto build : builds_array) {
            if (!build[ESPHOME_F("chipFamily")].is<const char *>())
              continue;
            if (build[ESPHOME_F("chipFamily")] != ESPHOME_VARIANT)
              continue;

            if (!build[ESPHOME_F("ota")].is<JsonObject>()) {
              ESP_LOGE(TAG, "Manifest does not contain required fields");
              return false;
            }
            JsonObject ota = build[ESPHOME_F("ota")].as<JsonObject>();
            if (!ota[ESPHOME_F("path")].is<const char *>() || !ota[ESPHOME_F("md5")].is<const char *>() ||
                !ota[ESPHOME_F("signature")].is<const char *>()) {
              ESP_LOGE(TAG, "Manifest is missing path/md5/signature — unsigned manifests are rejected");
              return false;
            }
            info.firmware_url = ota[ESPHOME_F("path")].as<std::string>();
            info.md5 = ota[ESPHOME_F("md5")].as<std::string>();
            signature_hex = ota[ESPHOME_F("signature")].as<std::string>();
            sig_present = true;

            if (ota[ESPHOME_F("summary")].is<const char *>())
              info.summary = ota[ESPHOME_F("summary")].as<std::string>();
            if (ota[ESPHOME_F("release_url")].is<const char *>())
              info.release_url = ota[ESPHOME_F("release_url")].as<std::string>();

            return true;
          }
          ESP_LOGE(TAG, "Manifest has no build for chip family %s", ESPHOME_VARIANT);
          return false;
        });
        allocator.deallocate(data, content_length);

        if (!valid) {
          ESP_LOGE(TAG, "Failed to parse JSON from %s", this->source_url_.c_str());
          error_str = LOG_STR("Failed to parse manifest JSON");
        } else if (!sig_present || !this->verify_signature_(info.latest_version, info.firmware_url, info.md5,
                                                             signature_hex)) {
          ESP_LOGE(TAG, "Manifest signature verification FAILED — refusing to trust update from %s",
                   this->source_url_.c_str());
          error_str = LOG_STR("Manifest signature verification failed");
        } else {
          ESP_LOGI(TAG, "Manifest signature OK (version %s)", info.latest_version.c_str());

          // Merge source_url_ and firmware_url, same rule as http_request's update platform.
          if (!info.firmware_url.empty() && info.firmware_url.find("http") == std::string::npos) {
            std::string path = info.firmware_url;
            if (path[0] == '/') {
              std::string domain = this->source_url_.substr(0, this->source_url_.find('/', 8));
              info.firmware_url = domain + path;
            } else {
              std::string domain = this->source_url_.substr(0, this->source_url_.rfind('/') + 1);
              info.firmware_url = domain + path;
            }
          }

#ifdef ESPHOME_PROJECT_VERSION
          info.current_version = ESPHOME_PROJECT_VERSION;
#else
          info.current_version = ESPHOME_VERSION;
#endif
        }
      }
    }
  }

  if (error_str != nullptr) {
    this->status_set_error(error_str);
    return;
  }

  bool trigger_update_available = false;
  update::UpdateState new_state;
  if (info.latest_version.empty() || info.latest_version == info.current_version) {
    new_state = update::UPDATE_STATE_NO_UPDATE;
  } else {
    new_state = update::UPDATE_STATE_AVAILABLE;
    if (this->state_ != update::UPDATE_STATE_AVAILABLE) {
      trigger_update_available = true;
    }
  }

  this->update_info_ = std::move(info);
  this->state_ = new_state;

  this->status_clear_error();
  this->publish_state();

  if (trigger_update_available) {
    this->get_update_available_trigger()->trigger(this->update_info_);
  }
}

void SignedHttpRequestUpdate::perform(bool force) {
  if (this->state_ != update::UPDATE_STATE_AVAILABLE && !force) {
    return;
  }

  this->state_ = update::UPDATE_STATE_INSTALLING;
  this->publish_state();

  this->ota_parent_->set_md5(this->update_info.md5);
  this->ota_parent_->set_url(this->update_info.firmware_url);
  // Flash in the next loop
  this->defer([this]() { this->ota_parent_->flash(); });
}

}  // namespace esphome::signed_update
