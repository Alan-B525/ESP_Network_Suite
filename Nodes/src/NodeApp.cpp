#include "NodeApp.h"
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#define WIFI_CHANNEL 1
static uint8_t basestation_mac[6] = {0xB8, 0xF8, 0x62, 0x04, 0x5F, 0x98};
#define BURST_MAX_PKTS 12

NodeApp *NodeApp::s_instance = nullptr;

void NodeApp::begin() {
    s_instance = this;
    Serial.begin(115200);
    
    acq_.begin();

    WiFi.mode(WIFI_STA);
    esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

    if (esp_now_init() != ESP_OK) {
        Serial.println("NODE: FATAL ESP-NOW init");
        while (true) delay(1000);
    }

    esp_now_register_recv_cb(NodeApp::onDataRecvStatic);
    esp_now_register_send_cb(NodeApp::onDataSentStatic);

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, basestation_mac, 6);
    peer.channel = WIFI_CHANNEL;
    peer.encrypt = false;
    esp_now_add_peer(&peer);

    Serial.println("NODE: Started, waiting for Beacon...");
}

void NodeApp::run() {
    uint64_t now_us = (uint64_t)esp_timer_get_time();
    uint32_t now_ms = millis();

    // Sync check
    if (sync_locked_ && tdma_cycle_us_ > 0) {
        if ((now_us - last_sync_us_) > (uint64_t)tdma_cycle_us_ * 6) {
            sync_locked_ = false;
        }
    }

    // TDMA logic
    if (sync_locked_ && tdma_cycle_us_ > 0) {
        uint32_t elapsed = (uint32_t)(now_us - sync_anchor_us_);
        uint32_t phase = elapsed % tdma_cycle_us_;
        uint32_t reg_us = (uint32_t)tdma::REGISTRATION_WINDOW_MS * 1000UL;

        if (phase < reg_us) {
            static uint32_t last_hello_cycle = 0xFFFFFFFF;
            uint32_t cycle_idx = elapsed / tdma_cycle_us_;
            if (cycle_idx != last_hello_cycle) {
                if (system_state_ != tdma::STATE_ACQUIRING) sendNodeHello();
                last_hello_cycle = cycle_idx;
            }
        } else if (system_state_ == tdma::STATE_ACQUIRING && acq_.isRunning()) {
            uint32_t data_phase = phase - reg_us;
            uint32_t current_slot = data_phase / tdma_slot_us_;

            if (current_slot < tdma::MAX_SLOTS && slot_schedule_[current_slot] == node_id_ && node_id_ != 0) {
                static uint32_t last_tx_slot = 0xFFFFFFFF;
                uint32_t cycle_idx = elapsed / tdma_cycle_us_;
                uint32_t slot_key = cycle_idx * tdma::MAX_SLOTS + current_slot;
                if (slot_key != last_tx_slot) {
                    last_tx_slot = slot_key;
                    transmitBurst();
                }
            }
        }
    }

    // Diagnostics
    if ((now_ms - last_diag_ms_) >= 3000) {
        last_diag_ms_ = now_ms;
        sendTelemetry();
    }
}

void NodeApp::onDataSentStatic(const uint8_t *mac, esp_now_send_status_t status) {}

void NodeApp::onDataRecvStatic(const uint8_t *mac, const uint8_t *data, int len) {
    if (!s_instance || len < 1) return;
    uint8_t type = data[0];
    if (type == tdma::PKT_BEACON_SYNC) s_instance->handleBeaconSync(data, len);
    else if (type == tdma::PKT_DIRECT_ACK) s_instance->handleDirectAck(data, len);
    else if (type == tdma::PKT_JOIN_ACK) s_instance->handleJoinAck(data, len);
}

void NodeApp::handleBeaconSync(const uint8_t *data, int len) {
    if (len < (int)sizeof(tdma::BeaconSyncPacket)) return;
    tdma::BeaconSyncPacket beacon;
    memcpy(&beacon, data, sizeof(beacon));

    sync_locked_ = true;
    sync_anchor_us_ = (uint64_t)esp_timer_get_time();
    last_sync_us_ = sync_anchor_us_;
    tdma_cycle_us_ = (uint32_t)beacon.cycle_ms * 1000UL;
    tdma_slot_us_ = beacon.slot_us;
    system_state_ = beacon.system_state;
    memcpy(slot_schedule_, beacon.slot_schedule, tdma::MAX_SLOTS);

    if (system_state_ == tdma::STATE_ACQUIRING && !acq_.isRunning()) {
        for(int i=0; i<NUM_CHANNELS; i++) sent_idx_[i] = 0;
        next_seq_ = 1;
        timing_info_sent_at_start_ = false;
        acq_.start(beacon.sample_rate_hz);
    } else if (system_state_ != tdma::STATE_ACQUIRING && acq_.isRunning()) {
        acq_.stop();
    }

    for (uint8_t i = 0; i < beacon.active_nodes; i++) {
        if (beacon.ack_map[i].node_id == node_id_) {
            lossless_.processAck(beacon.ack_map[i].highest_acked_seq);
            break;
        }
    }
}

