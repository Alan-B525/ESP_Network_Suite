// ============================================================
// Nodo remoto ESP32-C3 — Protocolo TDMA v5 / ESP-NOW
// ============================================================
// Refactored Version: Logic moved to NodeApp, Acquisition, etc.
// ============================================================

#include <Arduino.h>
#include "NodeApp.h"

static NodeApp g_app;

void setup() {
    g_app.begin();
}

void loop() {
    g_app.run();
    delay(0);
}