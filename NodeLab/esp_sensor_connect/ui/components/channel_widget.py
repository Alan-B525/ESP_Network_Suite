import flet as ft
import flet.canvas as cv

from ui.design_tokens import (
    FONT_FAMILY, FONT_MONO,
    BG_SURFACE_1, BG_SURFACE_2, BG_DEEPEST,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER_DEFAULT, BORDER_SUBTLE, RADIUS_MD, SPACE_SM, SPACE_MD,
    shadow_card
)

class ChannelWidget(ft.Container):
    """Mini-widget para visualizar un nodo y un canal específico."""
    
    MAX_POINTS = 100
    
    def __init__(self, node_id: int, channel_id: int, color: str, on_close):
        super().__init__()
        self.node_id = node_id
        self.channel_id = channel_id
        self.color = color
        self.on_close = on_close

        # Value text
        self._val_text = ft.Text("---", size=20, weight=ft.FontWeight.W_700,
                                 color=TEXT_PRIMARY, font_family=FONT_MONO)

        # Sparkline
        self._sparkline = cv.Canvas(
            shapes=[],
            expand=True,
        )
        
        self.bgcolor = BG_SURFACE_1
        self.border_radius = RADIUS_MD
        self.border = ft.border.all(1, BORDER_DEFAULT)
        self.shadow = shadow_card()
        self.padding = SPACE_MD
        
        self.content = ft.Column(
            controls=[
                # Header
                ft.Row(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Container(bgcolor=self.color, width=10, height=10, border_radius=5),
                                ft.Text(f"NODO {self.node_id} - CH {self.channel_id}", size=11, weight=ft.FontWeight.W_700, color=TEXT_SECONDARY),
                            ],
                            spacing=SPACE_SM,
                        ),
                        ft.Container(expand=True),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE_ROUNDED,
                            icon_size=14,
                            icon_color=TEXT_TERTIARY,
                            on_click=lambda e: self.on_close(self),
                            tooltip="Quitar widget",
                            width=24, height=24,
                        )
                    ],
                ),
                self._val_text,
                ft.Container(
                    content=self._sparkline,
                    bgcolor=BG_DEEPEST,
                    border_radius=RADIUS_MD,
                    border=ft.border.all(1, BORDER_SUBTLE),
                    expand=True,
                )
            ],
            spacing=SPACE_SM,
        )

    def update_data(self, values: list[float]):
        if not values:
            return
            
        self._val_text.value = f"{values[-1]:.2f}"
        
        w = 300.0  # approximate canvas width when in grid
        h = 100.0  # approximate canvas height
        
        y_min = min(values)
        y_max = max(values)
        rng = y_max - y_min
        if rng < 1.0:
            mid = (y_max + y_min) / 2.0
            y_min = mid - 0.5
            y_max = mid + 0.5
            rng = 1.0
            
        margin = rng * 0.15
        y_min -= margin
        y_max += margin
        rng = y_max - y_min
            
        path_els = []
        n = len(values)
        for i, v in enumerate(values):
            px = (i / max(self.MAX_POINTS - 1, 1)) * w
            py = h - ((v - y_min) / rng) * h
            py = max(0, min(h, py))
            if i == 0:
                path_els.append(cv.Path.MoveTo(px, py))
            else:
                path_els.append(cv.Path.LineTo(px, py))
                
        shapes = []
        
        shapes.append(cv.Path(
            path_els,
            paint=ft.Paint(
                color=ft.Colors.with_opacity(0.3, self.color), 
                stroke_width=4,
                style=ft.PaintingStyle.STROKE,
                anti_alias=True
            ),
        ))
        shapes.append(cv.Path(
            path_els,
            paint=ft.Paint(
                color=self.color, 
                stroke_width=2,
                style=ft.PaintingStyle.STROKE,
                anti_alias=True
            ),
        ))
        
        if n > 0:
            last_px = ((n - 1) / max(self.MAX_POINTS - 1, 1)) * w
            last_py = h - ((values[-1] - y_min) / rng) * h
            last_py = max(0, min(h, last_py))
            shapes.append(cv.Circle(
                x=last_px, y=last_py, radius=3,
                paint=ft.Paint(color=self.color, style=ft.PaintingStyle.FILL),
            ))
            
        self._sparkline.shapes = shapes
        
        try:
            self.update()
        except Exception:
            pass
