#include "TDMAManager.h"
#include "GatewaySerial.h"
#include <esp_now.h>
#include <WiFi.h>

static const uint8_t kBroadcastMac[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

TDMAManager::TDMAManager(NodeRegistry &registry) : registry_(registry) {}

void TDMAManager::begin() {
    cycle_started_ms_ = millis();
}

void TDMAManager::update(uint32_t now_ms) {
    if ((now_ms - cycle_started_ms_) >= tdma::CYCLE_MS) {
        startNewCycle(now_ms);
    }
}

void TDMAManager::setRtcTime(uint64_t epoch_ms) {
    rtc_epoch_ms_ = epoch_ms;
    rtc_set_at_us_64_ = (uint64_t)esp_timer_get_time();
}

uint64_t TDMAManager::getCurrentEpochMs() {
    if (rtc_epoch_ms_ == 0) return 0;
    uint64_t now_us = (uint64_t)esp_timer_get_time();
    uint64_t elapsed_us = now_us - rtc_set_at_us_64_;
    return rtc_epoch_ms_ + (elapsed_us / 1000ULL);
}

void TDMAManager::startNewCycle(uint32_t now_ms) {
    registry_.pruneInactiveNodes(now_ms, tdma::NODE_INACTIVE_TIMEOUT_MS);
    rebuildSchedule();
    sendBeaconSync();

    cycle_started_ms_ = now_ms;

    if (system_state_ == tdma::STATE_DISCOVERY && active_count_ > 0) {
        system_state_ = tdma::STATE_IDLE;
    }
}

void TDMAManager::rebuildSchedule() {
    active_count_ = registry_.getActiveCount(sorted_node_ids_);
    tdma::buildRoundRobinSchedule(sorted_node_ids_, active_count_, slot_schedule_);
}

void TDMAManager::sendBeaconSync() {
    tdma::BeaconSyncPacket beacon = {};
    beacon.type = tdma::PKT_BEACON_SYNC;
    beacon.version = tdma::PROTOCOL_VERSION;
    beacon.system_state = system_state_;
    beacon.active_nodes = active_count_;
    beacon.cycle_ms = tdma::CYCLE_MS;
    beacon.slot_us = tdma::SLOT_US;
    beacon.slot_guard_us = tdma::SLOT_GUARD_US;
    beacon.registration_window_ms = tdma::REGISTRATION_WINDOW_MS;
    beacon.sample_rate_hz = target_rate_hz_;
    beacon.beacon_sequence = beacon_sequence_++;
    beacon.rtc_epoch_ms = getCurrentEpochMs();

    memcpy(beacon.slot_schedule, slot_schedule_, tdma::MAX_SLOTS);

    for (uint8_t i = 0; i < active_count_ && i < tdma::MAX_NODES; i++) {
        ActiveNodeEntry *n = registry_.findNodeById(sorted_node_ids_[i]);
        if (n) {
            beacon.ack_map[i].node_id = n->node_id;
            beacon.ack_map[i].highest_acked_seq = n->highest_seq_acked;
        }
    }

    esp_err_t err = esp_now_send(kBroadcastMac, reinterpret_cast<const uint8_t *>(&beacon), sizeof(beacon));
    if (err != ESP_OK) beacon_errors_++;

    // BEACON info to serial
    char beacon_info[256];
    int len = snprintf(beacon_info, sizeof(beacon_info), 
                  "BEACON,%lu,STATE=%u,NODES=%u,SLOT_US=%u,RATE=%u,RTC=%llu,SCHED=",
                  (unsigned long)beacon.beacon_sequence,
                  beacon.system_state, beacon.active_nodes, beacon.slot_us,
                  beacon.sample_rate_hz, (unsigned long long)beacon.rtc_epoch_ms);

    for (uint8_t i = 0; i < tdma::MAX_SLOTS; i++) {
        if (i > 0) len += snprintf(beacon_info + len, sizeof(beacon_info) - len, ";");
        len += snprintf(beacon_info + len, sizeof(beacon_info) - len, "%u", slot_schedule_[i]);
    }

    len += snprintf(beacon_info + len, sizeof(beacon_info) - len, ",ACKS=");
    for (uint8_t i = 0; i < active_count_; i++) {
        if (i > 0) len += snprintf(beacon_info + len, sizeof(beacon_info) - len, ";");
        len += snprintf(beacon_info + len, sizeof(beacon_info) - len, "%u:%u", 
                        beacon.ack_map[i].node_id, beacon.ack_map[i].highest_acked_seq);
    }
    GatewaySerial::sendAsciiMsg("%s", beacon_info);
}
