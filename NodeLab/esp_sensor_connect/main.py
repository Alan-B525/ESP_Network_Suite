"""
main.py - Punto de entrada de ESP Sensor Connect
==================================================

Aplicacion de escritorio para adquisicion de datos de una red
de sensores inalambricos TDMA basados en ESP32 (ESP-NOW).

La PC se conecta via USB (Puerto Serie) a una Base Station (Gateway),
la cual retransmite los datos empaquetados de hasta 10 nodos remotos.

Arquitectura:
  +------------+     +------------------+     +--------------+
  |   Flet UI  |---->|  SerialManager   |---->|  DataLogger  |
  |  (main thd)|     |  (Reader Thread) |     |  (Writer Thd)|
  |            |<----|  -> Queue+Buffer |     |  -> CSV      |
  +------------+     +------------------+     +--------------+
       |                  |
       +----- page.run_task (async refresh) ----+

Para ejecutar:
  1. python -m venv venv
  2. venv\\Scripts\\activate  (Windows)
  3. pip install -r requirements.txt
  4. python main.py
"""

import sys
import os

# Agregar el directorio del proyecto al path para imports relativos
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import flet as ft

from core.network_manager import NetworkManager
from core.data_logger import DataLogger
from ui.main_window import MainWindow
from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO, FONT_INTER_URL, FONT_MONO_URL,
    BG_DEEPEST, ACCENT_PRIMARY, STATUS_OK, STATUS_CRITICAL,
    BG_SURFACE_0, TEXT_PRIMARY, TEXT_TERTIARY, BORDER_SUBTLE,
)


def main(page: ft.Page):
    """
    Funcion principal de Flet. Se ejecuta cuando la pagina esta lista.

    Registra fuentes custom (Inter + JetBrains Mono), configura el
    tema oscuro profesional y crea la ventana principal.
    """
    # ============================================================
    # Registro de fuentes profesionales
    # ============================================================
    page.fonts = {
        FONT_FAMILY: FONT_INTER_URL,
        FONT_MONO: FONT_MONO_URL,
    }

    # ============================================================
    # Configuracion de la ventana
    # ============================================================
    page.title = "ESP Sensor Connect"
    page.width = 1360
    page.height = 860
    page.bgcolor = BG_DEEPEST
    page.padding = 0

    # ============================================================
    # Tema profesional (Material Design 3 oscuro)
    # ============================================================
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(
        font_family=FONT_FAMILY,
        color_scheme=ft.ColorScheme(
            primary=ACCENT_PRIMARY,
            secondary=STATUS_OK,
            surface=BG_SURFACE_0,
            on_surface=TEXT_PRIMARY,
            error=STATUS_CRITICAL,
        ),
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color=BORDER_SUBTLE,
            track_color=BG_SURFACE_0,
            thickness=6,
            radius=3,
        ),
    )

    # ============================================================
    # Inicializacion del Core
    # ============================================================

    serial_manager = NetworkManager()

    data_logger = DataLogger(
        data_queue=serial_manager.data_queue,
        data_dir=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data_sessions"
        ),
    )

    # ============================================================
    # Construccion de la UI
    # ============================================================

    main_window = MainWindow(
        page=page,
        serial_manager=serial_manager,
        data_logger=data_logger,
    )
    main_window.build()

    # ============================================================
    # Limpieza al cerrar la aplicacion
    # ============================================================

    def on_close(e):
        """Handler para el evento de cierre de la ventana."""
        print("[APP] Cerrando aplicacion...")

        if serial_manager.is_acquiring:
            serial_manager.stop_acquisition()

        data_logger.cleanup()
        serial_manager.cleanup()

        print("[APP] Limpieza completa.")

    page.on_close = on_close

    print("[APP] ESP Sensor Connect iniciado correctamente")
    print("[APP] Ventana: 1360x860 - Tema: Industrial Dark")
    print("[APP] Fuentes: Inter + JetBrains Mono")
    print("[APP] Listo para conectar a la Base Station")


# ============================================================
# Punto de entrada
# ============================================================

if __name__ == "__main__":
    ft.run(main)
