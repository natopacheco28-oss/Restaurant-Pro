"""Gestor de impresión térmica de tickets — estilo ABCell Pro.

Impresión DIRECTA, sin abrir ventanas de Windows:
1. Se elige la impresora: la configurada en Ajustes; si falta o no existe,
   la predeterminada de Windows; si tampoco hay, la primera disponible.
2. Se DETECTA el formato de papel (58 mm u 80 mm) por el nombre/driver de
   la impresora y por el ancho de papel de Windows (PaperWidth), igual que
   ABCell Pro. Con el formato se sabe el ancho real en caracteres
   (32 para 58 mm, 44 para 80 mm).
3. Si el ticket venía formateado para otro ancho (p. ej. 48 caracteres en
   un rollo de 58 mm), se REALINEA línea por línea: separadores al ancho
   exacto, renglones etiqueta↔importe rejustados y párrafos envueltos —
   esto elimina la impresión "en escalera".
4. Se envía RAW/ESC-POS con win32print (pywin32): init ESC @, logo
   rasterizado GS v 0, texto CP437 (acentos y ñ) y corte GS V. Sin QPrintDialog:
   la alternativa gráfica (QPrinter) también imprime en silencio.

Cualquier fallo regresa como (False, mensaje claro) y queda en el log,
sin detener el programa.
"""
from __future__ import annotations

import logging
import re
import textwrap
from typing import Any, Optional

from PySide6.QtGui import QFont, QTextDocument
# QPrinter, QPrintDialog, QPrintPreviewDialog y QPrinterInfo pertenecen a
# QtPrintSupport (NO a QtWidgets — en Qt 6 un import equivocado reventa
# "cannot import name 'QPrintDialog' from 'PySide6.QtWidgets'").
# Se reexportan aquí por compatibilidad (tests) — nunca se abren diálogos.
from PySide6.QtPrintSupport import (  # noqa: F401
    QPrintDialog,
    QPrinter,
    QPrinterInfo,
)

log = logging.getLogger("restaurante.printing")

# Reexportados por compatibilidad (tests y consumidores avanzados)
__all__ = [
    "QPrinter",
    "QPrintDialog",
    "QPrinterInfo",
    "PrinterManager",
    "classify_paper_format",
    "default_printer_name",
    "detect_paper_format",
    "list_printers",
    "print_raw_windows",
    "print_text_qt",
    "realign_ticket_text",
    "resolve_printer",
    "ticket_source_width",
]

# win32print solo existe en Windows (pywin32); fuera de él se usa QPrinter
try:
    import win32print  # type: ignore

    HAS_WIN32PRINT = True
except ImportError:
    win32print = None  # type: ignore[assignment]
    HAS_WIN32PRINT = False

# ----------------------------------------------------------------------
# Detección de formato de papel (portada de ABCell Pro)
# ----------------------------------------------------------------------

_RE_80MM = re.compile(
    r"(^|[^0-9])(80\s*mm|pos[-\s_]*80|xp[-\s_]*80|rp[-\s_]*80|tp[-\s_]*80|"
    r"ec[-\s_]*pm[-\s_]*80|atp[-\s_]*80|tm[-\s_]*t88|tm[-\s_]*t82|"
    r"tm[-\s_]*m30|srp[-\s_]*3[35]0|tsp\s*1[04]|ct[-\s_]*s310|72\s*mm|80c\b)",
    re.IGNORECASE,
)
_RE_58MM = re.compile(
    r"(^|[^0-9])(58\s*mm|pos[-\s_]*58|xp[-\s_]*58|rp[-\s_]*58|tp[-\s_]*58|"
    r"ec[-\s_]*pm[-\s_]*58|pt[-\s_]*210|tm[-\s_]*t20|mtp[-\s_]*(ii|2|3)|"
    r"goojprt|48\s*mm|58c\b)",
    re.IGNORECASE,
)

# Ancho imprimible en caracteres por formato (58 mm → 32, 80 mm → 44)
FORMAT_WIDTH_CHARS = {"58mm": 32, "80mm": 44}
# Puntos del ancho del logo rasterizado por formato
FORMAT_DOTS = {"58mm": 384, "80mm": 512}


