#include "LosslessEngine.h"

LosslessEngine::LosslessEngine(Acquisition &acq) : acq_(acq) {}

void LosslessEngine::record(uint16_t seq, uint8_t ch, uint32_t first_idx, uint16_t count) {
    inflight_ring_[head_] = {seq, ch, first_idx, count, millis()};
    head_ = (head_ + 1) % INFLIGHT_CAPACITY;
}

void LosslessEngine::processAck(uint16_t acked_seq) {
    while (tail_ != head_) {
        InflightEntry &e = inflight_ring_[tail_];
        int16_t delta = (int16_t)(e.seq_id - acked_seq);
        if (delta > 0) break;

        acq_.advanceAcked(e.channel_id, e.first_idx + e.count);
        tail_ = (tail_ + 1) % INFLIGHT_CAPACITY;
    }
}

void LosslessEngine::reset() {
    head_ = 0;
    tail_ = 0;
}

bool LosslessEngine::isFull() const {
    return ((head_ + 1) % INFLIGHT_CAPACITY) == tail_;
}

uint8_t LosslessEngine::getCount() const {
    return (uint8_t)((head_ - tail_) % INFLIGHT_CAPACITY);
}

bool LosslessEngine::checkTimeout(uint32_t cycle_us, uint32_t &rewind_seq_out) {
    if (tail_ == head_) return false;
    
    uint32_t timeout_ms = (cycle_us > 0) ? (cycle_us / 500) : 2000;
    if (timeout_ms < 200) timeout_ms = 200;

    if ((millis() - inflight_ring_[tail_].tx_time_ms) > timeout_ms) {
        rewind_seq_out = inflight_ring_[tail_].seq_id;
        reset();
        return true;
    }
    return false;
}
