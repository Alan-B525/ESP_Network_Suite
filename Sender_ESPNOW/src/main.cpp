// ============================================================
// Nodo remoto ESP32-C3 — Protocolo TDMA v3 / ESP-NOW
// ============================================================
//
// Adquiere muestras simuladas (senoidal + ruido) a 100 Hz via
// hardware timer ISR, las almacena en un ring buffer, y las
// transmite a la Base Station en su slot TDMA asignado.
//
// Protocolo v3:
//   PKT_BEACON_SYNC (0x11) — recibido del gateway (broadcast)
//   PKT_NODE_HELLO  (0x12) — enviado para registrarse
//   PKT_DATA        (0x13) — enviado con muestras int16
//   PKT_DIRECT_ACK  (0x14) — recibido del gateway (unicast)
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
// Configuracion del nodo
// ============================================================

#define WIFI_CHANNEL 1
#define NODE_ID 1
#define BASESTATION_MAC {0xB8, 0xF8, 0x62, 0x04, 0x5F, 0x98}

#define ACQ_SAMPLE_HZ 100U
#define ACQ_SAMPLE_PERIOD_US (1000000UL / ACQ_SAMPLE_HZ)
#define SAMPLE_RING_CAPACITY 2048U

#define SYNC_TIMEOUT_CYCLES 6U

// Maximo de muestras int16 que caben en un paquete ESP-NOW v3
// (250 - sizeof(DataPacketHeader)) / sizeof(int16_t)
#define MAX_SAMPLES_PER_PKT ((ESPNOW_MAX_PAYLOAD_BYTES - DATA_HEADER_SIZE) / sizeof(int16_t))

// ============================================================
// Tipos locales
// ============================================================

typedef struct __attribute__((packed)) {
    uint32_t ts_local_us;
    uint16_t value;
} AcqSample;

typedef struct {
    bool active;
    uint16_t seq;
    uint64_t start_sample_index;
    uint8_t sample_count;
    uint8_t retries;
    uint8_t packet_buf[ESPNOW_MAX_PAYLOAD_BYTES];
    size_t packet_len;
} InflightPacket;

// ============================================================
// Estado global
// ============================================================

static uint8_t basestation_mac[6] = BASESTATION_MAC;

// ---- Adquisicion ----
static hw_timer_t *acq_timer = nullptr;
static portMUX_TYPE acq_isr_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint32_t pending_acq_ticks = 0;
static volatile uint32_t lost_acq_ticks = 0;

static portMUX_TYPE state_mux = portMUX_INITIALIZER_UNLOCKED;

static AcqSample sample_ring[SAMPLE_RING_CAPACITY] = {};
static uint64_t produced_samples = 0;
static uint64_t acked_samples = 0;
static uint64_t dropped_samples = 0;

// ---- Transmision ----
static InflightPacket inflight = {};
static uint16_t next_data_seq = 1;

// ---- Sincronizacion TDMA ----
static bool sync_locked = false;
static uint64_t sync_anchor_local_us = 0;
static uint64_t last_sync_rx_local_us = 0;
static uint32_t tdma_cycle_us = 0;      // cycle_ms * 1000
static uint16_t tdma_slot_us = 0;
static uint16_t tdma_guard_us = 0;
static uint8_t tdma_node_count = 0;
static uint16_t tdma_slot_index = 0;

// ---- Registro ----
static bool registration_done = false;
static uint16_t hello_seq = 1;
static uint32_t boot_nonce = 0;

// ---- Diagnostico ----
static uint32_t last_data_tx_cycle = UINT32_MAX;
static uint32_t last_hello_tx_cycle = UINT32_MAX;
static uint32_t last_diag_ms = 0;

// ---- Datos simulados ----
static int16_t sine_lut[256] = {};
static uint16_t sine_phase = 0;
static uint32_t prng_state = 0x5A17C3E5u;
static uint32_t acq_local_clock_us = 0;

// ============================================================
// Utilidades
// ============================================================

