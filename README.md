# ESP Network Suite

Sistema de adquisición de datos inalámbrico basado en **ESP-NOW** con protocolo **TDMA v3** (Time Division Multiple Access) para redes de sensores industriales ESP32.

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
│   └── tdma_protocol.h              #    Header CANÓNICO del protocolo v3
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
│       │   └── data_logger.py       #    Persistencia CSV
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

## Protocolo TDMA v3

| Parámetro | Valor |
|---|---|
| Versión | 3 |
| Max Nodos | 10 |
| Ciclo TDMA | 1000 ms |
| Ventana de Registro | 120 ms |
| Guard Time | 200 µs |
| Timeout Inactividad | 5000 ms |
| Encoding Soportado | INT16, FLOAT32 |

### Tipos de Paquete (over-the-air)

| Tipo | Código | Dirección | Descripción |
|---|---|---|---|
| `PKT_BEACON_SYNC` | `0x11` | Gateway → Broadcast | Sincronización + schedule |
| `PKT_NODE_HELLO` | `0x12` | Nodo → Gateway | Registro del nodo |
| `PKT_DATA` | `0x13` | Nodo → Gateway | Datos de sensores |
| `PKT_DIRECT_ACK` | `0x14` | Gateway → Nodo (unicast) | Confirmación de recepción |

### Formato Serial (Gateway → PC)

```
DATA_INT16,node_id,seq,gw_rx_us,node_ts_us,val1,val2,...
DATA_FLOAT,node_id,seq,gw_rx_us,node_ts_us,val1,val2,...
BEACON,seq,NODES=n,SLOT_US=us,REG_MS=ms,ACKS=id:seq;id:seq
HELLO,node_id,mac
NODE_JOIN,node_id,mac
NODE_TIMEOUT,node_id,mac
LOSS,node_id,EXPECTED=x,GOT=y
BOOT,key[,value]
STATS_BEGIN / STATS,...  / NODE,... / STATS_END
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

Si agregas un nuevo campo de sensor (ej: `battery_level`):

1. ✏️ **`shared/tdma_protocol.h`** — Agregar campo al struct
2. ✏️ **`Comunicacion_ESPNOW/src/main.cpp`** — Incluir en `Serial.print()` del CSV
3. ✏️ **`Sender_ESPNOW/src/main.cpp`** — Llenar el campo en el paquete
4. ✏️ **`NodeLab/.../protocol_parser.py`** — Actualizar parser para el nuevo campo
5. ✏️ **`NodeLab/.../ui/`** — Mostrar en la interfaz

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
**Protocolo**: v3  
**Estado**: Producción (funcional, mejoras en progreso)
