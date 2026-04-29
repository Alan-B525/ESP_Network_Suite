#ifndef TDMA_MANAGER_H
#define TDMA_MANAGER_H

#include "NodeRegistry.h"
#include <esp_timer.h>

class TDMAManager {
public:
    TDMAManager(NodeRegistry &registry);
    
    void begin();
    void update(uint32_t now_ms);
    
    void setSystemState(uint8_t state) { system_state_ = state; }
    uint8_t getSystemState() const { return system_state_; }
    
    void setTargetRate(uint16_t rate) { target_rate_hz_ = rate; }
    uint16_t getTargetRate() const { return target_rate_hz_; }
    
    void setRtcTime(uint64_t epoch_ms);
    uint64_t getCurrentEpochMs();

    uint32_t getBeaconErrors() const { return beacon_errors_; }

private:
    void startNewCycle(uint32_t now_ms);
    void rebuildSchedule();
    void sendBeaconSync();

    NodeRegistry &registry_;
    
    uint8_t system_state_ = tdma::STATE_DISCOVERY;
    uint16_t target_rate_hz_ = 1000;
    uint64_t rtc_epoch_ms_ = 0;
    uint64_t rtc_set_at_us_64_ = 0;
    
    uint32_t cycle_started_ms_ = 0;
    uint32_t beacon_sequence_ = 1;
    uint32_t beacon_errors_ = 0;
    
    uint8_t slot_schedule_[tdma::MAX_SLOTS] = {};
    uint8_t active_count_ = 0;
    uint8_t sorted_node_ids_[tdma::MAX_NODES] = {};
};

#endif // TDMA_MANAGER_H
