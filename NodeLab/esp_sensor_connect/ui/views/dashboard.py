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

from core.network_manager import NetworkManager
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
from ui.components.channel_widget import ChannelWidget


class DashboardView(ft.Column):
    """Vista principal de dashboard con KPIs y grafico en tiempo real."""

    MAX_CHART_POINTS = 100
    REFRESH_RATE = 0.1  # 10 FPS

    def __init__(self, serial_manager: NetworkManager, page: ft.Page):
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

        # ---- Selector de canal y añadir widget ----
        self._add_widget_btn = ft.ElevatedButton(
            "Añadir Gráfico",
            icon=ft.Icons.ADD_CHART_ROUNDED,
            color=BG_DEEPEST,
            bgcolor=ACCENT_PRIMARY,
            on_click=self._open_add_dialog
        )

        # ---- Chart header ----
        chart_header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("SENSOR DATA MULTI-CANAL", size=11, color=TEXT_TERTIARY,
                                weight=ft.FontWeight.W_700, font_family=FONT_FAMILY),
                        ft.Text("Visualización independiente por nodo y canal", size=11,
                                color=TEXT_TERTIARY, font_family=FONT_FAMILY),
                    ],
                    spacing=2,
                ),
                ft.Container(expand=True),
                self._add_widget_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.END,
        )

        # ---- Grid de Widgets ----
        self._widgets = []
        self._widget_grid = ft.GridView(
            expand=True,
            runs_count=5,
            max_extent=320,
            child_aspect_ratio=1.5,
            spacing=SPACE_MD,
            run_spacing=SPACE_MD,
        )

        # ---- Empty state ----
        self._no_data_overlay = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Icon(ft.Icons.DASHBOARD_CUSTOMIZE_ROUNDED, size=40,
                                        color=TEXT_TERTIARY),
                        bgcolor=BG_SURFACE_2,
                        border_radius=RADIUS_LG,
                        padding=SPACE_LG,
                        width=72, height=72,
                    ),
                    ft.Text("No hay widgets", size=15, color=TEXT_SECONDARY,
                            weight=ft.FontWeight.W_600, font_family=FONT_FAMILY),
                    ft.Text("Usa 'Añadir Gráfico' para ver datos",
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
                          ft.Stack(controls=[self._widget_grid, self._no_data_overlay],
                                   expand=True)],
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
    # Add Widget Dialog
    # ============================================================

    def _open_add_dialog(self, e):
        node_ids = self._serial_manager.get_all_node_ids()
        if not node_ids:
            # Fallback if no nodes, allow 0-10 for testing
            node_ids = list(range(1, 11))
            
        node_dropdown = styled_dropdown(
            label="Nodo",
            value=str(node_ids[0]) if node_ids else "1",
            options=[ft.dropdown.Option(str(n), f"Nodo {n}") for n in node_ids]
        )
        
        channel_dropdown = styled_dropdown(
            label="Canal",
            value="0",
            options=[ft.dropdown.Option(str(i), f"Canal {i}") for i in range(4)]
        )
        
        def close_dlg(e):
            dlg.open = False
            self._page.update()

        def add_and_close(e):
            nid = int(node_dropdown.value)
            cid = int(channel_dropdown.value)
            self._add_widget(nid, cid)
            dlg.open = False
            self._page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Añadir Widget de Canal"),
            content=ft.Column([node_dropdown, channel_dropdown], tight=True, spacing=SPACE_MD),
            actions=[
                ft.TextButton("Cancelar", on_click=close_dlg),
                ft.ElevatedButton("Añadir", on_click=add_and_close, color=BG_DEEPEST, bgcolor=ACCENT_PRIMARY),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self._page.overlay.append(dlg)
        dlg.open = True
        self._page.update()

    def _add_widget(self, node_id: int, channel_id: int):
        color = NODE_PALETTE[node_id % len(NODE_PALETTE)]
        w = ChannelWidget(node_id, channel_id, color, self._remove_widget)
        self._widgets.append(w)
        self._widget_grid.controls.append(w)
        
        self._no_data_overlay.visible = False
        self._safe_update(self._no_data_overlay)
        self._safe_update(self._widget_grid)
        
    def _remove_widget(self, widget: ChannelWidget):
        if widget in self._widgets:
            self._widgets.remove(widget)
        if widget in self._widget_grid.controls:
            self._widget_grid.controls.remove(widget)
            
        if not self._widgets:
            self._no_data_overlay.visible = True
            
        self._safe_update(self._no_data_overlay)
        self._safe_update(self._widget_grid)

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
        if not self._widgets:
            return

        for w in self._widgets:
            vals = self._serial_manager.get_node_data(w.node_id, w.channel_id, count=ChannelWidget.MAX_POINTS)
            w.update_data(vals)

    def _safe_update(self, control):
        try:
            control.update()
        except Exception:
            pass
