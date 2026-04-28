# ESP-NOW Sensor Network — System Architecture v5

> **Single Source of Truth** for AI agents and developers.
> Describes the data contracts binding the 3 components of the system.

---

## 1. System Components

```
  Sender_ESPNOW ──(ESP-NOW)──▶ Comunicacion_ESPNOW ──(USB Serial)──▶ NodeLab
     (Nodes)                      (Base Station)                    (Desktop App)
     C++ / PlatformIO             C++ / PlatformIO                  Python / Flet
```

## 2. System States

```
  DISCOVERY (0) ──▶ IDLE (1) ──▶ ACQUIRING (2) ──▶ IDLE (1)
      │                 ▲              │                │
      │ auto (1st node) │  CMD_START   │   CMD_STOP     │
      └─────────────────┘              └────────────────┘
```

| State | Gateway | Nodes | NodeLab |
|---|---|---|---|
| DISCOVERY | Beacon broadcast, accepts HELLO | Sends HELLO (node_id=0 for Auto-ID) | Shows discovered nodes |
| IDLE | Beacon with schedule, no data | Synced, no sampling | START button enabled |
| ACQUIRING | Receives/forwards data | Samples + transmits (lossless) | Records data, shows graphs |

**Commands (NodeLab → Gateway via Serial):**
```
CMD_START\n           → Gateway: STATE_ACQUIRING, ACK,CMD_START,OK
CMD_STOP\n            → Gateway: STATE_IDLE, ACK,CMD_STOP,OK
CMD_SET_TIME,{ms}\n   → Gateway: sync RTC, ACK,CMD_SET_TIME,OK
CMD_SET_RATE,{hz}\n   → Gateway: set sample rate, ACK,CMD_SET_RATE,{hz}
```

## 3. Shared Protocol (shared/tdma_protocol.h)

### Constants
```
PROTOCOL_VERSION       = 5
MAX_NODES              = 10
MAX_SLOTS              = 10 (fixed, round-robin filled)
MAX_CHANNELS_PER_NODE  = 4
CYCLE_MS               = 1000
REGISTRATION_WINDOW_MS = 100
SLOT_US                = 90000 (derived)
SLOT_GUARD_US          = 200
NODE_INACTIVE_TIMEOUT  = 10000 ms
TIMING_INFO_INTERVAL   = 5000 ms
ESPNOW_MAX_PAYLOAD     = 250 bytes
```

### TDMA Round-Robin Schedule
Always 10 slots. Active nodes fill all slots via round-robin:
```
4 nodes: [1,2,3,4, 1,2,3,4, 1,2]  → nodes 1,2 get 3 slots
1 node:  [1,1,1,1, 1,1,1,1, 1,1]  → max throughput
10 nodes:[1,2,3,4, 5,6,7,8, 9,10] → 1 slot each
```

### Packet Types
| Type | Code | Direction | Struct | Size |
|---|---|---|---|---|
| PKT_BEACON_SYNC | 0x11 | GW → Broadcast | `BeaconSyncPacket` | **80B** |
| PKT_NODE_HELLO | 0x12 | Node → GW | `NodeHelloPacket` | 8B |
| PKT_DATA | 0x13 | Node → GW | `DataPacketHeader` + samples | **16B**+ |
| PKT_DIRECT_ACK | 0x14 | GW → Node | `DirectAckPacket` | 10B |
| PKT_TIMING_INFO | 0x15 | Node → GW | `TimingInfoPacket` | **26B** |
| PKT_NODE_TELEMETRY | 0x16 | Node → GW | `NodeTelemetryPacket` | 16B |
| PKT_JOIN_ACK | 0x17 | GW → Node | `JoinAckPacket` | 4B |

### v5 Additions (vs v4)

#### CRC-16 CCITT Integrity
`DataPacketHeader` and `TimingInfoPacket` include a `uint16_t crc16` field.
The sender calculates CRC-16 over the entire packet (with crc16=0), then fills it.
The gateway recalculates and discards corrupted frames silently (ARQ handles retransmission).

#### Auto-ID (Plug & Play)
Nodes boot with `node_id = 0`. On receiving a HELLO with id=0, the gateway assigns the
first available ID (1-10) and replies with `PKT_JOIN_ACK`. The node stores the ID in RAM
and proceeds to synchronization.

#### Node Telemetry
`PKT_NODE_TELEMETRY` is sent every ~3 seconds with health diagnostics:
- `rssi_dbm`: RSSI of last beacon received
- `battery_pct`: Battery percentage (ADC or simulated)
- `temperature_c`: Chip temperature
- `buffer_usage_pct`: Ring buffer usage percentage
- `overflow_count`: Accumulated overflows
- `tx_errors`: TX error count
- `uptime_s`: Node uptime in seconds

