import flet as ft
from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO,
    BG_SURFACE_0, BG_SURFACE_2, BG_DEEPEST,
    BORDER_DEFAULT, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_TERTIARY,
    STATUS_OK, STATUS_CRITICAL, STATUS_ACQUIRING,
    RADIUS_SM,
    SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL,
    primary_button
)
from ui.components.status_indicator import StatusIndicator

class Header(ft.Container):
    """Custom header bar component for the application."""

    def __init__(self, on_start_stop):
        super().__init__()
        self.on_start_stop = on_start_stop
        
        self.padding = ft.Padding(SPACE_LG, SPACE_XL, SPACE_LG, SPACE_XL)
        self.bgcolor = BG_SURFACE_0
        self.border = ft.Border(bottom=ft.BorderSide(1, BORDER_SUBTLE))
        
        # Components
        self.status_indicator = StatusIndicator()
        self.status_indicator.set_searching()
        
        self.timer_text = ft.Text(
            "00:00:00", size=16, color=TEXT_TERTIARY,
            weight=ft.FontWeight.W_600,
            font_family=FONT_MONO,
        )
        
        self.timer_container = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SCHEDULE_ROUNDED, color=TEXT_TERTIARY, size=16),
                    self.timer_text,
                ],
                spacing=SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=BG_SURFACE_2,
            border=ft.border.all(1, BORDER_DEFAULT),
            border_radius=RADIUS_SM,
            padding=ft.Padding(SPACE_SM, SPACE_MD, SPACE_SM, SPACE_MD),
        )
        
        self.start_btn = primary_button(
            "START", icon=ft.Icons.PLAY_ARROW_ROUNDED,
            on_click=self._on_btn_click, color=STATUS_OK,
        )
        self.start_btn.disabled = True
        
        self.title_text = ft.Text(
            "Dashboard", size=18, color=TEXT_PRIMARY,
            weight=ft.FontWeight.W_600, font_family=FONT_FAMILY
        )

        self.content = ft.Row(
            controls=[
                self.title_text,
                ft.Container(expand=True),
                self.status_indicator,
                ft.Container(width=SPACE_MD),
                self.timer_container,
                ft.Container(width=SPACE_MD),
                self.start_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _on_btn_click(self, e):
        if self.on_start_stop:
            self.on_start_stop(e)

    def set_title(self, title: str):
        self.title_text.value = title
        self.title_text.update()

    def set_acquiring_state(self, acquiring: bool, port: str = ""):
        if acquiring:
            self.start_btn.text = "STOP"
            self.start_btn.icon = ft.Icons.STOP_ROUNDED
            self.start_btn.bgcolor = STATUS_CRITICAL
            self.start_btn.color = "#FFFFFF"
            if hasattr(self.start_btn, "style") and self.start_btn.style:
                self.start_btn.style.shadow_color = ft.Colors.with_opacity(0.2, STATUS_CRITICAL)
            
            self.status_indicator.set_acquiring()
            self.timer_text.color = STATUS_ACQUIRING
            self.timer_container.border = ft.border.all(1, ft.Colors.with_opacity(0.3, STATUS_ACQUIRING))
        else:
            self.start_btn.text = "START"
            self.start_btn.icon = ft.Icons.PLAY_ARROW_ROUNDED
            self.start_btn.bgcolor = STATUS_OK
            self.start_btn.color = BG_DEEPEST
            if hasattr(self.start_btn, "style") and self.start_btn.style:
                self.start_btn.style.shadow_color = ft.Colors.with_opacity(0.2, STATUS_OK)
            
            if port:
                self.status_indicator.set_connected(port)
            else:
                self.status_indicator.set_searching()
                
            self.timer_text.color = TEXT_TERTIARY
            self.timer_container.border = ft.border.all(1, BORDER_DEFAULT)
            
        self.start_btn.update()
        self.timer_text.update()
        self.timer_container.update()

    def update_timer(self, time_str: str):
        self.timer_text.value = time_str
        self.timer_text.update()

    def set_connection_state(self, connected: bool, port: str = ""):
        if connected:
            self.status_indicator.set_connected(port)
            self.start_btn.disabled = False
        else:
            self.status_indicator.set_searching()
            self.start_btn.disabled = True
        self.start_btn.update()
