// ============================================================
// Nodo remoto ESP32-C3 — Protocolo TDMA v4 / ESP-NOW
// ============================================================
//
// Adquiere muestras de hasta 4 canales a frecuencia configurable.
// Transmite datos al Gateway en slots TDMA round-robin.
//
// Cambios v4:
//   - Multi-canal (NUM_CHANNELS configurable 1-4)
//   - Solo transmite en STATE_ACQUIRING
//   - Envía TIMING_INFO con t0/dt para reconstrucción temporal
//   - RTC sincronizado desde beacon
//   - Burst mode: múltiples paquetes por slot
//   - DataPacket con channel_id + first_sample_index (sin timestamp)
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
#define NODE_ID 1
#define BASESTATION_MAC {0xB8, 0xF8, 0x62, 0x04, 0x5F, 0x98}

#define NUM_CHANNELS 4
#define ACQ_SAMPLE_HZ 100U
#define ACQ_SAMPLE_PERIOD_US (1000000UL / ACQ_SAMPLE_HZ)
#define SAMPLE_RING_CAPACITY 512U  // Per-channel

#define SYNC_TIMEOUT_CYCLES 6U
#define BURST_MAX_PKTS_PER_SLOT 8

// ============================================================
// Estado global
// ============================================================

static uint8_t basestation_mac[6] = BASESTATION_MAC;

// ---- Adquisición ----
static hw_timer_t *acq_timer = nullptr;
static portMUX_TYPE acq_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint32_t pending_ticks = 0;

static int16_t sample_ring[NUM_CHANNELS][SAMPLE_RING_CAPACITY];
static uint32_t produced[NUM_CHANNELS] = {};
static uint32_t sent[NUM_CHANNELS] = {};   // Índice hasta donde se ha enviado
static bool acq_running = false;

// ---- Transmisión ----
static uint16_t next_seq = 1;

// ---- Sincronización TDMA ----
static portMUX_TYPE state_mux = portMUX_INITIALIZER_UNLOCKED;
static bool sync_locked = false;
static uint64_t sync_anchor_us = 0;
static uint64_t last_sync_us = 0;
static uint32_t tdma_cycle_us = 0;
static uint16_t tdma_slot_us = 0;
static uint16_t tdma_guard_us = 0;
static uint8_t slot_schedule[MAX_SLOTS] = {};
static uint8_t system_state_from_gw = STATE_DISCOVERY;
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

// ---- Generación simulada ----
static int16_t sine_lut[256];
static uint16_t sine_phase[NUM_CHANNELS] = {};
static uint32_t prng_state = 0x5A17C3E5u;

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
    // Cada canal tiene una frecuencia diferente para testing
    uint16_t step = 3 + ch * 2;
    sine_phase[ch] = (sine_phase[ch] + step) & 0xFF;
    int32_t sine_v = (int32_t)sine_lut[sine_phase[ch]] * 1200 / 32767;
    int32_t noise = (int32_t)(xorshift32() % 101U) - 50;
    int32_t val = 2048 + sine_v + noise + ch * 200;  // Offset por canal
    if (val < 0) val = 0;
    if (val > 4095) val = 4095;
    return (int16_t)val;
}

// ============================================================
// Adquisición — ISR + tarea
// ============================================================

void IRAM_ATTR onAcqTimerISR() {
    portENTER_CRITICAL_ISR(&acq_mux);
    if (pending_ticks < 10000U) pending_ticks++;
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
            for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
                uint32_t idx = produced[ch] % SAMPLE_RING_CAPACITY;
                sample_ring[ch][idx] = generateSample(ch);
            }
            // Incrementar todos los canales juntos (muestreo simultáneo)
            for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
                produced[ch]++;
            }
        }
    }
}

static void startAcquisition() {
    if (acq_running) return;

    // Registrar t0 para timing info
    acq_t0_epoch_ms = getCurrentEpochMs();
    acq_t0_sample_index = 0;
    for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
        produced[ch] = 0;
        sent[ch] = 0;
    }
    timing_info_sent = false;
    acq_running = true;
    Serial.println("NODE: Adquisicion iniciada");
}

static void stopAcquisition() {
    if (!acq_running) return;
    acq_running = false;
    timing_info_sent = false;
    Serial.println("NODE: Adquisicion detenida");
}

