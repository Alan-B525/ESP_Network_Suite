"""
status_indicator.py - Indicador visual de estado de conexion (Premium)
=======================================================================

Widget tipo "chip" que muestra el estado de conexion con la Base Station
mediante un punto de color con doble glow y texto descriptivo.

Estados:
  - Conectado:    Punto verde con glow pulsante + "Conectado a COMx"
  - Desconectado: Punto rojo estatico + "Sin conexion"
  - Adquiriendo:  Punto cyan con glow intenso + "LIVE - Adquiriendo"
"""

import flet as ft
from ui.design_tokens import (
    FONT_FAMILY, BG_SURFACE_2, BORDER_DEFAULT, RADIUS_MD,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    STATUS_OK, STATUS_CRITICAL, STATUS_ACQUIRING, STATUS_INACTIVE,
    SPACE_SM, SPACE_MD, shadow_glow,
)


class StatusIndicator(ft.Container):
    """
    Indicador de estado premium con chip visual.

    Uso:
        indicator = StatusIndicator()
        indicator.set_connected("COM3")
        indicator.set_disconnected()
        indicator.set_acquiring()
    """

    def __init__(self):
        super().__init__()

        # Punto indicador con doble halo
        self._dot_inner = ft.Container(
            width=8,
            height=8,
            border_radius=4,
            bgcolor=STATUS_CRITICAL,
        )

        self._dot_outer = ft.Container(
            content=self._dot_inner,
            width=18,
            height=18,
            border_radius=9,
            bgcolor=ft.Colors.with_opacity(0.15, STATUS_CRITICAL),
            alignment=ft.Alignment.CENTER,
            shadow=shadow_glow(STATUS_CRITICAL, 0.3, 10),
            animate=ft.Animation(800, ft.AnimationCurve.EASE_IN_OUT),
        )

        # Etiqueta de texto
        self._label = ft.Text(
            value="Sin conexion",
            size=12,
            color=TEXT_SECONDARY,
            weight=ft.FontWeight.W_500,
            font_family=FONT_FAMILY,
        )

        # Badge de estado
        self._badge = ft.Container(
            content=ft.Text(
                "OFFLINE", size=9, color=STATUS_CRITICAL,
                weight=ft.FontWeight.W_700, font_family=FONT_FAMILY,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, STATUS_CRITICAL),
            border_radius=4,
            padding=ft.Padding(3, 6, 3, 6),
            visible=True,
        )

        # Layout del chip
        self.content = ft.Row(
            controls=[self._dot_outer, self._label, self._badge],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.bgcolor = BG_SURFACE_2
        self.border = ft.border.all(1, BORDER_DEFAULT)
        self.border_radius = RADIUS_MD
        self.padding = ft.Padding(SPACE_SM, SPACE_MD, SPACE_SM, SPACE_MD)

    def set_connected(self, port: str = ""):
        """Muestra estado conectado (verde)."""
        self._dot_inner.bgcolor = STATUS_OK
        self._dot_outer.bgcolor = ft.Colors.with_opacity(0.15, STATUS_OK)
        self._dot_outer.shadow = shadow_glow(STATUS_OK, 0.4, 12)

        port_text = f" {port}" if port else ""
        self._label.value = f"Conectado{port_text}"
        self._label.color = TEXT_PRIMARY

        self._badge.content = ft.Text(
            "READY", size=9, color=STATUS_OK,
            weight=ft.FontWeight.W_700, font_family=FONT_FAMILY,
        )
        self._badge.bgcolor = ft.Colors.with_opacity(0.12, STATUS_OK)

        self.border = ft.border.all(1, ft.Colors.with_opacity(0.3, STATUS_OK))
        self._safe_update()

    def set_disconnected(self):
        """Muestra estado desconectado (rojo)."""
        self._dot_inner.bgcolor = STATUS_CRITICAL
        self._dot_outer.bgcolor = ft.Colors.with_opacity(0.15, STATUS_CRITICAL)
        self._dot_outer.shadow = shadow_glow(STATUS_CRITICAL, 0.3, 10)

        self._label.value = "Sin conexion"
        self._label.color = TEXT_SECONDARY

        self._badge.content = ft.Text(
            "OFFLINE", size=9, color=STATUS_CRITICAL,
            weight=ft.FontWeight.W_700, font_family=FONT_FAMILY,
        )
        self._badge.bgcolor = ft.Colors.with_opacity(0.12, STATUS_CRITICAL)

        self.border = ft.border.all(1, BORDER_DEFAULT)
        self._safe_update()

    def set_acquiring(self):
        """Muestra estado adquiriendo datos (cyan pulsante)."""
        self._dot_inner.bgcolor = STATUS_ACQUIRING
        self._dot_outer.bgcolor = ft.Colors.with_opacity(0.2, STATUS_ACQUIRING)
        self._dot_outer.shadow = shadow_glow(STATUS_ACQUIRING, 0.6, 16)

        self._label.value = "Adquiriendo datos"
        self._label.color = STATUS_ACQUIRING

        self._badge.content = ft.Text(
            "LIVE", size=9, color=STATUS_ACQUIRING,
            weight=ft.FontWeight.W_700, font_family=FONT_FAMILY,
        )
        self._badge.bgcolor = ft.Colors.with_opacity(0.15, STATUS_ACQUIRING)

        self.border = ft.border.all(1, ft.Colors.with_opacity(0.4, STATUS_ACQUIRING))
        self._safe_update()

    def _safe_update(self):
        """Actualiza el componente solo si ya fue montado en la pagina."""
        try:
            self.update()
        except Exception:
            pass
