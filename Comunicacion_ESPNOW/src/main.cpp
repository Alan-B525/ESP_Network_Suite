// ============================================================
// Base Station (Gateway) — Protocolo TDMA v4 / ESP-NOW
// ============================================================
//
// Coordina red de hasta 10 nodos ESP32 con hasta 4 canales cada uno.
//
// Funcionalidades v4:
//   - Estados: DISCOVERY → IDLE → ACQUIRING (controlado por PC)
//   - TDMA Round-Robin: 10 slots fijos, sin tiempos muertos
//   - Reenvío de TIMING_INFO y DATA al PC vía serial
//   - Sincronización RTC: PC → Gateway → Beacon → Nodos
//   - Comandos serial: CMD_START, CMD_STOP, CMD_SET_TIME
// ============================================================

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <tdma_protocol.h>
#include <esp_timer.h>

#include <stdio.h>
#include <string.h>

#define RX_LED 8
#define WIFI_CHANNEL 1
#define SERIAL_BAUD 921600
#define RX_QUEUE_LEN 32
#define LED_PULSE_MS 20
#define STATS_INTERVAL_MS 5000
#define SERIAL_CMD_BUF_LEN 64

using namespace tdma;

static const uint8_t kBroadcastMac[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

// ============================================================
// Tipos locales
// ============================================================

struct RxFrame {
    uint8_t mac[6];
    uint8_t len;
    uint8_t payload[ESPNOW_MAX_PAYLOAD_BYTES];
    uint32_t rx_us;
};

struct ActiveNodeEntry {
    bool in_use;
    uint8_t node_id;
    uint8_t mac[6];
    uint8_t channel_mask;
    uint8_t channel_count;
    uint16_t sample_rate_hz;
    uint32_t last_seen_ms;
    uint16_t highest_seq_received;
    uint16_t highest_seq_acked;
    uint32_t received_packets;
    uint32_t emitted_packets;
    uint32_t lost_packets;
    uint32_t invalid_packets;
};

// ============================================================
// Clase Gateway
// ============================================================

class TDMAGateway {
public:
    void begin() {
        Serial.setTxBufferSize(8192); // Buffer grande para rafagas de 4 canales
        Serial.begin(SERIAL_BAUD);
        delay(120);

        pinMode(RX_LED, OUTPUT);
        digitalWrite(RX_LED, LOW);

        WiFi.mode(WIFI_STA);
        delay(100);
        esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

        if (esp_now_init() != ESP_OK) {
            sendAsciiMsg("FATAL,ESP_NOW_INIT_FAILED");
            while (true) delay(1000);
        }

        if (!addBroadcastPeer()) {
            sendAsciiMsg("WARN,BROADCAST_PEER_ADD_FAILED");
        }

        s_instance = this;
        esp_now_register_recv_cb(TDMAGateway::onDataRecvStatic);
        esp_now_register_send_cb(TDMAGateway::onDataSentStatic);

        cycle_started_ms_ = millis();
        registration_deadline_ms_ = cycle_started_ms_;
        last_stats_ms_ = cycle_started_ms_;

        printStartupInfo();
        system_state_ = STATE_DISCOVERY;
    }

    void run() {
        uint32_t now_ms = millis();

        checkSerialCommands();
        processRxQueue();
        runStateMachine(now_ms);
        serviceLed(now_ms);

        if ((now_ms - last_stats_ms_) >= STATS_INTERVAL_MS) {
            printStats(now_ms);
            last_stats_ms_ = now_ms;
        }
    }

private:
    static TDMAGateway *s_instance;

    // ---- Callbacks ESP-NOW ----

    static void onDataRecvStatic(const uint8_t *mac, const uint8_t *data, int len) {
        if (s_instance) s_instance->enqueueRxFrame(mac, data, len);
    }

    static void onDataSentStatic(const uint8_t *mac, esp_now_send_status_t status) {
        if (s_instance && status != ESP_NOW_SEND_SUCCESS) {
            s_instance->tx_errors_++;
        }
    }

    // ---- Estado del sistema ----
    uint8_t system_state_ = STATE_DISCOVERY;
    uint16_t target_rate_hz_ = 1000;     // Default sample rate
    uint64_t rtc_epoch_ms_ = 0;
    // ---- RTC con timer de 64 bits para evitar wrap de micros() ----
    uint64_t rtc_set_at_us_64_ = 0;

    uint64_t getCurrentEpochMs() {
        if (rtc_epoch_ms_ == 0) return 0;
        uint64_t now_us = (uint64_t)esp_timer_get_time();
        uint64_t elapsed_us = now_us - rtc_set_at_us_64_;
        return rtc_epoch_ms_ + (elapsed_us / 1000ULL);
    }

    // ---- Nodos y schedule ----
    ActiveNodeEntry nodes_[MAX_NODES] = {};
    uint8_t sorted_node_ids_[MAX_NODES] = {};
    uint8_t active_count_ = 0;
    uint8_t slot_schedule_[MAX_SLOTS] = {};

    // ---- Timing del ciclo ----
    uint32_t cycle_started_ms_ = 0;
    uint32_t registration_deadline_ms_ = 0;
    uint32_t beacon_sequence_ = 1;
    uint32_t last_stats_ms_ = 0;

    // ---- Cola RX ----
    RxFrame rx_queue_[RX_QUEUE_LEN] = {};
    volatile uint8_t rx_head_ = 0;
    volatile uint8_t rx_tail_ = 0;
    volatile uint32_t rx_overruns_ = 0;
    portMUX_TYPE rx_mux_ = portMUX_INITIALIZER_UNLOCKED;

    // ---- Errores ----
    uint32_t tx_errors_ = 0;
    uint32_t beacon_errors_ = 0;

    // ---- LED ----
    bool led_on_ = false;
    uint32_t led_off_ms_ = 0;

    // ---- Serial command buffer ----
    char cmd_buf_[SERIAL_CMD_BUF_LEN] = {};
    uint8_t cmd_len_ = 0;

    // ---- Emisión serial binaria ----
    void sendBinaryMsg(SerialMsgType type, const uint8_t *payload, size_t len) {
        uint8_t raw_buf[len + 1];
        raw_buf[0] = type;
        if (len > 0 && payload) memcpy(raw_buf + 1, payload, len);

        size_t cobs_max = len + 1 + (len + 1) / 254 + 2;
        uint8_t cobs_buf[cobs_max];
        size_t cobs_len = tdma::cobsEncode(raw_buf, len + 1, cobs_buf);

        Serial.write(cobs_buf, cobs_len);
    }

    void sendAsciiMsg(const char *fmt, ...) {
        char buf[256];
        va_list args;
        va_start(args, fmt);
        int len = vsnprintf(buf, sizeof(buf), fmt, args);
        va_end(args);
        if (len > 0) {
            sendBinaryMsg(SER_MSG_ASCII, (const uint8_t*)buf, len);
        }
    }

    // ============================================================
    // Serial Commands (PC → Gateway)
    // ============================================================

    void checkSerialCommands() {
        while (Serial.available() > 0) {
            char c = Serial.read();
            if (c == '\n' || c == '\r') {
                if (cmd_len_ > 0) {
                    cmd_buf_[cmd_len_] = '\0';
                    processCommand(cmd_buf_);
                    cmd_len_ = 0;
                }
            } else if (cmd_len_ < SERIAL_CMD_BUF_LEN - 1) {
                cmd_buf_[cmd_len_++] = c;
            }
        }
    }

    void processCommand(const char *cmd) {
        if (strcmp(cmd, "CMD_START") == 0) {
            system_state_ = STATE_ACQUIRING;
            for (uint8_t i = 0; i < MAX_NODES; i++) {
                if (nodes_[i].in_use) {
                    nodes_[i].highest_seq_acked = 0;
                    nodes_[i].highest_seq_received = 0;
                }
            }
            sendAsciiMsg("ACK,CMD_START,OK");
        } else if (strcmp(cmd, "CMD_STOP") == 0) {
            system_state_ = STATE_IDLE;
            sendAsciiMsg("ACK,CMD_STOP,OK");
        } else if (strncmp(cmd, "CMD_SET_TIME,", 13) == 0) {
            rtc_epoch_ms_ = strtoull(cmd + 13, nullptr, 10);
            rtc_set_at_us_64_ = (uint64_t)esp_timer_get_time();
            sendAsciiMsg("ACK,CMD_SET_TIME,OK");
        } else if (strncmp(cmd, "CMD_SET_RATE,", 13) == 0) {
            uint16_t rate = (uint16_t)atoi(cmd + 13);
            if (rate >= 1 && rate <= 10000) {
                target_rate_hz_ = rate;
                sendAsciiMsg("ACK,CMD_SET_RATE,%u", rate);
            } else {
                sendAsciiMsg("ACK,CMD_SET_RATE,ERR_RANGE");
            }
        }
    }

    // ============================================================
    // Máquina de estados
    // ============================================================

    void runStateMachine(uint32_t now_ms) {
        // Nuevo ciclo TDMA cada CYCLE_MS
        if ((now_ms - cycle_started_ms_) >= CYCLE_MS) {
            startNewCycle(now_ms);
        }
    }

    void startNewCycle(uint32_t now_ms) {
        pruneInactiveNodes(now_ms);
        rebuildSchedule();
        sendBeaconSync();

        cycle_started_ms_ = now_ms;
        registration_deadline_ms_ = now_ms + REGISTRATION_WINDOW_MS;

        // Auto-transición DISCOVERY → IDLE cuando hay nodos
        if (system_state_ == STATE_DISCOVERY && active_count_ > 0) {
            system_state_ = STATE_IDLE;
        }
    }

    // ============================================================
    // Schedule Round-Robin
    // ============================================================

    void rebuildSchedule() {
        active_count_ = 0;

        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (nodes_[i].in_use) {
                sorted_node_ids_[active_count_++] = nodes_[i].node_id;
            }
        }

        // Insertion sort por node_id para schedule determinista
        for (uint8_t i = 1; i < active_count_; i++) {
            uint8_t key = sorted_node_ids_[i];
            int8_t j = static_cast<int8_t>(i) - 1;
            while (j >= 0 && sorted_node_ids_[j] > key) {
                sorted_node_ids_[j + 1] = sorted_node_ids_[j];
                j--;
            }
            sorted_node_ids_[j + 1] = key;
        }

        buildRoundRobinSchedule(sorted_node_ids_, active_count_, slot_schedule_);
    }

    // ============================================================
    // Cola RX
    // ============================================================

    void enqueueRxFrame(const uint8_t *mac, const uint8_t *data, int len) {
        if (!mac || !data || len <= 0) return;

        uint8_t clipped = (len > ESPNOW_MAX_PAYLOAD_BYTES)
                          ? ESPNOW_MAX_PAYLOAD_BYTES : static_cast<uint8_t>(len);

        portENTER_CRITICAL_ISR(&rx_mux_);
        uint8_t next = (rx_head_ + 1U) % RX_QUEUE_LEN;
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

    bool popRxFrame(RxFrame &out) {
        bool ok = false;
        portENTER_CRITICAL(&rx_mux_);
        if (rx_tail_ != rx_head_) {
            out = rx_queue_[rx_tail_];
            rx_tail_ = (rx_tail_ + 1U) % RX_QUEUE_LEN;
            ok = true;
        }
        portEXIT_CRITICAL(&rx_mux_);
        return ok;
    }

    void processRxQueue() {
        RxFrame frame = {};
        while (popRxFrame(frame)) {
            if (frame.len < 1) continue;

            uint8_t pkt_type = frame.payload[0];
            switch (pkt_type) {
                case PKT_NODE_HELLO:  handleNodeHello(frame);  break;
                case PKT_DATA:        handleDataPacket(frame); break;
                case PKT_TIMING_INFO: handleTimingInfo(frame); break;
                case PKT_NODE_TELEMETRY: handleNodeTelemetry(frame); break;
                default: break;
            }
        }
    }

    // ============================================================
    // Handlers de paquetes
    // ============================================================

    void handleNodeHello(const RxFrame &frame) {
        if (frame.len != sizeof(NodeHelloPacket)) return;

        NodeHelloPacket hello = {};
        memcpy(&hello, frame.payload, sizeof(hello));
        if (hello.version != PROTOCOL_VERSION) return;

        uint8_t target_node_id = hello.node_id;
        if (target_node_id == 0) {
            ActiveNodeEntry *existing = nullptr;
            for (uint8_t i = 0; i < MAX_NODES; i++) {
                if (nodes_[i].in_use && memcmp(nodes_[i].mac, frame.mac, 6) == 0) {
                    existing = &nodes_[i];
                    break;
                }
            }
            if (existing) {
                target_node_id = existing->node_id;
            } else {
                for (uint8_t i = 1; i <= MAX_NODES; i++) {
                    if (!findNodeById(i)) {
                        target_node_id = i;
                        break;
                    }
                }
            }
        }
        if (target_node_id == 0 || !isValidNodeId(target_node_id)) return;

        ActiveNodeEntry *node = findOrCreateNode(frame.mac, target_node_id);
        if (!node) return;
        
        if (hello.node_id == 0) {
            JoinAckPacket ack = {};
            ack.type = PKT_JOIN_ACK;
            ack.version = PROTOCOL_VERSION;
            ack.assigned_node_id = node->node_id;
            ack.system_state = system_state_;
            ensurePeerPresent(node->mac);
            esp_now_send(node->mac, (const uint8_t*)&ack, sizeof(ack));
        }

        node->last_seen_ms = millis();
        node->channel_mask = hello.channel_mask;
        node->channel_count = hello.channel_count;
        node->sample_rate_hz = hello.sample_rate_hz;
        ensurePeerPresent(node->mac);

        char mac_text[18] = {};
        formatMac(node->mac, mac_text, sizeof(mac_text));
        sendAsciiMsg("HELLO,%u,%s,CH=0x%02X,RATE=%u",
                      node->node_id, mac_text,
                      node->channel_mask, node->sample_rate_hz);
    }

    void handleDataPacket(const RxFrame &frame) {
        if (frame.len < DATA_HEADER_SIZE) return;

        // Solo aceptar datos en modo ACQUIRING
        if (system_state_ != STATE_ACQUIRING) return;

        DataPacketHeader header = {};
        memcpy(&header, frame.payload, DATA_HEADER_SIZE);
        if (header.version != PROTOCOL_VERSION || !isValidNodeId(header.node_id)) return;

        ActiveNodeEntry *node = findOrCreateNode(frame.mac, header.node_id);
        if (!node) return;
        node->last_seen_ms = millis();

        size_t expected_len = dataPacketExpectedLength(header);
        uint16_t max_s = maxSamplesForEncoding(header.sample_encoding);
        if (expected_len == 0 || header.sample_count == 0 ||
            header.sample_count > max_s || frame.len != expected_len) {
            node->invalid_packets++;
            return;
        }

        // CRC Check
        uint16_t rcv_crc = header.crc16;
        DataPacketHeader *hdr_ptr = (DataPacketHeader*)frame.payload;
        hdr_ptr->crc16 = 0;
        uint16_t calc_crc = crc16_ccitt(frame.payload, expected_len);
        if (calc_crc != rcv_crc) {
            node->invalid_packets++;
            return;
        }
        hdr_ptr->crc16 = rcv_crc;

        // Detección de pérdida por secuencia
        bool should_emit = false;
        if (node->highest_seq_acked == 0) {
            node->highest_seq_acked = header.sequence_id;
            should_emit = true;
        } else {
            uint16_t expected_next = node->highest_seq_acked + 1U;
            int16_t delta = static_cast<int16_t>(header.sequence_id - expected_next);
            if (delta == 0) {
                node->highest_seq_acked = header.sequence_id;
                should_emit = true;
            } else if (delta > 0) {
                // ARQ Go-Back-N: Descartar el paquete desordenado
                // NO avanzamos highest_seq_acked para forzar la retransmisión
                node->lost_packets += delta; // Solo para estadísticas de red
                should_emit = false;
                sendAsciiMsg("LOSS,%u,EXPECTED=%u,GOT=%u",
                              node->node_id, expected_next, header.sequence_id);
            }
            // delta < 0: duplicado, se ignora payload pero se re-ACKea
        }

        if (isSequenceNewer(header.sequence_id, node->highest_seq_received)) {
            node->highest_seq_received = header.sequence_id;
        }

        node->received_packets++;
        sendDirectAck(*node, frame.rx_us);

        if (should_emit) {
            emitDataBinary(*node, header, frame.payload + DATA_HEADER_SIZE);
            node->emitted_packets++;
            pulseRxLed();
        }
    }

    void handleTimingInfo(const RxFrame &frame) {
        if (frame.len != sizeof(TimingInfoPacket)) return;

        TimingInfoPacket timing = {};
        memcpy(&timing, frame.payload, sizeof(timing));
        if (timing.version != PROTOCOL_VERSION || !isValidNodeId(timing.node_id)) return;

        // CRC Check
        uint16_t rcv_crc = timing.crc16;
        TimingInfoPacket *tim_ptr = (TimingInfoPacket*)frame.payload;
        tim_ptr->crc16 = 0;
        if (crc16_ccitt(frame.payload, sizeof(TimingInfoPacket)) != rcv_crc) {
            return;
        }
        tim_ptr->crc16 = rcv_crc;

        ActiveNodeEntry *node = findNodeById(timing.node_id);
        if (node) node->last_seen_ms = millis();

        // Reenviar al PC como trama binaria
        sendBinaryMsg(SER_MSG_TIMING, (const uint8_t*)&timing, sizeof(timing));
    }

    void handleNodeTelemetry(const RxFrame &frame) {
        if (frame.len != sizeof(NodeTelemetryPacket)) return;

        NodeTelemetryPacket tel = {};
        memcpy(&tel, frame.payload, sizeof(tel));
        if (tel.version != PROTOCOL_VERSION || !isValidNodeId(tel.node_id)) return;

        ActiveNodeEntry *node = findNodeById(tel.node_id);
        if (node) node->last_seen_ms = millis();

        // TELEMETRY,node_id,rssi,battery,temp,buf,ovf,tx_err,uptime
        sendAsciiMsg("TELEMETRY,%u,%d,%u,%d,%u,%u,%u,%lu",
                      tel.node_id, tel.rssi_dbm, tel.battery_pct, tel.temperature_c,
                      tel.buffer_usage_pct, tel.overflow_count, tel.tx_errors,
                      (unsigned long)tel.uptime_s);
    }

    // ============================================================
    // Emisión serial
    // ============================================================

    void emitDataBinary(const ActiveNodeEntry &node,
                     const DataPacketHeader &header,
                     const uint8_t *payload) {
        size_t payload_len = header.sample_count * sampleSizeBytes(header.sample_encoding);
        size_t total_len = DATA_HEADER_SIZE + payload_len;
        
        uint8_t msg_buf[total_len];
        memcpy(msg_buf, &header, DATA_HEADER_SIZE);
        memcpy(msg_buf + DATA_HEADER_SIZE, payload, payload_len);
        
        sendBinaryMsg(SER_MSG_DATA, msg_buf, total_len);
    }

    // ============================================================
    // Beacon y ACK
    // ============================================================

    void sendBeaconSync() {
        BeaconSyncPacket beacon = {};
        beacon.type = PKT_BEACON_SYNC;
        beacon.version = PROTOCOL_VERSION;
        beacon.system_state = system_state_;
        beacon.active_nodes = active_count_;
        beacon.cycle_ms = CYCLE_MS;
        beacon.slot_us = SLOT_US;  // uint32_t: cabe sin truncar
        beacon.slot_guard_us = SLOT_GUARD_US;
        beacon.registration_window_ms = REGISTRATION_WINDOW_MS;
        beacon.sample_rate_hz = target_rate_hz_;
        beacon.beacon_sequence = beacon_sequence_++;
        beacon.rtc_epoch_ms = getCurrentEpochMs();

        memcpy(beacon.slot_schedule, slot_schedule_, MAX_SLOTS);

        for (uint8_t i = 0; i < active_count_ && i < MAX_NODES; i++) {
            ActiveNodeEntry *n = findNodeById(sorted_node_ids_[i]);
            if (n) {
                beacon.ack_map[i].node_id = n->node_id;
                beacon.ack_map[i].highest_acked_seq = n->highest_seq_acked;
            }
        }

        esp_err_t err = esp_now_send(kBroadcastMac,
                                      reinterpret_cast<const uint8_t *>(&beacon),
                                      sizeof(beacon));
        if (err != ESP_OK) beacon_errors_++;

        // Construir string de beacon
        char beacon_info[256];
        int len = snprintf(beacon_info, sizeof(beacon_info), 
                      "BEACON,%lu,STATE=%u,NODES=%u,SLOT_US=%u,RATE=%u,RTC=%llu,SCHED=",
                      (unsigned long)beacon.beacon_sequence,
                      beacon.system_state,
                      beacon.active_nodes,
                      beacon.slot_us,
                      beacon.sample_rate_hz,
                      (unsigned long long)beacon.rtc_epoch_ms);

        for (uint8_t i = 0; i < MAX_SLOTS; i++) {
            if (i > 0) len += snprintf(beacon_info + len, sizeof(beacon_info) - len, ";");
            len += snprintf(beacon_info + len, sizeof(beacon_info) - len, "%u", slot_schedule_[i]);
        }

        len += snprintf(beacon_info + len, sizeof(beacon_info) - len, ",ACKS=");
        for (uint8_t i = 0; i < active_count_; i++) {
            if (i > 0) len += snprintf(beacon_info + len, sizeof(beacon_info) - len, ";");
            len += snprintf(beacon_info + len, sizeof(beacon_info) - len, "%u:%u", 
                            beacon.ack_map[i].node_id, beacon.ack_map[i].highest_acked_seq);
        }
        sendAsciiMsg("%s", beacon_info);
    }

    void sendDirectAck(const ActiveNodeEntry &node, uint32_t rx_us) {
        DirectAckPacket ack = {};
        ack.type = PKT_DIRECT_ACK;
        ack.version = PROTOCOL_VERSION;
        ack.node_id = node.node_id;
        ack.system_state = system_state_;
        ack.highest_acked_seq = node.highest_seq_acked;
        ack.gateway_rx_us = rx_us;

        if (!ensurePeerPresent(node.mac)) return;
        esp_now_send(node.mac, reinterpret_cast<const uint8_t *>(&ack), sizeof(ack));
    }

    // ============================================================
    // Gestión de nodos
    // ============================================================

    void pruneInactiveNodes(uint32_t now_ms) {
        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (!nodes_[i].in_use) continue;
            if ((now_ms - nodes_[i].last_seen_ms) > NODE_INACTIVE_TIMEOUT_MS) {
                char mac_text[18] = {};
                formatMac(nodes_[i].mac, mac_text, sizeof(mac_text));
                sendAsciiMsg("NODE_TIMEOUT,%u,%s", nodes_[i].node_id, mac_text);
                memset(&nodes_[i], 0, sizeof(nodes_[i]));
            }
        }
    }

    ActiveNodeEntry *findOrCreateNode(const uint8_t *mac, uint8_t node_id) {
        // Buscar por MAC
        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (nodes_[i].in_use && memcmp(nodes_[i].mac, mac, 6) == 0) {
                if (nodes_[i].node_id != node_id && isValidNodeId(node_id)) {
                    nodes_[i].node_id = node_id;
                }
                return &nodes_[i];
            }
        }
        if (!isValidNodeId(node_id)) return nullptr;

        // Verificar que el ID no esté en uso por otra MAC
        if (findNodeById(node_id)) return nullptr;

        // Crear nuevo
        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (nodes_[i].in_use) continue;
            nodes_[i].in_use = true;
            nodes_[i].node_id = node_id;
            memcpy(nodes_[i].mac, mac, 6);
            nodes_[i].last_seen_ms = millis();
            nodes_[i].channel_mask = 0;
            nodes_[i].channel_count = 0;
            nodes_[i].sample_rate_hz = 0;
            nodes_[i].highest_seq_received = 0;
            nodes_[i].highest_seq_acked = 0;
            nodes_[i].received_packets = 0;
            nodes_[i].emitted_packets = 0;
            nodes_[i].lost_packets = 0;
            nodes_[i].invalid_packets = 0;

            char mac_text[18] = {};
            formatMac(mac, mac_text, sizeof(mac_text));
            sendAsciiMsg("NODE_JOIN,%u,%s", node_id, mac_text);
            return &nodes_[i];
        }
        return nullptr;
    }

    ActiveNodeEntry *findNodeById(uint8_t node_id) {
        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (nodes_[i].in_use && nodes_[i].node_id == node_id) return &nodes_[i];
        }
        return nullptr;
    }

    // ============================================================
    // Peers y utilidades
    // ============================================================

    bool addBroadcastPeer() {
        if (esp_now_is_peer_exist(kBroadcastMac)) return true;
        esp_now_peer_info_t peer = {};
        memcpy(peer.peer_addr, kBroadcastMac, 6);
        peer.channel = WIFI_CHANNEL;
        peer.encrypt = false;
        return esp_now_add_peer(&peer) == ESP_OK;
    }

    bool ensurePeerPresent(const uint8_t *mac) {
        if (esp_now_is_peer_exist(mac)) return true;
        esp_now_peer_info_t peer = {};
        memcpy(peer.peer_addr, mac, 6);
        peer.channel = WIFI_CHANNEL;
        peer.encrypt = false;
        return esp_now_add_peer(&peer) == ESP_OK;
    }

    static void formatMac(const uint8_t *mac, char *out, size_t sz) {
        if (!mac || !out || sz < 18) return;
        snprintf(out, sz, "%02X:%02X:%02X:%02X:%02X:%02X",
                 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    }

    void pulseRxLed() {
        digitalWrite(RX_LED, HIGH);
        led_on_ = true;
        led_off_ms_ = millis() + LED_PULSE_MS;
    }

    void serviceLed(uint32_t now_ms) {
        if (led_on_ && (int32_t)(now_ms - led_off_ms_) >= 0) {
            digitalWrite(RX_LED, LOW);
            led_on_ = false;
        }
    }

    // ============================================================
    // Info y estadísticas
    // ============================================================

    void printStartupInfo() {
        sendAsciiMsg("BOOT,ESP32C3_TDMA_GATEWAY_V4");
        sendAsciiMsg("BOOT,MAC,%s", WiFi.macAddress().c_str());
        sendAsciiMsg("BOOT,CHANNEL,%d", WIFI_CHANNEL);
        sendAsciiMsg("BOOT,CYCLE_MS,%u", CYCLE_MS);
        sendAsciiMsg("BOOT,REG_MS,%u", REGISTRATION_WINDOW_MS);
        sendAsciiMsg("BOOT,MAX_NODES,%u", MAX_NODES);
        sendAsciiMsg("BOOT,MAX_SLOTS,%u", MAX_SLOTS);
        sendAsciiMsg("BOOT,SLOT_US,%lu", (unsigned long)SLOT_US);
        sendAsciiMsg("BOOT,MAX_CHANNELS,%u", MAX_CHANNELS_PER_NODE);
        sendAsciiMsg("BOOT,SERIAL_FORMAT,BINARY_COBS_ENCODED");
    }

    void printStats(uint32_t now_ms) {
        sendAsciiMsg("STATS_BEGIN");
        sendAsciiMsg("STATS,STATE,%u", system_state_);
        sendAsciiMsg("STATS,ACTIVE_NODES,%u", active_count_);
        sendAsciiMsg("STATS,SLOT_US,%lu", (unsigned long)SLOT_US);
        sendAsciiMsg("STATS,RX_OVERRUN,%lu", (unsigned long)rx_overruns_);
        sendAsciiMsg("STATS,BEACON_TX_ERR,%lu", (unsigned long)beacon_errors_);
        sendAsciiMsg("STATS,TX_ERR,%lu", (unsigned long)tx_errors_);

        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (!nodes_[i].in_use) continue;
            char mac_text[18] = {};
            formatMac(nodes_[i].mac, mac_text, sizeof(mac_text));
            sendAsciiMsg("NODE,%u,MAC=%s,CH=0x%02X,RATE=%u,RX=%lu,EMIT=%lu,ACKED=%u,LOST=%lu,INVALID=%lu,AGE_MS=%lu",
                          nodes_[i].node_id,
                          mac_text,
                          nodes_[i].channel_mask,
                          nodes_[i].sample_rate_hz,
                          (unsigned long)nodes_[i].received_packets,
                          (unsigned long)nodes_[i].emitted_packets,
                          nodes_[i].highest_seq_acked,
                          (unsigned long)nodes_[i].lost_packets,
                          (unsigned long)nodes_[i].invalid_packets,
                          (unsigned long)(now_ms - nodes_[i].last_seen_ms));
        }
        sendAsciiMsg("STATS_END");
    }
};

TDMAGateway *TDMAGateway::s_instance = nullptr;
static TDMAGateway g_gateway;

void setup() { g_gateway.begin(); }
void loop()  { g_gateway.run(); delay(0); }
