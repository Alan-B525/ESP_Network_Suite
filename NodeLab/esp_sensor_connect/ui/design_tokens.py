"""
design_tokens.py - Sistema de diseno centralizado
===================================================

Modulo de tokens de diseno que define toda la paleta visual de
la aplicacion ESP Sensor Connect. Inspirado en las mejores practicas
de diseno SCADA/HMI (ISA-101) y dashboards industriales modernos.

Toda la UI debe usar UNICAMENTE estas constantes y funciones helper.
Esto garantiza consistencia visual total y permite cambiar el tema
completo desde un solo lugar.
"""

import flet as ft


# ================================================================
# FUENTES
# ================================================================

FONT_INTER_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf"
FONT_FAMILY = "Inter"
FONT_MONO = "JetBrains Mono"
FONT_MONO_URL = "https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/fonts/ttf/JetBrainsMono-Regular.ttf"


# ================================================================
# SUPERFICIES (de mas oscura a mas clara)
# ================================================================

BG_DEEPEST = "#020617"        # Fondo de la ventana (Slate 950)
BG_SIDEBAR = "#080F1D"        # Sidebar / areas de navegacion
BG_SURFACE_0 = "#0F172A"      # Contenedor de primer nivel (Slate 900)
BG_SURFACE_1 = "#1E293B"      # Tarjetas, secciones (Slate 800)
BG_SURFACE_2 = "#334155"      # Campos de input, inner cards (Slate 700)
BG_SURFACE_3 = "#475569"      # Hover states

# ================================================================
# BORDES
# ================================================================

BORDER_SUBTLE = "#1E293B"      # Bordes muy sutiles entre paneles
BORDER_DEFAULT = "#334155"     # Bordes de tarjetas
BORDER_STRONG = "#475569"     # Bordes de inputs, botones
BORDER_FOCUS = "#0EA5E9"      # Borde al enfocar un input


# ================================================================
# TEXTOS
# ================================================================

TEXT_PRIMARY = "#F8FAFC"       # Titulos, valores principales (Slate 50)
TEXT_SECONDARY = "#94A3B8"     # Labels, descripciones (Slate 400)
TEXT_TERTIARY = "#64748B"      # Placeholders, metadata menor (Slate 500)
TEXT_DISABLED = "#475569"      # Texto deshabilitado


# ================================================================
# COLORES SEMANTICOS (ISA-101 inspirado)
# ================================================================

# Acento principal de la marca
ACCENT_PRIMARY = "#0EA5E9"     # Sky Blue — accion principal
ACCENT_PRIMARY_DIM = "#0284C7" # Sky Blue apagado — fondos de acento
ACCENT_SECONDARY = "#8B5CF6"   # Violeta — acento complementario

# Estados operacionales
STATUS_OK = "#10B981"          # Emerald — normal, conectado, ok
STATUS_OK_DIM = "#065F46"      # Emerald apagado
STATUS_WARNING = "#F59E0B"     # Amber — atencion, aceptable
STATUS_WARNING_DIM = "#92400E" # Amber apagado
STATUS_CRITICAL = "#EF4444"    # Red — error, critico
STATUS_CRITICAL_DIM = "#7F1D1D"  # Red apagado
STATUS_ACQUIRING = "#06B6D4"   # Cyan brillante — adquiriendo datos
STATUS_INACTIVE = "#64748B"    # Gris — inactivo

# Colores por nodo (10 nodos, paleta optimizada para fondo oscuro)
NODE_PALETTE = [
    "#00E5FF",   # Cyan
    "#76FF03",   # Lima
    "#FF9100",   # Naranja
    "#E040FB",   # Purpura
    "#FFD740",   # Ambar
    "#00E676",   # Verde
    "#FF5252",   # Rojo
    "#448AFF",   # Azul
    "#FF6E40",   # Coral
    "#69F0AE",   # Menta
]


# ================================================================
# ESPACIADO
# ================================================================

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32


# ================================================================
# RADIOS
# ================================================================

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14
RADIUS_XL = 18


# ================================================================
# SOMBRAS PREDEFINIDAS
# ================================================================

def shadow_glow(color: str, intensity: float = 0.3, radius: float = 16) -> ft.BoxShadow:
    """Crea una sombra tipo glow para indicadores y acentos."""
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=radius,
        color=ft.Colors.with_opacity(intensity, color),
    )


def shadow_card() -> ft.BoxShadow:
    """Sombra estandar para tarjetas elevadas."""
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=24,
        color=ft.Colors.with_opacity(0.15, "#000000"),
        offset=ft.Offset(0, 4),
    )


