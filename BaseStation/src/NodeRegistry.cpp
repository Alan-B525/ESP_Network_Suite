#include "NodeRegistry.h"
#include "GatewaySerial.h"
#include <string.h>

NodeRegistry::NodeRegistry() {
    memset(nodes_, 0, sizeof(nodes_));
}

ActiveNodeEntry* NodeRegistry::findOrCreateNode(const uint8_t *mac, uint8_t node_id) {
    // Buscar por MAC
    for (uint8_t i = 0; i < tdma::MAX_NODES; i++) {
        if (nodes_[i].in_use && memcmp(nodes_[i].mac, mac, 6) == 0) {
            if (nodes_[i].node_id != node_id && tdma::isValidNodeId(node_id)) {
                nodes_[i].node_id = node_id;
            }
            return &nodes_[i];
        }
    }
    if (!tdma::isValidNodeId(node_id)) return nullptr;

    // Verificar que el ID no esté en uso por otra MAC
    if (findNodeById(node_id)) return nullptr;

    // Crear nuevo
    for (uint8_t i = 0; i < tdma::MAX_NODES; i++) {
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

        GatewaySerial::sendAsciiMsg("NODE_JOIN,%u,%02X:%02X:%02X:%02X:%02X:%02X", 
                                    node_id, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
        return &nodes_[i];
    }
    return nullptr;
}

ActiveNodeEntry* NodeRegistry::findNodeById(uint8_t node_id) {
    for (uint8_t i = 0; i < tdma::MAX_NODES; i++) {
        if (nodes_[i].in_use && nodes_[i].node_id == node_id) return &nodes_[i];
    }
    return nullptr;
}

void NodeRegistry::pruneInactiveNodes(uint32_t now_ms, uint32_t timeout_ms) {
    for (uint8_t i = 0; i < tdma::MAX_NODES; i++) {
        if (!nodes_[i].in_use) continue;
        if ((now_ms - nodes_[i].last_seen_ms) > timeout_ms) {
            GatewaySerial::sendAsciiMsg("NODE_TIMEOUT,%u,%02X:%02X:%02X:%02X:%02X:%02X", 
                                        nodes_[i].node_id, nodes_[i].mac[0], nodes_[i].mac[1], 
                                        nodes_[i].mac[2], nodes_[i].mac[3], nodes_[i].mac[4], nodes_[i].mac[5]);
            memset(&nodes_[i], 0, sizeof(nodes_[i]));
        }
    }
}

uint8_t NodeRegistry::getActiveCount(uint8_t *sorted_ids_out) {
    uint8_t count = 0;
    for (uint8_t i = 0; i < tdma::MAX_NODES; i++) {
        if (nodes_[i].in_use) {
            if (sorted_ids_out) sorted_ids_out[count] = nodes_[i].node_id;
            count++;
        }
    }

    if (sorted_ids_out && count > 1) {
        // Insertion sort
        for (uint8_t i = 1; i < count; i++) {
            uint8_t key = sorted_ids_out[i];
            int8_t j = static_cast<int8_t>(i) - 1;
            while (j >= 0 && sorted_ids_out[j] > key) {
                sorted_ids_out[j + 1] = sorted_ids_out[j];
                j--;
            }
            sorted_ids_out[j + 1] = key;
        }
    }
    return count;
}
