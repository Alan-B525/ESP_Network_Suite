#ifndef GATEWAY_TYPES_H
#define GATEWAY_TYPES_H

#include <Arduino.h>
#include <tdma_protocol.h>

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

#endif // GATEWAY_TYPES_H
