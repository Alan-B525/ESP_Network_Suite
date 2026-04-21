#pragma once

// ============================================================
// tdma_protocol.h — Protocolo TDMA v3 para ESP-NOW Sensor Network
// ============================================================
//
// ARCHIVO CANÓNICO COMPARTIDO.
// Esta es la ÚNICA copia autorizada del protocolo. Tanto
// Comunicacion_ESPNOW (Base Station) como Sender_ESPNOW (Nodos)
// lo incluyen desde aquí a través de lib_extra_dirs.
//
// Si necesitas modificar el protocolo, edita SOLO este archivo.
// Luego actualiza el parser Python en NodeLab/esp_sensor_connect/core/protocol_parser.py
// para que coincida con los cambios.
//
// Referencia de tramas seriales (Base Station → PC):
//   DATA_INT16,node_id,seq,gw_rx_us,node_ts_us,val1,val2,...
//   DATA_FLOAT,node_id,seq,gw_rx_us,node_ts_us,val1,val2,...
//   BEACON,seq,NODES=n,SLOT_US=us,REG_MS=ms,ACKS=id:seq;...
//   HELLO,node_id,mac
//   NODE_JOIN,node_id,mac
//   NODE_TIMEOUT,node_id,mac
//   LOSS,node_id,EXPECTED=x,GOT=y
//   BOOT,key[,value]
//   WARN,type,detail
//   STATS_BEGIN / NODE,... / STATS_END
// ============================================================

#include <stddef.h>
#include <stdint.h>

namespace tdma {

// Versionado explícito para permitir evolución del protocolo sin romper nodos existentes.
constexpr uint8_t PROTOCOL_VERSION = 3;

// Restricción de diseño: red industrial de hasta 10 nodos remotos.
constexpr uint8_t MAX_NODES = 10;

// Límite físico de payload para ESP-NOW.
constexpr uint8_t ESPNOW_MAX_PAYLOAD_BYTES = 250;

// Duración nominal del superciclo TDMA. El coordinador emite 1 BEACON por ciclo.
constexpr uint16_t CYCLE_MS = 1000;

// Ventana corta para permitir que nodos nuevos/reiniciados anuncien su presencia.
constexpr uint16_t REGISTRATION_WINDOW_MS = 120;

// Guarda temporal dentro de cada slot para absorber jitter de radio/firmware.
constexpr uint16_t SLOT_GUARD_US = 200;

// Si un nodo no transmite por este tiempo, se considera inactivo.
constexpr uint32_t NODE_INACTIVE_TIMEOUT_MS = 5000;

enum PacketType : uint8_t {
    PKT_BEACON_SYNC = 0x11,
    PKT_NODE_HELLO = 0x12,
    PKT_DATA = 0x13,
    PKT_DIRECT_ACK = 0x14,
};

enum SampleEncoding : uint8_t {
    SAMPLE_INT16 = 1,
    SAMPLE_FLOAT32 = 2,
};

typedef struct __attribute__((packed)) {
    uint8_t node_id;
    uint8_t reserved;
    uint16_t highest_acked_seq;
} BeaconAckEntry;

typedef struct __attribute__((packed)) {
    uint8_t type;
    uint8_t version;
    uint8_t active_nodes;
    uint8_t reserved;
    uint16_t cycle_ms;
    uint16_t registration_window_ms;
    uint16_t slot_us;
    uint16_t slot_guard_us;
    uint32_t beacon_sequence;
    uint32_t gateway_time_us;
    uint8_t slot_node_ids[MAX_NODES];
    BeaconAckEntry ack_map[MAX_NODES];
} BeaconSyncPacket;

typedef struct __attribute__((packed)) {
    uint8_t type;
    uint8_t version;
    uint8_t node_id;
    uint8_t flags;
} NodeHelloPacket;

typedef struct __attribute__((packed)) {
    uint8_t type;
    uint8_t version;
    uint8_t node_id;
    uint8_t sample_encoding;
    uint16_t sequence_id;
    uint16_t sample_count;
    uint32_t node_timestamp_us;
} DataPacketHeader;

typedef struct __attribute__((packed)) {
    uint8_t type;
    uint8_t version;
    uint8_t node_id;
    uint8_t reserved;
    uint16_t highest_acked_seq;
    uint32_t gateway_rx_us;
} DirectAckPacket;

constexpr size_t DATA_HEADER_SIZE = sizeof(DataPacketHeader);

inline bool isValidNodeId(uint8_t node_id) {
    return node_id >= 1 && node_id <= MAX_NODES;
}

inline uint8_t sampleSizeBytes(uint8_t encoding) {
    switch (encoding) {
        case SAMPLE_INT16:
            return sizeof(int16_t);
        case SAMPLE_FLOAT32:
            return sizeof(float);
        default:
            return 0;
    }
}

inline bool isSupportedEncoding(uint8_t encoding) {
    return sampleSizeBytes(encoding) != 0;
}

inline size_t dataPacketExpectedLength(const DataPacketHeader &header) {
    uint8_t bytes_per_sample = sampleSizeBytes(header.sample_encoding);
    if (bytes_per_sample == 0) {
        return 0;
    }
    return DATA_HEADER_SIZE + static_cast<size_t>(header.sample_count) * bytes_per_sample;
}

inline uint16_t maxSamplesForEncoding(uint8_t encoding) {
    uint8_t bytes_per_sample = sampleSizeBytes(encoding);
    if (bytes_per_sample == 0 || DATA_HEADER_SIZE >= ESPNOW_MAX_PAYLOAD_BYTES) {
        return 0;
    }
    return static_cast<uint16_t>((ESPNOW_MAX_PAYLOAD_BYTES - DATA_HEADER_SIZE) / bytes_per_sample);
}

inline uint16_t computeDynamicSlotUs(uint8_t active_nodes) {
    if (active_nodes == 0) {
        return 0;
    }

    uint32_t registration_us = static_cast<uint32_t>(REGISTRATION_WINDOW_MS) * 1000UL;
    uint32_t cycle_us = static_cast<uint32_t>(CYCLE_MS) * 1000UL;
    uint32_t remaining_us = (registration_us < cycle_us) ? (cycle_us - registration_us) : 0;

    // Regla principal solicitada: slot dinámico = tiempo restante / nodos activos.
    return static_cast<uint16_t>(remaining_us / active_nodes);
}

} // namespace tdma
