"""Cuadros numéricos (spinboxes) consistentes en TODO el programa.

Los `SpinBox`/`DoubleSpinBox` de qfluentwidgets dibujan los botones de
flecha ↑/↓ DENTRO del cuadro, flotando sobre el lado derecho. Sin un ancho
mínimo y sin reservarles espacio (padding), los números quedan debajo de
las flechas o recortados — sobre todo con valores de varios dígitos y
decimales (p. ej. 1,250.50) o al escribir a mano.

`AppSpinBox` y `AppDoubleSpinBox` corrigen la causa de raíz y se usan en
todo el proyecto para que se vean y comporten igual:

- Ancho mínimo cómodo: nunca menor a 110 px (130 por defecto) y se AMPLÍA
  automáticamente según la cantidad de dígitos que puede tener el valor
  (rango, decimales, prefijo y sufijo), por lo que funciona al maximizar.
- Altura 33 px (estándar Fluent, dentro del rango 33–36 px).
- Alineación vertical centrada y padding derecho que respeta el área de
  las flechas para que el texto nunca quede debajo de los botones.
- Repetición acelerada al mantener presionadas las flechas.

Se ve bien en claro y oscuro: el padding no cambia colores y el resto del
estilo Fluent se hereda sin alteraciones.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from qfluentwidgets import DoubleSpinBox, SpinBox

# Espacio que ocupan los botones ↑/↓ flotando a la derecha (+ márgenes)
BUTTON_AREA_PX = 56

# Ancho mínimo absoluto pedido
MIN_WIDTH_PX = 110

# Ancho mínimo por defecto (cómodo para montos comunes)
DEFAULT_WIDTH_PX = 130

# Altura estándar Fluent de un control de entrada
MIN_HEIGHT_PX = 33

# Aproximación del ancho de un carácter numérico en la fuente Fluent
CHAR_WIDTH_PX = 9


def _width_for_text(text: str) -> int:
    """Ancho necesario para mostrar `text` completo junto a las flechas."""
    return max(MIN_WIDTH_PX, 18 + BUTTON_AREA_PX + (len(text) + 2) * CHAR_WIDTH_PX)


class _AppSpinMixin:
    """Tamaño, alineación y padding consistentes para los spinboxes."""

    minimum_width: int = DEFAULT_WIDTH_PX

    def _apply_comfort(self) -> None:
        self.setMinimumWidth(max(int(self.minimum_width), MIN_WIDTH_PX))
        self.setMinimumHeight(MIN_HEIGHT_PX)
        self.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # Reservar el área de las flechas: el número nunca queda debajo
        line_edit = self.lineEdit()
        previous = line_edit.styleSheet().strip()
        rule = f"QLineEdit {{ padding-right: {BUTTON_AREA_PX}px; }}"
        line_edit.setStyleSheet(f"{previous}\n{rule}" if previous else rule)
        # Repetir el paso al mantener presionadas las flechas
        self.setAccelerated(True)

    # ------------------------------------------------------------------
    # El ancho se recalcula cuando cambia lo que puede llegar a mostrarse
    # ------------------------------------------------------------------

    def _fit_width(self) -> None:
        text = (self.prefix() + self.textFromValue(self.maximum())
                + self.suffix())
        self.setMinimumWidth(max(int(self.minimum_width), _width_for_text(text)))

    # QAbstractSpinBox API (los nombres de Qt se conservan)
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


class AppSpinBox(_AppSpinMixin, SpinBox):
    """SpinBox entero (flechas ↑/↓) con tamaño y padding correctos."""

    def __init__(self, parent=None, minimum_width: int = DEFAULT_WIDTH_PX):
        self.minimum_width = int(minimum_width)
        super().__init__(parent)
        self._apply_comfort()
        self._fit_width()


class AppDoubleSpinBox(_AppSpinMixin, DoubleSpinBox):
    """DoubleSpinBox decimal (flechas ↑/↓) con tamaño y padding correctos."""

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
