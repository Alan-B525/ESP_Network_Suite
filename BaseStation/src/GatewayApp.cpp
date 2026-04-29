#include "GatewayApp.h"
#include "GatewaySerial.h"
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#define RX_LED 8
#define WIFI_CHANNEL 1
#define SERIAL_BAUD 921600
#define STATS_INTERVAL_MS 5000
#define LED_PULSE_MS 20

GatewayApp *GatewayApp::s_instance = nullptr;

void GatewayApp::begin() {
    s_instance = this;
    GatewaySerial::begin(SERIAL_BAUD);
    delay(120);

    pinMode(RX_LED, OUTPUT);
    digitalWrite(RX_LED, LOW);

    WiFi.mode(WIFI_STA);
    delay(100);
    esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

    if (esp_now_init() != ESP_OK) {
        GatewaySerial::sendAsciiMsg("FATAL,ESP_NOW_INIT_FAILED");
        while (true) delay(1000);
    }

    esp_now_register_recv_cb(GatewayApp::onDataRecvStatic);
    
    if (!addBroadcastPeer()) {
        GatewaySerial::sendAsciiMsg("WARN,BROADCAST_PEER_ADD_FAILED");
    }
    
    tdma_manager_.begin();
    printStartupInfo();
    last_stats_ms_ = millis();
}

void GatewayApp::run() {
    uint32_t now_ms = millis();

    checkSerialCommands();
    processRxQueue();
    tdma_manager_.update(now_ms);
    serviceLed(now_ms);

    if ((now_ms - last_stats_ms_) >= STATS_INTERVAL_MS) {
        printStats(now_ms);
        last_stats_ms_ = now_ms;
    }
}

void GatewayApp::onDataRecvStatic(const uint8_t *mac, const uint8_t *data, int len) {
    if (s_instance) s_instance->enqueueRxFrame(mac, data, len);
}

void GatewayApp::enqueueRxFrame(const uint8_t *mac, const uint8_t *data, int len) {
    if (!mac || !data || len <= 0) return;
    uint8_t clipped = (len > ESPNOW_MAX_PAYLOAD_BYTES) ? ESPNOW_MAX_PAYLOAD_BYTES : (uint8_t)len;

    portENTER_CRITICAL_ISR(&rx_mux_);
    uint8_t next = (rx_head_ + 1U) % tdma::RX_QUEUE_LEN;
    if (next == rx_tail_) {
        rx_overruns_++;
        portEXIT_CRITICAL_ISR(&rx_mux_);
        return;
    }
    RxFrame &slot = rx_queue_[rx_head_];
    memcpy(slot.mac, mac, 6);
    slot.len = clipped;
    slot.rx_us = micros();
    memcpy(slot.payload, data, clipped);
    rx_head_ = next;
    portEXIT_CRITICAL_ISR(&rx_mux_);
}

bool GatewayApp::popRxFrame(RxFrame &out) {
    bool ok = false;
    portENTER_CRITICAL(&rx_mux_);
    if (rx_tail_ != rx_head_) {
        out = rx_queue_[rx_tail_];
        rx_tail_ = (rx_tail_ + 1U) % tdma::RX_QUEUE_LEN;
        ok = true;
    }
    portEXIT_CRITICAL(&rx_mux_);
    return ok;
}

void GatewayApp::processRxQueue() {
    RxFrame frame = {};
    while (popRxFrame(frame)) {
        if (frame.len < 1) continue;
        uint8_t pkt_type = frame.payload[0];
        switch (pkt_type) {
            case tdma::PKT_NODE_HELLO:     handleNodeHello(frame);  break;
            case tdma::PKT_DATA:           handleDataPacket(frame); break;
            case tdma::PKT_TIMING_INFO:    handleTimingInfo(frame); break;
            case tdma::PKT_NODE_TELEMETRY: handleNodeTelemetry(frame); break;
        }
    }
}

