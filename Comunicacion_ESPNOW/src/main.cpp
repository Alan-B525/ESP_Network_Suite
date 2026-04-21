#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <tdma_protocol.h>

#include <stdio.h>
#include <string.h>

#define RX_LED 8
#define WIFI_CHANNEL 1
#define SERIAL_BAUD 921600
#define RX_QUEUE_LEN 16
#define LED_PULSE_MS 20
#define STATS_INTERVAL_MS 5000

using namespace tdma;

static const uint8_t kBroadcastMac[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

enum SystemState : uint8_t {
    BROADCASTING_BEACON = 0,
    REGISTRATION_WINDOW = 1,
    WAITING_SLOTS = 2,
};

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
    uint32_t last_seen_ms;
    uint16_t highest_seq_received;
    uint16_t highest_seq_acked;
    uint32_t received_packets;
    uint32_t emitted_packets;
    uint32_t lost_packets;
    uint32_t invalid_packets;
};

class TDMAGateway {
public:
    void begin() {
        Serial.begin(SERIAL_BAUD);
        delay(120);

        pinMode(RX_LED, OUTPUT);
        digitalWrite(RX_LED, LOW);

        WiFi.mode(WIFI_STA);
        delay(100);
        esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

        if (esp_now_init() != ESP_OK) {
            Serial.println("FATAL,ESP_NOW_INIT_FAILED");
            while (true) {
                delay(1000);
            }
        }

        if (!addBroadcastPeer()) {
            Serial.println("WARN,BROADCAST_PEER_ADD_FAILED");
        }

        s_instance = this;
        esp_now_register_recv_cb(TDMAGateway::onDataRecvStatic);
        esp_now_register_send_cb(TDMAGateway::onDataSentStatic);

        cycle_started_ms_ = millis();
        registration_deadline_ms_ = cycle_started_ms_;
        last_stats_ms_ = cycle_started_ms_;

        printStartupInfo();
        state_ = BROADCASTING_BEACON;
    }

    void run() {
        uint32_t now_ms = millis();

        processRxQueue();
        runStateMachine(now_ms);
        serviceLed(now_ms);

        if ((int32_t)(now_ms - last_stats_ms_) >= 0 && (now_ms - last_stats_ms_) >= STATS_INTERVAL_MS) {
            printStats(now_ms);
            last_stats_ms_ = now_ms;
        }
    }

private:
    static TDMAGateway *s_instance;

    // Callback de ESP-NOW: solo copia a una cola lock-free corta.
    // Evitar Serial o parseo pesado aqui reduce jitter y no bloquea la radio.
    static void onDataRecvStatic(const uint8_t *mac, const uint8_t *incomingData, int len) {
        if (s_instance != nullptr) {
            s_instance->enqueueRxFrame(mac, incomingData, len);
        }
    }

    static void onDataSentStatic(const uint8_t *mac_addr, esp_now_send_status_t status) {
        if (s_instance != nullptr) {
            s_instance->handleSendStatus(mac_addr, status);
        }
    }

    void handleSendStatus(const uint8_t *mac_addr, esp_now_send_status_t status) {
        if (status == ESP_NOW_SEND_SUCCESS) {
            return;
        }

        char mac_text[18] = {0};
        formatMac(mac_addr, mac_text, sizeof(mac_text));
        Serial.print("WARN,TX_FAIL,");
        Serial.print(mac_text);
        Serial.print(",STATUS=");
        Serial.println(static_cast<uint8_t>(status));
    }

    void runStateMachine(uint32_t now_ms) {
        switch (state_) {
            case BROADCASTING_BEACON:
                startNewCycle(now_ms);
                break;

            case REGISTRATION_WINDOW:
                if ((int32_t)(now_ms - registration_deadline_ms_) >= 0) {
                    state_ = WAITING_SLOTS;
                }
                if ((now_ms - cycle_started_ms_) >= CYCLE_MS) {
                    state_ = BROADCASTING_BEACON;
                }
                break;

            case WAITING_SLOTS:
                if ((now_ms - cycle_started_ms_) >= CYCLE_MS) {
                    state_ = BROADCASTING_BEACON;
                }
                break;
        }
    }