// ============================================================
// Transmisión de paquetes
// ============================================================

static void sendTimingInfo() {
    TimingInfoPacket pkt = {};
    pkt.type = PKT_TIMING_INFO;
    pkt.version = PROTOCOL_VERSION;
    pkt.node_id = NODE_ID;
    pkt.channel_id = 0xFF;  // Aplica a todos los canales
    pkt.sample_rate_hz = ACQ_SAMPLE_HZ;
    pkt.dt_us = ACQ_SAMPLE_PERIOD_US;
    pkt.t0_epoch_ms = acq_t0_epoch_ms;
    pkt.t0_sample_index = acq_t0_sample_index;

    esp_err_t err = esp_now_send(basestation_mac,
                                  (const uint8_t *)&pkt, sizeof(pkt));
    if (err == ESP_OK) {
        timing_info_sent = true;
        last_timing_info_ms = millis();
        Serial.printf("NODE: TX TIMING_INFO rate=%u dt=%lu t0=%llu\n",
                      ACQ_SAMPLE_HZ, (unsigned long)ACQ_SAMPLE_PERIOD_US,
                      (unsigned long long)acq_t0_epoch_ms);
    }
}

static uint8_t sendDataForChannel(uint8_t ch) {
    uint32_t pending = produced[ch] - sent[ch];
    if (pending == 0) return 0;

    uint16_t max_samples = maxSamplesForEncoding(SAMPLE_INT16);
    uint16_t count = (pending > max_samples) ? max_samples : (uint16_t)pending;

    uint8_t buf[ESPNOW_MAX_PAYLOAD_BYTES];

    DataPacketHeader header = {};
    header.type = PKT_DATA;
    header.version = PROTOCOL_VERSION;
    header.node_id = NODE_ID;
    header.channel_id = ch;
    header.sample_encoding = SAMPLE_INT16;
    header.sequence_id = next_seq++;
    header.sample_count = count;
    header.first_sample_index = sent[ch];

    memcpy(buf, &header, DATA_HEADER_SIZE);

    for (uint16_t i = 0; i < count; i++) {
        uint32_t idx = (sent[ch] + i) % SAMPLE_RING_CAPACITY;
        int16_t val = sample_ring[ch][idx];
        memcpy(buf + DATA_HEADER_SIZE + i * sizeof(int16_t), &val, sizeof(int16_t));
    }

    size_t pkt_len = DATA_HEADER_SIZE + count * sizeof(int16_t);
    esp_err_t err = esp_now_send(basestation_mac, buf, pkt_len);

    if (err == ESP_OK) {
        sent[ch] += count;
        return 1;
    }
    return 0;
}

