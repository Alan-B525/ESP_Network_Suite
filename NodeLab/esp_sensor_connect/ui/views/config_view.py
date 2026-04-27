"""
config_view.py - Vista de configuracion profesional
=====================================================

Secciones con tarjetas acentuadas para conexion serie,
parametros TDMA, y terminal de comandos estilizada.
"""

import datetime
import json
import os
import flet as ft

from core.serial_manager import SerialManager
from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO,
    BG_DEEPEST, BG_SURFACE_0, BG_SURFACE_1, BG_SURFACE_2,
    BORDER_DEFAULT, BORDER_SUBTLE, BORDER_STRONG,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    ACCENT_PRIMARY, ACCENT_SECONDARY, STATUS_OK, STATUS_CRITICAL, STATUS_WARNING,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
    SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL,
    section_card, input_field, styled_dropdown,
    primary_button, danger_button, ghost_button,
    shadow_card,
)


class ConfigView(ft.Column):
    """Vista de configuracion con secciones estilizadas y terminal."""

    def __init__(self, serial_manager: SerialManager, page: ft.Page):
        super().__init__()

        self._serial_manager = serial_manager
        self._page = page
        self._selected_port = ""
        self._selected_baudrate = str(SerialManager.DEFAULT_BAUDRATE)
        self._tdma_freq = "100"
        self._tdma_slot = "10"
        self._tdma_max_nodes = "10"
        self._log_lines: list[str] = ["[ Sistema listo ]"]
        self._config_file = "app_config.json"
        
        self._load_config()
        self._serial_manager.set_on_raw_line(self._on_serial_line)

        # ============================================================
        # SECCION 1: Conexion Serie
        # ============================================================

        self._port_dropdown = styled_dropdown(
            label="Puerto COM",
            options=[],
            on_select=self._on_port_selected,
            width=280,
        )

        self._refresh_btn = ghost_button(
            icon=ft.Icons.REFRESH_ROUNDED,
            tooltip="Buscar puertos COM",
            on_click=self._on_refresh_ports,
        )

        self._port_info = ft.Text(
            "", size=11, color=TEXT_TERTIARY,
            font_family=FONT_FAMILY, italic=True,
        )

        self._baudrate_dropdown = styled_dropdown(
            label="Baudrate",
            value=self._selected_baudrate,
            options=[ft.dropdown.Option(str(b), f"{b:,} baud")
                     for b in SerialManager.BAUDRATES],
            on_select=self._on_baudrate_selected,
            width=180,
        )

        self._connect_btn = primary_button(
            "Conectar", icon=ft.Icons.USB_ROUNDED,
            on_click=self._on_connect, color=ACCENT_PRIMARY,
        )

        self._disconnect_btn = danger_button(
            "Desconectar", icon=ft.Icons.USB_OFF_ROUNDED,
            on_click=self._on_disconnect,
        )
        self._disconnect_btn.visible = False

        connection_section = section_card(
            accent_color=ACCENT_PRIMARY,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            self._port_dropdown,
                            self._refresh_btn,
                            ft.Container(width=SPACE_SM),
                            self._baudrate_dropdown,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    self._port_info,
                    ft.Row(
                        controls=[self._connect_btn, self._disconnect_btn],
                        spacing=SPACE_MD,
                    ),
                ],
                spacing=SPACE_MD,
            ),
        )

        # ============================================================
        # SECCION 2: Parametros de Adquisicion
        # ============================================================

        self._freq_input = input_field(
            label="Sample Rate (Hz)", value=self._tdma_freq, width=200,
            icon=ft.Icons.SPEED_ROUNDED,
        )

        # Info de solo lectura — estos son parámetros compilados en el firmware
        self._slot_info = ft.Text(
            "Slot: 90ms | Ciclo: 1000ms | Guard: 200µs",
            size=11, color=TEXT_TERTIARY,
            font_family=FONT_MONO, italic=True,
        )
        self._max_nodes_info = ft.Text(
            "Max Nodos: 10 | Max Slots: 10 | Max Canales/Nodo: 4",
            size=11, color=TEXT_TERTIARY,
            font_family=FONT_MONO, italic=True,
        )

        self._apply_tdma_btn = primary_button(
            "Aplicar Sample Rate", icon=ft.Icons.SEND_ROUNDED,
            on_click=self._on_apply_tdma, color=STATUS_OK,
        )

        tdma_section = section_card(
            accent_color=STATUS_OK,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[self._freq_input],
                        spacing=SPACE_LG,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    self._slot_info,
                    self._max_nodes_info,
                    self._apply_tdma_btn,
                ],
                spacing=SPACE_MD,
            ),
        )

        # ============================================================
        # SECCION 2.5: Identificacion de Nodos
        # ============================================================

        self._alias_mac_dropdown = styled_dropdown(
            label="Seleccionar Nodo (MAC)",
            options=[],
            on_select=self._on_alias_node_selected,
            width=280,
        )

        self._refresh_alias_btn = ghost_button(
            icon=ft.Icons.REFRESH_ROUNDED,
            tooltip="Actualizar lista de nodos",
            on_click=self._on_refresh_alias_nodes,
        )

        self._alias_input = input_field(
            label="Alias del Nodo", value="", width=200,
            icon=ft.Icons.BADGE_ROUNDED,
        )

        self._save_alias_btn = primary_button(
            "Guardar Alias", icon=ft.Icons.SAVE_ROUNDED,
            on_click=self._on_save_alias, color=ACCENT_PRIMARY,
        )

        alias_section = section_card(
            accent_color=ACCENT_PRIMARY,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            self._alias_mac_dropdown,
                            self._refresh_alias_btn,
                            ft.Container(width=SPACE_SM),
                            self._alias_input,
                            self._save_alias_btn,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.END,
                        wrap=True,
                    ),
                ],
                spacing=SPACE_MD,
            ),
        )

        # ============================================================
        # SECCION 3: Terminal
        # ============================================================

        self._cmd_input = input_field(
            label="Comando",
            hint_text="CMD:SET_FREQ=200",
            width=400, mono=True,
            icon=ft.Icons.TERMINAL_ROUNDED,
            on_submit=self._on_send_manual_cmd,
        )

        self._send_btn = ghost_button(
            icon=ft.Icons.SEND_ROUNDED,
            tooltip="Enviar comando",
            on_click=self._on_send_manual_cmd,
        )

        # Terminal output
        self._terminal_output = ft.Text(
            value="[ Sistema listo ]\n",
            size=11,
            color=TEXT_SECONDARY,
            font_family=FONT_MONO,
            selectable=True,
        )

        terminal_scroll = ft.Container(
            content=ft.Column(
                controls=[self._terminal_output],
                scroll=ft.ScrollMode.AUTO,
                auto_scroll=True,
            ),
            bgcolor=BG_DEEPEST,
            border_radius=RADIUS_SM,
            border=ft.border.all(1, BORDER_SUBTLE),
            padding=SPACE_MD,
            height=180,
            expand=True,
        )

        # Terminal header decoration
        terminal_header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(width=8, height=8, border_radius=4,
                                 bgcolor="#FF5F57"),
                    ft.Container(width=8, height=8, border_radius=4,
                                 bgcolor="#FFBD2E"),
                    ft.Container(width=8, height=8, border_radius=4,
                                 bgcolor="#28C840"),
                    ft.Container(width=SPACE_MD),
                    ft.Text("Terminal", size=10, color=TEXT_TERTIARY,
                            font_family=FONT_MONO, weight=ft.FontWeight.W_500),
                ],
                spacing=SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.5, BG_SURFACE_2),
            border_radius=ft.BorderRadius(RADIUS_SM, RADIUS_SM, 0, 0),
            padding=ft.Padding(SPACE_SM, SPACE_MD, SPACE_SM, SPACE_MD),
        )

        terminal_section = section_card(
            accent_color=ACCENT_SECONDARY,
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[self._cmd_input, self._send_btn],
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    ft.Container(
                        content=ft.Column(
                            controls=[terminal_header, terminal_scroll],
                            spacing=0,
                        ),
                        expand=True,
                    ),
                ],
                spacing=SPACE_MD,
                expand=True,
            ),
        )

        # ============================================================
        # LAYOUT
        # ============================================================

        # Section labels
        lbl_conn = self._section_label("CONEXION SERIE")
        lbl_tdma = self._section_label("PARAMETROS DE ADQUISICION")
        lbl_alias = self._section_label("IDENTIFICACION DE NODOS")
        lbl_term = self._section_label("TERMINAL DE COMANDOS")

        self.controls = [
            lbl_conn, connection_section,
            ft.Container(height=SPACE_SM),
            lbl_tdma, tdma_section,
            ft.Container(height=SPACE_SM),
            lbl_alias, alias_section,
            ft.Container(height=SPACE_SM),
            lbl_term, terminal_section,
        ]
        self.spacing = SPACE_SM
        self.expand = True
        self.scroll = ft.ScrollMode.AUTO

        self._refresh_ports()

    # ============================================================
    # Helpers
    # ============================================================

    def _section_label(self, title: str) -> ft.Text:
        return ft.Text(
            title, size=10, color=TEXT_TERTIARY,
            weight=ft.FontWeight.W_700, font_family=FONT_FAMILY,
        )

    def _log(self, message: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_lines.append(f"[{ts}] {message}")
        if len(self._log_lines) > 200:
            self._log_lines = self._log_lines[-100:]
        self._terminal_output.value = "\n".join(self._log_lines) + "\n"
        try:
            self._terminal_output.update()
        except Exception:
            pass

    # ============================================================
    # Handlers - Puerto Serie
    # ============================================================

    def _refresh_ports(self):
        ports = SerialManager.list_available_ports()
        self._port_dropdown.options = [
            ft.dropdown.Option(p["device"],
                               f'{p["device"]} - {p["description"]}')
            for p in ports
        ]
        self._port_info.value = (
            f"{len(ports)} puertos detectados" if ports
            else "No se detectaron puertos COM"
        )

    def _on_refresh_ports(self, e):
        self._refresh_ports()
        self._log("Puertos COM actualizados")
        try:
            self._port_dropdown.update()
            self._port_info.update()
        except Exception:
            pass

    def _on_port_selected(self, e):
        self._selected_port = e.control.value
        self._save_config()
        self._log(f"Puerto seleccionado: {self._selected_port}")

    def _on_baudrate_selected(self, e):
        self._selected_baudrate = e.control.value
        self._save_config()
        self._log(f"Baudrate: {self._selected_baudrate}")

    def _on_connect(self, e):
        if not self._selected_port:
            self._show_snackbar("Selecciona un puerto COM primero", STATUS_WARNING)
            return

        baudrate = int(self._selected_baudrate)
        self._log(f"Conectando a {self._selected_port} @ {baudrate}...")

        success = self._serial_manager.connect(
            port=self._selected_port, baudrate=baudrate,
        )

        if success:
            self._log(f"OK Conectado a {self._selected_port}")
            self._connect_btn.visible = False
            self._disconnect_btn.visible = True
            self._show_snackbar(f"Conectado a {self._selected_port}", STATUS_OK)
        else:
            self._log(f"ERROR al conectar a {self._selected_port}")
            self._show_snackbar(f"Error al conectar", STATUS_CRITICAL)

        try:
            self._connect_btn.update()
            self._disconnect_btn.update()
        except Exception:
            pass

    def _on_disconnect(self, e):
        self._serial_manager.disconnect()
        self._log("Desconectado del puerto serie")
        self._connect_btn.visible = True
        self._disconnect_btn.visible = False
        self._show_snackbar("Desconectado", TEXT_SECONDARY)
        try:
            self._connect_btn.update()
            self._disconnect_btn.update()
        except Exception:
            pass

    # ============================================================
    # Handlers - TDMA
    # ============================================================

    def _on_apply_tdma(self, e):
        if not self._serial_manager.is_connected:
            self._show_snackbar("No hay conexion activa", STATUS_WARNING)
            return

        rate_str = self._freq_input.value.strip()
        try:
            rate_hz = int(rate_str)
        except ValueError:
            self._show_snackbar(f"Valor inválido: '{rate_str}'. Ingresa un número entero.", STATUS_CRITICAL)
            return
        
        if rate_hz < 1 or rate_hz > 10000:
            self._show_snackbar(f"Rate fuera de rango: {rate_hz} Hz (válido: 1-10000)", STATUS_WARNING)
            return
        
        ok = self._serial_manager.set_sample_rate(rate_hz)
        if ok:
            self._log(f"OK > CMD_SET_RATE,{rate_hz}")
            self._show_snackbar(f"Sample rate configurado a {rate_hz} Hz", STATUS_OK)
        else:
            self._log(f"FAIL > CMD_SET_RATE,{rate_hz}")
            self._show_snackbar("Error al enviar comando", STATUS_CRITICAL)

        self._save_config()

    # ============================================================
    # Handlers - Identificacion
    # ============================================================

    def _on_refresh_alias_nodes(self, e):
        node_ids = self._serial_manager.get_all_node_ids()
        options = []
        for nid in node_ids:
            mac = self._serial_manager.get_node_mac(nid)
            if mac:
                alias = self._serial_manager.get_node_alias(mac)
                label = f"NODO {nid} - {mac}" + (f" ({alias})" if alias else "")
                options.append(ft.dropdown.Option(mac, label))
        
        self._alias_mac_dropdown.options = options
        try:
            self._alias_mac_dropdown.update()
        except Exception:
            pass

    def _on_alias_node_selected(self, e):
        mac = e.control.value
        alias = self._serial_manager.get_node_alias(mac)
        self._alias_input.value = alias
        try:
            self._alias_input.update()
        except Exception:
            pass

    def _on_save_alias(self, e):
        mac = self._alias_mac_dropdown.value
        if not mac:
            self._show_snackbar("Selecciona un nodo primero", STATUS_WARNING)
            return
        
        alias = self._alias_input.value.strip()
        self._serial_manager.set_node_alias(mac, alias)
        self._show_snackbar("Alias guardado correctamente", STATUS_OK)
        self._on_refresh_alias_nodes(None)

    # ============================================================
    # Handlers - Terminal
    # ============================================================

    def _on_send_manual_cmd(self, e):
        cmd = self._cmd_input.value
        if not cmd:
            return
        if not self._serial_manager.is_connected:
            self._show_snackbar("No hay conexion activa", STATUS_WARNING)
            return

        ok = self._serial_manager.send_command(cmd)
        s = ">" if ok else "FAIL"
        self._log(f"{s} {cmd}")
        self._cmd_input.value = ""
        try:
            self._cmd_input.update()
        except Exception:
            pass

    # ============================================================
    # Utilidades
    # ============================================================

    def _on_serial_line(self, line: str):
        self._log(f'RX: {line}')

    def _show_snackbar(self, message: str, color: str = TEXT_PRIMARY):
        try:
            snack = ft.SnackBar(
                content=ft.Text(message, color=TEXT_PRIMARY,
                                font_family=FONT_FAMILY),
                bgcolor=BG_SURFACE_1,
                duration=3000,
                open=True,
            )
            self._page.overlay.append(snack)
            self._page.update()
        except Exception:
            pass

    def update_connection_state(self, connected: bool):
        """Actualiza la UI cuando cambia el estado de conexion externamente."""
        self._connect_btn.visible = not connected
        self._disconnect_btn.visible = connected
        try:
            self._connect_btn.update()
            self._disconnect_btn.update()
        except Exception:
            pass

    def _load_config(self):
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, "r") as f:
                    cfg = json.load(f)
                    self._selected_port = cfg.get("port", "")
                    self._selected_baudrate = cfg.get("baudrate", str(SerialManager.DEFAULT_BAUDRATE))
                    self._tdma_freq = cfg.get("tdma_freq", "100")
                    self._tdma_slot = cfg.get("tdma_slot", "10")
                    self._tdma_max_nodes = cfg.get("tdma_max_nodes", "10")
            except Exception as e:
                print(f"[CONFIG] Error cargando config: {e}")

    def _save_config(self):
        cfg = {
            "port": self._selected_port,
            "baudrate": self._selected_baudrate,
            "tdma_freq": self._freq_input.value,
        }
        try:
            with open(self._config_file, "w") as f:
                json.dump(cfg, f, indent=4)
        except Exception as e:
            print(f"[CONFIG] Error guardando config: {e}")
