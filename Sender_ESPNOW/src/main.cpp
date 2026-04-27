// ============================================================
// Nodo remoto ESP32-C3 — Protocolo TDMA v4 / ESP-NOW
// ============================================================
//
// Sistema LOSSLESS de adquisición multicanal:
//   - ACK-gated ring buffer: datos solo se liberan al recibir ACK
//   - Retransmisión automática de paquetes no confirmados
//   - Frecuencia configurable desde beacon (CMD_SET_RATE)
//   - Burst mode: múltiples paquetes por slot TDMA
//   - Buffer overflow detection + WARN
// ============================================================

#include <Arduino.h>
#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_timer.h>
#include <esp_system.h>
#include <math.h>
#include <string.h>

#include <tdma_protocol.h>

using namespace tdma;

// ============================================================
// Configuración del nodo (EDITAR PARA CADA NODO)
// ============================================================

#define WIFI_CHANNEL 1
static uint8_t node_id = 0; // Assigned by gateway
#define BASESTATION_MAC {0xB8, 0xF8, 0x62, 0x04, 0x5F, 0x98}

#define NUM_CHANNELS 4
#define DEFAULT_SAMPLE_HZ 1000U
#define SAMPLE_RING_CAPACITY 4096U   // Per-channel (≥1s at 4kHz)
#define SYNC_TIMEOUT_CYCLES 6U
#define BURST_MAX_PKTS_PER_SLOT 12   // Max frames per slot

// ---- Inflight tracking for lossless ----
#define INFLIGHT_CAPACITY 48         // Max unACKed packets

// ============================================================
// Tipos para tracking lossless
// ============================================================

struct InflightEntry {
    uint16_t seq_id;
    uint8_t  channel_id;
    uint32_t first_idx;
    uint16_t count;
    uint32_t tx_time_ms;
};

// ============================================================
// Estado global
// ============================================================

static uint8_t basestation_mac[6] = BASESTATION_MAC;

// ---- Adquisición ----
static esp_timer_handle_t acq_timer = nullptr;
static portMUX_TYPE acq_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint32_t pending_ticks = 0;

static int16_t sample_ring[NUM_CHANNELS][SAMPLE_RING_CAPACITY];
static uint32_t produced[NUM_CHANNELS] = {};
static uint32_t sent[NUM_CHANNELS] = {};
static uint32_t acked[NUM_CHANNELS] = {};  // Lossless: last confirmed index
static bool acq_running = false;

// ---- Rate ----
static uint32_t current_rate_hz = DEFAULT_SAMPLE_HZ;
static uint32_t current_period_us = 1000000UL / DEFAULT_SAMPLE_HZ;

// ---- Inflight tracking (lossless) ----
static InflightEntry inflight_ring[INFLIGHT_CAPACITY];
static uint8_t inflight_head = 0;
static uint8_t inflight_tail = 0;

// ---- Transmisión ----
static uint16_t next_seq = 1;

// ---- Sincronización TDMA ----
static portMUX_TYPE state_mux = portMUX_INITIALIZER_UNLOCKED;
static bool sync_locked = false;
static uint64_t sync_anchor_us = 0;
static uint64_t last_sync_us = 0;
static uint32_t tdma_cycle_us = 0;
static uint32_t tdma_slot_us = 0;
static uint16_t tdma_guard_us = 0;
static uint8_t slot_schedule[MAX_SLOTS] = {};
static uint8_t system_state_from_gw = STATE_DISCOVERY;
static uint16_t beacon_rate_hz = DEFAULT_SAMPLE_HZ;
static bool was_acquiring = false;

// ---- RTC sync ----
static uint64_t rtc_epoch_ms = 0;
static uint64_t rtc_set_at_us = 0;

// ---- Timing info ----
static uint64_t acq_t0_epoch_ms = 0;
static uint32_t acq_t0_sample_index = 0;
static bool timing_info_sent = false;
static uint32_t last_timing_info_ms = 0;

