# ESP Network Suite

Sistema de adquisición de datos inalámbrico basado en **ESP-NOW** con protocolo **TDMA v5** para redes de sensores ESP32.

```
  ┌──────────────┐    ESP-NOW     ┌──────────────────┐    USB/Serial    ┌──────────────┐
  │  Nodo ESP32  │───────────────▶│   Base Station    │────────────────▶│   NodeLab    │
  │ (Sensor x N) │    2.4 GHz    │  (Gateway ESP32)  │    921600 baud  │  (PC / Flet) │
  └──────────────┘               └──────────────────┘                  └──────────────┘
   Sender_ESPNOW               Comunicacion_ESPNOW                       NodeLab/
```

---

## Estructura del Monorepo

```
ESP_Network_Suite/
├── shared/                          # ← Código compartido entre firmware
│   └── tdma_protocol.h              #    Header CANÓNICO del protocolo v5
│
├── Comunicacion_ESPNOW/             # ← Base Station (Gateway)
│   ├── src/main.cpp                 #    Firmware C++ (PlatformIO)
│   ├── lib/tdma_protocol.h          #    Redirect → shared/
│   ├── include/tdma_protocol.h      #    Redirect → lib/
│   └── platformio.ini               #    ESP32-C3 DevKit-M1, 921600 baud
│
├── Sender_ESPNOW/                   # ← Nodos Remotos
│   ├── src/main.cpp                 #    Firmware C++ (PlatformIO)
│   ├── lib/tdma_protocol.h          #    Redirect → shared/
│   ├── include/tdma_protocol.h      #    Redirect → lib/
│   └── platformio.ini               #    ESP32-C3, 115200 baud (debug)
│
├── NodeLab/                         # ← Aplicación de Escritorio
│   └── esp_sensor_connect/
│       ├── main.py                  #    Punto de entrada (Flet UI)
│       ├── core/                    #    Serial, parser, logger
│       │   ├── protocol_parser.py   #    Deserializa tramas binarias COBS
│       │   ├── serial_manager.py    #    Conexión USB + hilo de lectura
│       │   └── data_logger.py       #    Persistencia CSV por nodo+canal
│       └── ui/                      #    Interfaz gráfica
│           ├── main_window.py
│           ├── design_tokens.py
│           ├── components/
│           └── views/
│
├── docs/                            # ← Documentación de migración
│   ├── PROTOCOL_v5_MIGRATION.md     #    Cambios v4 → v5
│   └── SYSTEM_EVOLUTION_v5.md       #    Evolución del sistema
│
├── SYSTEM_ARCHITECTURE.md           # ← Contratos de datos entre componentes
├── README.md                        # ← Este archivo
└── .gitignore
```

---

## Protocolo TDMA v5

| Parámetro | Valor |
|---|---|
| Versión | **5** |
| Max Nodos | 10 |
| Max Canales/Nodo | 4 |
| Ciclo TDMA | 1000 ms |
| Slots por ciclo | 10 (round-robin adaptativo) |
| Ventana de Registro | 100 ms |
| Slot Time | 90000 µs (derivado) |
| Guard Time | 200 µs |
| Timeout Inactividad | 10000 ms |
| Rate Configurable | 1–10000 Hz (default 1000 Hz) |
| Encoding Soportado | INT16, FLOAT32, DELTA_8BIT |
| Integridad | CRC-16 CCITT en DATA y TIMING |
| ID de Nodos | Auto-asignado por Gateway (Plug & Play) |
| Transporte Serial | COBS binario con delimitador 0x00 |

### Novedades v5 (respecto a v4)

- **CRC-16 CCITT** en `DataPacketHeader` y `TimingInfoPacket` para integridad de datos
- **Auto-ID (Plug & Play)**: Los nodos arrancan con `node_id = 0` y el gateway les asigna un ID único vía `PKT_JOIN_ACK`
- **Telemetría de Nodos** (`PKT_NODE_TELEMETRY`): RSSI, batería, temperatura, uso de buffer, errores TX, uptime
- **Compresión Delta-8bit** (`SAMPLE_DELTA_8BIT`): Selección automática para reducir ancho de banda
- **Comunicación serial COBS**: Encoding binario eficiente para DATA y TIMING de alto throughput

### Tipos de Paquete (over-the-air)

