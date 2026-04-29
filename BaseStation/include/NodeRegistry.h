#ifndef NODE_REGISTRY_H
#define NODE_REGISTRY_H

#include "GatewayTypes.h"

class NodeRegistry {
public:
    NodeRegistry();
    
    ActiveNodeEntry* findOrCreateNode(const uint8_t *mac, uint8_t node_id);
    ActiveNodeEntry* findNodeById(uint8_t node_id);
    void pruneInactiveNodes(uint32_t now_ms, uint32_t timeout_ms);
    
    ActiveNodeEntry* getNodes() { return nodes_; }
    uint8_t getActiveCount(uint8_t *sorted_ids_out = nullptr);

private:
    ActiveNodeEntry nodes_[tdma::MAX_NODES];
};

#endif // NODE_REGISTRY_H
