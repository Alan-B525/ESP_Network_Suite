#ifndef GATEWAY_SERIAL_H
#define GATEWAY_SERIAL_H

#include <Arduino.h>
#include <tdma_protocol.h>

class GatewaySerial {
public:
    static void begin(unsigned long baud);
    static void sendBinaryMsg(tdma::SerialMsgType type, const uint8_t *payload, size_t len);
    static void sendAsciiMsg(const char *fmt, ...);
};

#endif // GATEWAY_SERIAL_H