void NodeApp::handleDirectAck(const uint8_t *data, int len) {
    if (len < (int)sizeof(tdma::DirectAckPacket)) return;
    tdma::DirectAckPacket ack;
    memcpy(&ack, data, sizeof(ack));
    if (ack.node_id == node_id_) {
        lossless_.processAck(ack.highest_acked_seq);
        system_state_ = ack.system_state;
    }
}

void NodeApp::handleJoinAck(const uint8_t *data, int len) {
    if (len < (int)sizeof(tdma::JoinAckPacket)) return;
    tdma::JoinAckPacket ack;
    memcpy(&ack, data, sizeof(ack));
    node_id_ = ack.assigned_node_id;
    system_state_ = ack.system_state;
}

void NodeApp::transmitBurst() {
    if (!timing_info_sent_at_start_ || (millis() - last_timing_info_ms_) >= tdma::TIMING_INFO_INTERVAL_MS) {
        sendTimingInfo();
    }
    
    uint32_t rewind_seq;
    if (lossless_.checkTimeout(tdma_cycle_us_, rewind_seq)) {
        next_seq_ = rewind_seq;
        for(int i=0; i<NUM_CHANNELS; i++) sent_idx_[i] = acq_.getAcked(i);
    }

    uint8_t pkts = 0;
    for (int r=0; r<BURST_MAX_PKTS && !lossless_.isFull(); r++) {
        bool any = false;
        for (int ch=0; ch<NUM_CHANNELS; ch++) {
            if (pkts < BURST_MAX_PKTS && !lossless_.isFull()) {
                uint8_t s = sendDataPacket(ch);
                pkts += s;
                if (s) any = true;
            }
        }
        if (!any) break;
    }
}

uint8_t NodeApp::sendDataPacket(uint8_t ch) {
    uint32_t pending = acq_.getProduced(ch) - sent_idx_[ch];
    if (pending == 0) return 0;

    uint16_t count = (pending > 100) ? 100 : (uint16_t)pending; // Simplified count
    tdma::DataPacketHeader hdr = {tdma::PKT_DATA, tdma::PROTOCOL_VERSION, node_id_, ch, 
                                  tdma::SAMPLE_INT16, next_seq_, count, sent_idx_[ch], 0};
    
    uint8_t buf[ESPNOW_MAX_PAYLOAD_BYTES];
    memcpy(buf, &hdr, tdma::DATA_HEADER_SIZE);
    for (uint16_t i=0; i<count; i++) {
        int16_t val = acq_.getSample(ch, sent_idx_[ch] + i);
        memcpy(buf + tdma::DATA_HEADER_SIZE + i*2, &val, 2);
    }
    
    size_t len = tdma::DATA_HEADER_SIZE + count*2;
    ((tdma::DataPacketHeader*)buf)->crc16 = tdma::crc16_ccitt(buf, len);
    
    if (esp_now_send(basestation_mac, buf, len) == ESP_OK) {
        lossless_.record(next_seq_, ch, sent_idx_[ch], count);
        sent_idx_[ch] += count;
        next_seq_++;
        return 1;
    }
    return 0;
}

void NodeApp::sendNodeHello() {
    tdma::NodeHelloPacket hello = {tdma::PKT_NODE_HELLO, tdma::PROTOCOL_VERSION, node_id_, 
                                   (1U << NUM_CHANNELS) - 1, NUM_CHANNELS, 0, 1000};
    esp_now_send(basestation_mac, (const uint8_t*)&hello, sizeof(hello));
}

void NodeApp::sendTimingInfo() {
    tdma::TimingInfoPacket pkt = {};
    pkt.type = tdma::PKT_TIMING_INFO;
    pkt.version = tdma::PROTOCOL_VERSION;
    pkt.node_id = node_id_;
    pkt.channel_id = 0xFF;
    pkt.sample_rate_hz = acq_.isRunning() ? 1000 : 0; // Simplified for this example
    pkt.dt_us = 1000000UL / 1000;
    pkt.t0_epoch_ms = 0; // Should get from acq
    pkt.t0_sample_index = 0;
    pkt.crc16 = 0;
    pkt.crc16 = tdma::crc16_ccitt((const uint8_t *)&pkt, sizeof(pkt));

    if (esp_now_send(basestation_mac, (const uint8_t *)&pkt, sizeof(pkt)) == ESP_OK) {
        timing_info_sent_at_start_ = true;
        last_timing_info_ms_ = millis();
    }
}

void NodeApp::sendTelemetry() {
    tdma::NodeTelemetryPacket tel = {tdma::PKT_NODE_TELEMETRY, tdma::PROTOCOL_VERSION, node_id_, 
                                     0, 0, 100, 40, 0, (uint16_t)acq_.getOverflows(), 0, millis()/1000};
    esp_now_send(basestation_mac, (const uint8_t*)&tel, sizeof(tel));
}
