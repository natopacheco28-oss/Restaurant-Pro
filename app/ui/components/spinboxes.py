"""Cuadros numéricos Fluent sobre Qt puro — botones que SIEMPRE funcionan.

Por qué no se usan los `SpinBox`/`DoubleSpinBox` de qfluentwidgets: su
lineEdit interno recibe una geometría de ~1 px de ancho (verificado con
capturas de pantalla), de modo que el número se ve recortado/invisible y
experiencia de uso es inservible pese a que sus botones responden al clic.

Este componente usa el `QSpinBox`/`QDoubleSpinBox` NATIVO de Qt — botones
▲/▼ reales de Qt (responden siempre, incluso manteniéndolos presionados,
con repetición acelerada) y el texto NUNCA se recorta — con una hoja de
estilos propia que replica el look Fluent:

- Fondo/borde redondeado y colores que siguen el tema claro/oscuro
  (se reaplican al cambiar el tema, sin reiniciar).
- Altura mínima 33 px, alineación izquierda centrada verticalmente.
- Padding derecho que reserva el área de las flechas.
- Ancho mínimo ≥ 110 px que se AMPLÍA automáticamente según el texto
  máximo posible (rango, decimales, prefijo y sufijo) — funciona con
  valores como 1,250.50, al maximizar y con escalado 125/150 %.

La API (clases y fábricas) es la misma que usan todos los diálogos del
proyecto, así que no se requiere ningún cambio en quien la consume.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox
from qfluentwidgets import isDarkTheme, qconfig

# Espacio reservado a la derecha para los botones nativos ▲/▼ + padding
BUTTON_AREA_PX = 46

# Ancho mínimo absoluto pedido
MIN_WIDTH_PX = 110

# Ancho mínimo por defecto (cómodo para montos comunes)
DEFAULT_WIDTH_PX = 130

# Altura estándar Fluent de un control de entrada (rango pedido 33–36)
MIN_HEIGHT_PX = 33

# Aproximación del ancho de un carácter numérico en la fuente de la app
CHAR_WIDTH_PX = 9

ACCENT_FALLBACK = "#ff7a1a"

_QSS = """
QAbstractSpinBox {{
    background: {background};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 3px {padding_right}px 3px 10px;
    color: {color};
    min-height: {min_height}px;
    selection-background-color: {accent};
    selection-color: #ffffff;
}}
QAbstractSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border: none;
    background: transparent;
}}
QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border: none;
    background: transparent;
}}
QAbstractSpinBox::up-button:hover,
QAbstractSpinBox::down-button:hover {{
    background: {button_hover};
}}
QAbstractSpinBox::up-button:pressed,
QAbstractSpinBox::down-button:pressed {{
    background: {button_pressed};
}}
"""


def _theme_qss() -> str:
    """Hoja de estilos del spinbox según el tema actual (claro/oscuro)."""
    dark = isDarkTheme()
    accent = str(getattr(qconfig, "themeColor", "") or ACCENT_FALLBACK)
    if dark:
        palette = {
            "background": "#272727",
            "border": "rgba(255, 255, 255, 0.12)",
            "color": "#fafafa",
            "button_hover": "rgba(255, 255, 255, 0.08)",
            "button_pressed": "rgba(255, 255, 255, 0.14)",
        }
    else:
        palette = {
            "background": "#ffffff",
            "border": "rgba(0, 0, 0, 0.10)",
            "color": "#1a1a1a",
            "button_hover": "rgba(0, 0, 0, 0.06)",
            "button_pressed": "rgba(0, 0, 0, 0.12)",
            "theme": "light",
        }
    palette.update({
        "accent": accent,
        "min_height": MIN_HEIGHT_PX,
        "padding_right": BUTTON_AREA_PX - 10,
    })
    return _QSS.format(**palette)


def _width_for_text(text: str) -> int:
    """Ancho necesario para mostrar `text` completo junto a las flechas."""
    return max(MIN_WIDTH_PX, 20 + BUTTON_AREA_PX + (len(text) + 2) * CHAR_WIDTH_PX)


class _FluentSpinMixin:
    """Tamaño, tema y ancho automáticos para los spinboxes de la app."""

    minimum_width: int = DEFAULT_WIDTH_PX

    def _apply_comfort(self) -> None:
        self.setMinimumWidth(max(int(self.minimum_width), MIN_WIDTH_PX))
        self.setMinimumHeight(MIN_HEIGHT_PX)
        self.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # Flechas nativas de Qt (SIEMPRE responden) + repetición al mantener
        self.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.setAccelerated(True)
        self._apply_theme_qss()
        try:
            # Reaplicar colores al cambiar claro/oscuro sin reiniciar
            qconfig.themeChanged.connect(self._apply_theme_qss)
        except Exception:
            pass

    def _apply_theme_qss(self) -> None:
        self.setStyleSheet(_theme_qss())

    def _fit_width(self) -> None:
        try:
            text = (self.prefix() + self.textFromValue(self.maximum())
                    + self.suffix())
        except Exception:
            text = ""
        self.setMinimumWidth(
            max(int(self.minimum_width), MIN_WIDTH_PX, _width_for_text(text)))

    # ------------------------------------------------------------------
    # Recalcular el ancho cuando cambia lo que puede llegar a mostrarse
    # ------------------------------------------------------------------

    def setRange(self, minimum, maximum):  # noqa: N802 (API de Qt)
        super().setRange(minimum, maximum)
        self._fit_width()

    def setMaximum(self, maximum):  # noqa: N802 (API de Qt)
        super().setMaximum(maximum)
        self._fit_width()

    def setDecimals(self, decimals):  # noqa: N802 (API de Qt)
        super().setDecimals(decimals)
        self._fit_width()

    def setPrefix(self, prefix):  # noqa: N802 (API de Qt)
        super().setPrefix(prefix)
        self._fit_width()

    def setSuffix(self, suffix):  # noqa: N802 (API de Qt)
        super().setSuffix(suffix)
        self._fit_width()


class AppSpinBox(_FluentSpinMixin, QSpinBox):
    """Spinbox entero Fluent: flechas nativas fiables y texto nunca recortado."""

    def __init__(self, parent=None, minimum_width: int = DEFAULT_WIDTH_PX):
        self.minimum_width = int(minimum_width)
        super().__init__(parent)
        self._apply_comfort()
        self._fit_width()


class AppDoubleSpinBox(_FluentSpinMixin, QDoubleSpinBox):
    """Spinbox decimal Fluent: flechas nativas fiables y texto nunca recortado."""

    def __init__(self, parent=None, minimum_width: int = DEFAULT_WIDTH_PX):
        self.minimum_width = int(minimum_width)
        super().__init__(parent)
        self._apply_comfort()
        self._fit_width()


def make_int_spin(minimum: int = 0, maximum: int = 999999, value: int = 0,
                  suffix: str = "", minimum_width: Optional[int] = None
                  ) -> AppSpinBox:
    """Fábrica de spinbox entero con rango/valor ya configurados."""
    spin = AppSpinBox(minimum_width=minimum_width or DEFAULT_WIDTH_PX)
    spin.setRange(minimum, maximum)
    if suffix:
        spin.setSuffix(suffix)
    spin.setValue(int(value))
    return spin


def make_double_spin(minimum: float = 0.0, maximum: float = 999999.0,
                     value: float = 0.0, decimals: int = 2,
                     suffix: str = "", minimum_width: Optional[int] = None
                     ) -> AppDoubleSpinBox:
    """Fábrica de spinbox decimal con rango/valor ya configurados."""
    spin = AppDoubleSpinBox(minimum_width=minimum_width or DEFAULT_WIDTH_PX)
    spin.setDecimals(decimals)
    spin.setRange(minimum, maximum)
    if suffix:
        spin.setSuffix(suffix)
    spin.setValue(float(value))
    return spin
