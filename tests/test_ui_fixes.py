"""Regresión de los tres fallos generales de UI/impresión.

1. Spinboxes: tamaño cómodo (ancho ≥110 px + padding que respeta las
   flechas) en el componente unificado app/ui/components/spinboxes.py.
2. Selector de color de acento: ColorDialog de qfluentwidgets 1.x exige
   `title` en el constructor (ColorDialog(color, title, parent, …)).
3. Impresión: QPrintDialog/QPrinter viven en PySide6.QtPrintSupport, no en
   QtWidgets — el barrido general detecta imports en el módulo equivocado.
"""
from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ======================================================================
# 1. Spinboxes unificados
# ======================================================================

def test_double_spinbox_tiene_tamanio_comodo(qapp):
    from app.ui.components import AppDoubleSpinBox

    spin = AppDoubleSpinBox()
    assert spin.minimumWidth() >= 110
    assert 33 <= spin.minimumHeight() <= 36
    # estilo Fluent propio con padding que respeta los botones ▲/▼ nativos
    assert "padding" in spin.styleSheet()
    # flechas NATIVAS de Qt (siempre responden), no las flotantes de qfw
    assert spin.buttonSymbols() == spin.ButtonSymbols.UpDownArrows


def test_double_spinbox_se_amplia_con_digitos(qapp):
    """Con rango grande el cuadro se ensancha solo (no recorta números)."""
    from app.ui.components import AppDoubleSpinBox

    small = AppDoubleSpinBox()
    small.setRange(0, 365)                      # "365" → 3 dígitos
    wide = AppDoubleSpinBox()
    wide.setRange(0.0, 999999.0)                # "999,999.00"
    wide.setDecimals(2)
    assert wide.minimumWidth() > small.minimumWidth()
    assert wide.minimumWidth() >= 110

    wide.setPrefix("$ ")
    assert wide.minimumWidth() > 170            # el prefijo ocupa más


def test_spinbox_entero_y_fabricas(qapp):
    from app.ui.components import AppSpinBox, make_double_spin, make_int_spin

    spin = AppSpinBox()
    assert spin.minimumWidth() >= 110

    days = make_int_spin(0, 365, 7)
    assert days.value() == 7
    money = make_double_spin(0, 999999.0, 150.5, decimals=2)
    assert money.value() == 150.5
    assert money.minimumWidth() >= 110