def shadow_elevated() -> ft.BoxShadow:
    """Sombra para elementos elevados (modales, popovers)."""
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=40,
        color=ft.Colors.with_opacity(0.25, "#000000"),
        offset=ft.Offset(0, 8),
    )


# ================================================================
# COMPONENTES BUILDER - Funciones para crear containers consistentes
# ================================================================

def section_card(
    content,
    accent_color: str = None,
    padding: int = SPACE_XL,
    expand: bool = False,
) -> ft.Container:
    """
    Crea una tarjeta de seccion con barra de acento superior opcional.

    Args:
        content: Contenido de la tarjeta.
        accent_color: Color de la barra superior decorativa (None = sin barra).
        padding: Padding interno.
        expand: Si la tarjeta debe expandirse.
    """
    children = []

    # Barra de acento superior
    if accent_color:
        children.append(
            ft.Container(
                height=3,
                bgcolor=accent_color,
                border_radius=ft.BorderRadius(RADIUS_MD, RADIUS_MD, 0, 0),
            )
        )

    children.append(
        ft.Container(
            content=content,
            padding=padding,
        )
    )

    return ft.Container(
        content=ft.Column(controls=children, spacing=0),
        bgcolor=BG_SURFACE_1,
        border_radius=RADIUS_LG,
        border=ft.border.all(1, BORDER_DEFAULT),
        shadow=shadow_card(),
        expand=expand,
    )


def glass_container(
    content,
    padding: int = SPACE_LG,
    border_color: str = BORDER_DEFAULT,
) -> ft.Container:
    """Crea un contenedor con efecto glassmorphism sutil."""
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=ft.Colors.with_opacity(0.4, BG_SURFACE_1),
        border=ft.border.all(1, ft.Colors.with_opacity(0.15, "#FFFFFF")),
        border_radius=RADIUS_LG,
        blur=ft.Blur(sigma_x=12, sigma_y=12),
    )


def metric_chip(label: str, value: str, color: str = ACCENT_PRIMARY) -> ft.Container:
    """
    Crea un chip de metrica compacto para KPIs.
    """
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(label, size=10, color=TEXT_TERTIARY,
                        weight=ft.FontWeight.W_600,
                        font_family=FONT_FAMILY),
                ft.Text(value, size=20, color=color,
                        weight=ft.FontWeight.W_700,
                        font_family=FONT_FAMILY),
            ],
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=BG_SURFACE_2,
        border=ft.border.all(1, BORDER_DEFAULT),
        border_radius=RADIUS_MD,
        padding=ft.Padding(SPACE_MD, SPACE_LG, SPACE_MD, SPACE_LG),
        expand=True,
    )


def kpi_card(
    icon: str,
    label: str,
    value: str,
    color: str = ACCENT_PRIMARY,
    sub_label: str = "",
) -> ft.Container:
    """
    Crea una tarjeta KPI estilo dashboard industrial.

    Icon + Label arriba, Valor grande abajo, sub-label opcional.
    """
    controls = [
        ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(icon, color=color, size=18),
                    bgcolor=ft.Colors.with_opacity(0.12, color),
                    border_radius=RADIUS_SM,
                    padding=SPACE_SM,
                    width=34,
                    height=34,
                ),
                ft.Text(label, size=11, color=TEXT_TERTIARY,
                        weight=ft.FontWeight.W_600,
                        font_family=FONT_FAMILY),
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Text(
            value, size=26, color=TEXT_PRIMARY,
            weight=ft.FontWeight.W_700,
            font_family=FONT_FAMILY,
        ),
    ]

    if sub_label:
        controls.append(
            ft.Text(sub_label, size=10, color=TEXT_TERTIARY,
                    font_family=FONT_FAMILY),
        )

    return ft.Container(
        content=ft.Column(
            controls=controls,
            spacing=SPACE_SM,
        ),
        bgcolor=BG_SURFACE_1,
        border=ft.border.all(1, BORDER_DEFAULT),
        border_radius=RADIUS_LG,
        padding=SPACE_LG,
        shadow=shadow_card(),
        expand=True,
    )


