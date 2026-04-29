#ifndef NODE_TYPES_H
#define NODE_TYPES_H

#include <Arduino.h>
#include <tdma_protocol.h>

struct InflightEntry {
    uint16_t seq_id;
    uint8_t  channel_id;
    uint32_t first_idx;
    uint16_t count;
    uint32_t tx_time_ms;
};

#endif // NODE_TYPES_H