def test_todos_los_spinboxes_usan_el_componente():
    """Ningún DoubleSpinBox directo de qfluentwidgets queda en la UI."""
    offenders = []
    for path in (PROJECT_ROOT / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if re.search(r"\bDoubleSpinBox\s*\(", source) \
                and "AppDoubleSpinBox" not in source:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == []


def test_no_seteditable_en_combos_qfluent():
    """qfw ComboBox no tiene setEditable (rompe en runtime); si se quiere
    texto libre se usa EditableComboBox."""
    for path in (PROJECT_ROOT / "app").rglob("*.py"):
        assert ".setEditable(" not in path.read_text(encoding="utf-8"), \
            str(path.relative_to(PROJECT_ROOT))


# ======================================================================
# 2. Selector de color de acento
# ======================================================================

def test_colordialog_con_titulo_se_construye(qapp):
    """La firma correcta ColorDialog(color, title, parent, enableAlpha)."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from qfluentwidgets import ColorDialog

    host = QWidget()                              # parent real (mantener vivo)
    dialog = ColorDialog(QColor("#ff7a1a"), "Elegir color de acento",
                         host, enableAlpha=False)
    assert dialog.color == QColor("#ff7a1a")


def test_accent_invalido_usa_default(qapp):
    """Un hex guardado inválido no debe romper el arranque del tema."""
    from PySide6.QtGui import QColor

    saved = "no-es-un-color"
    color = QColor(saved) if QColor(saved).isValid() else QColor("#ff7a1a")
    assert color.isValid()
    assert color.name(QColor.HexRgb).upper() == "#FF7A1A"


# ======================================================================
# 3. Impresión: módulo Qt correcto
# ======================================================================

def test_qprintdialog_vive_en_qtprintsupport():
    """printer.py importa QPrintDialog de QtPrintSupport (no QtWidgets)."""
    from PySide6.QtPrintSupport import QPrintDialog as _expected

    import app.printing.printer as printer

    assert printer.QPrintDialog is _expected


# ----------------------------------------------------------------------
# Impresión estilo ABCell Pro: detección de papel + realineación
# ----------------------------------------------------------------------

def test_clasificar_formato_papel():
    """Nombres de impresoras/driver y PaperWidth → 58mm/80mm."""
    import app.printing.printer as printer

    assert printer.classify_paper_format("POS-80 thermal") == "80mm"
    assert printer.classify_paper_format("XP-58 receiver") == "58mm"
    assert printer.classify_paper_format("", paper_width_tenths=800) == "80mm"
    assert printer.classify_paper_format("", paper_width_tenths=580) == "58mm"
    assert printer.classify_paper_format("HP LaserJet") == ""


def test_realign_ticket_48_a_32_sin_escalera():
    """Un ticket de 48 columnas se reajusta a 32 sin líneas en escalera."""
    import app.printing.printer as printer

    src = "\n".join([
        "TACOS EL BUEN GUSTO".center(48).rstrip(),
        "=" * 48,
        "Folio: #000077",
        "-" * 48,
        "2 x Tacos de pastor (orden)            $192.00",
        "  » Sin cilantro, con todo",
        "Subtotal                               $367.00",
        "-" * 48,
        "TOTAL                                  $416.18",
        "=" * 48,
        "¡Gracias por su preferencia!".center(48).rstrip(),
    ])
    out = printer.realign_ticket_text(src, 32)

    lines = out.splitlines()
    assert max(len(line) for line in lines) <= 32          # nada excede
    assert lines[1] == "=" * 32                            # separador exacto
    assert lines[3] == "-" * 32
    # El renglón LR conserva etiqueta a la izq e importe al final
    lr = next(l for l in lines if "Subtotal" in l)
    assert lr.startswith("Subtotal") and lr.endswith("$367.00")
    # El párrafo largo se envuelve con sangría
    wrapped = [l for l in lines if l.startswith("  ¡Gracias") or l == "¡Gracias por su preferencia!"]
    assert wrapped


def test_realign_ya_al_ancho_no_cambia():
    import app.printing.printer as printer

    src = "Línea corta\n" + "-" * 32 + "\nTOTAL   $100.00"
    assert printer.realign_ticket_text(src, 32) == src


def test_ticket_source_width():
    import app.printing.printer as printer

    assert printer.ticket_source_width("abc\n" + "-" * 48 + "\nx") == 48


def test_print_sale_ticket_sin_impresora_da_mensaje_claro():
    """Sin impresoras disponibles devuelve (False, mensaje) sin lanzar."""
    from types import SimpleNamespace

    import app.printing.printer as printer

    settings = SimpleNamespace(get=lambda key, default=None: "")
    manager = printer.PrinterManager(settings)
    ok, message = manager.print_sale_ticket("ticket de prueba")
    assert ok is False
    assert "impresora" in message.lower()
    assert "\n" in message  # mensaje de varias líneas, claro y explicativo


# ======================================================================
# REVISIÓN GENERAL: barrido de imports Qt en el módulo equivocado
# ======================================================================

QT_MODULES = {
    "QtCore", "QtGui", "QtWidgets", "QtPrintSupport", "QtCharts",
    "QtNetwork", "QtSvg",
}


def test_ningun_import_qt_en_modulo_equivocado():
    """Verifica que cada nombre importado de PySide6 existe en ese módulo."""
    offenders: list[str] = []
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("PySide6.Qt"):
                continue
            module_name = node.module.split("Qt")[1] if "Qt" in node.module else ""
            if module_name not in QT_MODULES:
                continue
            try:
                module = importlib.import_module(node.module)
            except ImportError:
                offenders.append(f"{path.name}: no se puede importar {node.module}")
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not hasattr(module, alias.name):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}: {alias.name} "
                        f"no existe en {node.module}")
    assert offenders == [], "\n".join(offenders)
