#ifndef GATEWAY_APP_H
#define GATEWAY_APP_H

#include "NodeRegistry.h"
#include "TDMAManager.h"

class GatewayApp {
public:
    void begin();
    void run();

private:
    void processRxQueue();
    void checkSerialCommands();
    void processCommand(const char *cmd);
    
    // Handlers
    void handleNodeHello(const RxFrame &frame);
    void handleDataPacket(const RxFrame &frame);
    void handleTimingInfo(const RxFrame &frame);
    void handleNodeTelemetry(const RxFrame &frame);
    
    // Utils
    void sendDirectAck(const ActiveNodeEntry &node, uint32_t rx_us);
    void printStartupInfo();
    void printStats(uint32_t now_ms);
    void serviceLed(uint32_t now_ms);
    void pulseRxLed();
    bool ensurePeerPresent(const uint8_t *mac);
    bool addBroadcastPeer();

    NodeRegistry registry_;
    TDMAManager tdma_manager_{registry_};
    
    // RX Queue
    static void onDataRecvStatic(const uint8_t *mac, const uint8_t *data, int len);
    void enqueueRxFrame(const uint8_t *mac, const uint8_t *data, int len);
    bool popRxFrame(RxFrame &out);

    RxFrame rx_queue_[tdma::RX_QUEUE_LEN];
    volatile uint8_t rx_head_ = 0;
    volatile uint8_t rx_tail_ = 0;
    volatile uint32_t rx_overruns_ = 0;
    portMUX_TYPE rx_mux_ = portMUX_INITIALIZER_UNLOCKED;

    uint32_t tx_errors_ = 0;
    uint32_t last_stats_ms_ = 0;
    
    // LED
    bool led_on_ = false;
    uint32_t led_off_ms_ = 0;
    
    // Serial Cmd
    char cmd_buf_[64] = {};
    uint8_t cmd_len_ = 0;

    static GatewayApp *s_instance;
};

#endif // GATEWAY_APP_H