void GatewayApp::handleNodeHello(const RxFrame &frame) {
    if (frame.len != sizeof(tdma::NodeHelloPacket)) return;
    tdma::NodeHelloPacket hello;
    memcpy(&hello, frame.payload, sizeof(hello));
    if (hello.version != tdma::PROTOCOL_VERSION) return;

    ActiveNodeEntry *node = registry_.findOrCreateNode(frame.mac, hello.node_id);
    if (!node) return;

    if (hello.node_id == 0) {
        tdma::JoinAckPacket ack = {tdma::PKT_JOIN_ACK, tdma::PROTOCOL_VERSION, node->node_id, tdma_manager_.getSystemState()};
        ensurePeerPresent(node->mac);
        esp_now_send(node->mac, (const uint8_t*)&ack, sizeof(ack));
    }

    node->last_seen_ms = millis();
    node->channel_mask = hello.channel_mask;
    node->channel_count = hello.channel_count;
    node->sample_rate_hz = hello.sample_rate_hz;
    
    GatewaySerial::sendAsciiMsg("HELLO,%u,%02X:%02X:%02X:%02X:%02X:%02X,CH=0x%02X,RATE=%u",
                                node->node_id, node->mac[0], node->mac[1], node->mac[2],
                                node->mac[3], node->mac[4], node->mac[5],
                                node->channel_mask, node->sample_rate_hz);
}

void GatewayApp::handleDataPacket(const RxFrame &frame) {
    if (frame.len < tdma::DATA_HEADER_SIZE) return;
    if (tdma_manager_.getSystemState() != tdma::STATE_ACQUIRING) return;

    tdma::DataPacketHeader header;
    memcpy(&header, frame.payload, tdma::DATA_HEADER_SIZE);
    if (header.version != tdma::PROTOCOL_VERSION) return;

    ActiveNodeEntry *node = registry_.findNodeById(header.node_id);
    if (!node) return;
    node->last_seen_ms = millis();

    size_t expected_len = tdma::dataPacketExpectedLength(header);
    if (frame.len != expected_len) { node->invalid_packets++; return; }

    uint16_t rcv_crc = header.crc16;
    header.crc16 = 0;
    memcpy((void*)frame.payload, &header, tdma::DATA_HEADER_SIZE); // Temporally clear CRC for check
    if (tdma::crc16_ccitt(frame.payload, expected_len) != rcv_crc) { node->invalid_packets++; return; }
    header.crc16 = rcv_crc;

    bool should_emit = false;
    if (node->highest_seq_acked == 0) {
        node->highest_seq_acked = header.sequence_id;
        should_emit = true;
    } else {
        uint16_t expected = node->highest_seq_acked + 1U;
        int16_t delta = (int16_t)(header.sequence_id - expected);
        if (delta == 0) {
            node->highest_seq_acked = header.sequence_id;
            should_emit = true;
        } else if (delta > 0) {
            node->lost_packets += delta;
            GatewaySerial::sendAsciiMsg("LOSS,%u,EXPECTED=%u,GOT=%u", node->node_id, expected, header.sequence_id);
        }
    }
    
    node->received_packets++;
    sendDirectAck(*node, frame.rx_us);

    if (should_emit) {
        GatewaySerial::sendBinaryMsg(tdma::SER_MSG_DATA, frame.payload, expected_len);
        node->emitted_packets++;
        pulseRxLed();
    }
}

void GatewayApp::handleTimingInfo(const RxFrame &frame) {
    if (frame.len != sizeof(tdma::TimingInfoPacket)) return;
    tdma::TimingInfoPacket timing;
    memcpy(&timing, frame.payload, sizeof(timing));
    
    ActiveNodeEntry *node = registry_.findNodeById(timing.node_id);
    if (node) node->last_seen_ms = millis();

    GatewaySerial::sendBinaryMsg(tdma::SER_MSG_TIMING, (const uint8_t*)&timing, sizeof(timing));
}

void GatewayApp::handleNodeTelemetry(const RxFrame &frame) {
    if (frame.len != sizeof(tdma::NodeTelemetryPacket)) return;
    tdma::NodeTelemetryPacket tel;
    memcpy(&tel, frame.payload, sizeof(tel));

    ActiveNodeEntry *node = registry_.findNodeById(tel.node_id);
    if (node) node->last_seen_ms = millis();

    GatewaySerial::sendAsciiMsg("TELEMETRY,%u,%d,%u,%d,%u,%u,%u,%lu",
                                tel.node_id, tel.rssi_dbm, tel.battery_pct, tel.temperature_c,
                                tel.buffer_usage_pct, tel.overflow_count, tel.tx_errors,
                                (unsigned long)tel.uptime_s);
}

void GatewayApp::sendDirectAck(const ActiveNodeEntry &node, uint32_t rx_us) {
    tdma::DirectAckPacket ack = {tdma::PKT_DIRECT_ACK, tdma::PROTOCOL_VERSION, node.node_id, 
                                 tdma_manager_.getSystemState(), node.highest_seq_acked, rx_us};
    ensurePeerPresent(node.mac);
    esp_now_send(node.mac, (const uint8_t*)&ack, sizeof(ack));
}

