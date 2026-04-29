import flet as ft
from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO,
    BG_SIDEBAR, BG_SURFACE_2,
    BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    ACCENT_PRIMARY,
    RADIUS_MD, RADIUS_SM,
    SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL,
    shadow_glow
)

class Sidebar(ft.Container):
    """Custom sidebar component for the application."""
    
    NAV_ITEMS = [
        {"icon": ft.Icons.INSIGHTS_ROUNDED, "label": "Dashboard", "idx": 0},
        {"icon": ft.Icons.CELL_TOWER_ROUNDED, "label": "Nodos", "idx": 1},
        {"icon": ft.Icons.TUNE_ROUNDED, "label": "Configuracion", "idx": 2},
    ]

    def __init__(self, on_nav_change):
        super().__init__()
        self.on_nav_change = on_nav_change
        self.width = 220
        self.bgcolor = BG_SIDEBAR
        self.padding = 0
        self.expand = False
        
        self._nav_buttons: list[ft.Container] = []
        self._current_index = 0
        
        self.content = self._build()

    def _build(self) -> ft.Column:
        # Logo area
        logo_area = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(ft.Icons.SENSORS_ROUNDED, color=ACCENT_PRIMARY, size=22),
                                bgcolor=ft.Colors.with_opacity(0.1, ACCENT_PRIMARY),
                                border_radius=RADIUS_MD,
                                padding=SPACE_SM,
                                width=40, height=40,
                                shadow=shadow_glow(ACCENT_PRIMARY, 0.15, 12),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text("ESP Sensor", size=14, weight=ft.FontWeight.W_700, color=TEXT_PRIMARY, font_family=FONT_FAMILY),
                                    ft.Text("Connect", size=14, weight=ft.FontWeight.W_300, color=ACCENT_PRIMARY, font_family=FONT_FAMILY),
                                ],
                                spacing=0,
                            ),
                        ],
                        spacing=SPACE_MD,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text("Wireless Sensor Network", size=9, color=TEXT_TERTIARY, font_family=FONT_FAMILY, weight=ft.FontWeight.W_500),
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

        self.nav_column = ft.Column(
            controls=nav_controls,
            spacing=SPACE_XS,
        )

        nav_section = ft.Container(
            content=self.nav_column,
            padding=ft.Padding(0, SPACE_MD, 0, SPACE_MD),
        )

        # System info (bottom)
        sys_info = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(height=1, bgcolor=BORDER_SUBTLE, margin=ft.Margin(0, SPACE_MD, 0, 0)),
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text("v1.0", size=9, color=TEXT_TERTIARY, font_family=FONT_MONO),
                                bgcolor=BG_SURFACE_2, border_radius=3, padding=ft.Padding(2, 5, 2, 5),
                            ),
                            ft.Text("TDMA", size=9, color=TEXT_TERTIARY, font_family=FONT_MONO, weight=ft.FontWeight.W_600),
                        ],
                        spacing=SPACE_SM,
                    ),
                    ft.Text("ESP-NOW Protocol", size=9, color=TEXT_TERTIARY, font_family=FONT_FAMILY),
                ],
                spacing=SPACE_SM,
            ),
            padding=ft.Padding(SPACE_LG, SPACE_XL, SPACE_LG, SPACE_XL),
        )

        return ft.Column(
            controls=[
                logo_area,
                nav_section,
                ft.Container(expand=True),
                sys_info,
            ],
            spacing=0,
        )

    def _make_nav_button(self, icon, label, selected, idx) -> ft.Container:
        bg = ft.Colors.with_opacity(0.08, ACCENT_PRIMARY) if selected else ft.Colors.TRANSPARENT
        txt_color = ACCENT_PRIMARY if selected else TEXT_SECONDARY
        icon_color = ACCENT_PRIMARY if selected else TEXT_TERTIARY

        return ft.Container(
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
            on_click=lambda e, i=idx: self._on_click(i),
            height=42,
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            on_hover=self._on_nav_hover,
            data={"selected": selected}
        )

    def _on_nav_hover(self, e):
        if not e.control.data["selected"]:
            e.control.bgcolor = ft.Colors.with_opacity(0.04, ACCENT_PRIMARY) if e.data == "true" else ft.Colors.TRANSPARENT
            e.control.update()

    def _on_click(self, index):
        if self._current_index == index:
            return
            
        self._current_index = index
        for i, item in enumerate(self.NAV_ITEMS):
            selected = (i == index)
            # Efficiently update existing buttons
            btn = self._nav_buttons[i]
            btn.bgcolor = ft.Colors.with_opacity(0.08, ACCENT_PRIMARY) if selected else ft.Colors.TRANSPARENT
            btn.data["selected"] = selected
            
            # Update row children (indicator and text)
            row = btn.content
            row.controls[0].bgcolor = ACCENT_PRIMARY if selected else ft.Colors.TRANSPARENT
            row.controls[0].shadow = shadow_glow(ACCENT_PRIMARY, 0.5, 8) if selected else None
            row.controls[2].color = ACCENT_PRIMARY if selected else TEXT_TERTIARY
            row.controls[4].color = ACCENT_PRIMARY if selected else TEXT_SECONDARY
            row.controls[4].weight = ft.FontWeight.W_600 if selected else ft.FontWeight.W_500
            
        self.nav_column.update()
        if self.on_nav_change:
            self.on_nav_change(index)
            
    def set_selected(self, index):
        """Programmatically set selected index without triggering on_nav_change."""
        self._current_index = index
        # Update UI same as _on_click but without callback
        for i, item in enumerate(self.NAV_ITEMS):
            selected = (i == index)
            btn = self._nav_buttons[i]
            btn.bgcolor = ft.Colors.with_opacity(0.08, ACCENT_PRIMARY) if selected else ft.Colors.TRANSPARENT
            btn.data["selected"] = selected
            row = btn.content
            row.controls[0].bgcolor = ACCENT_PRIMARY if selected else ft.Colors.TRANSPARENT
            row.controls[2].color = ACCENT_PRIMARY if selected else TEXT_TERTIARY
            row.controls[4].color = ACCENT_PRIMARY if selected else TEXT_SECONDARY
        self.nav_column.update()
