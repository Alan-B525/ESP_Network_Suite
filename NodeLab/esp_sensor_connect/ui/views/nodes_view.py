"""
nodes_view.py - Vista de nodos de la red (Premium)
====================================================

Muestra una cuadricula de NodeCards con resumen de red
y empty state mejorado.
"""

import asyncio
import flet as ft

from core.serial_manager import SerialManager
from ui.components.node_card import NodeCard
from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO,
    BG_SURFACE_1, BG_SURFACE_2, BG_DEEPEST,
    BORDER_DEFAULT, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    ACCENT_PRIMARY, STATUS_OK, STATUS_WARNING,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
    SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL,
    section_card,
)


class NodesView(ft.Column):
    """Vista de grid de nodos con resumen de red y tarjetas premium."""

    REFRESH_RATE = 0.5  # 2 FPS

    def __init__(self, serial_manager: SerialManager, page: ft.Page):
        super().__init__()

        self._serial_manager = serial_manager
        self._page = page
        self._refresh_task = None
        self._is_active = False
        self._node_cards: dict[int, NodeCard] = {}

        # ---- Header ----
        self._title = ft.Text(
            "NETWORK NODES", size=11, color=TEXT_TERTIARY,
            weight=ft.FontWeight.W_700, font_family=FONT_FAMILY,
        )

        # Resumen de red (chips)
        self._chip_active = self._make_summary_chip("Activos", "0", STATUS_OK)
        self._chip_inactive = self._make_summary_chip("Inactivos", "0", TEXT_TERTIARY)
        self._chip_avg_loss = self._make_summary_chip("Avg Loss", "0.0%", STATUS_WARNING)

        summary_row = ft.Row(
            controls=[self._chip_active, self._chip_inactive, self._chip_avg_loss],
            spacing=SPACE_SM,
        )

        header = ft.Row(
            controls=[
                ft.Column(controls=[self._title], spacing=2),
                ft.Container(expand=True),
                summary_row,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ---- Grid de tarjetas ----
        self._cards_grid = ft.Row(
            controls=[],
            wrap=True,
            spacing=SPACE_MD,
            run_spacing=SPACE_MD,
        )

        # ---- Empty state ----
        self._empty_state = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Icon(ft.Icons.CELL_TOWER_ROUNDED, size=36,
                                        color=TEXT_TERTIARY),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        bgcolor=BG_SURFACE_2,
                        border_radius=RADIUS_LG,
                        padding=SPACE_XL,
                        width=80, height=80,
                    ),
                    ft.Text("Sin nodos detectados", size=15,
                            color=TEXT_SECONDARY, weight=ft.FontWeight.W_600,
                            font_family=FONT_FAMILY),
                    ft.Text("Los nodos apareceran aqui cuando se reciban datos",
                            size=12, color=TEXT_TERTIARY, font_family=FONT_FAMILY),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=SPACE_SM,
            ),
            alignment=ft.Alignment.CENTER,
            padding=ft.Padding(0, 80, 0, 0),
            visible=True,
        )

        # ---- Layout ----
        self.controls = [
            header,
            ft.Container(height=SPACE_SM),
            ft.Stack(
                controls=[
                    ft.Container(
                        content=self._cards_grid,
                        expand=True,
                    ),
                    self._empty_state,
                ],
                expand=True,
            ),
        ]
        self.spacing = SPACE_SM
        self.expand = True

    # ============================================================
    # Summary chip helper
    # ============================================================

    def _make_summary_chip(self, label, value, color):
        val_text = ft.Text(value, size=13, color=color,
                           weight=ft.FontWeight.W_700, font_family=FONT_MONO)
        lbl_text = ft.Text(label, size=9, color=TEXT_TERTIARY,
                           font_family=FONT_FAMILY, weight=ft.FontWeight.W_600)
        container = ft.Container(
            content=ft.Row(
                controls=[lbl_text, val_text],
                spacing=SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=BG_SURFACE_2,
            border=ft.border.all(1, BORDER_DEFAULT),
            border_radius=RADIUS_SM,
            padding=ft.Padding(SPACE_XS, SPACE_MD, SPACE_XS, SPACE_MD),
        )
        container._val = val_text  # ref para actualizar
        return container

    # ============================================================
    # Activacion / desactivacion
    # ============================================================

    async def activate(self):
        self._is_active = True
        if self._refresh_task is None:
            self._refresh_task = self._page.run_task(self._refresh_loop)

    def deactivate(self):
        self._is_active = False

    async def _refresh_loop(self):
        while self._is_active:
            try:
                self._update_nodes()
            except Exception as e:
                print(f"[NODES] Refresh error: {e}")
            await asyncio.sleep(self.REFRESH_RATE)
        self._refresh_task = None

    # ============================================================
    # Actualizacion de nodos
    # ============================================================

    def _update_nodes(self):
        node_ids = self._serial_manager.get_all_node_ids()

        if not node_ids:
            self._empty_state.visible = True
            self._safe_update(self._empty_state)
            return

        if self._empty_state.visible:
            self._empty_state.visible = False
            self._safe_update(self._empty_state)

        # Crear cards para nodos nuevos
        cards_changed = False
        for nid in node_ids:
            if nid not in self._node_cards:
                card = NodeCard(node_id=nid)
                self._node_cards[nid] = card
                cards_changed = True

        if cards_changed:
            self._cards_grid.controls = list(self._node_cards.values())
            self._safe_update(self._cards_grid)

        # Actualizar datos
        active_count = 0
        total_loss = 0.0
        for nid, card in self._node_cards.items():
            is_healthy = self._serial_manager.is_node_healthy(nid)
            card.set_health(is_healthy)
            
            # Actualizar MAC y Alias
            mac = self._serial_manager.get_node_mac(nid)
            if mac:
                card.set_mac(mac)
                alias = self._serial_manager.get_node_alias(mac)
                card.set_alias(alias)
            
            data = self._serial_manager.get_node_data(nid, 10)
            if data:
                # Find latest packet for CH0 (primary)
                latest = next((p for p in reversed(data) if p.channel_id == 0), data[-1])
                pkts = self._serial_manager.packets_received.get(nid, 0)
                loss = self._serial_manager.get_packet_loss_rate(nid)
                card.update_data(latest.values, latest.sequence, pkts, loss)
                
            if is_healthy:
                active_count += 1
                total_loss += self._serial_manager.get_packet_loss_rate(nid)

        # Actualizar summary chips
        self._chip_active._val.value = str(active_count)
        inactive = len(self._node_cards) - active_count
        self._chip_inactive._val.value = str(inactive)
        avg_loss = total_loss / max(active_count, 1)
        self._chip_avg_loss._val.value = f"{avg_loss:.1f}%"

        self._safe_update(self._chip_active)
        self._safe_update(self._chip_inactive)
        self._safe_update(self._chip_avg_loss)

    def _safe_update(self, ctrl):
        try:
            ctrl.update()
        except Exception:
            pass