static inline uint32_t min_u32(uint32_t a, uint32_t b) {
    return (a < b) ? a : b;
}

static uint32_t xorshift32() {
    uint32_t x = prng_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    prng_state = x;
    return x;
}

static uint16_t generateSimulatedSample() {
    sine_phase = (uint16_t)((sine_phase + 5U) & 0x00FFU);

    int32_t sine_component = (int32_t)sine_lut[sine_phase] * 1200 / 32767;
    int32_t noise_component = (int32_t)(xorshift32() % 121U) - 60;
    int32_t value = 2048 + sine_component + noise_component;

    if (value < 0) {
        value = 0;
    } else if (value > 4095) {
        value = 4095;
    }

    return (uint16_t)value;
}

// ============================================================
// Adquisicion — ISR + tarea FreeRTOS
// ============================================================

void IRAM_ATTR onAcqTimerISR() {
    portENTER_CRITICAL_ISR(&acq_isr_mux);
    if (pending_acq_ticks < 10000U) {
        pending_acq_ticks++;
    } else {
        lost_acq_ticks++;
    }
    portEXIT_CRITICAL_ISR(&acq_isr_mux);
}

static void acquisitionTask(void *param) {
    (void)param;

    for (;;) {
        uint32_t ticks_to_process = 0;
        uint32_t lost_ticks = 0;

        portENTER_CRITICAL(&acq_isr_mux);
        ticks_to_process = pending_acq_ticks;
        pending_acq_ticks = 0;
        lost_ticks = lost_acq_ticks;
        lost_acq_ticks = 0;
        portEXIT_CRITICAL(&acq_isr_mux);

        if (lost_ticks > 0) {
            portENTER_CRITICAL(&state_mux);
            dropped_samples += lost_ticks;
            portEXIT_CRITICAL(&state_mux);
        }

        if (ticks_to_process == 0) {
            vTaskDelay(pdMS_TO_TICKS(1));
            continue;
        }

        for (uint32_t i = 0; i < ticks_to_process; i++) {
            AcqSample sample;
            acq_local_clock_us += ACQ_SAMPLE_PERIOD_US;
            sample.ts_local_us = acq_local_clock_us;
            sample.value = generateSimulatedSample();

            portENTER_CRITICAL(&state_mux);
            uint64_t queued = produced_samples - acked_samples;
            if (queued < SAMPLE_RING_CAPACITY) {
                sample_ring[(uint32_t)(produced_samples % SAMPLE_RING_CAPACITY)] = sample;
                produced_samples++;
            } else {
                dropped_samples++;
            }
            portEXIT_CRITICAL(&state_mux);
        }
    }
}

// ============================================================
// Ventana TDMA
// ============================================================

static bool isInsideWindow(uint32_t phase_us, uint32_t start_us, uint32_t length_us, uint32_t cycle_us) {
    if (cycle_us == 0 || length_us == 0 || start_us >= cycle_us) {
        return false;
    }

    uint32_t end_us = start_us + length_us;
    if (end_us <= cycle_us) {
        return (phase_us >= start_us) && (phase_us < end_us);
    }

    uint32_t wrapped_end = end_us % cycle_us;
    return (phase_us >= start_us) || (phase_us < wrapped_end);
}

// ============================================================
// ACK handling
// ============================================================

static void clearInflightAndAckLocked() {
    acked_samples = inflight.start_sample_index + inflight.sample_count;
    inflight.active = false;
    inflight.sample_count = 0;
    inflight.retries = 0;
    inflight.packet_len = 0;
}

static void applyAck(uint16_t ack_seq, const char *source_tag) {
    bool acked = false;
    uint64_t queued_after = 0;

    portENTER_CRITICAL(&state_mux);
    if (inflight.active && inflight.seq == ack_seq) {
        clearInflightAndAckLocked();
        acked = true;
    }
    queued_after = produced_samples - acked_samples;
    portEXIT_CRITICAL(&state_mux);

    if (acked) {
        Serial.printf("NODE: ACK confirmado (%s) seq=%u, cola=%llu\n",
                      source_tag,
                      ack_seq,
                      (unsigned long long)queued_after);
    }
}