### Sample Encoding
| Encoding | Code | Bytes/sample | Description |
|---|---|---|---|
| SAMPLE_INT16 | 1 | 2 | Raw 16-bit signed integer |
| SAMPLE_FLOAT32 | 2 | 4 | IEEE 754 float |
| SAMPLE_DELTA_8BIT | 3 | variable | 1st=int16 (2B), rest=int8 deltas (1B each) |

Delta-8bit is auto-selected by the node when all inter-sample deltas fit in [-128, 127].
Falls back to INT16 otherwise. Max samples per packet varies by encoding.

### Data Timing (t0 + dt)
Instead of a timestamp per sample, nodes send `TimingInfoPacket` with:
- `t0_epoch_ms`: absolute RTC time (Unix ms) at sample index 0
- `dt_us`: period in µs (e.g., 10000 for 100Hz)
- `first_sample_index`: in each DATA packet

**Reconstruction:** `sample_time[i] = t0 + (first_sample_index + i) * dt / 1000`

### RTC Sync Chain
```
PC clock → CMD_SET_TIME → Gateway rtc_epoch_ms → Beacon → Node RTC
```

### Lossless Delivery
- Nodes use an **ACK-gated ring buffer**: samples are retained until ACKed.
- The gateway sends `DirectAckPacket` with `highest_acked_seq` per node.
- Additionally, beacon ACK map carries the same info as backup.
- Nodes track inflight packets and perform **ARQ rewind** on timeout.
- Burst mode: up to 12 packets per TDMA slot.

## 4. Serial Transport Format (Gateway → PC)

### Binary COBS Encoding
All serial communication uses **COBS (Consistent Overhead Byte Stuffing)** encoding
with `0x00` as frame delimiter. Each frame starts with a `SerialMsgType` byte:

| MsgType | Code | Content |
|---|---|---|
| SER_MSG_ASCII | 0x01 | UTF-8 text (events, stats, logs) |
| SER_MSG_DATA | 0x02 | Binary DataPacketHeader + samples |
| SER_MSG_TIMING | 0x03 | Binary TimingInfoPacket (26 bytes) |

**Frame structure:**
```
[COBS-encoded payload][0x00 delimiter]
  └─ payload = [SerialMsgType byte][content bytes...]
```

### ASCII Message Types (inside SER_MSG_ASCII)
```
DATA,{node_id},{ch_id},{seq},{encoding},{first_idx},{count},{val1},{val2},...
TIMING,{node_id},{ch_id},{rate_hz},{dt_us},{t0_epoch_ms},{t0_sample_idx}
BEACON,{seq},STATE={s},NODES={n},SLOT_US={us},RATE={hz},RTC={ms},SCHED={id;...},ACKS={id:seq;...}
HELLO,{node_id},{mac},CH={mask},RATE={hz}
ACK,{command},{result}
NODE_JOIN,{node_id},{mac}
NODE_TIMEOUT,{node_id},{mac}
TELEMETRY,{node_id},{rssi},{battery},{temp},{buf},{ovf},{tx_err},{uptime}
LOSS,{node_id},EXPECTED={x},GOT={y}
BOOT,{key}[,{value}]
WARN,{type},{detail}
STATS_BEGIN / STATS,... / NODE,... / STATS_END
```

> **Note:** High-throughput DATA and TIMING frames are sent as binary (SER_MSG_DATA /
> SER_MSG_TIMING) for efficiency. All other messages use SER_MSG_ASCII with the formats above.

## 5. Communication Parameters

| Parameter | Base Station | Nodes | NodeLab |
|---|---|---|---|
| Serial Baud (USB) | 921600 | 115200 (debug) | 921600 (default) |
| WiFi Channel | 1 | 1 | N/A |
| Serial Encoding | COBS binary | N/A (debug only) | COBS binary |

## 6. AI Directives

1. **Read `shared/tdma_protocol.h` first** — defines all structs.
2. **Any protocol change → update ALL 3 components.**
3. **Test with `pio run`** in both firmware dirs.
4. **Serial format is COBS-encoded binary** — not plain text.
5. **t0+dt timing**: never add per-sample timestamps to DATA packets.
6. **Lossless**: node uses ACK-gated ring buffer — data retained until ACKed.
7. **Rate**: configurable 1–10000 Hz via CMD_SET_RATE, propagated via beacon.
8. **Auto-ID**: nodes start with id=0, gateway assigns via PKT_JOIN_ACK.
9. **DataPacketHeader is 16 bytes** (includes CRC-16). Parser must unpack 16B, not 14B.
10. **DELTA_8BIT payload** is variable: `2 + (count-1)` bytes, not `count * 1`.
