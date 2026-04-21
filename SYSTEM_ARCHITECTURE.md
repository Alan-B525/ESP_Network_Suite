# ESP-NOW Sensor Network — System Architecture

> **Single Source of Truth** for AI agents (Cursor, Gemini, Claude) and developers.
> Describes the data contracts binding the 3 components of the system.

---

## 1. System Components

```
  Sender_ESPNOW ──(ESP-NOW)──▶ Comunicacion_ESPNOW ──(USB Serial)──▶ NodeLab
     (Nodes)                      (Base Station)                    (Desktop App)
     C++ / PlatformIO             C++ / PlatformIO                  Python / Flet
```

1. **Sender_ESPNOW (Nodes / C++)**
   - ESP32-C3 microcontrollers acquiring sensor data (simulated at 100 Hz).
   - Transmit via ESP-NOW to the Base Station using packed binary structs.
   - TDMA-scheduled: each node transmits only in its assigned time slot.
   - Serial baudrate: 115200 (debug only, does NOT reach PC).

2. **Comunicacion_ESPNOW (Base Station / C++)**
   - ESP32-C3 acting as central gateway.
   - Receives ESP-NOW packets from all nodes.
   - Broadcasts BEACON_SYNC every cycle (1s) for TDMA coordination.
   - Sends DIRECT_ACK unicast to confirm reception.
   - Forwards data over USB/Serial at **921600 baud** in CSV format.

3. **NodeLab (Desktop App / Python)**
   - Reads USB COM port for data from the Base Station.
   - `protocol_parser.py` deserializes CSV lines into typed dataclasses.
   - `serial_manager.py` manages connection + reader thread.
   - `data_logger.py` persists data to CSV sessions.
   - Flet-based UI with real-time visualization and node monitoring.

---

## 2. Shared Protocol Header

**Canonical file:** `shared/tdma_protocol.h`

Both firmware projects include this via redirect files in their `lib/` directories.
The Python parser in NodeLab must match the serial output format defined by the
Base Station's `emitPayloadCsv()` function.

### Protocol Constants
```cpp
PROTOCOL_VERSION       = 3
MAX_NODES              = 10
ESPNOW_MAX_PAYLOAD     = 250 bytes
CYCLE_MS               = 1000 ms
REGISTRATION_WINDOW_MS = 120 ms
SLOT_GUARD_US          = 200 µs
NODE_INACTIVE_TIMEOUT  = 5000 ms
```

### Packet Types
| Type | Code | Direction | Struct |
|---|---|---|---|
| PKT_BEACON_SYNC | 0x11 | Gateway → Broadcast | `BeaconSyncPacket` |
| PKT_NODE_HELLO | 0x12 | Node → Gateway | `NodeHelloPacket` |
| PKT_DATA | 0x13 | Node → Gateway | `DataPacketHeader` + samples |
| PKT_DIRECT_ACK | 0x14 | Gateway → Node | `DirectAckPacket` |

### Sample Encodings
| Encoding | Code | Bytes/sample |
|---|---|---|
| SAMPLE_INT16 | 1 | 2 |
| SAMPLE_FLOAT32 | 2 | 4 |

---

## 3. Serial Output Format (Base Station → PC)

The Base Station serializes received data to the USB serial port. **NodeLab's
`ProtocolParser` class must exactly match these formats.**

### Data Lines
```
DATA_INT16,{node_id},{seq},{gw_rx_us},{node_ts_us},{val1},{val2},...
DATA_FLOAT,{node_id},{seq},{gw_rx_us},{node_ts_us},{val1},{val2},...
```

### Network Events
```
BEACON,{seq},NODES={n},SLOT_US={us},REG_MS={ms},ACKS={id}:{seq};{id}:{seq}
HELLO,{node_id},{mac}
NODE_JOIN,{node_id},{mac}
NODE_TIMEOUT,{node_id},{mac}
LOSS,{node_id},EXPECTED={x},GOT={y}
```

### System Messages
```
BOOT,{key}[,{value}]
WARN,{type},{detail}
```

### Statistics Block (multiline)
```
STATS_BEGIN
STATS,STATE,{0|1|2}
STATS,ACTIVE_NODES,{n}
STATS,SLOT_US,{us}
STATS,RX_OVERRUN,{count}
STATS,BEACON_TX_ERR,{count}
STATS,DIRECT_ACK_TX_ERR,{count}
NODE,{id},MAC={mac},RX={n},EMIT={n},ACKED={seq},LOST={n},INVALID={n},AGE_MS={ms}
STATS_END
```

### Python Parser Mapping
```python
# In NodeLab/esp_sensor_connect/core/protocol_parser.py
parser = ProtocolParser()
frame = parser.parse("DATA_INT16,1,105,483921,12340,2048,2100")
# Returns: DataFrame(node_id=1, sequence=105, values=[2048.0, 2100.0], ...)
```

---

## 4. Communication Parameters

| Parameter | Base Station | Nodes | NodeLab |
|---|---|---|---|
| Serial Baud (USB) | 921600 | 115200 (debug) | 921600 (default) |
| WiFi Channel | 1 | 1 | N/A |
| ESP-NOW Encryption | None | None | N/A |

---

## 5. AI Directives

If you are an AI agent modifying this codebase:

1. **Read `shared/tdma_protocol.h` first** — it defines all structs and constants.
2. **Any protocol change requires updates in ALL 3 components:**
   - `shared/tdma_protocol.h` — struct definitions
   - `Comunicacion_ESPNOW/src/main.cpp` — serial output format
   - `Sender_ESPNOW/src/main.cpp` — packet construction
   - `NodeLab/.../protocol_parser.py` — parser logic
3. **Never update only one component without updating the rest.**
4. **Test with `pio run`** in both firmware directories after any header change.
5. **The serial format is the contract** between C++ and Python — keep them in sync.