// ---- Diagnóstico ----
static uint32_t last_diag_ms = 0;
static uint32_t overflow_count = 0;

// ---- Generación simulada ----
static int16_t sine_lut[256];
static uint16_t sine_phase[NUM_CHANNELS] = {};
static uint32_t prng_state = 0x5A17C3E5u;

// ---- Telemetry ----
static uint16_t total_tx_errors = 0;

// ============================================================
// Utilidades
// ============================================================

static uint32_t xorshift32() {
    uint32_t x = prng_state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    prng_state = x;
    return x;
}

static uint64_t getCurrentEpochMs() {
    if (rtc_epoch_ms == 0) return 0;
    uint64_t now_us = (uint64_t)esp_timer_get_time();
    return rtc_epoch_ms + ((now_us - rtc_set_at_us) / 1000UL);
}

static int16_t generateSample(uint8_t ch) {
    uint16_t step = 2 + ch; // Diferente frecuencia por canal
    sine_phase[ch] = (sine_phase[ch] + step) & 0xFF;
    
    int32_t val = 2048;
    int32_t amplitude = 1500; // Rango de ADC de 12 bits (0-4095)
    
    switch (ch) {
        case 0: {
            // Canal 0: Onda Senoidal
            int32_t sine_v = (int32_t)sine_lut[sine_phase[ch]] * amplitude / 32767;
            val = 2048 + sine_v;
            break;
        }
        case 1: {
            // Canal 1: Onda Cuadrada
            val = (sine_phase[ch] < 128) ? (2048 + amplitude) : (2048 - amplitude);
            break;
        }
        case 2: {
            // Canal 2: Onda Triangular
            if (sine_phase[ch] < 128) {
                val = 2048 - amplitude + (amplitude * 2 * sine_phase[ch] / 127);
            } else {
                val = 2048 + amplitude - (amplitude * 2 * (sine_phase[ch] - 128) / 127);
            }
            break;
        }
        case 3: {
            // Canal 3: Onda Diente de Sierra (Sawtooth)
            val = 2048 - amplitude + (amplitude * 2 * sine_phase[ch] / 255);
            break;
        }
        default:
            val = 2048;
            break;
    }
    
    // Añadimos un ruido ligero (opcional, para simular señales reales)
    int32_t noise = (int32_t)(xorshift32() % 21U) - 10;
    val += noise;
    
    // Clamping para asegurar que se mantiene en el rango de un ADC de 12 bits
    if (val < 0) val = 0;
    if (val > 4095) val = 4095;
    
    return (int16_t)val;
}

// ============================================================
// Inflight tracking — lossless core
// ============================================================

static uint8_t inflightCount() {
    return (uint8_t)((inflight_head - inflight_tail) % INFLIGHT_CAPACITY);
}

static bool inflightFull() {
    return ((inflight_head + 1) % INFLIGHT_CAPACITY) == inflight_tail;
}

static void inflightRecord(uint16_t seq, uint8_t ch, uint32_t first_idx, uint16_t count) {
    inflight_ring[inflight_head] = {seq, ch, first_idx, count, millis()};
    inflight_head = (inflight_head + 1) % INFLIGHT_CAPACITY;
}

static void inflightProcessAck(uint16_t acked_seq) {
    // Advance acked[] for all inflight entries with seq <= acked_seq
    while (inflight_tail != inflight_head) {
        InflightEntry &e = inflight_ring[inflight_tail];
        // Check if this entry was ACKed (seq <= acked_seq, with wrap-around)
        int16_t delta = (int16_t)(e.seq_id - acked_seq);
        if (delta > 0) break;  // Not yet ACKed

        // This packet confirmed — advance acked pointer for its channel
        uint32_t new_acked = e.first_idx + e.count;
        if (new_acked > acked[e.channel_id]) {
            acked[e.channel_id] = new_acked;
        }
        inflight_tail = (inflight_tail + 1) % INFLIGHT_CAPACITY;
    }
}

static void inflightReset() {
    inflight_head = 0;
    inflight_tail = 0;
}

