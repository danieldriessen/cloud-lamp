#pragma once

#include <array>
#include <string>

#include "esphome/core/component.h"

#include "esphome/components/http_request/http_request.h"
#include "esphome/components/http_request/ota/ota_http_request.h"
#include "esphome/components/update/update_entity.h"

namespace esphome::signed_update {

// Drop-in equivalent of http_request's HttpRequestUpdate, but the manifest is
// fetched over plain HTTP (source_url_ is expected to be http://, not
// https://) and is rejected unless it carries a valid Ed25519 signature over
// "<version>|<path>|<md5>" for our public_key_. See __init__.py for why.
//
// ESP8266-only by design (this whole firmware targets ESP8266) — unlike
// upstream's HttpRequestUpdate this does not offload the check to a FreeRTOS
// task, since there is no ESP32 build of this project to justify the extra
// complexity.
class SignedHttpRequestUpdate final : public update::UpdateEntity,
                                       public PollingComponent,
                                       public ota::OTAStateListener {
 public:
  void setup() override;
  void update() override;

  void perform(bool force) override;
  void check() override { this->update(); }

  void set_source_url(const std::string &source_url) { this->source_url_ = source_url; }
  void set_public_key(const std::string &public_key_hex);

  void set_request_parent(http_request::HttpRequestComponent *request_parent) {
    this->request_parent_ = request_parent;
  }
  void set_ota_parent(http_request::OtaHttpRequestComponent *ota_parent) { this->ota_parent_ = ota_parent; }

  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

  void on_ota_state(ota::OTAState state, float progress, uint8_t error) override;

 protected:
  bool verify_signature_(const std::string &version, const std::string &path, const std::string &md5,
                         const std::string &signature_hex) const;

  http_request::HttpRequestComponent *request_parent_{nullptr};
  http_request::OtaHttpRequestComponent *ota_parent_{nullptr};
  std::string source_url_;
  std::array<uint8_t, 32> public_key_{};

  static constexpr uint32_t INITIAL_CHECK_INTERVAL_ID = 0;
  static constexpr uint32_t INITIAL_CHECK_INTERVAL_MS = 10000;
  static constexpr uint8_t INITIAL_CHECK_MAX_ATTEMPTS = 6;
  uint8_t initial_check_remaining_{0};
};

}  // namespace esphome::signed_update