| Tipo | Código | Dirección | Tamaño | Descripción |
|---|---|---|---|---|
| `PKT_BEACON_SYNC` | `0x11` | Gateway → Broadcast | **80B** | Sincronización + schedule + RTC + rate |
| `PKT_NODE_HELLO` | `0x12` | Nodo → Gateway | 8B | Registro con capabilities |
| `PKT_DATA` | `0x13` | Nodo → Gateway | **16B**+ | Datos de un canal (lossless, con CRC) |
| `PKT_DIRECT_ACK` | `0x14` | Gateway → Nodo | 10B | Confirmación de recepción |
| `PKT_TIMING_INFO` | `0x15` | Nodo → Gateway | **26B** | Sincronización temporal t0+dt (con CRC) |
| `PKT_NODE_TELEMETRY` | `0x16` | Nodo → Gateway | 16B | Diagnóstico de salud del nodo |
| `PKT_JOIN_ACK` | `0x17` | Gateway → Nodo | 4B | Asignación de ID al nodo |

### Formato Serial Binario (Gateway → PC)

La comunicación serial usa **COBS encoding** con `0x00` como delimitador. Cada frame contiene un byte de tipo:

| Tipo | Código | Contenido |
|---|---|---|
| `SER_MSG_ASCII` | `0x01` | Texto UTF-8 (eventos, stats, logs) |
| `SER_MSG_DATA` | `0x02` | DataPacketHeader binario + samples |
| `SER_MSG_TIMING` | `0x03` | TimingInfoPacket binario (26B) |

### Mensajes ASCII (dentro de SER_MSG_ASCII)

```
DATA,{node_id},{ch_id},{seq},{encoding},{first_idx},{count},{val1},{val2},...
TIMING,{node_id},{ch_id},{sample_rate_hz},{dt_us},{t0_epoch_ms},{t0_sample_idx}
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

### Comandos Serial (PC → Gateway)

```
CMD_START\n           → ACK,CMD_START,OK
CMD_STOP\n            → ACK,CMD_STOP,OK
CMD_SET_TIME,{ms}\n   → ACK,CMD_SET_TIME,OK
CMD_SET_RATE,{hz}\n   → ACK,CMD_SET_RATE,{hz}
```

---

## Quickstart

### 1. Compilar Base Station

```bash
cd Comunicacion_ESPNOW
pio run                    # Compilar
pio run -t upload          # Subir al ESP32-C3
pio device monitor         # Monitor serial (921600 baud)
```

### 2. Compilar Nodo(s)

Los nodos usan **Auto-ID** (Plug & Play). No necesitas configurar el `NODE_ID` manualmente.
Solo necesitas ajustar la MAC de tu gateway:

```cpp
// En Sender_ESPNOW/src/main.cpp:
#define BASESTATION_MAC {0xB8, 0xF8, 0x62, 0x04, 0x5F, 0x98}  // MAC de tu gateway
```

```bash
cd Sender_ESPNOW
pio run                    # Compilar
pio run -t upload          # Subir al ESP32-C3
```

### 3. Ejecutar NodeLab (App Desktop)

```bash
cd NodeLab/esp_sensor_connect
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements.txt
python main.py
```

---

## Regla de Oro para Modificaciones

> **Nunca actualices un solo componente sin actualizar los demás.**

Si cambias el protocolo:

1. ✏️ **`shared/tdma_protocol.h`** — Modificar struct/constante
2. ✏️ **`Comunicacion_ESPNOW/src/main.cpp`** — Actualizar gateway
3. ✏️ **`Sender_ESPNOW/src/main.cpp`** — Actualizar nodo
4. ✏️ **`NodeLab/.../protocol_parser.py`** — Actualizar parser
5. ✏️ **`SYSTEM_ARCHITECTURE.md`** — Actualizar documentación
6. 🔨 **`pio run`** en ambos firmware — Verificar compilación

---

## Hardware

| Componente | Board | Chip |
|---|---|---|
| Base Station | ESP32-C3-DevKitM-1 | ESP32-C3 |
| Nodos | ESP32-C3-DevKitC-02 | ESP32-C3 |

---

## Dependencias

### Firmware (PlatformIO)
- Platform: `espressif32`
- Framework: `arduino`
- Sin librerías externas (solo ESP-IDF + Arduino core)

### NodeLab (Python)
- `flet >= 0.25.0` — UI framework
- `pyserial >= 3.5` — Comunicación serie
- `pandas >= 2.0.0` — Exportación de datos

---

**Última actualización**: Abril 2026
**Protocolo**: v5
**Estado**: Desarrollo activo
