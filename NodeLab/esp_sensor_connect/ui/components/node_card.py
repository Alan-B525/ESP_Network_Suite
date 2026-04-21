"""
node_card.py - Tarjeta premium de nodo sensor
===============================================

Widget tipo Card con diseno industrial que muestra informacion
de un nodo inalambrico: estado, metricas, sparkline, y alertas
visuales basadas en la calidad del enlace.
"""

import flet as ft
import flet.canvas as cv

from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO, NODE_PALETTE,
    BG_SURFACE_1, BG_SURFACE_2, BG_DEEPEST,
    BORDER_DEFAULT, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    STATUS_OK, STATUS_WARNING, STATUS_CRITICAL, STATUS_ACQUIRING,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
    SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG,
    shadow_glow, shadow_card,
)


class NodeCard(ft.Card):
    """
    Tarjeta visual premium para un nodo sensor de la red.

    Incluye:
      - Header con gradiente del color del nodo
      - Indicador de estado con badge LIVE
      - Valor principal con unidades separadas
      - Mini sparkline con los ultimos 20 valores
      - Barra de perdida de paquetes con coloreo semantico
    """

    # Maximo de puntos para la sparkline
    SPARKLINE_POINTS = 20

    def __init__(self, node_id: int, mac_address: str = ""):
        super().__init__()

        self.node_id = node_id
        self.mac_address = mac_address

        # Color asignado a este nodo
        self._color = NODE_PALETTE[node_id % len(NODE_PALETTE)]

        # Buffer interno para sparkline
        self._sparkline_data: list[float] = []

        # ---- Componentes ----

        # Status dot
        self._status_dot = ft.Container(
            width=8, height=8, border_radius=4,
            bgcolor=STATUS_OK,
            shadow=shadow_glow(STATUS_OK, 0.5, 6),
        )

        # LIVE badge
        self._live_badge = ft.Container(
            content=ft.Text(
                "LIVE", size=8, color=STATUS_ACQUIRING,
                weight=ft.FontWeight.W_700, font_family=FONT_FAMILY,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, STATUS_ACQUIRING),
            border_radius=3,
            padding=ft.Padding(2, 5, 2, 5),
            visible=True,
        )

        # Node ID
        self._id_text = ft.Text(
            f"NODO {node_id:02d}",
            size=11,
            weight=ft.FontWeight.W_700,
            color=self._color,
            font_family=FONT_FAMILY,
        )

        # MAC
        self._mac_text = ft.Text(
            mac_address if mac_address else "MAC: --:--:--",
            size=10,
            color=TEXT_TERTIARY,
            font_family=FONT_MONO,
        )

        # Valor principal
        self._value_number = ft.Text(
            "--.-",
            size=32,
            weight=ft.FontWeight.W_700,
            color=TEXT_PRIMARY,
            font_family=FONT_FAMILY,
        )
        self._value_unit = ft.Text(
            " C",
            size=14,
            color=TEXT_TERTIARY,
            weight=ft.FontWeight.W_500,
            font_family=FONT_FAMILY,
        )

        # Metricas secundarias
        self._seq_text = ft.Text(
            "SEQ --", size=10, color=TEXT_TERTIARY,
            font_family=FONT_MONO, weight=ft.FontWeight.W_500,
        )
        self._packets_text = ft.Text(
            "0 pkt", size=10, color=TEXT_TERTIARY,
            font_family=FONT_MONO, weight=ft.FontWeight.W_500,
        )

        # Barra de perdida
        self._loss_bar = ft.ProgressBar(
            value=0, bar_height=3,
            color=STATUS_OK, bgcolor=BG_DEEPEST,
            border_radius=2,
        )
        self._loss_text = ft.Text(
            "0.0% loss", size=9, color=TEXT_TERTIARY,
            font_family=FONT_MONO,
        )

        # Sparkline canvas
        self._sparkline = cv.Canvas(
            shapes=[],
            width=float("inf"),
            height=30,
        )

        # ---- Layout ----

        # Header con barra de color
        header = ft.Container(
            content=ft.Row(
                controls=[
                    self._status_dot,
                    ft.Container(width=SPACE_XS),
                    self._id_text,
                    ft.Container(expand=True),
                    self._live_badge,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(SPACE_MD, SPACE_MD, SPACE_SM, SPACE_MD),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[
                    ft.Colors.with_opacity(0.08, self._color),
                    ft.Colors.TRANSPARENT,
                ],
            ),
            border=ft.Border(
                bottom=ft.BorderSide(1, BORDER_SUBTLE),
            ),
        )

        # Valor principal
        value_section = ft.Container(
            content=ft.Column(
                controls=[
                    self._mac_text,
                    ft.Row(
                        controls=[
                            self._value_number,
                            self._value_unit,
                        ],
                        spacing=2,
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                spacing=SPACE_XS,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(SPACE_SM, SPACE_MD, SPACE_SM, SPACE_MD),
        )

        # Metricas row
        metrics = ft.Container(
            content=ft.Row(
                controls=[self._seq_text, self._packets_text],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding(SPACE_XS, SPACE_MD, SPACE_XS, SPACE_MD),
        )

        # Sparkline section
        sparkline_section = ft.Container(
            content=self._sparkline,
            bgcolor=BG_DEEPEST,
            border_radius=RADIUS_SM,
            padding=ft.Padding(SPACE_XS, SPACE_SM, SPACE_XS, SPACE_SM),
            margin=ft.Margin(0, SPACE_MD, 0, SPACE_MD),
        )

        # Loss bar
        loss_section = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("PACKET LOSS", size=8, color=TEXT_TERTIARY,
                                    weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                            self._loss_text,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    self._loss_bar,
                ],
                spacing=SPACE_XS,
            ),
            padding=ft.Padding(SPACE_MD, SPACE_MD, SPACE_SM, SPACE_MD),
        )

        # Tarjeta completa
        self.content = ft.Container(
            content=ft.Column(
                controls=[header, value_section, metrics,
                          sparkline_section, loss_section],
                spacing=0,
            ),
            border_radius=RADIUS_LG,
            bgcolor=BG_SURFACE_1,
            border=ft.border.all(1, ft.Colors.with_opacity(0.2, self._color)),
            shadow=shadow_card(),
            width=250,
            animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
        )

        self.elevation = 0
        self.color = ft.Colors.TRANSPARENT

    # ============================================================
    # Actualizacion de datos
    # ============================================================

    def update_data(self, last_values: list[float], sequence: int,
                    packets: int, loss_rate: float):
        """Actualiza la tarjeta con los datos mas recientes."""
        # Valor principal
        if last_values:
            main_val = last_values[0]
            self._value_number.value = f"{main_val:.1f}"

            # Actualizar sparkline buffer
            self._sparkline_data.append(main_val)
            if len(self._sparkline_data) > self.SPARKLINE_POINTS:
                self._sparkline_data = self._sparkline_data[-self.SPARKLINE_POINTS:]

            self._draw_sparkline()

        # Metricas
        self._seq_text.value = f"SEQ {sequence}"
        self._packets_text.value = f"{packets:,} pkt"

        # Perdida de paquetes con coloreo semantico
        self._loss_bar.value = min(loss_rate / 100.0, 1.0)
        self._loss_text.value = f"{loss_rate:.1f}%"

        if loss_rate < 1.0:
            self._loss_bar.color = STATUS_OK
            self._loss_text.color = STATUS_OK
        elif loss_rate < 5.0:
            self._loss_bar.color = STATUS_WARNING
            self._loss_text.color = STATUS_WARNING
        else:
            self._loss_bar.color = STATUS_CRITICAL
            self._loss_text.color = STATUS_CRITICAL

        self._safe_update()

    def _draw_sparkline(self):
        """Dibuja la mini-linea de tendencia con Canvas."""
        data = self._sparkline_data
        if len(data) < 2:
            return

        w = 210.0   # ancho aproximado del canvas
        h = 26.0
        n = len(data)

        y_min = min(data)
        y_max = max(data)
        y_range = y_max - y_min if y_max != y_min else 1.0

        # Construir path
        path_elements = []
        for i, v in enumerate(data):
            px = (i / max(n - 1, 1)) * w
            py = h - ((v - y_min) / y_range) * (h - 4) - 2
            if i == 0:
                path_elements.append(cv.Path.MoveTo(px, py))
            else:
                path_elements.append(cv.Path.LineTo(px, py))

        shapes = [
            # Linea principal
            cv.Path(
                path_elements,
                paint=ft.Paint(
                    color=self._color,
                    stroke_width=1.5,
                    style=ft.PaintingStyle.STROKE,
                    anti_alias=True,
                ),
            ),
            # Punto final
            cv.Circle(
                x=(len(data) - 1) / max(n - 1, 1) * w,
                y=h - ((data[-1] - y_min) / y_range) * (h - 4) - 2,
                radius=3,
                paint=ft.Paint(color=self._color, style=ft.PaintingStyle.FILL),
            ),
        ]

        self._sparkline.shapes = shapes

    def set_active(self, active: bool = True):
        """Marca el nodo como activo o inactivo visualmente."""
        if active:
            self._status_dot.bgcolor = STATUS_OK
            self._status_dot.shadow = shadow_glow(STATUS_OK, 0.5, 6)
            self._live_badge.visible = True
        else:
            self._status_dot.bgcolor = TEXT_TERTIARY
            self._status_dot.shadow = None
            self._live_badge.visible = False
        self._safe_update()

    def set_mac(self, mac: str):
        """Actualiza la direccion MAC mostrada."""
        self.mac_address = mac
        self._mac_text.value = mac
        self._safe_update()

    def _safe_update(self):
        try:
            self.update()
        except Exception:
            pass
