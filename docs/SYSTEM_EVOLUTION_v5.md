# Evolución del Sistema ESP Network Suite: Arquitectura y Justificación (v4 → v5)

Este documento detalla los cambios fundamentales introducidos en la suite de comunicación (Gateway, Sender y NodeLab) y explica *por qué* son necesarios para transformar un prototipo funcional en una herramienta de nivel industrial y profesional, inspirada en estándares como LXRS/LXRS+ y plataformas analíticas como MicroStrain SensorConnect.

---

## 1. Integridad de Datos (CRC-16 End-to-End)

**El Problema:**
En la v4, el protocolo confiaba exclusivamente en la comprobación de errores a nivel físico (Wi-Fi/ESP-NOW) y en el enmarcado COBS del puerto serie USB. Si ocurría un desbordamiento de buffer, corrupción eléctrica en el cable USB, o interferencia durante el procesamiento de la interrupción en el Gateway, los datos basura se asumían como válidos. Esto podía provocar "saltos" irreales en las mediciones o caídas críticas del parser de Python al intentar descifrar basura binaria.

**La Solución:**
Se introdujo una comprobación cíclica de redundancia (CRC-16 CCITT) nativa dentro de las propias estructuras de datos críticas (`DataPacketHeader` y `TimingInfoPacket`). 

**Por qué es crucial:**
Garantiza una filosofía "Lossless" estricta: si un paquete llega a NodeLab, es matemáticamente seguro que los datos son idénticos a como salieron del ADC del nodo emisor. Si la validación criptográfica falla en el Gateway, el paquete se descarta de forma silenciosa y controlada, y el protocolo ARQ (Auto-Repeat-Request) solicitará su retransmisión limpia de forma transparente al usuario.

---

## 2. Auto-Asignación de IDs (Plug & Play)

**El Problema:**
Anteriormente, cada nodo físico necesitaba tener su identificador (`NODE_ID`) programado "a fuego" (hardcoded) en el código fuente de C++ (ej. `#define NODE_ID 1`). Si querías escalar una red a 10 o 50 nodos, tenías que mantener y compilar un firmware distinto para cada hardware físico, lo cual es inmanejable logísticamente.

**La Solución:**
Se implementó un handshake dinámico basado en la dirección física MAC del microcontrolador ESP32:
1. El nodo arranca en estado "huérfano" (`node_id = 0`) y transmite repetidamente un paquete de descubrimiento `HELLO` con su MAC address única.
2. El Gateway actúa como maestro, manteniendo una tabla de enrutamiento interna. Al ver una MAC desconocida que solicita unirse, le asigna el primer ID disponible en el slot de red.
3. El Gateway responde con un paquete `JOIN_ACK` indicando al nodo cuál es su nueva identidad oficial, permitiéndole acoplarse al Round-Robin TDMA.

**Por qué es crucial:**
Permite un sistema "Flashear y Olvidar". Puedes quemar el mismo archivo binario genérico en infinidad de placas idénticas; al encenderlas, el sistema orquestará el orden de la red automáticamente sin fricción de software.

---

## 3. Telemetría de Diagnóstico (Node Health)

**El Problema:**
NodeLab mostraba en su interfaz barras de "Batería" y "Señal (RSSI)", pero en la versión de legado estos valores eran completamente simulados con generadores aleatorios simplemente para justificar visualmente la UI.

**La Solución:**
Se diseñó un nuevo paquete de protocolo `PKT_NODE_TELEMETRY`. Cada nodo ahora extrae un breve periodo de su ciclo de adquisición para medir e informar sobre su salud interna real (Uso límite del Ring Buffer en RAM, Calidad del enlace de radiofrecuencia RSSI en dBm, Temperatura interna del SoC, y un historial de Errores/Retransmisiones).

**Por qué es crucial:**
Para un despliegue de laboratorio o industrial, la predictibilidad de fallo es mandatoria. Saber en tiempo real que a un sensor remoto le resta poca energía, o que está a punto de perder la línea de visión (RSSI crítico), evita perder datos irreparables de un experimento en curso.

---

## 4. Reestructuración de NodeLab: Dashboard Multi-Canal Modular

**El Problema:**
El panel analítico original en Flet dibujaba todas las trazas de todos los nodos obligatoriamente superpuestos en un solo lienzo. Además, el protocolo ya soportaba inherentemente hardware multi-canal (ej. acelerómetros triaxiales + termocupla en el mismo nodo), pero la interfaz forzaba al usuario a monitorear un único índice de canal global.

**La Solución:**
Se reescribió el Dashboard adoptando un paradigma modular. En lugar de un gráfico estático, se provee un sistema de *widgets acoplables*. El usuario puede pulsar "Añadir Gráfico" e instanciar en pantalla módulos individuales para un Nodo y un Canal específicos.

**Por qué es crucial:**
Otorga el control de análisis absoluto al técnico. Le permite correlacionar libremente fenómenos: puede apilar visualmente el *Eje Z* (Canal 2) del Nodo 1 al lado del *Eje X* (Canal 0) del Nodo 3, filtrando el ruido informativo y construyendo una central de comando a medida del ensayo actual.

---

## 5. Exportación de Datos Temporales Absolutos (Data Logger)

**El Problema:**
El módulo de escritura CSV nativo guardaba simplemente un par de valores: el `índice de la muestra` consecutivo y el `valor numérico`. Esto dejaba al analista posterior con la pesada tarea de recalcular la base de tiempo y alinear arrays en hojas de cálculo externas.

**La Solución:**
El Logger procesa activamente los paquetes auxiliares de sincronización (`TIMING_INFO`) en segundo plano. Interpola la frecuencia de muestreo configurada (`dt_us`), la marca de época absoluta de inicio dictaminada por el Gateway (`t0_epoch_ms`) y el incremento de índice secuencial. El CSV exportado guarda directamente el valor flotante real `timestamp_ms`.

**Por qué es crucial:**
Significa exportación directa y profesional (Zero-Friction). El usuario obtiene archivos `.csv` listos para ingesta cruda en algoritmos de post-procesamiento de MATLAB, Simulink o librerías de Python Pandas, con su vector de tiempo UTC perfectamente alineado temporalmente y documentado en la metadata del mismo archivo.