    void startNewCycle(uint32_t now_ms) {
        pruneInactiveNodes(now_ms);
        rebuildSchedule();

        // Sincronizacion temporal:
        // 1) El ciclo total es fijo (1 s) para que la PC tenga una cadencia estable.
        // 2) Se reserva una ventana corta de registro al inicio para nodos nuevos.
        // 3) El tiempo restante se reparte dinamicamente entre nodos activos.
        // Esta politica evita slots desperdiciados cuando hay pocos nodos y se adapta
        // automaticamente al crecimiento/disminucion de la red.
        dynamic_slot_us_ = computeDynamicSlotUs(active_schedule_count_);

        sendBeaconSync();

        cycle_started_ms_ = now_ms;
        registration_deadline_ms_ = now_ms + REGISTRATION_WINDOW_MS;
        state_ = REGISTRATION_WINDOW;
    }

    void enqueueRxFrame(const uint8_t *mac, const uint8_t *incomingData, int len) {
        if (mac == nullptr || incomingData == nullptr || len <= 0) {
            return;
        }

        uint8_t clipped_len = (len > ESPNOW_MAX_PAYLOAD_BYTES) ? ESPNOW_MAX_PAYLOAD_BYTES : static_cast<uint8_t>(len);

        portENTER_CRITICAL_ISR(&rx_queue_mux_);
        uint8_t next_head = static_cast<uint8_t>((rx_head_ + 1U) % RX_QUEUE_LEN);
        if (next_head == rx_tail_) {
            rx_queue_overruns_++;
            portEXIT_CRITICAL_ISR(&rx_queue_mux_);
            return;
        }

        RxFrame &slot = rx_queue_[rx_head_];
        memcpy(slot.mac, mac, 6);
        slot.len = clipped_len;
        slot.rx_us = micros();
        memcpy(slot.payload, incomingData, clipped_len);

        rx_head_ = next_head;
        portEXIT_CRITICAL_ISR(&rx_queue_mux_);
    }

    bool popRxFrame(RxFrame &out) {
        bool has_data = false;

        portENTER_CRITICAL(&rx_queue_mux_);
        if (rx_tail_ != rx_head_) {
            out = rx_queue_[rx_tail_];
            rx_tail_ = static_cast<uint8_t>((rx_tail_ + 1U) % RX_QUEUE_LEN);
            has_data = true;
        }
        portEXIT_CRITICAL(&rx_queue_mux_);

        return has_data;
    }

    void processRxQueue() {
        RxFrame frame = {};
        while (popRxFrame(frame)) {
            if (frame.len < 1) {
                continue;
            }

            uint8_t packet_type = frame.payload[0];
            if (packet_type == PKT_NODE_HELLO) {
                handleNodeHello(frame);
            } else if (packet_type == PKT_DATA) {
                handleDataPacket(frame);
            }
        }
    }

    void handleNodeHello(const RxFrame &frame) {
        if (frame.len != sizeof(NodeHelloPacket)) {
            return;
        }

        NodeHelloPacket hello = {};
        memcpy(&hello, frame.payload, sizeof(hello));

        if (hello.version != PROTOCOL_VERSION || !isValidNodeId(hello.node_id)) {
            return;
        }

        ActiveNodeEntry *node = findOrCreateNode(frame.mac, hello.node_id);
        if (node == nullptr) {
            return;
        }

        node->last_seen_ms = millis();
        ensurePeerPresent(node->mac);

        char mac_text[18] = {0};
        formatMac(node->mac, mac_text, sizeof(mac_text));
        Serial.print("HELLO,");
        Serial.print(node->node_id);
        Serial.print(",");
        Serial.println(mac_text);
    }