def nav_button(
    icon: str,
    label: str,
    selected: bool = False,
    on_click=None,
) -> ft.Container:
    """Crea un boton de navegacion para la sidebar custom."""
    bg = ft.Colors.with_opacity(0.08, ACCENT_PRIMARY) if selected else ft.Colors.TRANSPARENT
    text_color = ACCENT_PRIMARY if selected else TEXT_SECONDARY
    icon_color = ACCENT_PRIMARY if selected else TEXT_TERTIARY

    return ft.Container(
        content=ft.Row(
            controls=[
                # Indicador lateral luminoso
                ft.Container(
                    width=3,
                    height=24,
                    border_radius=2,
                    bgcolor=ACCENT_PRIMARY if selected else ft.Colors.TRANSPARENT,
                    shadow=shadow_glow(ACCENT_PRIMARY, 0.5, 8) if selected else None,
                ),
                ft.Container(width=SPACE_SM),
                ft.Icon(icon, color=icon_color, size=20),
                ft.Container(width=SPACE_SM),
                ft.Text(
                    label, size=13, color=text_color,
                    weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                    font_family=FONT_FAMILY,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        ),
        padding=ft.Padding(SPACE_SM, 0, SPACE_LG, 0),
        border_radius=RADIUS_SM,
        bgcolor=bg,
        on_click=on_click,
        on_hover=lambda e: _on_nav_hover(e, selected),
        height=44,
        animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
    )


def _on_nav_hover(e, selected: bool):
    """Handle hover effect en botones de navegacion."""
    if not selected:
        e.control.bgcolor = (
            ft.Colors.with_opacity(0.05, ACCENT_PRIMARY)
            if e.data == "true"
            else ft.Colors.TRANSPARENT
        )
        try:
            e.control.update()
        except Exception:
            pass


def input_field(
    label: str,
    value: str = "",
    width: int = 200,
    icon: str = None,
    on_change=None,
    on_submit=None,
    hint_text: str = "",
    read_only: bool = False,
    mono: bool = False,
) -> ft.TextField:
    """Crea un campo de texto estilizado con el design system."""
    return ft.TextField(
        label=label,
        value=value,
        width=width,
        hint_text=hint_text,
        read_only=read_only,
        prefix_icon=icon,
        on_change=on_change,
        on_submit=on_submit,
        border_color=BORDER_STRONG,
        focused_border_color=ACCENT_PRIMARY,
        label_style=ft.TextStyle(color=TEXT_SECONDARY, font_family=FONT_FAMILY),
        text_style=ft.TextStyle(
            color=TEXT_PRIMARY,
            font_family=FONT_MONO if mono else FONT_FAMILY,
        ),
        hint_style=ft.TextStyle(color=TEXT_TERTIARY),
        bgcolor=BG_SURFACE_2,
        focused_bgcolor=BG_SURFACE_2,
        border_radius=RADIUS_SM,
        cursor_color=ACCENT_PRIMARY,
        content_padding=ft.Padding(SPACE_MD, SPACE_LG, SPACE_MD, SPACE_LG),
    )


def styled_dropdown(
    label: str,
    value: str = "",
    options: list = None,
    width: int = 200,
    on_select=None,
) -> ft.Dropdown:
    """Crea un dropdown estilizado con el design system."""
    return ft.Dropdown(
        label=label,
        value=value,
        options=options or [],
        on_select=on_select,
        width=width,
        border_color=BORDER_STRONG,
        focused_border_color=ACCENT_PRIMARY,
        label_style=ft.TextStyle(color=TEXT_SECONDARY, font_family=FONT_FAMILY),
        text_style=ft.TextStyle(color=TEXT_PRIMARY, font_family=FONT_FAMILY),
        bgcolor=BG_SURFACE_2,
        border_radius=RADIUS_SM,
    )


def primary_button(
    label: str,
    icon: str = None,
    on_click=None,
    color: str = ACCENT_PRIMARY,
    text_color: str = BG_DEEPEST,
) -> ft.ElevatedButton:
    """Crea un boton primario estilizado."""
    return ft.ElevatedButton(
        label,
        icon=icon,
        on_click=on_click,
        bgcolor=color,
        color=text_color,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            padding=ft.Padding(SPACE_MD, SPACE_XL, SPACE_MD, SPACE_XL),
            text_style=ft.TextStyle(
                weight=ft.FontWeight.W_600,
                size=13,
                font_family=FONT_FAMILY,
            ),
            shadow_color=ft.Colors.with_opacity(0.2, color),
            elevation=2,
        ),
    )


def danger_button(label: str, icon: str = None, on_click=None) -> ft.ElevatedButton:
    """Crea un boton de accion destructiva/stop."""
    return primary_button(label, icon, on_click,
                          color=STATUS_CRITICAL, text_color="#FFFFFF")


def ghost_button(
    icon: str,
    tooltip: str = "",
    on_click=None,
) -> ft.IconButton:
    """Crea un boton icono fantasma (sin fondo visible)."""
    return ft.IconButton(
        icon=icon,
        icon_color=TEXT_SECONDARY,
        tooltip=tooltip,
        on_click=on_click,
        icon_size=20,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=RADIUS_SM),
            bgcolor=ft.Colors.TRANSPARENT,
        ),
    )