// ============================================================
// Adquisición — ISR + tarea
// ============================================================

void IRAM_ATTR onAcqTimerISR(void* arg) {
    (void)arg;
    portENTER_CRITICAL_ISR(&acq_mux);
    if (pending_ticks < 50000U) pending_ticks++;
    portEXIT_CRITICAL_ISR(&acq_mux);
}

static void acquisitionTask(void *param) {
    (void)param;
    for (;;) {
        uint32_t ticks = 0;
        portENTER_CRITICAL(&acq_mux);
        ticks = pending_ticks;
        pending_ticks = 0;
        portEXIT_CRITICAL(&acq_mux);

        if (ticks == 0 || !acq_running) {
            vTaskDelay(pdMS_TO_TICKS(1));
            continue;
        }

        for (uint32_t t = 0; t < ticks; t++) {
            // Check for overflow BEFORE writing
            bool overflow = false;
            for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
                if ((produced[ch] - acked[ch]) >= SAMPLE_RING_CAPACITY - 1) {
                    overflow = true;
                    break;
                }
            }
            if (overflow) {
                overflow_count++;
                continue;  // Drop sample — buffer full
            }

            for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
                uint32_t idx = produced[ch] % SAMPLE_RING_CAPACITY;
                sample_ring[ch][idx] = generateSample(ch);
            }
            for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
                produced[ch]++;
            }
        }
    }
}

static void reconfigureTimer(uint32_t new_rate_hz) {
    if (new_rate_hz == current_rate_hz || new_rate_hz == 0) return;
    if (new_rate_hz > 10000) new_rate_hz = 10000;

    current_rate_hz = new_rate_hz;
    current_period_us = 1000000UL / new_rate_hz;

    // esp_timer: stop → re-start con nuevo periodo
    if (acq_timer) {
        esp_timer_stop(acq_timer);
        esp_timer_start_periodic(acq_timer, current_period_us);
    }

    Serial.printf("NODE: Rate reconfigured to %lu Hz (period %lu us)\n",
                  (unsigned long)current_rate_hz, (unsigned long)current_period_us);
}

static void startAcquisition() {
    if (acq_running) return;

    acq_t0_epoch_ms = getCurrentEpochMs();
    acq_t0_sample_index = 0;
    for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
        produced[ch] = 0;
        sent[ch] = 0;
        acked[ch] = 0;
    }
    inflightReset();
    next_seq = 1;
    overflow_count = 0;
    timing_info_sent = false;
    acq_running = true;
    Serial.printf("NODE: Acquisition started at %lu Hz\n", (unsigned long)current_rate_hz);
}

static void stopAcquisition() {
    if (!acq_running) return;
    acq_running = false;
    timing_info_sent = false;
    portENTER_CRITICAL(&acq_mux);
    pending_ticks = 0;
    portEXIT_CRITICAL(&acq_mux);
    Serial.printf("NODE: Acquisition stopped (overflows=%lu)\n",
                  (unsigned long)overflow_count);
}

// ============================================================
// Transmisión de paquetes
// ============================================================

static void sendTimingInfo() {
    TimingInfoPacket pkt = {};
    pkt.type = PKT_TIMING_INFO;
    pkt.version = PROTOCOL_VERSION;
    pkt.node_id = node_id;
    pkt.channel_id = 0xFF;
    pkt.sample_rate_hz = current_rate_hz;
    pkt.dt_us = current_period_us;
    pkt.t0_epoch_ms = acq_t0_epoch_ms;
    pkt.t0_sample_index = acq_t0_sample_index;
    pkt.crc16 = 0;
    pkt.crc16 = crc16_ccitt((const uint8_t *)&pkt, sizeof(pkt));

    esp_err_t err = esp_now_send(basestation_mac,
                                  (const uint8_t *)&pkt, sizeof(pkt));
    if (err == ESP_OK) {
        timing_info_sent = true;
        last_timing_info_ms = millis();
    }
}