    void handleDataPacket(const RxFrame &frame) {
        if (frame.len < DATA_HEADER_SIZE) {
            return;
        }

        DataPacketHeader header = {};
        memcpy(&header, frame.payload, DATA_HEADER_SIZE);

        if (header.version != PROTOCOL_VERSION || !isValidNodeId(header.node_id)) {
            return;
        }

        ActiveNodeEntry *node = findOrCreateNode(frame.mac, header.node_id);
        if (node == nullptr) {
            return;
        }

        node->last_seen_ms = millis();

        size_t expected_len = dataPacketExpectedLength(header);
        uint16_t max_samples = maxSamplesForEncoding(header.sample_encoding);
        if (expected_len == 0 || header.sample_count == 0 || header.sample_count > max_samples || frame.len != expected_len) {
            node->invalid_packets++;
            return;
        }

        bool should_emit_payload = false;
        if (node->highest_seq_acked == 0) {
            // Primer paquete aceptado: se establece frontera inicial de ACK.
            node->highest_seq_acked = header.sequence_id;
            should_emit_payload = true;
        } else {
            uint16_t expected_next = static_cast<uint16_t>(node->highest_seq_acked + 1U);
            int16_t seq_delta = static_cast<int16_t>(header.sequence_id - expected_next);

            if (seq_delta == 0) {
                // Camino ideal: paquete exactamente esperado, ACK avanza de forma contigua.
                node->highest_seq_acked = header.sequence_id;
                should_emit_payload = true;
            } else if (seq_delta > 0) {
                // Llego un paquete futuro. Se detecta hueco y NO se avanza ACK para
                // forzar retransmision desde el ultimo contiguo recibido.
                node->lost_packets += static_cast<uint32_t>(seq_delta);
                Serial.print("LOSS,");
                Serial.print(node->node_id);
                Serial.print(",EXPECTED=");
                Serial.print(expected_next);
                Serial.print(",GOT=");
                Serial.println(header.sequence_id);
            }
            // seq_delta < 0: duplicado/retransmision antigua; se ignora payload pero se re-ACKea.
        }

        if (isSequenceNewer(header.sequence_id, node->highest_seq_received)) {
            node->highest_seq_received = header.sequence_id;
        }

        node->received_packets++;
        sendDirectAck(*node, frame.rx_us);

        if (should_emit_payload) {
            emitPayloadCsv(*node, header, frame.payload + DATA_HEADER_SIZE, frame.rx_us);
            node->emitted_packets++;
            pulseRxLed();
        }
    }

    void emitPayloadCsv(const ActiveNodeEntry &node,
                        const DataPacketHeader &header,
                        const uint8_t *payload,
                        uint32_t gateway_rx_us) {
        if (header.sample_encoding == SAMPLE_INT16) {
            Serial.print("DATA_INT16,");
            Serial.print(node.node_id);
            Serial.print(",");
            Serial.print(header.sequence_id);
            Serial.print(",");
            Serial.print(gateway_rx_us);
            Serial.print(",");
            Serial.print(header.node_timestamp_us);

            for (uint16_t i = 0; i < header.sample_count; i++) {
                int16_t value = 0;
                memcpy(&value, payload + (i * sizeof(int16_t)), sizeof(int16_t));
                Serial.print(",");
                Serial.print(value);
            }
            Serial.println();
            return;
        }

        if (header.sample_encoding == SAMPLE_FLOAT32) {
            Serial.print("DATA_FLOAT,");
            Serial.print(node.node_id);
            Serial.print(",");
            Serial.print(header.sequence_id);
            Serial.print(",");
            Serial.print(gateway_rx_us);
            Serial.print(",");
            Serial.print(header.node_timestamp_us);

            for (uint16_t i = 0; i < header.sample_count; i++) {
                float value = 0.0f;
                memcpy(&value, payload + (i * sizeof(float)), sizeof(float));
                Serial.print(",");
                Serial.print(value, 6);
            }
            Serial.println();
        }
    }

