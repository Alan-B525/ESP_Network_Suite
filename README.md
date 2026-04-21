# ESP Network Suite

Sistema de adquisición de datos inalámbrico basado en **ESP-NOW** con protocolo **TDMA v4** para redes de sensores ESP32.

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
│   └── tdma_protocol.h              #    Header CANÓNICO del protocolo v4
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
│       │   ├── protocol_parser.py   #    Deserializa tramas del gateway
│       │   ├── serial_manager.py    #    Conexión USB + hilo de lectura
│       │   └── data_logger.py       #    Persistencia CSV por nodo+canal
│       └── ui/                      #    Interfaz gráfica
│           ├── main_window.py
│           ├── design_tokens.py
│           ├── components/
│           └── views/
│
├── SYSTEM_ARCHITECTURE.md           # ← Contratos de datos entre componentes
├── README.md                        # ← Este archivo
└── .gitignore
```

---

## Protocolo TDMA v4

| Parámetro | Valor |
|---|---|
| Versión | **4** |
| Max Nodos | 10 |
| Max Canales/Nodo | 4 |
| Ciclo TDMA | 1000 ms |
| Slots por ciclo | 10 (round-robin adaptativo) |
| Ventana de Registro | 100 ms |
| Slot Time | 90000 µs (derivado) |
| Guard Time | 200 µs |
| Timeout Inactividad | 10000 ms |
| Rate Configurable | 1–10000 Hz (default 1000 Hz) |
| Encoding Soportado | INT16, FLOAT32 |

### Tipos de Paquete (over-the-air)

| Tipo | Código | Dirección | Tamaño | Descripción |
|---|---|---|---|---|
| `PKT_BEACON_SYNC` | `0x11` | Gateway → Broadcast | **78B** | Sincronización + schedule + RTC + rate |
| `PKT_NODE_HELLO` | `0x12` | Nodo → Gateway | 8B | Registro con capabilities |
| `PKT_DATA` | `0x13` | Nodo → Gateway | 14B+ | Datos de un canal (lossless) |
| `PKT_DIRECT_ACK` | `0x14` | Gateway → Nodo | 10B | Confirmación de recepción |
| `PKT_TIMING_INFO` | `0x15` | Nodo → Gateway | 24B | Sincronización temporal t0+dt |

### Formato Serial (Gateway → PC)

```
DATA,{node_id},{ch_id},{seq},{encoding},{first_idx},{count},{val1},{val2},...
TIMING,{node_id},{ch_id},{rate_hz},{dt_us},{t0_epoch_ms},{t0_sample_idx}
BEACON,{seq},STATE={s},NODES={n},SLOT_US={us},RATE={hz},RTC={ms},SCHED={id;...},ACKS={id:seq;...}
HELLO,{node_id},{mac},CH={mask},RATE={hz}
ACK,{command},{result}
NODE_JOIN,{node_id},{mac}
NODE_TIMEOUT,{node_id},{mac}
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

Editar `Sender_ESPNOW/src/main.cpp`:
```cpp
#define NODE_ID 1  // Cambiar para cada nodo (1-10)
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
**Protocolo**: v4
**Estado**: Desarrollo activo