static void transmitBurstInSlot() {
    // 1. Enviar TIMING_INFO si no se ha enviado o toca reenviar
    if (!timing_info_sent ||
        (millis() - last_timing_info_ms) >= TIMING_INFO_INTERVAL_MS) {
        sendTimingInfo();
    }

    // 2. Enviar datos de cada canal (burst)
    uint8_t pkts_sent = 0;
    for (uint8_t round = 0; round < BURST_MAX_PKTS_PER_SLOT && pkts_sent < BURST_MAX_PKTS_PER_SLOT; round++) {
        bool any_sent = false;
        for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
            if (pkts_sent >= BURST_MAX_PKTS_PER_SLOT) break;
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
    hello.node_id = NODE_ID;
    hello.channel_mask = (1U << NUM_CHANNELS) - 1;  // e.g., 0x0F for 4 channels
    hello.channel_count = NUM_CHANNELS;
    hello.flags = 0;
    hello.sample_rate_hz = ACQ_SAMPLE_HZ;

    esp_now_send(basestation_mac, (const uint8_t *)&hello, sizeof(hello));
    Serial.printf("NODE: TX HELLO id=%u ch=%u rate=%u\n",
                  NODE_ID, NUM_CHANNELS, ACQ_SAMPLE_HZ);
}

// ============================================================
// Callbacks ESP-NOW
// ============================================================

static void onDataSent(const uint8_t *mac, esp_now_send_status_t status) {
    (void)mac;
    (void)status;
}

static void onDataRecv(const uint8_t *mac, const uint8_t *data, int len) {
    (void)mac;
    if (len <= 0 || !data) return;

    uint8_t pkt_type = data[0];

    // ---- Direct ACK ----
    if (pkt_type == PKT_DIRECT_ACK && len >= (int)sizeof(DirectAckPacket)) {
        DirectAckPacket ack;
        memcpy(&ack, data, sizeof(ack));
        if (ack.version == PROTOCOL_VERSION && ack.node_id == NODE_ID) {
            // Actualizar estado del sistema desde ACK
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
    memcpy(slot_schedule, beacon.slot_schedule, MAX_SLOTS);
    portEXIT_CRITICAL(&state_mux);

    // Sincronizar RTC desde beacon
    if (beacon.rtc_epoch_ms > 0) {
        rtc_epoch_ms = beacon.rtc_epoch_ms;
        rtc_set_at_us = (uint64_t)esp_timer_get_time();
    }

    Serial.printf("NODE: BEACON state=%u nodes=%u slot_us=%u\n",
                  beacon.system_state, beacon.active_nodes, beacon.slot_us);
}

// ============================================================
// Setup
// ============================================================

void setup() {
    Serial.begin(115200);
    delay(100);

    // Inicializar LUT de seno
    for (int i = 0; i < 256; i++) {
        sine_lut[i] = (int16_t)(sinf(2.0f * PI * (float)i / 256.0f) * 32767.0f);
    }

    WiFi.mode(WIFI_STA);
    delay(100);
    esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

    Serial.println("\n=== Nodo ESP32-C3 TDMA/ESP-NOW v4 ===");
    Serial.printf("NODE: id=%u channels=%u rate=%u Hz\n",
                  NODE_ID, NUM_CHANNELS, ACQ_SAMPLE_HZ);

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

    // Tarea de adquisición
    xTaskCreatePinnedToCore(acquisitionTask, "acq", 4096, nullptr, 3, nullptr, 0);

    // Timer de hardware para adquisición
    acq_timer = timerBegin(0, 80, true);
    timerAttachInterrupt(acq_timer, &onAcqTimerISR, true);
    timerAlarmWrite(acq_timer, ACQ_SAMPLE_PERIOD_US, true);
    timerAlarmEnable(acq_timer);

    Serial.println("NODE: Esperando BEACON...");
}

// ============================================================
// Loop principal
// ============================================================

void loop() {
    uint64_t now_us = (uint64_t)esp_timer_get_time();
    uint32_t now_ms = millis();

    // ---- Leer estado sincronizado ----
    bool local_sync = false;
    uint8_t local_state = STATE_DISCOVERY;
    uint32_t cycle_us = 0;
    uint32_t slot_us_val = 0;
    uint32_t guard_us = 0;
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
        guard_us = tdma_guard_us;
        anchor = sync_anchor_us;
        memcpy(local_schedule, slot_schedule, MAX_SLOTS);
    }
    portEXIT_CRITICAL(&state_mux);

    // ---- Gestionar adquisición según estado ----
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

        // Ventana de registro: enviar HELLO
        uint32_t reg_us = (uint32_t)REGISTRATION_WINDOW_MS * 1000UL;
        if (phase < reg_us) {
            // Enviar HELLO una vez por ciclo
            static uint32_t last_hello_cycle = UINT32_MAX;
            uint32_t cycle_idx = elapsed / cycle_us;
            if (cycle_idx != last_hello_cycle) {
                sendNodeHello();
                last_hello_cycle = cycle_idx;
            }
        }

        // Fase de datos: solo si ACQUIRING
        if (local_state == STATE_ACQUIRING && acq_running) {
            uint32_t data_phase = phase - reg_us;
            uint32_t current_slot = data_phase / slot_us_val;

            if (current_slot < MAX_SLOTS && local_schedule[current_slot] == NODE_ID) {
                // Estamos en nuestro slot — transmitir burst
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

    // ---- Diagnóstico periódico ----
    if ((now_ms - last_diag_ms) >= 3000U) {
        last_diag_ms = now_ms;
        uint32_t total_pending = 0;
        for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
            total_pending += produced[ch] - sent[ch];
        }
        Serial.printf("NODE: sync=%d state=%u acq=%d pending=%lu seq=%u\n",
                      local_sync ? 1 : 0, local_state,
                      acq_running ? 1 : 0,
                      (unsigned long)total_pending, next_seq);
    }

    delay(0);
}