    void sendDirectAck(const ActiveNodeEntry &node, uint32_t gateway_rx_us) {
        DirectAckPacket ack = {};
        ack.type = PKT_DIRECT_ACK;
        ack.version = PROTOCOL_VERSION;
        ack.node_id = node.node_id;
        ack.highest_acked_seq = node.highest_seq_acked;
        ack.gateway_rx_us = gateway_rx_us;

        if (!ensurePeerPresent(node.mac)) {
            direct_ack_send_errors_++;
            return;
        }

        esp_err_t err = esp_now_send(node.mac, reinterpret_cast<const uint8_t *>(&ack), sizeof(ack));
        if (err != ESP_OK) {
            direct_ack_send_errors_++;
        }
    }

    void sendBeaconSync() {
        BeaconSyncPacket beacon = {};
        beacon.type = PKT_BEACON_SYNC;
        beacon.version = PROTOCOL_VERSION;
        beacon.active_nodes = active_schedule_count_;
        beacon.cycle_ms = CYCLE_MS;
        beacon.registration_window_ms = REGISTRATION_WINDOW_MS;
        beacon.slot_us = dynamic_slot_us_;
        beacon.slot_guard_us = SLOT_GUARD_US;
        beacon.beacon_sequence = beacon_sequence_++;
        beacon.gateway_time_us = micros();

        for (uint8_t i = 0; i < active_schedule_count_; i++) {
            const ActiveNodeEntry &node = nodes_[schedule_indices_[i]];
            beacon.slot_node_ids[i] = node.node_id;
            beacon.ack_map[i].node_id = node.node_id;
            beacon.ack_map[i].highest_acked_seq = node.highest_seq_acked;
        }

        esp_err_t err = esp_now_send(kBroadcastMac, reinterpret_cast<const uint8_t *>(&beacon), sizeof(beacon));
        if (err != ESP_OK) {
            beacon_send_errors_++;
        }

        Serial.print("BEACON,");
        Serial.print(beacon.beacon_sequence);
        Serial.print(",NODES=");
        Serial.print(beacon.active_nodes);
        Serial.print(",SLOT_US=");
        Serial.print(beacon.slot_us);
        Serial.print(",REG_MS=");
        Serial.print(beacon.registration_window_ms);
        Serial.print(",ACKS=");

        for (uint8_t i = 0; i < active_schedule_count_; i++) {
            if (i > 0) {
                Serial.print(";");
            }
            Serial.print(beacon.ack_map[i].node_id);
            Serial.print(":");
            Serial.print(beacon.ack_map[i].highest_acked_seq);
        }
        Serial.println();
    }

    void printStartupInfo() {
        Serial.println("BOOT,ESP32C3_TDMA_GATEWAY");
        Serial.print("BOOT,MAC,");
        Serial.println(WiFi.macAddress());
        Serial.print("BOOT,CHANNEL,");
        Serial.println(WIFI_CHANNEL);
        Serial.print("BOOT,CYCLE_MS,");
        Serial.println(CYCLE_MS);
        Serial.print("BOOT,REGISTRATION_MS,");
        Serial.println(REGISTRATION_WINDOW_MS);
        Serial.print("BOOT,MAX_NODES,");
        Serial.println(MAX_NODES);
        Serial.println("BOOT,SERIAL_FORMAT,DATA_INT16|DATA_FLOAT,node_id,seq,gw_rx_us,node_ts_us,val1...");
    }