static uint8_t sendDataForChannel(uint8_t ch) {
    // Lossless: send from sent[ch], NOT from acked[ch]
    // (acked advances only when gateway confirms)
    uint32_t pending = produced[ch] - sent[ch];
    if (pending == 0) return 0;
    if (inflightFull()) return 0;

    uint16_t count = (pending > maxSamplesForEncoding(SAMPLE_DELTA_8BIT)) 
                   ? maxSamplesForEncoding(SAMPLE_DELTA_8BIT) 
                   : (uint16_t)pending;

    uint8_t encoding = SAMPLE_DELTA_8BIT;
    int16_t prev_val = sample_ring[ch][sent[ch] % SAMPLE_RING_CAPACITY];
    
    for(uint16_t i = 1; i < count; i++) {
        int16_t val = sample_ring[ch][(sent[ch] + i) % SAMPLE_RING_CAPACITY];
        int32_t diff = (int32_t)val - (int32_t)prev_val;
        if(diff < -128 || diff > 127) {
            encoding = SAMPLE_INT16;
            count = (pending > maxSamplesForEncoding(SAMPLE_INT16)) 
                  ? maxSamplesForEncoding(SAMPLE_INT16) 
                  : (uint16_t)pending;
            break;
        }
        prev_val = val;
    }

    uint8_t buf[ESPNOW_MAX_PAYLOAD_BYTES];

    DataPacketHeader header = {};
    header.type = PKT_DATA;
    header.version = PROTOCOL_VERSION;
    header.node_id = node_id;
    header.channel_id = ch;
    header.sample_encoding = encoding;
    header.sequence_id = next_seq;
    header.sample_count = count;
    header.first_sample_index = sent[ch];
    header.crc16 = 0;

    memcpy(buf, &header, DATA_HEADER_SIZE);

    if (encoding == SAMPLE_DELTA_8BIT) {
        int16_t base_val = sample_ring[ch][sent[ch] % SAMPLE_RING_CAPACITY];
        memcpy(buf + DATA_HEADER_SIZE, &base_val, sizeof(int16_t));
        int16_t p_val = base_val;
        for (uint16_t i = 1; i < count; i++) {
            int16_t val = sample_ring[ch][(sent[ch] + i) % SAMPLE_RING_CAPACITY];
            int8_t delta = (int8_t)(val - p_val);
            buf[DATA_HEADER_SIZE + 2 + (i - 1)] = (uint8_t)delta;
            p_val = val;
        }
    } else {
        for (uint16_t i = 0; i < count; i++) {
            int16_t val = sample_ring[ch][(sent[ch] + i) % SAMPLE_RING_CAPACITY];
            memcpy(buf + DATA_HEADER_SIZE + i * sizeof(int16_t), &val, sizeof(int16_t));
        }
    }

    size_t pkt_len = dataPacketExpectedLength(header);
    
    DataPacketHeader* hdr = (DataPacketHeader*)buf;
    hdr->crc16 = crc16_ccitt(buf, pkt_len);
    
    esp_err_t err = esp_now_send(basestation_mac, buf, pkt_len);

    if (err == ESP_OK) {
        // Record in inflight table for ACK tracking
        inflightRecord(next_seq, ch, sent[ch], count);
        sent[ch] += count;
        next_seq++;
        return 1;
    }
    return 0;
}