def classify_paper_format(printer_name: str = "", driver_name: str = "",
                          form_name: str = "", paper_width_tenths: int = 0) -> str:
    """Determina si una impresora térmica es de formato 80 mm o 58 mm.

    `paper_width_tenths` es el PaperWidth del DEVMODE de Windows, en décimas
    de milímetro (p. ej. 800 = 80.0 mm). Devuelve "80mm", "58mm" o "".
    """
    text = f"{printer_name} {driver_name} {form_name}".strip()
    if _RE_80MM.search(text):
        return "80mm"
    if _RE_58MM.search(text):
        return "58mm"
    if 650 <= int(paper_width_tenths or 0) <= 950:
        return "80mm"
    if 380 <= int(paper_width_tenths or 0) < 650:
        return "58mm"
    return ""


def _detect_format_in_handle(handle) -> str:
    """Formato de la impresora abierta (driver + FormName + PaperWidth)."""
    driver_name, form_name, paper_width = "", "", 0
    try:
        info2 = win32print.GetPrinter(handle, 2)
        if isinstance(info2, dict):
            driver_name = str(info2.get("pDriverName") or "")
            devmode = info2.get("pDevMode")
            if devmode is not None:
                form_name = str(getattr(devmode, "FormName", "") or "")
                paper_width = int(getattr(devmode, "PaperWidth", 0) or 0)
    except Exception:
        pass
    return classify_paper_format(driver_name=driver_name, form_name=form_name,
                                 paper_width_tenths=paper_width)


def detect_paper_format(printer_name: str) -> str:
    """Formato de papel de una impresora instalada ("", "58mm" u "80mm")."""
    if not printer_name:
        return ""
    if not HAS_WIN32PRINT:
        # Fuera de Windows se infiere por el nombre
        return classify_paper_format(printer_name=printer_name)
    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        return _detect_format_in_handle(handle)
    except Exception:
        return classify_paper_format(printer_name=printer_name)
    finally:
        if handle:
            try:
                win32print.ClosePrinter(handle)
            except Exception:
                pass


def list_printers() -> list[str]:
    """Impresoras instaladas en el sistema (nombres)."""
    if HAS_WIN32PRINT:
        try:
            flags = (win32print.PRINTER_ENUM_LOCAL
                     | win32print.PRINTER_ENUM_CONNECTIONS)
            return [p[2] for p in win32print.EnumPrinters(flags, None, 4)]
        except Exception:
            pass
    return list(QPrinterInfo.availablePrinterNames())


def default_printer_name() -> str:
    """Impresora predeterminada de Windows ("", si no hay)."""
    if HAS_WIN32PRINT:
        try:
            return str(win32print.GetDefaultPrinter() or "").strip()
        except Exception:
            return ""
    try:
        return str(QPrinterInfo.defaultPrinterName() or "").strip()
    except Exception:
        return ""


def resolve_printer(configured: str) -> tuple[str, str]:
    """Elige la impresora SIN abrir ventanas.

    Orden: la configurada (si existe) → la predeterminada de Windows →
    la primera instalada. Devuelve (nombre, formato_detectado).
    """
    installed = list_printers()
    name = ""
    configured = str(configured or "").strip()
    if configured and configured in installed:
        name = configured
    if not name:
        candidate = default_printer_name()
        if candidate and candidate in installed:
            name = candidate
            log.info("Usando la impresora predeterminada de Windows: %s", name)
    if not name and installed:
        name = installed[0]
        log.info("Usando la primera impresora disponible: %s", name)
    return name, detect_paper_format(name)


# ----------------------------------------------------------------------
# Realineación del ticket al ancho real del papel (anti-escalera)
# ----------------------------------------------------------------------

_SEP_RE = re.compile(r"^[=\-]{3,}$")
_LR_RE = re.compile(r"^(.*?\S)(\s{2,})(\S.*)$")
# Importe al final de la línea (tras un solo espacio también): $1,000.00, 15%, …
_LR_MONEY_RE = re.compile(r"^(.*?\S)\s+([$€£]?[\d][\d.,]*%?)$")
_AMOUNT_RE = re.compile(r"^[$€£]?[\d][\d.,]*%?$")


