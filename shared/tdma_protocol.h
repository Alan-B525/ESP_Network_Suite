#pragma once

// ============================================================
// tdma_protocol.h — Protocolo TDMA v5 para ESP-NOW Sensor Network
// ============================================================
//
// ARCHIVO CANÓNICO COMPARTIDO.
// Cambios v4 → v5:
//   - CRC-16 CCITT añadido a DataPacketHeader y TimingInfoPacket.
//   - Auto-ID: Gateway asigna ID mediante PKT_JOIN_ACK y MAC address.
//   - PKT_NODE_TELEMETRY para transmitir métricas en tiempo real.
//   - SystemState: DISCOVERY / IDLE / ACQUIRING
//   - TDMA Round-Robin: 10 slots fijos, llenados con nodos activos
//   - Multi-canal: hasta 4 canales/sensores por nodo
//
// Formato serial v5 (Base Station → PC):
//   DATA,node_id,ch_id,seq,encoding,first_idx,sample_count,val1,val2,...
//   TIMING,node_id,ch_id,sample_rate_hz,dt_us,t0_epoch_ms,t0_sample_idx
//   BEACON,seq,STATE=s,NODES=n,SLOT_US=us,RATE=hz,RTC=ms,SCHED=id;id;...,ACKS=id:seq;...
//   HELLO,node_id,mac,CH=mask,RATE=hz
//   NODE_JOIN,node_id,mac
//   NODE_TIMEOUT,node_id,mac
//   TELEMETRY,node_id,rssi,battery,temp,buf,ovf,tx_err,uptime
//   LOSS,node_id,EXPECTED=x,GOT=y
//   BOOT,key[,value]
//   WARN,type,detail
//   ACK,command,result
//   STATS_BEGIN / STATS,... / NODE,... / STATS_END
//
// Comandos serial v5 (PC → Base Station):
//   CMD_START\n          → ACK,CMD_START,OK
//   CMD_STOP\n           → ACK,CMD_STOP,OK
//   CMD_SET_TIME,{ms}\n  → ACK,CMD_SET_TIME,OK
//   CMD_SET_RATE,{hz}\n  → ACK,CMD_SET_RATE,{hz}
// ============================================================

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace tdma {

// ---- Versión del protocolo ----
constexpr uint8_t PROTOCOL_VERSION = 5;

// ---- Límites de red ----
constexpr uint8_t MAX_NODES = 10;
constexpr uint8_t MAX_SLOTS = 10;               // Siempre 10 slots por ciclo
constexpr uint8_t MAX_CHANNELS_PER_NODE = 4;

// ---- Límite físico ESP-NOW ----
constexpr uint8_t ESPNOW_MAX_PAYLOAD_BYTES = 250;

// ---- Timing TDMA ----
constexpr uint16_t CYCLE_MS = 1000;
constexpr uint16_t REGISTRATION_WINDOW_MS = 100;
constexpr uint16_t SLOT_GUARD_US = 500;

// Slot fijo: (cycle - reg_window) / MAX_SLOTS
// = (1000000 - 100000) / 10 = 90000 µs = 90 ms
constexpr uint32_t SLOT_US = ((uint32_t)CYCLE_MS * 1000UL
                              - (uint32_t)REGISTRATION_WINDOW_MS * 1000UL)
                             / MAX_SLOTS;

// ---- Timeouts ----
constexpr uint32_t NODE_INACTIVE_TIMEOUT_MS = 10000;

// ---- Intervalo de reenvío de TIMING_INFO (ms) ----
constexpr uint32_t TIMING_INFO_INTERVAL_MS = 5000;

// ============================================================
// Enums
// ============================================================

enum SystemState : uint8_t {
    STATE_DISCOVERY  = 0,   // Boot: buscando nodos
    STATE_IDLE       = 1,   // Nodos registrados, sin adquisición
    STATE_ACQUIRING  = 2,   // Adquisición activa
};

enum PacketType : uint8_t {
    PKT_BEACON_SYNC  = 0x11,
    PKT_NODE_HELLO   = 0x12,
    PKT_DATA         = 0x13,
    PKT_DIRECT_ACK   = 0x14,
    PKT_TIMING_INFO  = 0x15,
    PKT_NODE_TELEMETRY = 0x16,
    PKT_JOIN_ACK     = 0x17,
};

enum SerialMsgType : uint8_t {
    SER_MSG_ASCII  = 0x01,  // Text logs, events, stats
    SER_MSG_DATA   = 0x02,  // High-speed DATA packet
    SER_MSG_TIMING = 0x03,  // TIMING_INFO packet
};

enum SampleEncoding : uint8_t {
    SAMPLE_INT16   = 1,
    SAMPLE_FLOAT32 = 2,
    SAMPLE_DELTA_8BIT = 3, // 1st is int16, rest are int8 deltas
};

// ============================================================
// Structs de paquetes
// ============================================================

// ---- Beacon ACK entry (dentro del beacon) ----
typedef struct __attribute__((packed)) {
    uint8_t  node_id;
    uint8_t  reserved;
    uint16_t highest_acked_seq;
} BeaconAckEntry;

// ---- Beacon Sync (gateway → broadcast) ----
typedef struct __attribute__((packed)) {
    uint8_t  type;                          // PKT_BEACON_SYNC
    uint8_t  version;                       // PROTOCOL_VERSION
    uint8_t  system_state;                  // SystemState
    uint8_t  active_nodes;
    uint16_t cycle_ms;
    uint32_t slot_us;                       // Duración de slot en µs (puede ser > 65535)
    uint16_t slot_guard_us;
    uint16_t registration_window_ms;
    uint16_t sample_rate_hz;                // Tasa de muestreo objetivo (configurable)
    uint16_t reserved_beacon;
    uint32_t beacon_sequence;
    uint64_t rtc_epoch_ms;                  // Hora UTC (Unix ms) del gateway
    uint8_t  slot_schedule[MAX_SLOTS];      // Round-robin: node_id por slot
    BeaconAckEntry ack_map[MAX_NODES];
} BeaconSyncPacket;
// sizeof = 1+1+1+1+2+4+2+2+2+2+4+8+10+40 = 80 bytes

// ---- Node Hello (nodo → gateway) ----
typedef struct __attribute__((packed)) {
    uint8_t  type;                          // PKT_NODE_HELLO
    uint8_t  version;
    uint8_t  node_id;
    uint8_t  channel_mask;                  // Bits 0-3: canales activos
    uint8_t  channel_count;                 // 1-4
    uint8_t  flags;                         // Bit0: has_rtc, Bit1: deep_sleep_capable
    uint16_t sample_rate_hz;                // Frecuencia de muestreo declarada
} NodeHelloPacket;
// sizeof = 8 bytes

// ---- Data Packet Header (nodo → gateway) ----
typedef struct __attribute__((packed)) {
    uint8_t  type;                          // PKT_DATA
    uint8_t  version;
    uint8_t  node_id;
    uint8_t  channel_id;                    // 0-3
    uint8_t  sample_encoding;               // SampleEncoding
    uint8_t  reserved;
    uint16_t sequence_id;                   // Secuencia global por nodo
    uint16_t sample_count;
    uint32_t first_sample_index;            // Índice global del primer sample
    uint16_t crc16;                         // CRC-16 CCITT del payload + header (sin incluir crc16)
} DataPacketHeader;
// sizeof = 16 bytes

// ---- Timing Info (nodo → gateway, reenviado a PC) ----
typedef struct __attribute__((packed)) {
    uint8_t  type;                          // PKT_TIMING_INFO
    uint8_t  version;
    uint8_t  node_id;
    uint8_t  channel_id;                    // 0xFF = aplica a todos los canales
    uint32_t sample_rate_hz;
    uint32_t dt_us;                         // Periodo en µs
    uint64_t t0_epoch_ms;                   // Hora UTC del sample index t0
    uint32_t t0_sample_index;               // Índice correspondiente a t0
    uint16_t crc16;                         // CRC-16 CCITT
} TimingInfoPacket;
// sizeof = 26 bytes

// ---- Direct ACK (gateway → nodo unicast) ----
typedef struct __attribute__((packed)) {
    uint8_t  type;                          // PKT_DIRECT_ACK
    uint8_t  version;
    uint8_t  node_id;
    uint8_t  system_state;                  // Para que el nodo sepa el estado
    uint16_t highest_acked_seq;
    uint32_t gateway_rx_us;
} DirectAckPacket;
// sizeof = 10 bytes

// ---- Join ACK (gateway → nodo unicast) ----
typedef struct __attribute__((packed)) {
    uint8_t  type;                          // PKT_JOIN_ACK
    uint8_t  version;
    uint8_t  assigned_node_id;
    uint8_t  system_state;
} JoinAckPacket;
// sizeof = 4 bytes

// ---- Node Telemetry (nodo → gateway) ----
typedef struct __attribute__((packed)) {
    uint8_t  type;            // PKT_NODE_TELEMETRY = 0x16
    uint8_t  version;
    uint8_t  node_id;
    uint8_t  flags;
    int8_t   rssi_dbm;       // RSSI del último beacon recibido
    uint8_t  battery_pct;    // Batería real (ADC del VCC)
    int8_t   temperature_c;  // Temperatura interna del ESP32
    uint8_t  buffer_usage_pct; // % del ring buffer usado
    uint16_t overflow_count; // Overflows acumulados
    uint16_t tx_errors;      // Errores de TX acumulados
    uint32_t uptime_s;       // Uptime del nodo en segundos
} NodeTelemetryPacket;       // 16 bytes

// ============================================================
// Constantes derivadas
// ============================================================

constexpr size_t DATA_HEADER_SIZE = sizeof(DataPacketHeader);

// ============================================================
// Funciones utilitarias inline
// ============================================================

inline bool isValidNodeId(uint8_t node_id) {
    return node_id >= 1 && node_id <= MAX_NODES;
}

inline uint16_t crc16_ccitt(const uint8_t *data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t j = 0; j < 8; ++j) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

inline bool isValidChannelId(uint8_t channel_id) {
    return channel_id < MAX_CHANNELS_PER_NODE;
}

inline uint8_t sampleSizeBytes(uint8_t encoding) {
    switch (encoding) {
        case SAMPLE_INT16:   return sizeof(int16_t);
        case SAMPLE_FLOAT32: return sizeof(float);
        case SAMPLE_DELTA_8BIT: return 1; // It's variable actually, but mostly 1.
        default:             return 0;
    }
}

inline bool isSupportedEncoding(uint8_t encoding) {
    return sampleSizeBytes(encoding) != 0;
}

inline size_t dataPacketExpectedLength(const DataPacketHeader &header) {
    if (header.sample_count == 0) return DATA_HEADER_SIZE;
    if (header.sample_encoding == SAMPLE_DELTA_8BIT) {
        return DATA_HEADER_SIZE + 2 + (header.sample_count - 1);
    }
    uint8_t bps = sampleSizeBytes(header.sample_encoding);
    if (bps == 0) return 0;
    return DATA_HEADER_SIZE + static_cast<size_t>(header.sample_count) * bps;
}

inline uint16_t maxSamplesForEncoding(uint8_t encoding) {
    if (DATA_HEADER_SIZE >= ESPNOW_MAX_PAYLOAD_BYTES) return 0;
    if (encoding == SAMPLE_DELTA_8BIT) {
        // 2 bytes for base, remaining for deltas
        return 1 + (ESPNOW_MAX_PAYLOAD_BYTES - DATA_HEADER_SIZE - 2);
    }
    uint8_t bps = sampleSizeBytes(encoding);
    if (bps == 0) return 0;
    return static_cast<uint16_t>((ESPNOW_MAX_PAYLOAD_BYTES - DATA_HEADER_SIZE) / bps);
}

inline uint8_t channelCountFromMask(uint8_t mask) {
    uint8_t count = 0;
    for (uint8_t i = 0; i < MAX_CHANNELS_PER_NODE; i++) {
        if (mask & (1U << i)) count++;
    }
    return count;
}

// Construye schedule round-robin: llena MAX_SLOTS slots con los nodos activos.
// active_ids: array de node_ids activos (ordenados).
// active_count: cantidad de nodos activos (0 a MAX_NODES).
// schedule_out: array de MAX_SLOTS bytes a llenar.
inline void buildRoundRobinSchedule(const uint8_t *active_ids,
                                     uint8_t active_count,
                                     uint8_t *schedule_out) {
    if (active_count == 0) {
        memset(schedule_out, 0, MAX_SLOTS);
        return;
    }
    for (uint8_t i = 0; i < MAX_SLOTS; i++) {
        schedule_out[i] = active_ids[i % active_count];
    }
}

// Cuenta cuántos slots tiene asignados un nodo en el schedule.
inline uint8_t countSlotsForNode(const uint8_t *schedule, uint8_t node_id) {
    uint8_t count = 0;
    for (uint8_t i = 0; i < MAX_SLOTS; i++) {
        if (schedule[i] == node_id) count++;
    }
    return count;
}

inline bool isSequenceNewer(uint16_t candidate, uint16_t reference) {
    return static_cast<int16_t>(candidate - reference) > 0;
}

// ============================================================
// COBS Encoding (Para comunicación Serial Binaria)
// ============================================================
inline size_t cobsEncode(const uint8_t *ptr, size_t length, uint8_t *dst) {
    size_t read_index = 0;
    size_t write_index = 1;
    size_t code_index = 0;
    uint8_t code = 1;

    while (read_index < length) {
        if (ptr[read_index] == 0) {
            dst[code_index] = code;
            code = 1;
            code_index = write_index++;
            read_index++;
        } else {
            dst[write_index++] = ptr[read_index++];
            code++;
            if (code == 0xFF) {
                dst[code_index] = code;
                code = 1;
                code_index = write_index++;
            }
        }
    }
    dst[code_index] = code;
    dst[write_index++] = 0; // Delimiter
    return write_index;
}

} // namespace tdma
