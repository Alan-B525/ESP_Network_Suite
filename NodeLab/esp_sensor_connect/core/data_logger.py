"""
data_logger.py - Persistencia robusta de datos a CSV
=====================================================

Lee DataFrames de la cola compartida (queue.Queue) y los escribe
en archivos CSV organizados por sesión.

ROBUSTEZ:
  - Cada sesión crea su propia carpeta con timestamp
  - Los datos se escriben con flush periódico (cada 5 segundos)
  - Si la aplicación se cierra inesperadamente, los datos ya flusheados
    están seguros en disco
  - Usa file.flush() + os.fsync() para máxima garantía

ESTRUCTURA DE ARCHIVOS:
  data_sessions/
  └── 2024-01-15_14-30-45/
      ├── session_info.txt
      ├── node_1.csv
      ├── node_2.csv
      └── ...
"""

import csv
import os
import threading
import time
import queue
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.protocol_parser import DataFrame, TimingFrame


class DataLogger:
    """
    Logger de datos que consume de una Queue y persiste a CSV.

    Opera en su propio Thread dedicado, leyendo DataFrames de la
    cola compartida con SerialManager.

    Attributes:
        session_path: Ruta de la carpeta de sesión actual.
        is_logging: Indica si el logger está activo.
        total_records: Contador total de registros escritos.
    """

    # Intervalo de flush a disco (en segundos)
    FLUSH_INTERVAL = 5.0

    # Directorio base para las sesiones de datos
    DEFAULT_DATA_DIR = "data_sessions"

    def __init__(self, data_queue: queue.Queue, data_dir: str = DEFAULT_DATA_DIR):
        """
        Inicializa el DataLogger.

        Args:
            data_queue: Cola de donde se leen los DataFrames (viene de SerialManager).
            data_dir: Directorio base donde se crean las carpetas de sesión.
        """
        self._data_queue = data_queue
        self._data_dir = data_dir
        self._logger_thread: Optional[threading.Thread] = None
        self._running = threading.Event()

        # Estado público
        self.session_path: Optional[Path] = None
        self.is_logging: bool = False
        self.total_records: int = 0

        # Internos para gestión de archivos CSV
        # csv_key -> {'file': file_obj, 'writer': csv_writer, 'count': int, 'last_written_index': int}
        self._csv_files: dict[tuple[int, int], dict] = {}
        self._timing_info: dict[tuple[int, int], TimingFrame] = {}
        self._last_flush_time: float = 0.0

    # ============================================================
    # Control del Logger
    # ============================================================

    def start_session(self) -> str:
        """
        Inicia una nueva sesión de grabación.

        Crea una carpeta con timestamp, inicializa los archivos necesarios
        e inicia el hilo de escritura.

        Returns:
            Ruta de la carpeta de sesión creada.
        """
        # Crear carpeta de sesión con timestamp
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_path = Path(self._data_dir) / timestamp_str
        self.session_path.mkdir(parents=True, exist_ok=True)

        # Crear archivo de información de sesión
        info_file = self.session_path / "session_info.txt"
        with open(info_file, 'w', encoding='utf-8') as f:
            f.write(f"Sesión de Adquisición de Datos\n")
            f.write(f"{'=' * 40}\n")
            f.write(f"Fecha de inicio: {datetime.now().isoformat()}\n")
            f.write(f"Directorio: {self.session_path.absolute()}\n")

        # Resetear contadores
        self.total_records = 0
        self._csv_files = {}
        self._last_flush_time = time.time()

        # Iniciar hilo de escritura
        self.is_logging = True
        self._running.set()
        self._logger_thread = threading.Thread(
            target=self._writer_loop,
            name="DataLogger",
            daemon=True,
        )
        self._logger_thread.start()

        print(f"[LOGGER] Sesion iniciada: {self.session_path}")
        return str(self.session_path)

    def stop_session(self):
        """
        Detiene la sesión de grabación de forma limpia.

        Secuencia de cierre:
          1. Señalizar al hilo que termine
          2. Esperar a que procese los datos pendientes
          3. Hacer flush final de todos los archivos
          4. Cerrar todos los archivos CSV
        """
        self.is_logging = False
        self._running.clear()

        # Esperar a que el hilo termine
        if self._logger_thread and self._logger_thread.is_alive():
            self._logger_thread.join(timeout=5.0)

        # Flush final y cierre de archivos
        self._flush_all_files()
        self._close_all_files()

        # Actualizar archivo de información de sesión
        if self.session_path:
            info_file = self.session_path / "session_info.txt"
            try:
                with open(info_file, 'a', encoding='utf-8') as f:
                    f.write(f"Fecha de fin: {datetime.now().isoformat()}\n")
                    f.write(f"Total de registros: {self.total_records}\n")
            except Exception as e:
                print(f"[LOGGER] Error al actualizar session_info: {e}")

        print(f"[LOGGER] Sesión finalizada. Total: {self.total_records} registros")

    # ============================================================
    # Hilo de escritura (ejecución en background)
    # ============================================================

    def _writer_loop(self):
        """
        Bucle principal de escritura a CSV.
        *** SE EJECUTA EN UN THREAD SEPARADO ***

        Lee DataFrames de la cola compartida y los escribe en archivos CSV
        separados por nodo. Hace flush periódico cada FLUSH_INTERVAL segundos.
        """
        print("[LOGGER] Hilo de escritura iniciado")

        while self._running.is_set():
            try:
                # Intentar leer un frame de la cola (con timeout para no bloquear)
                try:
                    frame = self._data_queue.get(timeout=0.1)
                except queue.Empty:
                    # No hay datos: verificar si toca flush periódico
                    self._periodic_flush()
                    continue

                # Procesar tramas relevantes para el logger
                if isinstance(frame, DataFrame):
                    self._write_data_frame(frame)
                elif isinstance(frame, TimingFrame):
                    self._handle_timing_frame(frame)

                # Flush periódico cada FLUSH_INTERVAL segundos
                self._periodic_flush()

            except Exception as e:
                print(f"[LOGGER] Error en escritura: {e}")
                time.sleep(0.01)

        # Al salir del bucle, drenar datos restantes en la cola
        self._drain_remaining_data()
        print("[LOGGER] Hilo de escritura finalizado")

    def _drain_remaining_data(self):
        """
        Drena y escribe todos los datos restantes en la cola.
        Se llama al finalizar el hilo para no perder datos en memoria.
        """
        drained = 0
        while not self._data_queue.empty():
            try:
                frame = self._data_queue.get_nowait()
                if isinstance(frame, DataFrame):
                    self._write_data_frame(frame)
                    drained += 1
                elif isinstance(frame, TimingFrame):
                    self._handle_timing_frame(frame)
            except queue.Empty:
                break

        if drained > 0:
            print(f"[LOGGER] Drenados {drained} registros pendientes")

    # ============================================================
    # Escritura CSV
    # ============================================================

    def _handle_timing_frame(self, frame: TimingFrame):
        """Almacena la metadata de tiempo para usarla en los encabezados del CSV."""
        csv_key = (frame.node_id, frame.channel_id)
        self._timing_info[csv_key] = frame

    def _write_data_frame(self, frame: DataFrame):
        """
        Escribe un DataFrame en el archivo CSV de forma continua.
        Rellena con NaN los saltos si se detecta pérdida de paquetes.
        """
        csv_key = (frame.node_id, frame.channel_id)

        # Crear archivo CSV para este nodo+canal si no existe
        if csv_key not in self._csv_files:
            self._create_csv_for_node(frame.node_id, frame.channel_id)

        csv_info = self._csv_files[csv_key]
        writer = csv_info['writer']
        last_idx = csv_info['last_written_index']
        start_idx = frame.first_sample_index

        timing = self._timing_info.get(csv_key) or self._timing_info.get((frame.node_id, 255))
        t0 = timing.t0_epoch_ms if timing else 0.0
        dt_us = timing.dt_us if timing else 0.0
        idx0 = timing.t0_sample_index if timing else 0

        def get_ts(idx: int) -> str:
            if dt_us == 0.0:
                return ""
            return f"{t0 + ((idx - idx0) * dt_us) / 1000.0:.3f}"

        # Si detectamos un salto (paquete perdido), insertamos NaNs
        if last_idx != -1 and start_idx > last_idx + 1:
            gap_size = start_idx - (last_idx + 1)
            # Para evitar cuelgues por errores gigantes, limitamos el gap
            if gap_size < 100000:
                for i in range(gap_size):
                    idx = last_idx + 1 + i
                    writer.writerow([get_ts(idx), idx, 'NaN'])
                    self.total_records += 1

        # Si recibimos datos solapados o atrasados (duplicados/desorden)
        if last_idx != -1 and start_idx <= last_idx:
            skip_count = last_idx - start_idx + 1
            if skip_count >= len(frame.values):
                return  # Paquete totalmente redundante, lo ignoramos
            values_to_write = frame.values[skip_count:]
            curr_idx = last_idx + 1
        else:
            values_to_write = frame.values
            curr_idx = start_idx

        # Escribimos las muestras verticalmente
        for val in values_to_write:
            writer.writerow([get_ts(curr_idx), curr_idx, val])
            curr_idx += 1
            self.total_records += 1

        csv_info['count'] += len(values_to_write)
        csv_info['last_written_index'] = curr_idx - 1

    def _create_csv_for_node(self, node_id: int, channel_id: int):
        """
        Crea el archivo CSV continuo para un nodo+canal específico,
        escribiendo la cabecera t0 y dt si está disponible.
        """
        if not self.session_path:
            return

        filepath = self.session_path / f"node_{node_id}_ch{channel_id}.csv"

        # Abrir archivo en modo write
        file_obj = open(filepath, 'w', newline='', encoding='utf-8')
        
        csv_key = (node_id, channel_id)
        # El nodo suele enviar channel_id = 255 (0xFF) para indicar que el timing aplica a todos los canales
        timing = self._timing_info.get(csv_key) or self._timing_info.get((node_id, 255))

        # Escribir metadatos como comentarios
        if timing:
            file_obj.write(f"# t0_epoch_ms = {timing.t0_epoch_ms}\n")
            file_obj.write(f"# t0_sample_index = {timing.t0_sample_index}\n")
            file_obj.write(f"# dt_us = {timing.dt_us}\n")
            file_obj.write(f"# sample_rate_hz = {timing.sample_rate_hz}\n")
        else:
            file_obj.write("# t0_epoch_ms = unknown\n")
            file_obj.write("# t0_sample_index = unknown\n")
            file_obj.write("# dt_us = unknown\n")
            file_obj.write("# sample_rate_hz = unknown\n")

        writer = csv.writer(file_obj)
        writer.writerow(['timestamp_ms', 'sample_index', 'value'])

        self._csv_files[csv_key] = {
            'file': file_obj,
            'writer': writer,
            'count': 0,
            'path': filepath,
            'last_written_index': -1,
        }

        print(f"[LOGGER] Archivo CSV creado: {filepath}")

    # ============================================================
    # Flush periódico
    # ============================================================

    def _periodic_flush(self):
        """
        Hace flush de todos los archivos si ha pasado el intervalo.

        Esto garantiza que los datos llegan al disco periódicamente,
        previniendo pérdida de datos si la aplicación se cierra
        inesperadamente.
        """
        current_time = time.time()
        if current_time - self._last_flush_time >= self.FLUSH_INTERVAL:
            self._flush_all_files()
            self._last_flush_time = current_time

    def _flush_all_files(self):
        """
        Fuerza la escritura al disco de todos los archivos CSV abiertos.

        Usa file.flush() + os.fsync() para máxima garantía de persistencia.
        """
        for node_id, csv_info in self._csv_files.items():
            try:
                file_obj = csv_info['file']
                if not file_obj.closed:
                    file_obj.flush()
                    os.fsync(file_obj.fileno())
            except Exception as e:
                print(f"[LOGGER] Error al hacer flush (nodo {node_id}): {e}")

    def _close_all_files(self):
        """Cierra todos los archivos CSV abiertos de forma segura."""
        for node_id, csv_info in self._csv_files.items():
            try:
                file_obj = csv_info['file']
                if not file_obj.closed:
                    file_obj.flush()
                    os.fsync(file_obj.fileno())
                    file_obj.close()
                    print(f"[LOGGER] Archivo cerrado: {csv_info['path']} "
                          f"({csv_info['count']} registros)")
            except Exception as e:
                print(f"[LOGGER] Error al cerrar archivo (nodo {node_id}): {e}")

        self._csv_files.clear()

    # ============================================================
    # Limpieza
    # ============================================================

    def cleanup(self):
        """Limpieza completa: detener sesión y liberar recursos."""
        if self.is_logging:
            self.stop_session()