// ============================================================
// Construccion y transmision de paquetes v3
// ============================================================

static bool ensureInflightPacket() {
    bool packet_ready = false;

    portENTER_CRITICAL(&state_mux);
    if (inflight.active) {
        packet_ready = true;
    } else {
        uint64_t queued = produced_samples - acked_samples;
        if (queued > 0) {
            uint16_t count = (uint16_t)min_u32((uint32_t)queued, (uint32_t)MAX_SAMPLES_PER_PKT);
            uint64_t start_index = acked_samples;

            // Construir DataPacketHeader
            DataPacketHeader header;
            memset(&header, 0, sizeof(header));
            header.type = PKT_DATA;
            header.version = PROTOCOL_VERSION;
            header.node_id = NODE_ID;
            header.sample_encoding = SAMPLE_INT16;
            header.sequence_id = next_data_seq++;
            header.sample_count = count;

            // Timestamp de la primera muestra
            const AcqSample &first = sample_ring[(uint32_t)(start_index % SAMPLE_RING_CAPACITY)];
            header.node_timestamp_us = first.ts_local_us;

            // Copiar header al buffer
            memcpy(inflight.packet_buf, &header, DATA_HEADER_SIZE);

            // Copiar samples como int16_t al buffer despues del header
            for (uint16_t i = 0; i < count; i++) {
                uint64_t absolute_index = start_index + i;
                const AcqSample &sample = sample_ring[(uint32_t)(absolute_index % SAMPLE_RING_CAPACITY)];
                int16_t val = (int16_t)sample.value;
                memcpy(inflight.packet_buf + DATA_HEADER_SIZE + (i * sizeof(int16_t)),
                       &val, sizeof(int16_t));
            }

            inflight.active = true;
            inflight.seq = header.sequence_id;
            inflight.start_sample_index = start_index;
            inflight.sample_count = (uint8_t)count;
            inflight.retries = 0;
            inflight.packet_len = DATA_HEADER_SIZE + ((size_t)count * sizeof(int16_t));
            packet_ready = true;
        }
    }
    portEXIT_CRITICAL(&state_mux);

    return packet_ready;
}

static void transmitInflightPacket(uint32_t cycle_index) {
    uint8_t packet_copy[ESPNOW_MAX_PAYLOAD_BYTES];
    size_t packet_len = 0;
    uint16_t seq = 0;
    bool have_inflight = false;
    uint8_t sample_count = 0;

    portENTER_CRITICAL(&state_mux);
    if (inflight.active) {
        memcpy(packet_copy, inflight.packet_buf, inflight.packet_len);
        packet_len = inflight.packet_len;
        seq = inflight.seq;
        sample_count = inflight.sample_count;
        have_inflight = true;
    }
    last_data_tx_cycle = cycle_index;
    portEXIT_CRITICAL(&state_mux);

    if (!have_inflight) {
        return;
    }

    esp_err_t send_result = esp_now_send(basestation_mac, packet_copy, packet_len);
    if (send_result == ESP_OK) {
        uint8_t retries = 0;
        uint64_t queued = 0;

        portENTER_CRITICAL(&state_mux);
        if (inflight.active && inflight.seq == seq) {
            inflight.retries++;
            retries = inflight.retries;
        }
        queued = produced_samples - acked_samples;
        portEXIT_CRITICAL(&state_mux);

        Serial.printf("NODE: TX DATA seq=%u samples=%u len=%u retry=%u cola=%llu\n",
                      seq,
                      sample_count,
                      (unsigned int)packet_len,
                      retries,
                      (unsigned long long)queued);
    } else {
        Serial.printf("NODE: error TX DATA seq=%u err=%d\n", seq, (int)send_result);
    }
}

// ============================================================
// NODE_HELLO (registro con el gateway)
// ============================================================

