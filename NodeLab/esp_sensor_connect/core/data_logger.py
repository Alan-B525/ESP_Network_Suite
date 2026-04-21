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

from core.protocol_parser import DataFrame


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
        # {node_id: {'file': file_obj, 'writer': csv_writer, 'count': int}}
        self._csv_files: dict[int, dict] = {}
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

                # Solo procesar DataFrames (ignorar otros tipos si llegan)
                if isinstance(frame, DataFrame):
                    self._write_data_frame(frame)
                    self.total_records += 1

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
                    self.total_records += 1
                    drained += 1
            except queue.Empty:
                break

        if drained > 0:
            print(f"[LOGGER] Drenados {drained} registros pendientes")

    # ============================================================
    # Escritura CSV
    # ============================================================

    def _write_data_frame(self, frame: DataFrame):
        """
        Escribe un DataFrame en el archivo CSV correspondiente al nodo.

        Si el archivo del nodo no existe, lo crea con el encabezado.
        El número de columnas de valores se determina automáticamente.

        Args:
            frame: DataFrame parseado con los datos del sensor.
        """
        node_id = frame.node_id

        # Crear archivo CSV para este nodo si no existe
        if node_id not in self._csv_files:
            self._create_csv_for_node(node_id, len(frame.values))

        # Escribir la fila de datos
        csv_info = self._csv_files[node_id]
        row = [
            frame.timestamp.isoformat(),  # Timestamp ISO 8601
            frame.node_id,                 # ID del nodo
            frame.sequence,                # Número de secuencia
        ] + frame.values                   # Valores del sensor

        csv_info['writer'].writerow(row)
        csv_info['count'] += 1

    def _create_csv_for_node(self, node_id: int, num_values: int):
        """
        Crea el archivo CSV y su writer para un nodo específico.

        Args:
            node_id: ID del nodo para el cual crear el archivo.
            num_values: Cantidad de valores por trama (columnas de valores).
        """
        if not self.session_path:
            return

        filepath = self.session_path / f"node_{node_id}.csv"

        # Abrir archivo en modo append con buffering de línea
        file_obj = open(filepath, 'w', newline='', encoding='utf-8')
        writer = csv.writer(file_obj)

        # Escribir encabezado
        header = ['timestamp', 'node_id', 'sequence']
        header += [f'value_{i}' for i in range(num_values)]
        writer.writerow(header)

        # Guardar referencia para uso posterior
        self._csv_files[node_id] = {
            'file': file_obj,
            'writer': writer,
            'count': 0,
            'path': filepath,
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
