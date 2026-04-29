#ifndef LOSSLESS_ENGINE_H
#define LOSSLESS_ENGINE_H

#include "NodeTypes.h"
#include "Acquisition.h"

#define INFLIGHT_CAPACITY 48

class LosslessEngine {
public:
    LosslessEngine(Acquisition &acq);
    
    void record(uint16_t seq, uint8_t ch, uint32_t first_idx, uint16_t count);
    void processAck(uint16_t acked_seq);
    void reset();
    
    bool isFull() const;
    uint8_t getCount() const;
    
    bool checkTimeout(uint32_t cycle_us, uint32_t &rewind_seq_out);

private:
    Acquisition &acq_;
    InflightEntry inflight_ring_[INFLIGHT_CAPACITY];
    uint8_t head_ = 0;
    uint8_t tail_ = 0;
};

#endif // LOSSLESS_ENGINE_H
