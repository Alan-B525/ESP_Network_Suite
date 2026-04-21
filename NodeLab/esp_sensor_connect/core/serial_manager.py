"""
serial_manager.py - Gestor de comunicacion serie en hilo separado
=================================================================

Maneja la conexion USB con la Base Station ESP32 (Gateway TDMA v3).

ARQUITECTURA CLAVE:
  La lectura del puerto serie se ejecuta en un Thread dedicado (daemon)
  para nunca bloquear la interfaz grafica de Flet. Los datos parseados
  se depositan en una queue.Queue thread-safe que es consumida por:
    1. El DataLogger (para persistir a CSV)
    2. Un buffer circular interno (para que la UI lea los ultimos N puntos)

Flujo de datos:
  Puerto Serie --> Reader Thread --> ProtocolParser
                                         |
                               +---------+---------+
                               v                   v
                          data_queue             _node_data_buffer
                        (DataLogger)               (UI graficos)
"""

import threading
import queue
import time
from typing import Optional, Callable

import serial
import serial.tools.list_ports

from core.protocol_parser import (
    ProtocolParser, DataFrame, TimingFrame, BeaconFrame, HelloFrame,
    JoinFrame, TimeoutFrame, LossFrame, StatsFrame, BootFrame, WarnFrame,
    AckFrame,
)