    void printStats(uint32_t now_ms) {
        Serial.println("STATS_BEGIN");
        Serial.print("STATS,STATE,");
        Serial.println(static_cast<uint8_t>(state_));
        Serial.print("STATS,ACTIVE_NODES,");
        Serial.println(active_schedule_count_);
        Serial.print("STATS,SLOT_US,");
        Serial.println(dynamic_slot_us_);
        Serial.print("STATS,RX_OVERRUN,");
        Serial.println(rx_queue_overruns_);
        Serial.print("STATS,BEACON_TX_ERR,");
        Serial.println(beacon_send_errors_);
        Serial.print("STATS,DIRECT_ACK_TX_ERR,");
        Serial.println(direct_ack_send_errors_);

        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (!nodes_[i].in_use) {
                continue;
            }

            char mac_text[18] = {0};
            formatMac(nodes_[i].mac, mac_text, sizeof(mac_text));

            Serial.print("NODE,");
            Serial.print(nodes_[i].node_id);
            Serial.print(",MAC=");
            Serial.print(mac_text);
            Serial.print(",RX=");
            Serial.print(nodes_[i].received_packets);
            Serial.print(",EMIT=");
            Serial.print(nodes_[i].emitted_packets);
            Serial.print(",ACKED=");
            Serial.print(nodes_[i].highest_seq_acked);
            Serial.print(",LOST=");
            Serial.print(nodes_[i].lost_packets);
            Serial.print(",INVALID=");
            Serial.print(nodes_[i].invalid_packets);
            Serial.print(",AGE_MS=");
            Serial.println(now_ms - nodes_[i].last_seen_ms);
        }

        Serial.println("STATS_END");
    }

    void pulseRxLed() {
        digitalWrite(RX_LED, HIGH);
        led_is_on_ = true;
        led_off_deadline_ms_ = millis() + LED_PULSE_MS;
    }

    void serviceLed(uint32_t now_ms) {
        if (led_is_on_ && (int32_t)(now_ms - led_off_deadline_ms_) >= 0) {
            digitalWrite(RX_LED, LOW);
            led_is_on_ = false;
        }
    }

    void pruneInactiveNodes(uint32_t now_ms) {
        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (!nodes_[i].in_use) {
                continue;
            }

            if ((now_ms - nodes_[i].last_seen_ms) > NODE_INACTIVE_TIMEOUT_MS) {
                char mac_text[18] = {0};
                formatMac(nodes_[i].mac, mac_text, sizeof(mac_text));
                Serial.print("NODE_TIMEOUT,");
                Serial.print(nodes_[i].node_id);
                Serial.print(",");
                Serial.println(mac_text);
                memset(&nodes_[i], 0, sizeof(nodes_[i]));
            }
        }
    }

    void rebuildSchedule() {
        active_schedule_count_ = 0;

        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (!nodes_[i].in_use) {
                continue;
            }
            schedule_indices_[active_schedule_count_++] = i;
        }

        // Orden estable por NodeID para que cada nodo tenga una referencia temporal
        // determinista entre ciclos y no dependa del orden de llegada por radio.
        for (uint8_t i = 1; i < active_schedule_count_; i++) {
            uint8_t key = schedule_indices_[i];
            int8_t j = static_cast<int8_t>(i) - 1;
            while (j >= 0 && nodes_[schedule_indices_[j]].node_id > nodes_[key].node_id) {
                schedule_indices_[j + 1] = schedule_indices_[j];
                j--;
            }
            schedule_indices_[j + 1] = key;
        }
    }

    ActiveNodeEntry *findOrCreateNode(const uint8_t *mac, uint8_t node_id) {
        int8_t by_mac = findNodeByMac(mac);
        if (by_mac >= 0) {
            ActiveNodeEntry &node = nodes_[by_mac];
            if (node.node_id != node_id && isValidNodeId(node_id)) {
                int8_t existing_id = findNodeById(node_id);
                if (existing_id < 0 || existing_id == by_mac) {
                    node.node_id = node_id;
                } else {
                    return nullptr;
                }
            }
            return &node;
        }

        if (!isValidNodeId(node_id)) {
            return nullptr;
        }

        if (findNodeById(node_id) >= 0) {
            return nullptr;
        }

        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (nodes_[i].in_use) {
                continue;
            }

            nodes_[i].in_use = true;
            nodes_[i].node_id = node_id;
            memcpy(nodes_[i].mac, mac, 6);
            nodes_[i].last_seen_ms = millis();
            nodes_[i].highest_seq_received = 0;
            nodes_[i].highest_seq_acked = 0;
            nodes_[i].received_packets = 0;
            nodes_[i].emitted_packets = 0;
            nodes_[i].lost_packets = 0;
            nodes_[i].invalid_packets = 0;

            char mac_text[18] = {0};
            formatMac(nodes_[i].mac, mac_text, sizeof(mac_text));
            Serial.print("NODE_JOIN,");
            Serial.print(node_id);
            Serial.print(",");
            Serial.println(mac_text);

            return &nodes_[i];
        }

        return nullptr;
    }

    int8_t findNodeByMac(const uint8_t *mac) {
        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (nodes_[i].in_use && memcmp(nodes_[i].mac, mac, 6) == 0) {
                return static_cast<int8_t>(i);
            }
        }
        return -1;
    }

    int8_t findNodeById(uint8_t node_id) {
        for (uint8_t i = 0; i < MAX_NODES; i++) {
            if (nodes_[i].in_use && nodes_[i].node_id == node_id) {
                return static_cast<int8_t>(i);
            }
        }
        return -1;
    }

    bool addBroadcastPeer() {
        if (esp_now_is_peer_exist(kBroadcastMac)) {
            return true;
        }

        esp_now_peer_info_t peer = {};
        memcpy(peer.peer_addr, kBroadcastMac, 6);
        peer.channel = WIFI_CHANNEL;
        peer.encrypt = false;
        return esp_now_add_peer(&peer) == ESP_OK;
    }

    bool ensurePeerPresent(const uint8_t *mac) {
        if (esp_now_is_peer_exist(mac)) {
            return true;
        }

        esp_now_peer_info_t peer = {};
        memcpy(peer.peer_addr, mac, 6);
        peer.channel = WIFI_CHANNEL;
        peer.encrypt = false;
        return esp_now_add_peer(&peer) == ESP_OK;
    }

    static bool isSequenceNewer(uint16_t candidate, uint16_t reference) {
        return static_cast<int16_t>(candidate - reference) > 0;
    }

    static void formatMac(const uint8_t *mac, char *out, size_t out_size) {
        if (mac == nullptr || out == nullptr || out_size < 18) {
            return;
        }
        snprintf(out,
                 out_size,
                 "%02X:%02X:%02X:%02X:%02X:%02X",
                 mac[0],
                 mac[1],
                 mac[2],
                 mac[3],
                 mac[4],
                 mac[5]);
    }

