#ifndef ACQUISITION_H
#define ACQUISITION_H

#include <Arduino.h>
#include <esp_timer.h>
#include <tdma_protocol.h>

// ============================================================
// Solo 1 canal activo: ADC1_CH0 en GPIO 0 (señal real)
// Los canales 1, 2, 3 no se utilizan.
// ============================================================
#define NUM_CHANNELS 1
#define ADC_PIN      0          // GPIO 0 = ADC1 Channel 0
#define SAMPLE_RING_CAPACITY 4096U

class Acquisition {
public:
    void begin();
    void start(uint32_t rate_hz, uint64_t sync_anchor_us);
    void stop();
    
    bool isRunning() const { return acq_running_; }
    uint32_t getProduced(uint8_t ch) const { return produced_[ch]; }
    uint32_t getOverflows() const { return overflow_count_; }
    
    int16_t getSample(uint8_t ch, uint32_t absolute_idx);
    
    void advanceAcked(uint8_t ch, uint32_t new_acked);
    uint32_t getAcked(uint8_t ch) const { return acked_[ch]; }

private:
    static void IRAM_ATTR onAcqTimerISR(void* arg);
    void processTicks();
    int16_t readADC();

    esp_timer_handle_t acq_timer_ = nullptr;
    bool acq_running_ = false;
    uint32_t current_rate_hz_ = 1000;
    
    int16_t sample_ring_[NUM_CHANNELS][SAMPLE_RING_CAPACITY];
    uint32_t produced_[NUM_CHANNELS] = {};
    uint32_t acked_[NUM_CHANNELS] = {};
    uint32_t overflow_count_ = 0;

    volatile uint32_t pending_ticks_ = 0;
    portMUX_TYPE acq_mux_ = portMUX_INITIALIZER_UNLOCKED;

    static Acquisition *s_instance;
};

#endif // ACQUISITION_H
