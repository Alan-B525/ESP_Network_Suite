"""
dashboard.py - Vista de Dashboard profesional con graficos en tiempo real
=========================================================================

Dashboard industrial con:
  - KPI cards (Nodos, Throughput, Perdida, Uptime)
  - Grafico de lineas Canvas con grilla, ejes y leyenda
  - Refresco a 10 FPS desacoplado de la tasa de muestreo
"""

import asyncio
import time
import flet as ft
import flet.canvas as cv

from core.serial_manager import SerialManager
from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO, NODE_PALETTE,
    BG_DEEPEST, BG_SURFACE_0, BG_SURFACE_1, BG_SURFACE_2,
    BORDER_DEFAULT, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    ACCENT_PRIMARY, STATUS_OK, STATUS_WARNING, STATUS_CRITICAL,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
    SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL,
    kpi_card, section_card, styled_dropdown, shadow_card,
)


class DashboardView(ft.Column):
    """Vista principal de dashboard con KPIs y grafico en tiempo real."""

    MAX_CHART_POINTS = 100
    REFRESH_RATE = 0.1  # 10 FPS

    def __init__(self, serial_manager: SerialManager, page: ft.Page):
        super().__init__()

        self._serial_manager = serial_manager
        self._page = page
        self._refresh_task = None
        self._is_active = False
        self._start_time = time.time()

        self._y_min = 0.0
        self._y_max = 50.0

        # ---- KPI Cards ----
        self._kpi_nodes = self._make_kpi_value("0")
        self._kpi_throughput = self._make_kpi_value("0")
        self._kpi_loss = self._make_kpi_value("0.0%")
        self._kpi_uptime = self._make_kpi_value("00:00")

        kpi_row = ft.Row(
            controls=[
                self._build_kpi(ft.Icons.CELL_TOWER_ROUNDED,
                                "NODOS ACTIVOS", self._kpi_nodes, ACCENT_PRIMARY),
                self._build_kpi(ft.Icons.SPEED_ROUNDED,
                                "THROUGHPUT", self._kpi_throughput, STATUS_OK),
                self._build_kpi(ft.Icons.WARNING_AMBER_ROUNDED,
                                "PACKET LOSS", self._kpi_loss, STATUS_WARNING),
                self._build_kpi(ft.Icons.SCHEDULE_ROUNDED,
                                "UPTIME", self._kpi_uptime, TEXT_SECONDARY),
            ],
            spacing=SPACE_MD,
        )

        # ---- Selector de canal ----
        self._value_index = 0
        self._value_selector = styled_dropdown(
            label="Canal",
            value="0",
            options=[ft.dropdown.Option(str(i), f"Canal {i}") for i in range(4)],
            on_select=self._on_value_index_changed,
            width=140,
        )

        # ---- Chart header ----
        chart_header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("SENSOR DATA", size=11, color=TEXT_TERTIARY,
                                weight=ft.FontWeight.W_700, font_family=FONT_FAMILY),
                        ft.Text("Ultimos 100 puntos por nodo", size=11,
                                color=TEXT_TERTIARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                ft.Container(expand=True),
                self._value_selector,
            ],
            vertical_alignment=ft.CrossAxisAlignment.END,
        )

        # ---- Canvas para el grafico ----
        self._chart_canvas = cv.Canvas(
            on_resize=self._on_canvas_resize,
            shapes=[],
            expand=True,
        )
        self._canvas_width = 800.0
        self._canvas_height = 350.0

        chart_box = ft.Container(
            content=self._chart_canvas,
            bgcolor=BG_DEEPEST,
            border_radius=RADIUS_MD,
            border=ft.border.all(1, BORDER_SUBTLE),
            padding=ft.Padding(SPACE_LG, SPACE_XL + 10, SPACE_LG + 30, SPACE_XL),
            expand=True,
        )

        # ---- Leyenda ----
        self._legend_row = ft.Row(controls=[], spacing=SPACE_MD, wrap=True)

        # ---- Empty state ----
        self._no_data_overlay = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Icon(ft.Icons.INSIGHTS_ROUNDED, size=40,
                                        color=TEXT_TERTIARY),
                        bgcolor=BG_SURFACE_2,
                        border_radius=RADIUS_LG,
                        padding=SPACE_LG,
                        width=72, height=72,
                    ),
                    ft.Text("Esperando datos...", size=15, color=TEXT_SECONDARY,
                            weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                    ft.Text("Conecta la Base Station y presiona START",
                            size=12, color=TEXT_TERTIARY, font_family=FONT_FAMILY),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=SPACE_SM,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
            visible=True,
        )

        # ---- Layout principal ----
        chart_section = section_card(
            content=ft.Column(
                controls=[chart_header,
                          ft.Stack(controls=[chart_box, self._no_data_overlay],
                                   expand=True),
                          self._legend_row],
                spacing=SPACE_MD,
                expand=True,
            ),
            accent_color=ACCENT_PRIMARY,
            expand=True,
        )

        self.controls = [kpi_row, chart_section]
        self.spacing = SPACE_MD
        self.expand = True

    # ============================================================
    # KPI helpers
    # ============================================================

    def _make_kpi_value(self, initial: str) -> ft.Text:
        return ft.Text(initial, size=24, weight=ft.FontWeight.W_700,
                       color=TEXT_PRIMARY, font_family=FONT_FAMILY)

    def _build_kpi(self, icon, label, value_text, color) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(icon, color=color, size=16),
                                bgcolor=ft.Colors.with_opacity(0.1, color),
                                border_radius=RADIUS_SM,
                                padding=6, width=30, height=30,
                            ),
                            ft.Text(label, size=9, color=TEXT_TERTIARY,
                                    weight=ft.FontWeight.W_700,
                                    font_family=FONT_FAMILY),
                        ],
                        spacing=SPACE_SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    value_text,
                ],
                spacing=SPACE_SM,
            ),
            bgcolor=BG_SURFACE_1,
            border=ft.border.all(1, BORDER_DEFAULT),
            border_radius=RADIUS_LG,
            padding=SPACE_LG,
            shadow=shadow_card(),
            expand=True,
        )

    # ============================================================
    # Canvas callback
    # ============================================================

    def _on_canvas_resize(self, e: cv.CanvasResizeEvent):
        self._canvas_width = e.width
        self._canvas_height = e.height

    # ============================================================
    # Activacion / desactivacion
    # ============================================================

    async def activate(self):
        self._is_active = True
        if self._refresh_task is None:
            self._refresh_task = self._page.run_task(self._refresh_loop)

    def deactivate(self):
        self._is_active = False

    # ============================================================
    # Refresh loop
    # ============================================================

    async def _refresh_loop(self):
        while self._is_active:
            try:
                self._update_chart()
                self._update_kpis()
            except Exception as e:
                print(f"[DASHBOARD] Refresh error: {e}")
            await asyncio.sleep(self.REFRESH_RATE)
        self._refresh_task = None

    def _update_kpis(self):
        node_ids = self._serial_manager.get_all_node_ids()

        # Nodos
        self._kpi_nodes.value = str(len(node_ids))

        # Throughput
        total = sum(self._serial_manager.packets_received.get(n, 0)
                    for n in node_ids)
        if total > 1000:
            self._kpi_throughput.value = f"{total / 1000:.1f}k"
        else:
            self._kpi_throughput.value = str(total)

        # Loss
        if node_ids:
            avg = sum(self._serial_manager.get_packet_loss_rate(n)
                      for n in node_ids) / len(node_ids)
            self._kpi_loss.value = f"{avg:.1f}%"
            
            # Check for any dead nodes to show critical
            any_dead = any(not self._serial_manager.is_node_healthy(n) for n in node_ids)
            
            if any_dead:
                self._kpi_loss.color = STATUS_CRITICAL
                self._kpi_loss.value = "NODO CAIDO"
            elif avg < 1:
                self._kpi_loss.color = STATUS_OK
            elif avg < 5:
                self._kpi_loss.color = STATUS_WARNING
            else:
                self._kpi_loss.color = STATUS_CRITICAL
        else:
            self._kpi_loss.value = "0.0%"
            self._kpi_loss.color = TEXT_PRIMARY

        # Uptime
        elapsed = time.time() - self._start_time
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        if mins >= 60:
            hrs = mins // 60
            mins = mins % 60
            self._kpi_uptime.value = f"{hrs}h{mins:02d}m"
        else:
            self._kpi_uptime.value = f"{mins:02d}:{secs:02d}"

        self._safe_update(self._kpi_nodes)
        self._safe_update(self._kpi_throughput)
        self._safe_update(self._kpi_loss)
        self._safe_update(self._kpi_uptime)

    def _update_chart(self):
        node_ids = self._serial_manager.get_all_node_ids()

        if not node_ids:
            if not self._no_data_overlay.visible:
                self._no_data_overlay.visible = True
                self._safe_update(self._no_data_overlay)
            return

        # Recopilar datos
        all_node_data = {}
        all_flat = []
        for nid in node_ids:
            pts = self._serial_manager.get_node_data(nid, self.MAX_CHART_POINTS)
            if not pts:
                continue
            # Filtrar por el canal seleccionado
            channel_pts = [p for p in pts if p.channel_id == self._value_index]
            
            vals = []
            for p in channel_pts:
                vals.extend(p.values)
                
            if len(vals) > self.MAX_CHART_POINTS:
                vals = vals[-self.MAX_CHART_POINTS:]

            if vals:
                all_node_data[nid] = vals
                all_flat.extend(vals)

        if not all_flat:
            if not self._no_data_overlay.visible:
                self._no_data_overlay.visible = True
                self._safe_update(self._no_data_overlay)
            return

        # Ocultar overlay si tenemos datos
        if self._no_data_overlay.visible:
            self._no_data_overlay.visible = False
            self._safe_update(self._no_data_overlay)

        # Rangos - auto-escalado estable
        y_min = min(all_flat)
        y_max = max(all_flat)
        rng = y_max - y_min
        
        # Rango mínimo para que no salte locamente con ruido
        if rng < 50.0:
            mid = (y_max + y_min) / 2.0
            y_min = mid - 25.0
            y_max = mid + 25.0
            rng = 50.0
            
        margin = rng * 0.15
        self._y_min = y_min - margin
        self._y_max = y_max + margin

        w = self._canvas_width
        h = self._canvas_height
        if w <= 0 or h <= 0:
            return

        shapes = []

        # Grid horizontal
        for i in range(6):
            gy = h - (i / 5) * h
            yv = self._y_min + (i / 5) * (self._y_max - self._y_min)
            shapes.append(cv.Line(
                x1=0, y1=gy, x2=w, y2=gy,
                paint=ft.Paint(color=ft.Colors.with_opacity(0.06, "#FFFFFF"),
                               stroke_width=1),
            ))
            shapes.append(cv.Text(
                x=-48, y=gy - 6,
                text=f"{yv:.1f}",
                style=ft.TextStyle(size=9, color=TEXT_TERTIARY,
                                   font_family=FONT_MONO),
            ))

        # Grid vertical
        for xl in [0, 25, 50, 75, 100]:
            gx = (xl / self.MAX_CHART_POINTS) * w
            shapes.append(cv.Line(
                x1=gx, y1=0, x2=gx, y2=h,
                paint=ft.Paint(color=ft.Colors.with_opacity(0.04, "#FFFFFF"),
                               stroke_width=1),
            ))
            shapes.append(cv.Text(
                x=gx - 6, y=h + 6,
                text=str(xl),
                style=ft.TextStyle(size=9, color=TEXT_TERTIARY,
                                   font_family=FONT_MONO),
            ))

        # Lineas de datos
        legend_items = []
        for nid, vals in all_node_data.items():
            color = NODE_PALETTE[nid % len(NODE_PALETTE)]
            # Si el nodo está caído, hacerlo semi-transparente
            if not self._serial_manager.is_node_healthy(nid):
                color = ft.Colors.with_opacity(0.3, color)

            n = len(vals)
            if n < 2:
                continue

            path_els = []
            for i, v in enumerate(vals):
                px = (i / max(self.MAX_CHART_POINTS - 1, 1)) * w
                py = h - ((v - self._y_min) /
                           max(self._y_max - self._y_min, 0.01)) * h
                py = max(0, min(h, py))
                if i == 0:
                    path_els.append(cv.Path.MoveTo(px, py))
                else:
                    path_els.append(cv.Path.LineTo(px, py))

            # Sombra exterior sutil para efecto glow
            shapes.append(cv.Path(
                path_els,
                paint=ft.Paint(color=ft.Colors.with_opacity(0.3, color), stroke_width=6,
                               style=ft.PaintingStyle.STROKE,
                               anti_alias=True),
            ))
            # Linea principal
            shapes.append(cv.Path(
                path_els,
                paint=ft.Paint(color=color, stroke_width=2.5,
                               style=ft.PaintingStyle.STROKE,
                               anti_alias=True),
            ))

            # Ultimo punto con doble halo
            last_px = ((n - 1) / max(self.MAX_CHART_POINTS - 1, 1)) * w
            last_py = h - ((vals[-1] - self._y_min) /
                            max(self._y_max - self._y_min, 0.01)) * h
            last_py = max(0, min(h, last_py))

            shapes.append(cv.Circle(
                x=last_px, y=last_py, radius=6,
                paint=ft.Paint(color=ft.Colors.with_opacity(0.2, color),
                               style=ft.PaintingStyle.FILL),
            ))
            shapes.append(cv.Circle(
                x=last_px, y=last_py, radius=3.5,
                paint=ft.Paint(color=color, style=ft.PaintingStyle.FILL),
            ))

            legend_items.append(self._legend_chip(f"Nodo {nid}", color))

        # Frame del chart
        shapes.append(cv.Rect(
            x=0, y=0, width=w, height=h,
            paint=ft.Paint(color=BORDER_SUBTLE, stroke_width=1,
                           style=ft.PaintingStyle.STROKE),
        ))

        self._chart_canvas.shapes = shapes
        self._safe_update(self._chart_canvas)

        self._legend_row.controls = legend_items
        self._safe_update(self._legend_row)

    # ============================================================
    # Helpers
    # ============================================================

    def _legend_chip(self, label, color) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(width=8, height=8, border_radius=4,
                                 bgcolor=color,
                                 shadow=ft.BoxShadow(spread_radius=0,
                                     blur_radius=6,
                                     color=ft.Colors.with_opacity(0.4, color))),
                    ft.Text(label, size=11, color=TEXT_SECONDARY,
                            font_family=FONT_FAMILY, weight=ft.FontWeight.W_500),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=BG_SURFACE_2,
            border=ft.border.all(1, BORDER_DEFAULT),
            border_radius=RADIUS_SM,
            padding=ft.Padding(SPACE_XS, SPACE_SM, SPACE_XS, SPACE_SM),
        )

    def _on_value_index_changed(self, e):
        self._value_index = int(e.control.value)

    def _safe_update(self, control):
        try:
            control.update()
        except Exception:
            pass
