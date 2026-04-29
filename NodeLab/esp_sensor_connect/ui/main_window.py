"""
main_window.py - Layout principal premium con arquitectura modular
==================================================================
Coordina la Sidebar, Header y las diferentes vistas de la aplicacion.
"""

import asyncio
import time
import flet as ft

from core.network_manager import NetworkManager
from core.data_logger import DataLogger
from ui.layout import Sidebar, Header
from ui.views.dashboard import DashboardView
from ui.views.nodes_view import NodesView
from ui.views.config_view import ConfigView
from ui.design_tokens import (
    BG_DEEPEST, BG_SURFACE_0, BORDER_SUBTLE,
    TEXT_PRIMARY, STATUS_CRITICAL, STATUS_OK,
    SPACE_XL, FONT_FAMILY, BG_SURFACE_1
)

class MainWindow:
    """Controlador principal de la interfaz."""

    def __init__(self, page: ft.Page, serial_manager: NetworkManager,
                 data_logger: DataLogger):
        self._page = page
        self._serial_manager = serial_manager
        self._data_logger = data_logger

        self._current_view_index = 0
        self._acquisition_start_time: float = 0.0
        self._timer_task = None

        # ---- Modular Layout Components ----
        self._sidebar = Sidebar(on_nav_change=self._on_nav_change)
        self._header = Header(on_start_stop=self._on_start_stop)

        # ---- Views ----
        self._dashboard_view = DashboardView(serial_manager, page)
        self._nodes_view = NodesView(serial_manager, page)
        self._config_view = ConfigView(serial_manager, page)
        self._views = [self._dashboard_view, self._nodes_view, self._config_view]

        # Content area
        self._content_area = ft.Container(
            content=self._views[0],
            expand=True,
            padding=SPACE_XL,
        )

        # ---- Register network callbacks ----
        self._serial_manager.set_on_connection_change(self._on_connection_changed)
        self._serial_manager.set_on_ack(self._on_ack_received)

    def build(self):
        """Construye el layout completo de la aplicacion."""
        self._page.title = "ESP Sensor Connect"
        self._page.theme_mode = ft.ThemeMode.DARK
        self._page.bgcolor = BG_DEEPEST
        self._page.padding = 0

        # Main content column (Header + View Area)
        content_column = ft.Column(
            controls=[self._header, self._content_area],
            spacing=0,
            expand=True,
        )

        # Full layout (Sidebar + Divider + Content)
        main_layout = ft.Row(
            controls=[
                self._sidebar,
                ft.Container(width=1, bgcolor=BORDER_SUBTLE, expand=False),
                ft.Container(content=content_column, expand=True, bgcolor=BG_SURFACE_0),
            ],
            expand=True,
            spacing=0,
        )

        self._page.add(main_layout)
        self._page.run_task(self._activate_view, 0)

    # ============================================================
    # Callbacks & Handlers
    # ============================================================

    def _on_nav_change(self, index: int):
        """Handler para cambios de navegacion desde la sidebar."""
        title = self._sidebar.NAV_ITEMS[index]["label"]
        self._header.set_title(title)
        self._page.run_task(self._activate_view, index)

    async def _activate_view(self, index: int):
        """Gestiona la activacion y desactivacion de vistas."""
        old_view = self._views[self._current_view_index]
        if hasattr(old_view, 'deactivate'):
            old_view.deactivate()

        self._current_view_index = index
        self._content_area.content = self._views[index]

        new_view = self._views[index]
        if hasattr(new_view, 'activate'):
            await new_view.activate()

        try:
            self._content_area.update()
        except Exception:
            pass

    def _on_start_stop(self, e):
        """Controlador del boton global de adquisicion."""
        if not self._serial_manager.is_acquiring:
            self._start_acquisition()
        else:
            self._stop_acquisition()

    def _start_acquisition(self):
        if not self._serial_manager.is_connected:
            self._show_snackbar("Conecta la Base Station primero (Config)")
            return

        session_path = self._data_logger.start_session()
        success = self._serial_manager.start_acquisition()

        if not success:
            self._data_logger.stop_session()
            self._show_snackbar("Error al enviar CMD:START")
            return

        self._acquisition_start_time = time.time()
        self._timer_task = self._page.run_task(self._timer_loop)
        
        self._header.set_acquiring_state(True)
        self._show_snackbar(f"Adquisicion iniciada - Sesion: {session_path}")

    def _stop_acquisition(self):
        self._serial_manager.stop_acquisition()
        self._data_logger.stop_session()
        
        self._header.set_acquiring_state(False, self._serial_manager.current_port)
        self._show_snackbar(f"Adquisicion detenida - {self._data_logger.total_records:,} registros")

    async def _timer_loop(self):
        """Hilo de actualizacion del timer en el Header."""
        while self._serial_manager.is_acquiring:
            elapsed = time.time() - self._acquisition_start_time
            h, m, s = int(elapsed // 3600), int((elapsed % 3600) // 60), int(elapsed % 60)
            self._header.update_timer(f"{h:02d}:{m:02d}:{s:02d}")
            await asyncio.sleep(1.0)

    def _on_connection_changed(self, connected: bool):
        """Evento de red: conexion/desconexion."""
        self._header.set_connection_state(connected, self._serial_manager.current_port)
        if not connected and self._serial_manager.is_acquiring:
            self._stop_acquisition()
            
        self._config_view.update_connection_state(connected)

    def _on_ack_received(self, ack_frame):
        self._show_snackbar(f"ACK: {ack_frame.command} -> {ack_frame.result}")

    def _show_snackbar(self, message: str):
        try:
            snack = ft.SnackBar(
                content=ft.Text(message, color=TEXT_PRIMARY, font_family=FONT_FAMILY, size=13),
                bgcolor=BG_SURFACE_1, duration=3000, open=True,
            )
            self._page.overlay.append(snack)
            self._page.update()
        except Exception:
            pass
