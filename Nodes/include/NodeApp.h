#ifndef NODE_APP_H
#define NODE_APP_H

#include "Acquisition.h"
#include "LosslessEngine.h"

class NodeApp {
public:
    void begin();
    void run();

private:
    void handleBeaconSync(const uint8_t *data, int len);
    void handleDirectAck(const uint8_t *data, int len);
    void handleJoinAck(const uint8_t *data, int len);
    
    void transmitBurst();
    void sendNodeHello();
    void sendTimingInfo();
    void sendTelemetry();
    uint8_t sendDataPacket(uint8_t ch);

    static void onDataSentStatic(const uint8_t *mac, esp_now_send_status_t status);
    static void onDataRecvStatic(const uint8_t *mac, const uint8_t *data, int len);

    Acquisition acq_;
    LosslessEngine lossless_{acq_};
    
    uint8_t node_id_ = 0;
    uint8_t system_state_ = tdma::STATE_DISCOVERY;
    
    // Sync state
    bool sync_locked_ = false;
    uint64_t sync_anchor_us_ = 0;
    uint64_t last_sync_us_ = 0;
    uint32_t tdma_cycle_us_ = 0;
    uint32_t tdma_slot_us_ = 0;
    uint8_t slot_schedule_[tdma::MAX_SLOTS] = {};
    
    uint16_t next_seq_ = 1;
    uint32_t last_diag_ms_ = 0;
    uint32_t last_timing_info_ms_ = 0;
    bool timing_info_sent_at_start_ = false;
    uint32_t sent_idx_[NUM_CHANNELS] = {};
    
    static NodeApp *s_instance;
};

#endif // NODE_APP_H
