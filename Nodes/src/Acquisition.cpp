#include "Acquisition.h"
#include <math.h>

Acquisition *Acquisition::s_instance = nullptr;

void Acquisition::begin() {
    s_instance = this;
    for (int i = 0; i < 256; i++) {
        sine_lut_[i] = (int16_t)(sinf(2.0f * PI * (float)i / 256.0f) * 32767.0f);
    }

    const esp_timer_create_args_t timer_args = {
        .callback = &Acquisition::onAcqTimerISR,
        .arg = nullptr,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "acq_timer",
        .skip_unhandled_events = true,
    };
    esp_timer_create(&timer_args, &acq_timer_);

    xTaskCreate([](void *p){
        for(;;) {
            ((Acquisition*)p)->processTicks();
            vTaskDelay(pdMS_TO_TICKS(1));
        }
    }, "acq_task", 4096, this, 3, nullptr);
}

void Acquisition::start(uint32_t rate_hz) {
    if (acq_running_) stop();
    current_rate_hz_ = rate_hz;
    uint32_t period_us = 1000000UL / rate_hz;
    
    for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
        produced_[ch] = 0;
        acked_[ch] = 0;
    }
    overflow_count_ = 0;
    acq_running_ = true;
    esp_timer_start_periodic(acq_timer_, period_us);
}

void Acquisition::stop() {
    if (!acq_running_) return;
    acq_running_ = false;
    esp_timer_stop(acq_timer_);
    portENTER_CRITICAL(&acq_mux_);
    pending_ticks_ = 0;
    portEXIT_CRITICAL(&acq_mux_);
}

int16_t Acquisition::getSample(uint8_t ch, uint32_t absolute_idx) {
    return sample_ring_[ch][absolute_idx % SAMPLE_RING_CAPACITY];
}

void Acquisition::advanceAcked(uint8_t ch, uint32_t new_acked) {
    if (new_acked > acked_[ch]) acked_[ch] = new_acked;
}

void IRAM_ATTR Acquisition::onAcqTimerISR(void* arg) {
    if (s_instance) {
        portENTER_CRITICAL_ISR(&s_instance->acq_mux_);
        if (s_instance->pending_ticks_ < 50000U) s_instance->pending_ticks_++;
        portEXIT_CRITICAL_ISR(&s_instance->acq_mux_);
    }
}

void Acquisition::processTicks() {
    uint32_t ticks = 0;
    portENTER_CRITICAL(&acq_mux_);
    ticks = pending_ticks_;
    pending_ticks_ = 0;
    portEXIT_CRITICAL(&acq_mux_);

    if (ticks == 0 || !acq_running_) return;

    for (uint32_t t = 0; t < ticks; t++) {
        bool overflow = false;
        for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
            if ((produced_[ch] - acked_[ch]) >= SAMPLE_RING_CAPACITY - 1) {
                overflow = true;
                break;
            }
        }
        if (overflow) {
            overflow_count_++;
            continue;
        }

        for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
            uint32_t idx = produced_[ch] % SAMPLE_RING_CAPACITY;
            sample_ring_[ch][idx] = generateSample(ch);
            produced_[ch]++;
        }
    }
}

int16_t Acquisition::generateSample(uint8_t ch) {
    uint16_t step = 2 + ch;
    sine_phase_[ch] = (sine_phase_[ch] + step) & 0xFF;
    int32_t amplitude = 1500;
    int32_t val = 2048;
    
    switch (ch) {
        case 0: val = 2048 + (int32_t)sine_lut_[sine_phase_[ch]] * amplitude / 32767; break;
        case 1: val = (sine_phase_[ch] < 128) ? (2048 + amplitude) : (2048 - amplitude); break;
        case 2: val = (sine_phase_[ch] < 128) ? (2048 - amplitude + (amplitude * 2 * sine_phase_[ch] / 127)) : (2048 + amplitude - (amplitude * 2 * (sine_phase_[ch] - 128) / 127)); break;
        case 3: val = 2048 - amplitude + (amplitude * 2 * sine_phase_[ch] / 255); break;
    }
    
    uint32_t x = prng_state_;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    prng_state_ = x;
    val += (int32_t)(x % 21U) - 10;
    
    if (val < 0) val = 0;
    if (val > 4095) val = 4095;
    return (int16_t)val;
}