static void transmitBurstInSlot() {
    // 1. Send TIMING_INFO if needed
    if (!timing_info_sent ||
        (millis() - last_timing_info_ms) >= TIMING_INFO_INTERVAL_MS) {
        sendTimingInfo();
    }

    // 2. ARQ Timeout & Rewind Check
    if (inflightCount() > 0) {
        InflightEntry &oldest = inflight_ring[inflight_tail];
        // Timeout dinámico: ~2 ciclos TDMA (mínimo 200ms)
        uint32_t timeout_ms = (tdma_cycle_us > 0) ? (tdma_cycle_us / 500) : 2000;
        if (timeout_ms < 200) timeout_ms = 200;

        if ((millis() - oldest.tx_time_ms) > timeout_ms) {
            // Timeout! Rebobinar los punteros para retransmitir
            next_seq = oldest.seq_id;
            for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
                sent[ch] = acked[ch];
            }
            inflightReset();
            Serial.printf("NODE: ARQ Rewind! Timeout on seq=%u\n", oldest.seq_id);
        }
    }

    // 3. Burst: send data for each channel round-robin
    uint8_t pkts_sent = 0;
    for (uint8_t round = 0; round < BURST_MAX_PKTS_PER_SLOT; round++) {
        if (pkts_sent >= BURST_MAX_PKTS_PER_SLOT || inflightFull()) break;
        bool any_sent = false;
        for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
            if (pkts_sent >= BURST_MAX_PKTS_PER_SLOT || inflightFull()) break;
            if (produced[ch] > sent[ch]) {
                pkts_sent += sendDataForChannel(ch);
                any_sent = true;
            }
        }
        if (!any_sent) break;
    }
}

static void sendNodeHello() {
    NodeHelloPacket hello = {};
    hello.type = PKT_NODE_HELLO;
    hello.version = PROTOCOL_VERSION;
    hello.node_id = node_id;
    hello.channel_mask = (1U << NUM_CHANNELS) - 1;
    hello.channel_count = NUM_CHANNELS;
    hello.flags = 0;
    hello.sample_rate_hz = (uint16_t)current_rate_hz;

    esp_now_send(basestation_mac, (const uint8_t *)&hello, sizeof(hello));
}

// ============================================================
// Callbacks ESP-NOW
// ============================================================

static void onDataSent(const uint8_t *mac, esp_now_send_status_t status) {
    (void)mac;
    if (status != ESP_NOW_SEND_SUCCESS) {
        total_tx_errors++;
    }
}

static void onDataRecv(const uint8_t *mac, const uint8_t *data, int len) {
    (void)mac;
    if (len <= 0 || !data) return;

    uint8_t pkt_type = data[0];

    if (pkt_type == PKT_DIRECT_ACK && len >= (int)sizeof(DirectAckPacket)) {
        DirectAckPacket ack;
        memcpy(&ack, data, sizeof(ack));
        if (ack.version == PROTOCOL_VERSION && ack.node_id == node_id) {
            // LOSSLESS: process ACK to advance acked[] pointers
            inflightProcessAck(ack.highest_acked_seq);

            portENTER_CRITICAL(&state_mux);
            system_state_from_gw = ack.system_state;
            portEXIT_CRITICAL(&state_mux);
        }
        return;
    }

    // ---- Join ACK ----
    if (pkt_type == PKT_JOIN_ACK && len >= (int)sizeof(JoinAckPacket)) {
        JoinAckPacket ack;
        memcpy(&ack, data, sizeof(ack));
        if (ack.version == PROTOCOL_VERSION) {
            node_id = ack.assigned_node_id;
            Serial.printf("NODE: Assigned ID = %u\n", node_id);
            portENTER_CRITICAL(&state_mux);
            system_state_from_gw = ack.system_state;
            portEXIT_CRITICAL(&state_mux);
        }
        return;
    }

    // ---- Beacon Sync ----
    if (pkt_type != PKT_BEACON_SYNC || len < (int)sizeof(BeaconSyncPacket)) return;

    BeaconSyncPacket beacon;
    memcpy(&beacon, data, sizeof(beacon));
    if (beacon.version != PROTOCOL_VERSION) return;

    uint32_t cycle_us = (uint32_t)beacon.cycle_ms * 1000UL;
    if (cycle_us == 0 || beacon.slot_us == 0) return;

    portENTER_CRITICAL(&state_mux);
    sync_locked = true;
    sync_anchor_us = (uint64_t)esp_timer_get_time();
    last_sync_us = sync_anchor_us;
    tdma_cycle_us = cycle_us;
    tdma_slot_us = beacon.slot_us;
    tdma_guard_us = beacon.slot_guard_us;
    system_state_from_gw = beacon.system_state;
    beacon_rate_hz = beacon.sample_rate_hz;
    memcpy(slot_schedule, beacon.slot_schedule, MAX_SLOTS);
    portEXIT_CRITICAL(&state_mux);

    // RTC sync
    if (beacon.rtc_epoch_ms > 0) {
        rtc_epoch_ms = beacon.rtc_epoch_ms;
        rtc_set_at_us = (uint64_t)esp_timer_get_time();
    }

    // Dynamic rate from beacon (also process ACKs from beacon)
    if (beacon.sample_rate_hz > 0 && beacon.sample_rate_hz != current_rate_hz) {
        reconfigureTimer(beacon.sample_rate_hz);
    }

    // Process beacon ACKs too
    for (uint8_t i = 0; i < beacon.active_nodes; i++) {
        if (beacon.ack_map[i].node_id == node_id) {
            inflightProcessAck(beacon.ack_map[i].highest_acked_seq);
            break;
        }
    }
}

