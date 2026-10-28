"""Light and dark colours for the widgets and the graph."""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

# Colour-blind-safe categorical palette; slot order matters (validated in this order).
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]

# Pressure gauges: deep / muted tones, so they do not read as MFC channels; used in the graph and the diagram.
GAUGES_LIGHT = {"chamber_frg": "#203a8f", "chamber_img": "#8e3fb0", "chamber_hfig": "#a8325e",
                "loadlock_frg": "#6b6a64", "gun": "#0e7f74", "column": "#8a5a1c"}
GAUGES_DARK = {"chamber_frg": "#8fa9f5", "chamber_img": "#c99be0", "chamber_hfig": "#e48aab",
               "loadlock_frg": "#b3b2aa", "gun": "#5fcfc2", "column": "#d9a868"}

# Status colours, always shown together with a text label.
GOOD = "#0ca30c"
WARNING = "#fab219"
SERIOUS = "#ec835a"
CRITICAL = "#d03b3b"


@dataclass(frozen=True)
class Theme:
    name: str
    dark: bool
    surface: str        # window and graph background
    panel: str          # cards, inputs
    text: str
    text_secondary: str
    grid: str
    border: str
    series: tuple
    gauges: tuple       # (gauge key, colour) pairs
    tint: str           # background of the secondary graph panels

    def channel_color(self, index, override=""):
        return override or self.series[index % len(self.series)]

    def gauge_color(self, key):
        return dict(self.gauges).get(key, self.text_secondary)


LIGHT = Theme("light", False, surface="#fcfcfb", panel="#ffffff", text="#0b0b0b", text_secondary="#52514e",
              grid="#e4e3df", border="#d3d2cc", series=tuple(SERIES_LIGHT), gauges=tuple(GAUGES_LIGHT.items()),
              tint="#f3f2ee")
DARK = Theme("dark", True, surface="#1a1a19", panel="#242422", text="#f0efec", text_secondary="#c3c2b7",
             grid="#383835", border="#45453f", series=tuple(SERIES_DARK), gauges=tuple(GAUGES_DARK.items()),
             tint="#212120")

MODES = ("system", "light", "dark")


def system_is_dark():
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def resolve(mode):
    if mode == "dark" or (mode == "system" and system_is_dark()):
        return DARK
    return LIGHT


def apply(app, mode):
    """Sets the Fusion style and the palette of `mode` ("system", "light", "dark"). Returns the Theme."""
    hints = app.styleHints()
    if mode == "system" and hasattr(hints, "unsetColorScheme"):
        hints.unsetColorScheme()        # back to following Windows
    theme = resolve(mode)
    app.setStyle("Fusion")
    p = QPalette()
    colors = {
        QPalette.Window: theme.surface, QPalette.WindowText: theme.text,
        QPalette.Base: theme.panel, QPalette.AlternateBase: theme.surface, QPalette.Text: theme.text,
        QPalette.Button: theme.panel, QPalette.ButtonText: theme.text, QPalette.BrightText: CRITICAL,
        QPalette.ToolTipBase: theme.panel, QPalette.ToolTipText: theme.text,
        QPalette.PlaceholderText: theme.text_secondary, QPalette.Highlight: theme.series[0],
        QPalette.HighlightedText: "#ffffff", QPalette.Link: theme.series[0],
        QPalette.Mid: theme.border, QPalette.Midlight: theme.grid, QPalette.Dark: theme.border,
        QPalette.Light: theme.panel, QPalette.Shadow: "#000000",
    }
    for role, color in colors.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(theme.text_secondary))
    app.setPalette(p)
    if mode != "system" and hasattr(hints, "setColorScheme"):     # Qt >= 6.8, also the title bar
        hints.setColorScheme(Qt.ColorScheme.Dark if theme.dark else Qt.ColorScheme.Light)
    return theme
