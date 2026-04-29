// ============================================================
// Base Station (Gateway) — Protocolo TDMA v5 / ESP-NOW
// ============================================================
// Refactored Version: Logic moved to GatewayApp, TDMAManager, etc.
// ============================================================

#include <Arduino.h>
#include "GatewayApp.h"

static GatewayApp g_app;

void setup() {
    g_app.begin();
}

void loop() {
    g_app.run();
    delay(0);
}