void GatewayApp::checkSerialCommands() {
    while (Serial.available() > 0) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (cmd_len_ > 0) {
                cmd_buf_[cmd_len_] = '\0';
                processCommand(cmd_buf_);
                cmd_len_ = 0;
            }
        } else if (cmd_len_ < 63) {
            cmd_buf_[cmd_len_++] = c;
        }
    }
}

void GatewayApp::processCommand(const char *cmd) {
    if (strcmp(cmd, "CMD_START") == 0) {
        tdma_manager_.setSystemState(tdma::STATE_ACQUIRING);
        GatewaySerial::sendAsciiMsg("ACK,CMD_START,OK");
    } else if (strcmp(cmd, "CMD_STOP") == 0) {
        tdma_manager_.setSystemState(tdma::STATE_IDLE);
        GatewaySerial::sendAsciiMsg("ACK,CMD_STOP,OK");
    } else if (strncmp(cmd, "CMD_SET_TIME,", 13) == 0) {
        tdma_manager_.setRtcTime(strtoull(cmd + 13, nullptr, 10));
        GatewaySerial::sendAsciiMsg("ACK,CMD_SET_TIME,OK");
    } else if (strncmp(cmd, "CMD_SET_RATE,", 13) == 0) {
        uint16_t rate = (uint16_t)atoi(cmd + 13);
        tdma_manager_.setTargetRate(rate);
        GatewaySerial::sendAsciiMsg("ACK,CMD_SET_RATE,%u", rate);
    }
}

void GatewayApp::printStartupInfo() {
    GatewaySerial::sendAsciiMsg("BOOT,ESP32C3_TDMA_GATEWAY_V5");
    GatewaySerial::sendAsciiMsg("BOOT,MAC,%s", WiFi.macAddress().c_str());
    GatewaySerial::sendAsciiMsg("BOOT,CYCLE_MS,%u", tdma::CYCLE_MS);
}

void GatewayApp::printStats(uint32_t now_ms) {
    GatewaySerial::sendAsciiMsg("STATS_BEGIN");
    GatewaySerial::sendAsciiMsg("STATS,STATE,%u", tdma_manager_.getSystemState());
    GatewaySerial::sendAsciiMsg("STATS,RX_OVERRUN,%lu", (unsigned long)rx_overruns_);
    GatewaySerial::sendAsciiMsg("STATS,BEACON_TX_ERR,%lu", (unsigned long)tdma_manager_.getBeaconErrors());

    ActiveNodeEntry *nodes = registry_.getNodes();
    for (uint8_t i = 0; i < tdma::MAX_NODES; i++) {
        if (!nodes[i].in_use) continue;
        GatewaySerial::sendAsciiMsg("NODE,%u,RX=%lu,EMIT=%lu,ACKED=%u,LOST=%lu,INVALID=%lu,AGE_MS=%lu",
                                    nodes[i].node_id, (unsigned long)nodes[i].received_packets,
                                    (unsigned long)nodes[i].emitted_packets, nodes[i].highest_seq_acked,
                                    (unsigned long)nodes[i].lost_packets, (unsigned long)nodes[i].invalid_packets,
                                    (unsigned long)(now_ms - nodes[i].last_seen_ms));
    }
    GatewaySerial::sendAsciiMsg("STATS_END");
}

void GatewayApp::pulseRxLed() {
    digitalWrite(RX_LED, HIGH);
    led_on_ = true;
    led_off_ms_ = millis() + LED_PULSE_MS;
}

void GatewayApp::serviceLed(uint32_t now_ms) {
    if (led_on_ && (int32_t)(now_ms - led_off_ms_) >= 0) {
        digitalWrite(RX_LED, LOW);
        led_on_ = false;
    }
}

bool GatewayApp::ensurePeerPresent(const uint8_t *mac) {
    if (esp_now_is_peer_exist(mac)) return true;
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, mac, 6);
    peer.channel = WIFI_CHANNEL;
    peer.encrypt = false;
    return esp_now_add_peer(&peer) == ESP_OK;
}

bool GatewayApp::addBroadcastPeer() {
    static const uint8_t kBroadcastMac[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
    if (esp_now_is_peer_exist(kBroadcastMac)) return true;
    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, kBroadcastMac, 6);
    peer.channel = WIFI_CHANNEL;
    peer.encrypt = false;
    return esp_now_add_peer(&peer) == ESP_OK;
}