static void transmitNodeHello(uint32_t cycle_index) {
    NodeHelloPacket hello;
    memset(&hello, 0, sizeof(hello));
    hello.type = PKT_NODE_HELLO;
    hello.version = PROTOCOL_VERSION;
    hello.node_id = NODE_ID;
    hello.flags = 0;

    portENTER_CRITICAL(&state_mux);
    last_hello_tx_cycle = cycle_index;
    portEXIT_CRITICAL(&state_mux);

    esp_err_t send_result = esp_now_send(basestation_mac, (const uint8_t *)&hello, sizeof(hello));
    if (send_result == ESP_OK) {
        Serial.printf("NODE: TX NODE_HELLO id=%u seq=%u\n", NODE_ID, hello_seq++);
    } else {
        Serial.printf("NODE: error TX NODE_HELLO err=%d\n", (int)send_result);
    }
}

// ============================================================
// Callbacks ESP-NOW
// ============================================================

static void onDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
    (void)mac_addr;
    if (status != ESP_NOW_SEND_SUCCESS) {
        Serial.println("NODE: nivel MAC reporta envio fallido");
    }
}

#if defined(ESP_IDF_VERSION_MAJOR) && (ESP_IDF_VERSION_MAJOR >= 5)
static void onDataRecv(const esp_now_recv_info_t *recv_info, const uint8_t *incomingData, int len)
#else
static void onDataRecv(const uint8_t *mac, const uint8_t *incomingData, int len)
#endif
{
#if defined(ESP_IDF_VERSION_MAJOR) && (ESP_IDF_VERSION_MAJOR >= 5)
    (void)recv_info;
#else
    (void)mac;
#endif

    if (len <= 0 || incomingData == nullptr) {
        return;
    }

    const uint8_t packet_type = incomingData[0];

    // ---- DirectAckPacket (unicast del gateway) ----
    if (packet_type == PKT_DIRECT_ACK) {
        if (len < (int)sizeof(DirectAckPacket)) {
            return;
        }

        DirectAckPacket ack;
        memcpy(&ack, incomingData, sizeof(ack));

        if (ack.version != PROTOCOL_VERSION || ack.node_id != NODE_ID) {
            return;
        }

        applyAck(ack.highest_acked_seq, "direct_ack");
        return;
    }

    // ---- BeaconSyncPacket (broadcast del gateway) ----
    if (packet_type != PKT_BEACON_SYNC || len < (int)sizeof(BeaconSyncPacket)) {
        return;
    }

    BeaconSyncPacket beacon;
    memcpy(&beacon, incomingData, sizeof(beacon));

    if (beacon.version != PROTOCOL_VERSION) {
        return;
    }

    // Convertir cycle_ms a microsegundos
    uint32_t cycle_us = (uint32_t)beacon.cycle_ms * 1000UL;
    if (cycle_us == 0 || beacon.slot_us == 0) {
        return;
    }

    // Buscar nuestro slot en slot_node_ids[]
    uint16_t my_slot = 0;
    bool slot_found = false;
    for (uint8_t i = 0; i < beacon.active_nodes && i < MAX_NODES; i++) {
        if (beacon.slot_node_ids[i] == NODE_ID) {
            my_slot = i;
            slot_found = true;
            break;
        }
    }

    // Buscar ACK para nuestro nodo en ack_map[]
    bool beacon_ack_valid = false;
    uint16_t beacon_ack_seq = 0;
    for (uint8_t i = 0; i < beacon.active_nodes && i < MAX_NODES; i++) {
        if (beacon.ack_map[i].node_id == NODE_ID) {
            beacon_ack_valid = true;
            beacon_ack_seq = beacon.ack_map[i].highest_acked_seq;
            break;
        }
    }

    portENTER_CRITICAL(&state_mux);
    sync_locked = true;
    sync_anchor_local_us = (uint64_t)esp_timer_get_time();
    last_sync_rx_local_us = sync_anchor_local_us;
    tdma_cycle_us = cycle_us;
    tdma_slot_us = beacon.slot_us;
    tdma_guard_us = beacon.slot_guard_us;
    tdma_node_count = beacon.active_nodes;

    if (slot_found) {
        // Slot asignado: ya estamos registrados
        tdma_slot_index = my_slot;
        registration_done = true;
    } else {
        // No estamos en el schedule: necesitamos enviar NODE_HELLO
        // Usar slot por defecto mientras nos registran
        tdma_slot_index = (NODE_ID > 0) ? (NODE_ID - 1U) : 0U;
        if (tdma_node_count > 0 && tdma_slot_index >= tdma_node_count) {
            tdma_slot_index = (uint16_t)(tdma_node_count);
        }
        registration_done = false;
    }
    portEXIT_CRITICAL(&state_mux);

    // Aplicar ACK del beacon fuera de la seccion critica
    if (beacon_ack_valid) {
        applyAck(beacon_ack_seq, "beacon");
    }

    Serial.printf("NODE: BEACON rx cycle_ms=%u slot_us=%u guard=%u nodes=%u my_slot=%u found=%s\n",
                  beacon.cycle_ms,
                  beacon.slot_us,
                  beacon.slot_guard_us,
                  beacon.active_nodes,
                  my_slot,
                  slot_found ? "yes" : "no");
}