class SerialManager:
    """
    Gestor del puerto serie con lectura en hilo separado.

    Principios de diseno:
      - Thread-safety: todo acceso a estado compartido usa Lock
      - Non-blocking: la UI nunca espera por operaciones de I/O
      - Graceful shutdown: el hilo se detiene limpiamente al desconectar

    Attributes:
        data_queue: Cola thread-safe donde se depositan los DataFrames
                    parseados para consumo del DataLogger.
        is_connected: Indica si hay una conexion serie activa.
        is_acquiring: Indica si la adquisicion esta en curso.
    """

    # Baudrates comunes para comunicacion con ESP32
    BAUDRATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
    DEFAULT_BAUDRATE = 921600  # Coincide con el gateway TDMA v3

    def __init__(self):
        # ---- Cola compartida para el DataLogger ----
        # maxsize previene consumo infinito de RAM si el logger se atrasa
        self.data_queue: queue.Queue = queue.Queue(maxsize=50000)

        # ---- Estado de conexion (protegido por _lock) ----
        self._lock = threading.Lock()
        self._serial: Optional[serial.Serial] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = threading.Event()  # Senal para controlar el hilo

        # ---- Estado observable por la UI ----
        self.is_connected: bool = False
        self.is_acquiring: bool = False
        self.current_port: str = ""
        self.current_baudrate: int = self.DEFAULT_BAUDRATE

        # ---- Estado de nodos ----
        self.active_nodes: list[str] = []  # MACs
        self.nodes_count: int = 0

        # ---- Buffer circular de datos por nodo (para la UI) ----
        # Estructura: {node_id: [DataFrame, DataFrame, ...]}
        self._node_data_buffer: dict[int, list[DataFrame]] = {}
        self._buffer_max_size = 200  # Puntos maximos por nodo en memoria

        # ---- Contadores para deteccion de perdida de paquetes ----
        # {node_id: ultimo_seq_recibido}
        self._last_sequence: dict[int, int] = {}
        # {node_id: total_paquetes_perdidos}
        self.packet_loss: dict[int, int] = {}
        # {node_id: total_paquetes_recibidos}
        self.packets_received: dict[int, int] = {}

        # ---- Info de nodos (MACs, etc.) ----
        self._node_macs: dict[int, str] = {}

        # ---- Ultimo beacon recibido ----
        self.last_beacon: Optional[BeaconFrame] = None

        # ---- Ultimo bloque STATS recibido ----
        self.last_stats: Optional[StatsFrame] = None

        # ---- Callbacks para notificaciones a la UI ----
        self._on_status_callback: Optional[Callable] = None
        self._on_ack_callback: Optional[Callable] = None
        self._on_connection_change: Optional[Callable] = None
        self._on_node_event: Optional[Callable] = None

        # ---- Parser de protocolo ----
        self._parser = ProtocolParser()

    # ============================================================
    # Metodos publicos - Deteccion de puertos
    # ============================================================

    @staticmethod
    def list_available_ports() -> list[dict]:
        """
        Lista todos los puertos COM disponibles en el sistema.

        Returns:
            Lista de diccionarios con informacion de cada puerto:
            [{'device': 'COM3', 'description': '...', 'manufacturer': '...'}]
        """
        ports = serial.tools.list_ports.comports()
        return [
            {
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid,
                "manufacturer": port.manufacturer or "Desconocido",
            }
            for port in sorted(ports, key=lambda p: p.device)
        ]

    # ============================================================
    # Metodos publicos - Conexion/Desconexion
    # ============================================================

    def connect(self, port: str, baudrate: int = DEFAULT_BAUDRATE,
                timeout: float = 1.0) -> bool:
        """
        Establece conexion con el puerto serie especificado.

        Args:
            port: Nombre del puerto (ej: 'COM3').
            baudrate: Velocidad de comunicacion en baudios.
            timeout: Timeout de lectura del buffer serie (segundos).

        Returns:
            True si la conexion fue exitosa, False en caso contrario.
        """
        if self.is_connected:
            self.disconnect()

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )

            self.is_connected = True
            self.current_port = port
            self.current_baudrate = baudrate

            # Iniciar el hilo de lectura (daemon = muere con la app)
            self._running.set()
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name="SerialReader",
                daemon=True,
            )
            self._reader_thread.start()

            print(f"[SERIAL] Conectado a {port} @ {baudrate} baud")

            # Sincronizar hora del PC con el Base Station (v4)
            self._sync_time()

            if self._on_connection_change:
                self._on_connection_change(True)

            return True

        except serial.SerialException as e:
            print(f"[SERIAL] Error al conectar a {port}: {e}")
            self.is_connected = False
            self._serial = None
            return False

    def disconnect(self):
        """Cierra la conexion serie y detiene el hilo de lectura."""
        self._running.clear()

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)

        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception as e:
                print(f"[SERIAL] Error al cerrar puerto: {e}")

        self._serial = None
        self.is_connected = False
        self.is_acquiring = False
        self.current_port = ""
        self.active_nodes = []
        self.nodes_count = 0

        print("[SERIAL] Desconectado")

        if self._on_connection_change:
            self._on_connection_change(False)

    # ============================================================
    # Metodos publicos - Envio de comandos
    # ============================================================

    def send_command(self, command: str) -> bool:
        """
        Envia un comando al Base Station a traves del puerto serie.

        Args:
            command: Comando completo a enviar.

        Returns:
            True si el envio fue exitoso, False si hay error.
        """
        if not self.is_connected or not self._serial:
            print("[SERIAL] No hay conexion activa para enviar comandos")
            return False

        try:
            if not command.endswith('\n'):
                command += '\n'

            self._serial.write(command.encode('utf-8'))
            self._serial.flush()
            print(f"[SERIAL] Comando enviado: {command.strip()}")
            return True

        except serial.SerialException as e:
            print(f"[SERIAL] Error al enviar comando: {e}")
            return False

    def start_acquisition(self) -> bool:
        """
        Inicia la adquisicion de datos.

        Gateway TDMA v4: envía CMD_START al Base Station para que
        los nodos cambien a estado ACQUIRING y empiecen a transmitir.
        """
        if not self.send_command("CMD_START"):
            print("[SERIAL] Error al enviar CMD_START")
            return False

        self.is_acquiring = True
        print("[SERIAL] CMD_START enviado - adquisicion iniciada")
        return True

    def stop_acquisition(self) -> bool:
        """
        Detiene la adquisicion de datos.

        Envía CMD_STOP al Base Station para cambiar a estado IDLE.
        """
        if self.is_connected:
            self.send_command("CMD_STOP")

        self.is_acquiring = False
        print("[SERIAL] CMD_STOP enviado - adquisicion detenida")
        return True

    def _sync_time(self):
        """Envía la hora UTC del PC al Base Station para sincronizacion RTC."""
        import time
        epoch_ms = int(time.time() * 1000)
        self.send_command(f"CMD_SET_TIME,{epoch_ms}")
        print(f"[SERIAL] Hora sincronizada: {epoch_ms} ms")
        return True

    def set_sample_rate(self, rate_hz: int) -> bool:
        """
        Configura la frecuencia de muestreo en todos los nodos.

        Envía CMD_SET_RATE al Base Station, que lo incluirá en el
        beacon. Los nodos reconfigurán su timer automáticamente.

        Args:
            rate_hz: Frecuencia de muestreo en Hz (1-10000).

        Returns:
            True si el comando fue enviado exitosamente.
        """
        if rate_hz < 1 or rate_hz > 10000:
            print(f"[SERIAL] Rate fuera de rango: {rate_hz} Hz (1-10000)")
            return False

        if not self.send_command(f"CMD_SET_RATE,{rate_hz}"):
            print("[SERIAL] Error al enviar CMD_SET_RATE")
            return False

        print(f"[SERIAL] CMD_SET_RATE,{rate_hz} enviado")
        return True

    # ============================================================
    # Metodos publicos - Acceso a datos (thread-safe)
    # ============================================================

    def get_node_data(self, node_id: int, count: int = 100) -> list[DataFrame]:
        """
        Obtiene los ultimos N datos de un nodo especifico.

        Thread-safe: usa Lock para acceder al buffer compartido.
        """
        with self._lock:
            buffer = self._node_data_buffer.get(node_id, [])
            return list(buffer[-count:])

    def get_all_node_ids(self) -> list[int]:
        """Retorna la lista de IDs de nodos que tienen datos en el buffer."""
        with self._lock:
            return sorted(self._node_data_buffer.keys())

    def get_packet_loss_rate(self, node_id: int) -> float:
        """
        Calcula el porcentaje de perdida de paquetes para un nodo.

        Returns:
            Porcentaje de perdida (0.0 a 100.0), o 0.0 si no hay datos.
        """
        received = self.packets_received.get(node_id, 0)
        lost = self.packet_loss.get(node_id, 0)
        total = received + lost
        if total == 0:
            return 0.0
        return (lost / total) * 100.0

    def get_node_mac(self, node_id: int) -> str:
        """Retorna la MAC de un nodo, o cadena vacia si no se conoce."""
        return self._node_macs.get(node_id, "")

    # ============================================================
    # Metodos publicos - Registro de callbacks
    # ============================================================

    def set_on_status(self, callback: Callable):
        """Registra callback que se invoca al recibir tramas STATS."""
        self._on_status_callback = callback

    def set_on_ack(self, callback: Callable):
        """Registra callback que se invoca al recibir tramas ACK."""
        self._on_ack_callback = callback

    def set_on_connection_change(self, callback: Callable):
        """Registra callback que se invoca al conectar/desconectar."""
        self._on_connection_change = callback

    def set_on_node_event(self, callback: Callable):
        """Registra callback para JOIN/TIMEOUT/HELLO events."""
        self._on_node_event = callback

    # ============================================================
    # Hilo de lectura (ejecucion en background)
    # ============================================================

    def _reader_loop(self):
        """
        Bucle principal de lectura del puerto serie.
        *** SE EJECUTA EN UN THREAD SEPARADO ***
        """
        print("[SERIAL] Hilo de lectura iniciado")

        while self._running.is_set():
            try:
                if not self._serial or not self._serial.is_open:
                    time.sleep(0.1)
                    continue

                if self._serial.in_waiting > 0:
                    raw_line = self._serial.readline().decode(
                        'utf-8', errors='replace'
                    )

                    if raw_line.strip():
                        frame = self._parser.parse(raw_line)
                        if frame is not None:
                            self._dispatch_frame(frame)
                else:
                    time.sleep(0.001)

            except serial.SerialException as e:
                print(f"[SERIAL] Error de lectura: {e}")
                self._running.clear()
                self.is_connected = False
                self.is_acquiring = False
                if self._on_connection_change:
                    self._on_connection_change(False)
                break

            except Exception as e:
                print(f"[SERIAL] Error inesperado en lectura: {e}")
                time.sleep(0.01)

        print("[SERIAL] Hilo de lectura finalizado")

    # ============================================================
    # Distribucion interna de tramas
    # ============================================================

    def _dispatch_frame(self, frame):
        """Distribuye la trama parseada a los consumidores apropiados."""
        if isinstance(frame, DataFrame):
            self._handle_data_frame(frame)
        elif isinstance(frame, TimingFrame):
            self._handle_timing_frame(frame)
        elif isinstance(frame, BeaconFrame):
            self._handle_beacon_frame(frame)
        elif isinstance(frame, (HelloFrame, JoinFrame)):
            self._handle_join_event(frame)
        elif isinstance(frame, TimeoutFrame):
            self._handle_timeout_event(frame)
        elif isinstance(frame, LossFrame):
            self._handle_loss_frame(frame)
        elif isinstance(frame, StatsFrame):
            self._handle_stats_frame(frame)
        elif isinstance(frame, BootFrame):
            self._handle_boot_frame(frame)
        elif isinstance(frame, WarnFrame):
            print(f"[SERIAL] WARN: {frame.warn_type} - {frame.detail}")
        elif isinstance(frame, AckFrame):
            self._handle_ack_frame(frame)

    def _handle_data_frame(self, frame: DataFrame):
        """Procesa una trama de datos: encola para logger y actualiza buffer UI."""
        # 1. Enviar a la cola del DataLogger
        try:
            self.data_queue.put_nowait(frame)
        except queue.Full:
            try:
                self.data_queue.get_nowait()
                self.data_queue.put_nowait(frame)
            except queue.Empty:
                pass

        # 2. Deteccion de perdida de paquetes por gaps en secuencia
        node_id = frame.node_id
        if node_id not in self.packets_received:
            self.packets_received[node_id] = 0
            self.packet_loss[node_id] = 0

        self.packets_received[node_id] += 1

        if node_id in self._last_sequence:
            expected_seq = self._last_sequence[node_id] + 1
            if frame.sequence > expected_seq:
                lost = frame.sequence - expected_seq
                self.packet_loss[node_id] += lost
        self._last_sequence[node_id] = frame.sequence

        # 3. Actualizar buffer circular por nodo
        with self._lock:
            if node_id not in self._node_data_buffer:
                self._node_data_buffer[node_id] = []

            self._node_data_buffer[node_id].append(frame)

            if len(self._node_data_buffer[node_id]) > self._buffer_max_size:
                self._node_data_buffer[node_id] = \
                    self._node_data_buffer[node_id][-self._buffer_max_size:]

    def _handle_timing_frame(self, frame: TimingFrame):
        """Procesa TIMING_INFO: almacena t0/dt por nodo+canal para reconstrucción temporal."""
        key = (frame.node_id, frame.channel_id)
        with self._lock:
            if not hasattr(self, '_timing_info'):
                self._timing_info = {}
            self._timing_info[key] = {
                'sample_rate_hz': frame.sample_rate_hz,
                'dt_us': frame.dt_us,
                't0_epoch_ms': frame.t0_epoch_ms,
                't0_sample_index': frame.t0_sample_index,
            }
        print(f"[SERIAL] TIMING node={frame.node_id} ch={frame.channel_id} "
              f"rate={frame.sample_rate_hz}Hz dt={frame.dt_us}us")

    def _handle_beacon_frame(self, frame: BeaconFrame):
        """Procesa beacon: actualiza estado de red."""
        self.last_beacon = frame
        self.nodes_count = frame.active_nodes

    def _handle_join_event(self, frame):
        """Procesa HELLO o NODE_JOIN: registra MAC del nodo."""
        self._node_macs[frame.node_id] = frame.mac
        if frame.mac and frame.mac not in self.active_nodes:
            self.active_nodes.append(frame.mac)
            self.nodes_count = len(self.active_nodes)

        event_type = "JOIN" if isinstance(frame, JoinFrame) else "HELLO"
        print(f"[SERIAL] {event_type}: Nodo {frame.node_id} - {frame.mac}")

        if self._on_node_event:
            self._on_node_event(frame)

    def _handle_timeout_event(self, frame: TimeoutFrame):
        """Procesa NODE_TIMEOUT: remueve nodo de la lista activa."""
        if frame.mac in self.active_nodes:
            self.active_nodes.remove(frame.mac)
            self.nodes_count = len(self.active_nodes)

        print(f"[SERIAL] TIMEOUT: Nodo {frame.node_id} - {frame.mac}")

        if self._on_node_event:
            self._on_node_event(frame)

    def _handle_loss_frame(self, frame: LossFrame):
        """Procesa LOSS: incrementa contador de perdida del gateway."""
        node_id = frame.node_id
        if node_id not in self.packet_loss:
            self.packet_loss[node_id] = 0

        lost_count = frame.got_seq - frame.expected_seq
        if lost_count > 0:
            self.packet_loss[node_id] += lost_count

    def _handle_stats_frame(self, frame: StatsFrame):
        """Procesa bloque STATS: actualiza metricas globales."""
        self.last_stats = frame
        self.nodes_count = frame.active_nodes

        # Actualizar loss/rx desde stats del gateway (fuente de verdad)
        for node_entry in frame.nodes:
            nid = node_entry.node_id
            self._node_macs[nid] = node_entry.mac
            # Solo sobreescribir si el gateway tiene datos mas completos
            if node_entry.rx > 0:
                self.packets_received[nid] = node_entry.emit
                self.packet_loss[nid] = node_entry.lost

        if self._on_status_callback:
            self._on_status_callback(frame)

    def _handle_boot_frame(self, frame: BootFrame):
        """Procesa BOOT: log informativo."""
        print(f"[SERIAL] BOOT: {frame.key} = {frame.value}")

    def _handle_ack_frame(self, frame: AckFrame):
        """Procesa ACK: notifica a la UI."""
        if self._on_ack_callback:
            self._on_ack_callback(frame)

    # ============================================================
    # Limpieza
    # ============================================================

    def cleanup(self):
        """
        Limpieza completa: desconectar y liberar todos los recursos.
        Llamar al cerrar la aplicacion.
        """
        self.disconnect()

        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

        with self._lock:
            self._node_data_buffer.clear()
            self._last_sequence.clear()
            self.packet_loss.clear()
            self.packets_received.clear()
