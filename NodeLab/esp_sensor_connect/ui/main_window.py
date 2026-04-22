"""
main_window.py - Layout principal premium con sidebar custom
==============================================================

Reemplaza el NavigationRail generico de Material Design por una
sidebar personalizada con:
  - Logo + branding area
  - Botones de navegacion con hover effects e indicador lateral luminoso
  - Info de sistema en la parte inferior

Header bar custom con:
  - Status indicator premium
  - Timer digital
  - Boton Start/Stop con glow
"""

import asyncio
import time
import flet as ft

from core.serial_manager import SerialManager
from core.data_logger import DataLogger
from ui.components.status_indicator import StatusIndicator
from ui.views.dashboard import DashboardView
from ui.views.nodes_view import NodesView
from ui.views.config_view import ConfigView
from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO,
    BG_DEEPEST, BG_SIDEBAR, BG_SURFACE_0, BG_SURFACE_1, BG_SURFACE_2,
    BORDER_DEFAULT, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    ACCENT_PRIMARY, ACCENT_PRIMARY_DIM,
    STATUS_OK, STATUS_CRITICAL, STATUS_ACQUIRING,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
    SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL, SPACE_XXL,
    shadow_glow, shadow_card,
    primary_button, danger_button,
)


class MainWindow:
    """Controlador principal con sidebar custom y header bar."""

    NAV_ITEMS = [
        {"icon": ft.Icons.INSIGHTS_ROUNDED, "label": "Dashboard", "idx": 0},
        {"icon": ft.Icons.CELL_TOWER_ROUNDED, "label": "Nodos", "idx": 1},
        {"icon": ft.Icons.TUNE_ROUNDED, "label": "Configuracion", "idx": 2},
    ]

    def __init__(self, page: ft.Page, serial_manager: SerialManager,
                 data_logger: DataLogger):
        self._page = page
        self._serial_manager = serial_manager
        self._data_logger = data_logger

        self._current_view_index = 0
        self._acquisition_start_time: float = 0.0
        self._timer_task = None

        # ---- Sidebar components ----
        self._nav_buttons: list[ft.Container] = []

        # ---- Header components ----
        self._status_indicator = StatusIndicator()
        self._status_indicator.set_searching()

        self._timer_text = ft.Text(
            "00:00:00", size=16, color=TEXT_TERTIARY,
            weight=ft.FontWeight.W_600,
            font_family=FONT_MONO,
        )

        self._timer_container = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SCHEDULE_ROUNDED, color=TEXT_TERTIARY, size=16),
                    self._timer_text,
                ],
                spacing=SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=BG_SURFACE_2,
            border=ft.border.all(1, BORDER_DEFAULT),
            border_radius=RADIUS_SM,
            padding=ft.Padding(SPACE_SM, SPACE_MD, SPACE_SM, SPACE_MD),
        )

        # Start/Stop button
        self._start_btn = primary_button(
            "START", icon=ft.Icons.PLAY_ARROW_ROUNDED,
            on_click=self._on_start_stop, color=STATUS_OK,
        )

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

        # ---- Register callbacks ----
        self._serial_manager.set_on_connection_change(self._on_connection_changed)
        self._serial_manager.set_on_ack(self._on_ack_received)

    # ============================================================
    # Build
    # ============================================================

    def build(self):
        """Construye el layout completo de la aplicacion."""
        self._page.title = "ESP Sensor Connect"
        self._page.theme_mode = ft.ThemeMode.DARK
        self._page.bgcolor = BG_DEEPEST
        self._page.padding = 0
        self._page.appbar = None  # No Material AppBar

        # Build sidebar
        sidebar = self._build_sidebar()

        # Build header
        header = self._build_header()

        # Main content area with header
        content_column = ft.Column(
            controls=[header, self._content_area],
            spacing=0,
            expand=True,
        )

        # Full layout
        main_layout = ft.Row(
            controls=[
                sidebar,
                ft.Container(
                    width=1,
                    bgcolor=BORDER_SUBTLE,
                    expand=False,
                ),
                ft.Container(
                    content=content_column,
                    expand=True,
                    bgcolor=BG_SURFACE_0,
                ),
            ],
            expand=True,
            spacing=0,
        )

        self._page.add(main_layout)
        self._page.run_task(self._activate_view, 0)

    def _build_sidebar(self) -> ft.Container:
        """Construye la sidebar personalizada."""

        # Logo area
        logo_area = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.SENSORS_ROUNDED,
                                                color=ACCENT_PRIMARY, size=22),
                                bgcolor=ft.Colors.with_opacity(0.1, ACCENT_PRIMARY),
                                border_radius=RADIUS_MD,
                                padding=SPACE_SM,
                                width=40, height=40,
                                shadow=shadow_glow(ACCENT_PRIMARY, 0.15, 12),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text("ESP Sensor", size=14,
                                            weight=ft.FontWeight.W_700,
                                            color=TEXT_PRIMARY,
                                            font_family=FONT_FAMILY),
                                    ft.Text("Connect", size=14,
                                            weight=ft.FontWeight.W_300,
                                            color=ACCENT_PRIMARY,
                                            font_family=FONT_FAMILY),
                                ],
                                spacing=0,
                            ),
                        ],
                        spacing=SPACE_MD,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text("Wireless Sensor Network", size=9,
                            color=TEXT_TERTIARY, font_family=FONT_FAMILY,
                            weight=ft.FontWeight.W_500),
                ],
                spacing=SPACE_SM,
            ),
            padding=ft.Padding(SPACE_LG, SPACE_XL, SPACE_XL, SPACE_XL),
        )

        # Navigation buttons
        self._nav_buttons = []
        nav_controls = []
        for item in self.NAV_ITEMS:
            btn = self._make_nav_button(
                item["icon"], item["label"],
                selected=(item["idx"] == 0),
                idx=item["idx"],
            )
            self._nav_buttons.append(btn)
            nav_controls.append(btn)

        nav_section = ft.Container(
            content=ft.Column(
                controls=nav_controls,
                spacing=SPACE_XS,
            ),
            padding=ft.Padding(0, SPACE_MD, 0, SPACE_MD),
        )

        # System info (bottom)
        sys_info = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        height=1, bgcolor=BORDER_SUBTLE,
                        margin=ft.Margin(0, SPACE_MD, 0, 0),
                    ),
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text("v1.0", size=9,
                                                color=TEXT_TERTIARY,
                                                font_family=FONT_MONO),
                                bgcolor=BG_SURFACE_2,
                                border_radius=3,
                                padding=ft.Padding(2, 5, 2, 5),
                            ),
                            ft.Text("TDMA", size=9, color=TEXT_TERTIARY,
                                    font_family=FONT_MONO,
                                    weight=ft.FontWeight.W_600),
                        ],
                        spacing=SPACE_SM,
                    ),
                    ft.Text("ESP-NOW Protocol", size=9,
                            color=TEXT_TERTIARY, font_family=FONT_FAMILY),
                ],
                spacing=SPACE_SM,
            ),
            padding=ft.Padding(SPACE_LG, SPACE_XL, SPACE_LG, SPACE_XL),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    logo_area,
                    nav_section,
                    ft.Container(expand=True),
                    sys_info,
                ],
                spacing=0,
            ),
            width=220,
            bgcolor=BG_SIDEBAR,
        )

    def _build_header(self) -> ft.Container:
        """Construye el header bar custom."""
        return ft.Container(
            content=ft.Row(
                controls=[
                    # Breadcrumb / title area
                    ft.Text("Dashboard", size=18, color=TEXT_PRIMARY,
                            weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                    ft.Container(expand=True),
                    # Status
                    self._status_indicator,
                    ft.Container(width=SPACE_MD),
                    # Timer
                    self._timer_container,
                    ft.Container(width=SPACE_MD),
                    # Start/Stop
                    self._start_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(SPACE_LG, SPACE_XL, SPACE_LG, SPACE_XL),
            bgcolor=BG_SURFACE_0,
            border=ft.Border(bottom=ft.BorderSide(1, BORDER_SUBTLE)),
        )

    def _make_nav_button(self, icon, label, selected, idx) -> ft.Container:
        """Crea un boton de navegacion para la sidebar."""
        bg = ft.Colors.with_opacity(0.08, ACCENT_PRIMARY) if selected else ft.Colors.TRANSPARENT
        txt_color = ACCENT_PRIMARY if selected else TEXT_SECONDARY
        icon_color = ACCENT_PRIMARY if selected else TEXT_TERTIARY

        btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=3, height=22, border_radius=2,
                        bgcolor=ACCENT_PRIMARY if selected else ft.Colors.TRANSPARENT,
                        shadow=shadow_glow(ACCENT_PRIMARY, 0.5, 8) if selected else None,
                    ),
                    ft.Container(width=SPACE_MD),
                    ft.Icon(icon, color=icon_color, size=19),
                    ft.Container(width=SPACE_SM),
                    ft.Text(label, size=13, color=txt_color,
                            weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                            font_family=FONT_FAMILY),
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(SPACE_XS, 0, SPACE_LG, 0),
            border_radius=RADIUS_SM,
            bgcolor=bg,
            on_click=lambda e, i=idx: self._on_sidebar_click(i),
            height=42,
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            on_hover=lambda e, sel=selected: self._on_nav_hover(e, sel),
        )
        return btn

    def _on_nav_hover(self, e, selected):
        if not selected:
            e.control.bgcolor = (
                ft.Colors.with_opacity(0.04, ACCENT_PRIMARY)
                if e.data == "true" else ft.Colors.TRANSPARENT
            )
            try:
                e.control.update()
            except Exception:
                pass

    def _on_sidebar_click(self, index):
        """Handler cuando se hace click en un item de la sidebar."""
        # Rebuild nav buttons visual state
        for i, item in enumerate(self.NAV_ITEMS):
            btn = self._make_nav_button(
                item["icon"], item["label"],
                selected=(i == index), idx=i,
            )
            self._nav_buttons[i] = btn

        # Update sidebar nav section
        # Find the nav column inside the sidebar and replace controls
        sidebar = self._page.controls[0].controls[0]  # main_layout > sidebar
        nav_section = sidebar.content.controls[1]  # nav_section
        nav_section.content.controls = self._nav_buttons

        try:
            nav_section.update()
        except Exception:
            pass

        self._page.run_task(self._activate_view, index)

    # ============================================================
    # Navigation
    # ============================================================

    async def _activate_view(self, index: int):
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

    # ============================================================
    # Start / Stop
    # ============================================================

    def _on_start_stop(self, e):
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

        # Update button to STOP state
        self._start_btn.text = "STOP"
        self._start_btn.icon = ft.Icons.STOP_ROUNDED
        self._start_btn.bgcolor = STATUS_CRITICAL
        self._start_btn.color = "#FFFFFF"

        self._status_indicator.set_acquiring()
        self._timer_text.color = STATUS_ACQUIRING
        self._timer_container.border = ft.border.all(
            1, ft.Colors.with_opacity(0.3, STATUS_ACQUIRING))

        try:
            self._start_btn.update()
            self._timer_text.update()
            self._timer_container.update()
        except Exception:
            pass

        self._show_snackbar(f"Adquisicion iniciada - Sesion: {session_path}")

    def _stop_acquisition(self):
        self._serial_manager.stop_acquisition()
        self._data_logger.stop_session()

        self._start_btn.text = "START"
        self._start_btn.icon = ft.Icons.PLAY_ARROW_ROUNDED
        self._start_btn.bgcolor = STATUS_OK
        self._start_btn.color = BG_DEEPEST

        self._status_indicator.set_connected(self._serial_manager.current_port)
        self._timer_text.color = TEXT_TERTIARY
        self._timer_container.border = ft.border.all(1, BORDER_DEFAULT)

        try:
            self._start_btn.update()
            self._timer_text.update()
            self._timer_container.update()
        except Exception:
            pass

        self._show_snackbar(
            f"Adquisicion detenida - {self._data_logger.total_records:,} registros")

    # ============================================================
    # Timer
    # ============================================================

    async def _timer_loop(self):
        while self._serial_manager.is_acquiring:
            elapsed = time.time() - self._acquisition_start_time
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            s = int(elapsed % 60)
            self._timer_text.value = f"{h:02d}:{m:02d}:{s:02d}"
            try:
                self._timer_text.update()
            except Exception:
                pass
            await asyncio.sleep(1.0)

    # ============================================================
    # Callbacks
    # ============================================================

    def _on_connection_changed(self, connected: bool):
        if connected:
            self._status_indicator.set_connected(
                self._serial_manager.current_port)
        else:
            self._status_indicator.set_searching()
            if self._serial_manager.is_acquiring:
                self._stop_acquisition()
        self._config_view.update_connection_state(connected)

    def _on_ack_received(self, ack_frame):
        color = STATUS_OK if ack_frame.result == "OK" else STATUS_CRITICAL
        self._show_snackbar(f"ACK: {ack_frame.command} -> {ack_frame.result}")

    def _show_snackbar(self, message: str):
        try:
            snack = ft.SnackBar(
                content=ft.Text(message, color=TEXT_PRIMARY,
                                font_family=FONT_FAMILY, size=13),
                bgcolor=BG_SURFACE_1,
                duration=3000,
                open=True,
            )
            self._page.overlay.append(snack)
            self._page.update()
        except Exception:
            pass