// ============================================================
// Setup
// ============================================================

static void setupAcquisitionTimer() {
    acq_timer = timerBegin(0, 80, true);
    if (acq_timer == nullptr) {
        Serial.println("NODE: no se pudo crear hardware timer");
        while (true) {
            delay(1000);
        }
    }

    timerAttachInterrupt(acq_timer, &onAcqTimerISR, true);
    timerAlarmWrite(acq_timer, ACQ_SAMPLE_PERIOD_US, true);
    timerAlarmEnable(acq_timer);
}

void setup() {
    Serial.begin(115200);

    boot_nonce = esp_random();

    for (size_t i = 0; i < 256U; i++) {
        float angle = (2.0f * PI * (float)i) / 256.0f;
        sine_lut[i] = (int16_t)(sinf(angle) * 32767.0f);
    }

    WiFi.mode(WIFI_STA);
    delay(100);
    esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);

    Serial.println("\n=== Nodo remoto ESP32-C3 TDMA/ESP-NOW v3 ===");
    Serial.printf("NODE: id=%u, sample_hz=%u, max_samples_pkt=%u, protocol_v=%u\n",
                  NODE_ID,
                  ACQ_SAMPLE_HZ,
                  (unsigned int)MAX_SAMPLES_PER_PKT,
                  PROTOCOL_VERSION);

    if (esp_now_init() != ESP_OK) {
        Serial.println("NODE: error inicializando ESP-NOW");
        while (true) {
            delay(1000);
        }
    }

    esp_now_register_recv_cb(onDataRecv);
    esp_now_register_send_cb(onDataSent);

    esp_now_peer_info_t peer_info = {};
    memcpy(peer_info.peer_addr, basestation_mac, 6);
    peer_info.channel = WIFI_CHANNEL;
    peer_info.encrypt = false;

    if (esp_now_add_peer(&peer_info) != ESP_OK) {
        Serial.println("NODE: error agregando peer base station");
        while (true) {
            delay(1000);
        }
    }

    BaseType_t task_ok = xTaskCreatePinnedToCore(
        acquisitionTask,
        "acq_task",
        4096,
        nullptr,
        3,
        nullptr,
        0);

    if (task_ok != pdPASS) {
        Serial.println("NODE: no se pudo crear tarea de adquisicion");
        while (true) {
            delay(1000);
        }
    }

    setupAcquisitionTimer();

    Serial.println("NODE: adquisicion activa, esperando BEACON...");
}

// ============================================================
// Loop principal
// ============================================================