// ============================================================
// Setup
// ============================================================

void setup() {
    Serial.begin(115200);
    delay(100);

    for (int i = 0; i < 256; i++) {
        sine_lut[i] = (int16_t)(sinf(2.0f * PI * (float)i / 256.0f) * 32767.0f);
    }

    WiFi.mode(WIFI_STA);
    delay(100);
    esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

    Serial.printf("\n=== Nodo ESP32-C3 TDMA/ESP-NOW v4 LOSSLESS ===\n");
    Serial.printf("NODE: ch=%u rate=%lu Hz ring=%u\n",
                  NUM_CHANNELS,
                  (unsigned long)current_rate_hz, SAMPLE_RING_CAPACITY);

    if (esp_now_init() != ESP_OK) {
        Serial.println("NODE: FATAL ESP-NOW init");
        while (true) delay(1000);
    }

    esp_now_register_recv_cb(onDataRecv);
    esp_now_register_send_cb(onDataSent);

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, basestation_mac, 6);
    peer.channel = WIFI_CHANNEL;
    peer.encrypt = false;
    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("NODE: FATAL add peer");
        while (true) delay(1000);
    }

    xTaskCreatePinnedToCore(acquisitionTask, "acq", 4096, nullptr, 3, nullptr, 0);

    // ---- Configurar timer de adquisición con esp_timer (estable en todas las versiones) ----
    const esp_timer_create_args_t timer_args = {
        .callback = &onAcqTimerISR,
        .arg = nullptr,
        .dispatch_method = ESP_TIMER_TASK,  // ISR context
        .name = "acq_timer",
        .skip_unhandled_events = true,
    };
    esp_timer_create(&timer_args, &acq_timer);
    esp_timer_start_periodic(acq_timer, current_period_us);

    Serial.println("NODE: Waiting for BEACON...");
}

// ============================================================
// Loop principal
// ============================================================