def realign_ticket_text(text: str, width: int) -> str:
    """Reajusta un ticket formateado por caracteres a otro ancho de papel.

    Un ticket de 48 columnas impreso en un rollo de 32 sale "en escalera"
    (los separadores cortados y cada renglón envuelto a destiempo). Esta
    función reconstruye cada línea al ancho real:

    - Separadores (`-----`, `=====`) → línea exacta del nuevo ancho.
    - Renglones etiqueta↔importe (hueco interior de 2+ espacios) →
      rejustados para que el importe termine en la misma columna; si no
      caben, el importe pasa a su propio renglón alineado a la derecha.
    - Líneas centradas que solo exceden por sus espacios de centrado →
      recentradas al nuevo ancho.
    - Párrafos (notas, direcciones) → envueltos con sangría de 2 espacios.
    - Las líneas que ya caben se respetan tal cual (conservando el centrado).
    """
    out: list[str] = []
    for line in text.splitlines():
        raw = line.rstrip()
        stripped = raw.strip()
        if not stripped:
            out.append("")
            continue
        leading = len(raw) - len(raw.lstrip())
        if _SEP_RE.match(stripped):
            out.append(stripped[0] * width)
            continue
        if len(stripped) <= width:
            if len(raw) <= width:
                out.append(raw)          # cabe tal cual
            elif leading >= 4:
                out.append(stripped.center(width).rstrip())
            else:
                # Cabe sin la sangría original: conservar sangría y envolver
                wrapped = textwrap.wrap(stripped, width - leading) or [""]
                out.append((" " * leading) + wrapped[0])
                out.extend("  " + part for part in wrapped[1:])
            continue
        match = _LR_RE.match(stripped)
        if match:
            left = match.group(1).rstrip()
            right = match.group(3)
            gap = width - len(left) - len(right)
            if gap >= 1:
                out.append(f"{left}{' ' * gap}{right}")
                continue
            if _AMOUNT_RE.match(right) and len(right) <= width:
                # Partida larga: nombre primero, importe a la derecha abajo
                if len(left) <= width:
                    out.append(left)
                else:
                    for part in textwrap.wrap(left, width - 2):
                        out.append(f"  {part}")
                out.append(right.rjust(width))
                continue
        else:
            money = _LR_MONEY_RE.match(stripped)
            if (money and _AMOUNT_RE.match(money.group(2))
                    and len(money.group(2)) <= width):
                # Partida con un solo espacio antes del importe que no cabe:
                # nombre completo arriba, importe alineado a la derecha abajo
                left = money.group(1).rstrip()
                right = money.group(2)
                if len(left) <= width:
                    out.append(left)
                else:
                    for part in textwrap.wrap(left, width - 2):
                        out.append(f"  {part}")
                out.append(right.rjust(width))
                continue
        # Párrafo largo: envolver con sangría en la continuación
        wrapped = textwrap.wrap(stripped, width - 2) or [""]
        out.append(wrapped[0])
        out.extend(f"  {part}" for part in wrapped[1:])
    return "\n".join(out)


def ticket_source_width(text: str) -> int:
    """Ancho en caracteres para el que fue formateado el ticket."""
    return max((len(line.rstrip()) for line in text.splitlines()), default=0)


# ----------------------------------------------------------------------
# Envío RAW (win32print) y ruta gráfica de Qt — ambas SIN ventanas
# ----------------------------------------------------------------------

