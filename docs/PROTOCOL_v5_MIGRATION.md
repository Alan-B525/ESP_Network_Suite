# Documentación de la Migración a Protocolo v5 y Fase 2/3 (ESP Network Suite)

Este documento detalla todas las modificaciones realizadas durante la transición del sistema desde la **v4 a la v5**, y las mejoras arquitectónicas introducidas en la interfaz de usuario (NodeLab) en las Fases 2 y 3 del proyecto.

---

## 1. Cambios en el Protocolo TDMA (v5)

El protocolo canonico (`tdma_protocol.h`) fue actualizado para priorizar la estabilidad, diagnóstico en tiempo real y escalabilidad (PnP).

### 1.1 Integridad de Datos mediante CRC-16 CCITT
Para eliminar la posibilidad de que ráfagas de ruido corrompan las muestras (generando saltos violentos o datos mal formateados), se incluyó un campo de validación CRC en las tramas críticas:
- Se añadió el campo `uint16_t crc16;` al final de `DataPacketHeader`.
- Se añadió el campo `uint16_t crc16;` al final de `TimingInfoPacket`.
- **Implementación**: El `Sender` ahora calcula el CRC-16 de todo el payload antes de emitirlo. El `Gateway` lo recalcula a su llegada; si no coinciden, la trama se cuenta como corrupta, se descarta silenciosamente, y se espera la retransmisión automática ARQ.

### 1.2 Auto-Asignación Dinámica de IDs (Plug & Play)
Se eliminó la necesidad de "quemar" el `NODE_ID` permanentemente en el firmware (`#define NODE_ID x` fue removido).
- **Proceso de descubrimiento**: Un nodo no configurado inicia con `node_id = 0`. Al arrancar, transmite su MAC Address en un `PKT_NODE_HELLO` y espera.
- **Asignación (Gateway)**: El Gateway detecta un Hello con ID `0`, busca en su tabla de ruteo si conoce esa MAC (o la asigna al primer ID libre entre 1 y 10). Luego, el Gateway responde con el nuevo `PKT_JOIN_ACK` indicando el ID oficial asignado.
- **Transición**: El `Sender` recibe el `JOIN_ACK`, configura su ID en memoria RAM, y prosigue a la fase de sincronización y muestreo.

### 1.3 Telemetría en Tiempo Real (Health Diagnostics)
Para monitorizar la salud de la red sin detener la captura de datos:
- Nuevo paquete: `PKT_NODE_TELEMETRY`.
- Se envía intermitentemente cada ~3 segundos (o cada N ciclos TDMA).
- **Contenido**:
  - `rssi_dbm` (Intensidad de señal wifi)
  - `battery_pct` (Estado de batería, actualmente simulado en firmware hasta conectar el ADC físico)
  - `temperature_c` (Temperatura del chip/batería)
  - `buffer_usage_pct` (Uso del ring-buffer)
  - `overflow_count` (Veces que el anillo ha perdido datos no procesados)
  - `tx_errors` (Cantidad de retransmisiones requeridas)
  - `uptime_s` (Tiempo en linea)

---

## 2. Actualizaciones en la Central de Control (NodeLab)

La interfaz en Python (Flet) fue rediseñada para aprovechar estas nuevas capacidades y parecerse a plataformas profesionales (ej: *SensorConnect*).

### 2.1 Parseo y Despliegue de Telemetría
- `ProtocolParser` fue expandido para soportar y decodificar tramas `TELEMETRY`.
- `SerialManager` almacena los últimos estados de telemetría por nodo.
- En `NodesView`, cada tarjeta de topología asimila estos datos, coloreando semánticamente (Verde, Amarillo, Rojo) el nivel de señal (RSSI) y la batería.

### 2.2 Dashboard Multi-Canal Modular (Estilo SensorConnect)
La vista analítica monolítica fue sustituida por un esquema de widgets dinámicos.
- Se creó el componente `ChannelWidget` (`ui/components/channel_widget.py`). Un pequeño tablero autocontenido con su propio lienzo de trazado Sparkline de alta resolución.
- El usuario puede **añadir widgets dinámicamente**, indicando específicamente qué `Nodo` y qué `Canal` desea monitorizar en pantalla.
- Los widgets pueden eliminarse en cualquier momento con su botón de cerrar.
- El motor de renderizado despacha independientemente a cada widget sus datos, optimizando el rendimiento (10 FPS).

### 2.3 Exportación de Datos Mejorada (DataLogger)
El sistema de persistencia a CSV (`data_logger.py`) fue reconstruido para ser compatible directamente con **MATLAB** y **Pandas** sin la necesidad de procesar los arrays de forma manual.
- Ahora calcula un `timestamp_ms` absoluto con precisión decimal combinando el `t0_epoch_ms` y el `dt_us` provenientes de la trama `TIMING_INFO`.
- **Formato CSV Exportado**:
  ```csv
  # t0_epoch_ms = 1700000000000
  # t0_sample_index = 0
  # dt_us = 1000
  # sample_rate_hz = 1000
  timestamp_ms,sample_index,value
  1700000000000.000,0,10.5
  1700000000001.000,1,10.6
  1700000000002.000,2,10.4
  ```
- Este modo de almacenamiento también rellena saltos abruptos (pérdidas reales de red) con celdas vacías o `NaN`, manteniendo la continuidad temporal en herramientas analíticas externas.

---

*Estado actual: Fase 3 finalizando diseño UI modular. Firmwares Gateway y Sender completamente compatibles y estables bajo la especificación v5.*
