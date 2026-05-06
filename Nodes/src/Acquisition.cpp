#include "Acquisition.h"

Acquisition *Acquisition::s_instance = nullptr;

void Acquisition::begin() {
    s_instance = this;

    // ── Configurar ADC para lectura real en GPIO 0 ──
    // Atenuación 11dB → rango de entrada 0 – ~3.3V
    // ESP32-C3 ADC es siempre 12 bits (0–4095)
    analogSetAttenuation(ADC_11db);
    pinMode(ADC_PIN, INPUT);

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

void Acquisition::start(uint32_t rate_hz, uint64_t sync_anchor_us) {
    if (acq_running_) stop();
    current_rate_hz_ = rate_hz;
    uint32_t period_us = 1000000UL / rate_hz;
    
    for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
        produced_[ch] = 0;
        acked_[ch] = 0;
    }
    overflow_count_ = 0;
    acq_running_ = true;
    
    // Phase alignment: calculate exactly when the next slot boundary is
    uint64_t now_us = esp_timer_get_time();
    uint32_t delay_us = period_us;
    if (sync_anchor_us > 0 && now_us > sync_anchor_us) {
        uint64_t elapsed_since_anchor = now_us - sync_anchor_us;
        delay_us = period_us - (elapsed_since_anchor % period_us);
    }
    if (delay_us > 0 && delay_us <= period_us) {
        ets_delay_us(delay_us); // Busy-wait to microsecond precision
    }
    
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

        // Leer ADC una sola vez por tick (solo canal 0)
        int16_t adc_value = readADC();
        for (uint8_t ch = 0; ch < NUM_CHANNELS; ch++) {
            uint32_t idx = produced_[ch] % SAMPLE_RING_CAPACITY;
            sample_ring_[ch][idx] = adc_value;
            produced_[ch]++;
        }
    }
}

// ── Lectura real del ADC ──
// Devuelve valor calibrado en miliVoltios directamente desde GPIO 0 usando eFuse
int16_t Acquisition::readADC() {
    return (int16_t)analogReadMilliVolts(ADC_PIN);
}