def print_raw_windows(printer_name: str, data: bytes) -> None:
    """Envía bytes RAW (ESC/POS) a la impresora de Windows.

    Lanza RuntimeError con un mensaje claro si algo falla.
    """
    if not HAS_WIN32PRINT:
        raise RuntimeError("win32print no está disponible fuera de Windows.")

    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        win32print.StartDocPrinter(handle, 1, ("Restaurante Pro - Ticket", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo imprimir en «{printer_name}» por el método RAW.\n"
            f"Detalle: {exc}"
        ) from exc
    finally:
        if handle:
            try:
                win32print.ClosePrinter(handle)
            except Exception:
                pass


def print_text_qt(text: str, printer_name: Optional[str] = None) -> None:
    """Imprime el texto del ticket con QPrinter — DIRECTO, sin diálogos.

    Ruta alternativa (Linux/macOS o impresoras sin soporte RAW): usa fuente
    monoespaciada y envía a la impresora indicada o a la predeterminada.
    """
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    name = printer_name or default_printer_name()
    if name:
        printer.setPrinterName(name)

    doc = QTextDocument()
    doc.setDefaultFont(QFont("Consolas", 8))
    doc.setPlainText(text)
    doc.print_(printer)


# ----------------------------------------------------------------------
# Orquestador
# ----------------------------------------------------------------------

class PrinterManager:
    """Orquesta la impresión según la configuración del ticket."""

    def __init__(self, settings: Any):
        self.settings = settings

    # ------------------------------------------------------------------

    def current_printer(self) -> str:
        return str(self.settings.get("ticket.printer_name", "") or "")

    def print_sale_ticket(
        self,
        ticket_text: str,
        logo_path: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Imprime el ticket DIRECTO, sin abrir ventanas de Windows.

        Devuelve (éxito, mensaje). Elige la impresora automáticamente
        (configurada → predeterminada → primera disponible), detecta el
        papel (58/80 mm), realinea el texto al ancho real del papel y
        envía RAW/ESC-POS con logo y corte. Nunca lanza: los fallos
        regresan como mensaje claro y quedan en el log.
        """
        try:
            return self._print(ticket_text, logo_path)
        except Exception as exc:
            log.error("Impresión falló: %s", exc, exc_info=True)
            return False, (
                "No se pudo imprimir el ticket.\n"
                f"Detalle: {exc}\n\n"
                "Verifica que la impresora esté encendida, con papel y sin "
                "errores en Windows (panel de impresoras).")

    def _print(self, ticket_text: str, logo_path: Optional[str]) -> tuple[bool, str]:
        printer_name, paper_format = resolve_printer(self.current_printer())

        if not printer_name:
            message = ("No hay ninguna impresora instalada en Windows.\n"
                       "Conecta la impresora térmica e instálala en el "
                       "panel de impresoras de Windows.")
            log.error(message)
            return False, message

        if self.current_printer() and self.current_printer() != printer_name:
            log.info("La impresora configurada «%s» no está disponible; "
                     "se usa «%s».", self.current_printer(), printer_name)

        # Ancho real del papel: detectado; si no, el configurado
        try:
            configured_width = int(
                self.settings.get("ticket.width_chars", 48) or 48)
        except (TypeError, ValueError):
            configured_width = 48
        target_chars = (FORMAT_WIDTH_CHARS.get(paper_format)
                        if paper_format else configured_width)
        source_width = ticket_source_width(ticket_text)
        if target_chars and source_width > target_chars:
            ticket_text = realign_ticket_text(ticket_text, target_chars)
            log.info("Ticket realineado de %s a %s columnas (formato %s).",
                     source_width, target_chars, paper_format or "configurado")

        width_chars = target_chars or configured_width

        if HAS_WIN32PRINT:
            data = self._build_escpos(ticket_text, logo_path, width_chars)
            try:
                print_raw_windows(printer_name, data)
                return True, (f"Ticket enviado a «{printer_name}»"
                              + (f" (formato {paper_format})." if paper_format else "."))
            except RuntimeError as exc:
                log.error("Impresión RAW falló en «%s»: %s", printer_name, exc)
                # Fallback silencioso a la ruta gráfica de Qt
                try:
                    print_text_qt(ticket_text, printer_name=printer_name)
                    return True, f"Impreso por QPrinter en «{printer_name}»."
                except Exception as qt_exc:
                    log.error("Fallback QPrinter también falló: %s", qt_exc)
                    return False, (
                        f"No se pudo imprimir en «{printer_name}».\n"
                        f"RAW/ESC-POS: {exc}\nQPrinter: {qt_exc}\n\n"
                        "Revisa que la impresora esté encendida, con papel "
                        "y sin errores en Windows.")

        # Ruta Qt (Linux, macOS o impresoras sin soporte RAW) — sin ventanas
        try:
            print_text_qt(ticket_text, printer_name=printer_name)
            return True, f"Ticket enviado a «{printer_name}» por QPrinter."
        except Exception as exc:
            log.error("Impresión por QPrinter falló: %s", exc)
            return False, (
                f"No se pudo imprimir el ticket.\nDetalle: {exc}\n\n"
                "Verifica que haya una impresora instalada y disponible.")

    def _build_escpos(self, ticket_text: str, logo_path: Optional[str],
                      width_chars: int) -> bytes:
        from app.printing.escpos import build_escpos

        return build_escpos(
            ticket_text,
            logo_path=logo_path,
            width_chars=width_chars,
            show_logo=bool(self.settings.get("ticket.show_logo", True)),
            auto_cut=bool(self.settings.get("ticket.auto_cut", True)),
            open_drawer=bool(self.settings.get("ticket.open_drawer", False)),
        )