static void printDiagIfNeeded() {
    uint32_t now_ms = millis();
    if ((uint32_t)(now_ms - last_diag_ms) < 2000U) {
        return;
    }
    last_diag_ms = now_ms;

    bool local_sync_locked;
    bool local_registered;
    bool local_inflight;
    uint64_t local_queued;
    uint64_t local_dropped;
    uint16_t local_inflight_seq;

    portENTER_CRITICAL(&state_mux);
    local_sync_locked = sync_locked;
    local_registered = registration_done;
    local_inflight = inflight.active;
    local_inflight_seq = inflight.seq;
    local_queued = produced_samples - acked_samples;
    local_dropped = dropped_samples;
    portEXIT_CRITICAL(&state_mux);

    Serial.printf("NODE: estado sync=%d reg=%d inflight=%d seq=%u cola=%llu drop=%llu\n",
                  local_sync_locked ? 1 : 0,
                  local_registered ? 1 : 0,
                  local_inflight ? 1 : 0,
                  local_inflight_seq,
                  (unsigned long long)local_queued,
                  (unsigned long long)local_dropped);
}

void loop() {
    uint64_t now_us = (uint64_t)esp_timer_get_time();
    bool sync_expired_now = false;

    bool can_schedule = false;
    bool local_reg_done = false;
    uint32_t cycle_us = 0;
    uint32_t slot_us = 0;
    uint32_t guard_us = 0;
    uint32_t slot_index = 0;
    uint64_t sync_anchor = 0;

    portENTER_CRITICAL(&state_mux);
    if (sync_locked && tdma_cycle_us > 0) {
        uint64_t timeout_us = (uint64_t)tdma_cycle_us * SYNC_TIMEOUT_CYCLES;
        if (timeout_us == 0 || (now_us - last_sync_rx_local_us) > timeout_us) {
            sync_locked = false;
            sync_expired_now = true;
        }
    }

    if (sync_locked && tdma_cycle_us > 0 && tdma_slot_us > 0) {
        can_schedule = true;
        cycle_us = tdma_cycle_us;
        slot_us = tdma_slot_us;
        guard_us = tdma_guard_us;
        slot_index = tdma_slot_index;
        local_reg_done = registration_done;
        sync_anchor = sync_anchor_local_us;
    }
    portEXIT_CRITICAL(&state_mux);

    if (sync_expired_now) {
        Serial.println("NODE: sync expirado, solo escucha y buffering");
    }

    if (can_schedule) {
        uint32_t elapsed_us = (uint32_t)(now_us - sync_anchor);
        uint32_t phase_us = (cycle_us > 0) ? (elapsed_us % cycle_us) : 0;
        uint32_t cycle_index = (cycle_us > 0) ? (elapsed_us / cycle_us) : 0;

        if (!local_reg_done) {
            // Enviar NODE_HELLO en la ventana de registro (inicio del ciclo)
            uint32_t reg_window_us = (uint32_t)REGISTRATION_WINDOW_MS * 1000UL;
            bool in_reg_window = isInsideWindow(phase_us, 0, reg_window_us, cycle_us);
            if (in_reg_window) {
                bool do_hello = false;
                portENTER_CRITICAL(&state_mux);
                do_hello = (cycle_index != last_hello_tx_cycle);
                portEXIT_CRITICAL(&state_mux);

                if (do_hello) {
                    transmitNodeHello(cycle_index);
                }
            }
        }

        if (local_reg_done) {
            // Calcular ventana de slot con offset por registro
            uint32_t reg_offset_us = (uint32_t)REGISTRATION_WINDOW_MS * 1000UL;
            uint32_t tx_start = reg_offset_us + slot_index * slot_us + (guard_us / 2U);
            uint32_t tx_len = (slot_us > guard_us) ? (slot_us - guard_us) : slot_us;

            if (isInsideWindow(phase_us, tx_start, tx_len, cycle_us)) {
                bool already_sent_this_cycle = false;
                portENTER_CRITICAL(&state_mux);
                already_sent_this_cycle = (cycle_index == last_data_tx_cycle);
                portEXIT_CRITICAL(&state_mux);

                if (!already_sent_this_cycle && ensureInflightPacket()) {
                    transmitInflightPacket(cycle_index);
                }
            }
        }
    }

    printDiagIfNeeded();
    delay(0);
}