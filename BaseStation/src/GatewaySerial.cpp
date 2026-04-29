#include "GatewaySerial.h"
#include <stdarg.h>

void GatewaySerial::begin(unsigned long baud) {
    Serial.setTxBufferSize(16384);
    Serial.begin(baud);
}

void GatewaySerial::sendBinaryMsg(tdma::SerialMsgType type, const uint8_t *payload, size_t len) {
    uint8_t raw_buf[len + 1];
    raw_buf[0] = type;
    if (len > 0 && payload) memcpy(raw_buf + 1, payload, len);

    size_t cobs_max = len + 1 + (len + 1) / 254 + 2;
    uint8_t cobs_buf[cobs_max];
    size_t cobs_len = tdma::cobsEncode(raw_buf, len + 1, cobs_buf);

    Serial.write(cobs_buf, cobs_len);
}

void GatewaySerial::sendAsciiMsg(const char *fmt, ...) {
    char buf[256];
    va_list args;
    va_start(args, fmt);
    int len = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (len > 0) {
        sendBinaryMsg(tdma::SER_MSG_ASCII, (const uint8_t*)buf, len);
    }
}
