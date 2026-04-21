# ESP-NOW Sensor Network — System Architecture v4

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
| DISCOVERY | Beacon broadcast, accepts HELLO | Sends HELLO | Shows discovered nodes |
| IDLE | Beacon with schedule, no data | Synced, no sampling | START button enabled |
| ACQUIRING | Receives/forwards data | Samples + transmits | Records data, shows graphs |

**Commands (NodeLab → Gateway via Serial):**
```
CMD_START\n           → Gateway: STATE_ACQUIRING, ACK,CMD_START,OK
CMD_STOP\n            → Gateway: STATE_IDLE, ACK,CMD_STOP,OK
CMD_SET_TIME,{ms}\n   → Gateway: sync RTC, ACK,CMD_SET_TIME,OK
```

## 3. Shared Protocol (shared/tdma_protocol.h)

### Constants
```
PROTOCOL_VERSION       = 4
MAX_NODES              = 10
MAX_SLOTS              = 10 (fixed, round-robin filled)
MAX_CHANNELS_PER_NODE  = 4
CYCLE_MS               = 1000
REGISTRATION_WINDOW_MS = 100
SLOT_US                = 90000 (derived)
SLOT_GUARD_US          = 200
NODE_INACTIVE_TIMEOUT  = 10000 ms
TIMING_INFO_INTERVAL   = 5000 ms
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
| PKT_BEACON_SYNC | 0x11 | GW → Broadcast | `BeaconSyncPacket` | 74B |
| PKT_NODE_HELLO | 0x12 | Node → GW | `NodeHelloPacket` | 8B |
| PKT_DATA | 0x13 | Node → GW | `DataPacketHeader` + samples | 14B+ |
| PKT_DIRECT_ACK | 0x14 | GW → Node | `DirectAckPacket` | 10B |
| PKT_TIMING_INFO | 0x15 | Node → GW | `TimingInfoPacket` | 24B |

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

## 4. Serial Output Format (Gateway → PC)

```
DATA,{node_id},{ch_id},{seq},{encoding},{first_idx},{count},{val1},{val2},...
TIMING,{node_id},{ch_id},{rate_hz},{dt_us},{t0_epoch_ms},{t0_sample_idx}
BEACON,{seq},STATE={s},NODES={n},SLOT_US={us},RTC={ms},SCHED={id;...},ACKS={id:seq;...}
HELLO,{node_id},{mac},CH={mask},RATE={hz}
ACK,{command},{result}
NODE_JOIN,{node_id},{mac}
NODE_TIMEOUT,{node_id},{mac}
LOSS,{node_id},EXPECTED={x},GOT={y}
BOOT,{key}[,{value}]
WARN,{type},{detail}
STATS_BEGIN / STATS,... / NODE,... / STATS_END
```

## 5. Communication Parameters

| Parameter | Base Station | Nodes | NodeLab |
|---|---|---|---|
| Serial Baud (USB) | 921600 | 115200 (debug) | 921600 (default) |
| WiFi Channel | 1 | 1 | N/A |

## 6. AI Directives

1. **Read `shared/tdma_protocol.h` first** — defines all structs.
2. **Any protocol change → update ALL 3 components.**
3. **Test with `pio run`** in both firmware dirs.
4. **Serial format is the contract** between C++ and Python.
5. **t0+dt timing**: never add per-sample timestamps to DATA packets.