void loop() {
    uint64_t now_us = (uint64_t)esp_timer_get_time();
    uint32_t now_ms = millis();

    // ---- Read synchronized state ----
    bool local_sync = false;
    uint8_t local_state = STATE_DISCOVERY;
    uint32_t cycle_us = 0;
    uint32_t slot_us_val = 0;
    uint64_t anchor = 0;
    uint8_t local_schedule[MAX_SLOTS];

    portENTER_CRITICAL(&state_mux);
    local_sync = sync_locked;
    local_state = system_state_from_gw;

    if (sync_locked && tdma_cycle_us > 0) {
        uint64_t timeout_us = (uint64_t)tdma_cycle_us * SYNC_TIMEOUT_CYCLES;
        if ((now_us - last_sync_us) > timeout_us) {
            sync_locked = false;
            local_sync = false;
        }
    }

    if (sync_locked) {
        cycle_us = tdma_cycle_us;
        slot_us_val = tdma_slot_us;
        anchor = sync_anchor_us;
        memcpy(local_schedule, slot_schedule, MAX_SLOTS);
    }
    portEXIT_CRITICAL(&state_mux);

    // ---- Acquisition state management ----
    if (local_state == STATE_ACQUIRING && !was_acquiring) {
        startAcquisition();
        was_acquiring = true;
    } else if (local_state != STATE_ACQUIRING && was_acquiring) {
        stopAcquisition();
        was_acquiring = false;
    }

    // ---- TDMA scheduling ----
    if (local_sync && cycle_us > 0 && slot_us_val > 0) {
        uint32_t elapsed = (uint32_t)(now_us - anchor);
        uint32_t phase = elapsed % cycle_us;
        uint32_t reg_us = (uint32_t)REGISTRATION_WINDOW_MS * 1000UL;

        // Registration window: send HELLO
        if (phase < reg_us) {
            static uint32_t last_hello_cycle = UINT32_MAX;
            uint32_t cycle_idx = elapsed / cycle_us;
            if (cycle_idx != last_hello_cycle) {
                if (local_state != STATE_ACQUIRING) {
                    sendNodeHello();
                }
                last_hello_cycle = cycle_idx;
            }
        }

        // Data phase: only if ACQUIRING
        if (local_state == STATE_ACQUIRING && acq_running && phase >= reg_us) {
            uint32_t data_phase = phase - reg_us;
            uint32_t current_slot = data_phase / slot_us_val;

            if (current_slot < MAX_SLOTS && local_schedule[current_slot] == node_id && node_id != 0) {
                static uint32_t last_tx_slot = UINT32_MAX;
                uint32_t cycle_idx = elapsed / cycle_us;
                uint32_t slot_key = cycle_idx * MAX_SLOTS + current_slot;

                if (slot_key != last_tx_slot) {
                    last_tx_slot = slot_key;
                    transmitBurstInSlot();
                }
            }
        }
    }

    // ---- Diagnostics ----
    if ((now_ms - last_diag_ms) >= 3000U) {
        last_diag_ms = now_ms;
        uint32_t total_pending = 0;
        uint32_t total_unacked = 0;
        for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
            total_pending += produced[ch] - sent[ch];
            total_unacked += sent[ch] - acked[ch];
        }
        Serial.printf("NODE: sync=%d state=%u acq=%d rate=%lu pending=%lu unacked=%lu inflight=%u ovf=%lu\n",
                      local_sync ? 1 : 0, local_state,
                      acq_running ? 1 : 0,
                      (unsigned long)current_rate_hz,
                      (unsigned long)total_pending,
                      (unsigned long)total_unacked,
                      inflightCount(),
                      (unsigned long)overflow_count);

        // Buffer warning
        uint8_t max_usage_pct = 0;
        for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
            uint32_t usage = produced[ch] - acked[ch];
            uint8_t pct = (usage * 100) / SAMPLE_RING_CAPACITY;
            if (pct > max_usage_pct) max_usage_pct = pct;
            
            if (usage > SAMPLE_RING_CAPACITY * 90 / 100) {
                Serial.printf("NODE: WARN ch%u buffer %lu/%u (%.0f%%)\n",
                              ch, (unsigned long)usage, SAMPLE_RING_CAPACITY,
                              100.0f * usage / SAMPLE_RING_CAPACITY);
            }
        }
        
        if (node_id > 0) {
            NodeTelemetryPacket tel = {};
            tel.type = PKT_NODE_TELEMETRY;
            tel.version = PROTOCOL_VERSION;
            tel.node_id = node_id;
            tel.flags = 0;
            tel.rssi_dbm = 0; // Not available in ESP-NOW recv cb in IDF v4
            tel.battery_pct = 100;
            tel.temperature_c = 40;
            tel.buffer_usage_pct = max_usage_pct;
            tel.overflow_count = (uint16_t)(overflow_count > 65535 ? 65535 : overflow_count);
            tel.tx_errors = total_tx_errors;
            tel.uptime_s = now_ms / 1000;
            esp_now_send(basestation_mac, (const uint8_t *)&tel, sizeof(tel));
        }
    }

    delay(0);
}