private:
    SystemState state_ = BROADCASTING_BEACON;

    ActiveNodeEntry nodes_[MAX_NODES] = {};
    uint8_t schedule_indices_[MAX_NODES] = {};
    uint8_t active_schedule_count_ = 0;

    uint16_t dynamic_slot_us_ = 0;
    uint32_t cycle_started_ms_ = 0;
    uint32_t registration_deadline_ms_ = 0;
    uint32_t beacon_sequence_ = 1;
    uint32_t last_stats_ms_ = 0;

    RxFrame rx_queue_[RX_QUEUE_LEN] = {};
    volatile uint8_t rx_head_ = 0;
    volatile uint8_t rx_tail_ = 0;
    volatile uint32_t rx_queue_overruns_ = 0;
    portMUX_TYPE rx_queue_mux_ = portMUX_INITIALIZER_UNLOCKED;

    uint32_t beacon_send_errors_ = 0;
    uint32_t direct_ack_send_errors_ = 0;

    bool led_is_on_ = false;
    uint32_t led_off_deadline_ms_ = 0;
};

TDMAGateway *TDMAGateway::s_instance = nullptr;
static TDMAGateway g_gateway;

void setup() {
    g_gateway.begin();
}

void loop() {
    g_gateway.run();
    delay(0);
}

