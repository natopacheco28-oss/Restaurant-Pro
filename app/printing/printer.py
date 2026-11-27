"""Gestor de impresión de tickets para Windows.

Dos rutas de impresión:
1. RAW + ESC/POS vía `win32print` — recomendada para térmicas 58/80 mm:
   envía bytes directos sin driver gráfico, con logo, corte y cajón.
2. QPrinter (QtPrintSupport) — alternativa universal que imprime el texto
   del ticket con fuente monoespaciada en cualquier impresora instalada.

El método se elige en Ajustes: `auto` (RAW si es posible, si no Qt),
`raw` (solo ESC/POS) o `qprinter`.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

# win32print solo existe en Windows (pywin32); fuera de él se usa QPrinter
try:
    import win32print  # type: ignore

    HAS_WIN32PRINT = True
except ImportError:
    win32print = None  # type: ignore[assignment]
    HAS_WIN32PRINT = False


def list_printers() -> list[str]:
    """Impresoras instaladas en el sistema (nombres)."""
    if HAS_WIN32PRINT:
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            return [p[2] for p in win32print.EnumPrinters(flags, None, 4)]
        except Exception:
            pass
    return list(QPrinterInfo.availablePrinterNames())


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


def print_text_qt(text: str, printer_name: Optional[str] = None,
                  ask_printer: bool = False) -> None:
    """Imprime el texto del ticket con QPrinter (ruta alternativa)."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    if printer_name:
        printer.setPrinterName(printer_name)
    if ask_printer:
        from PySide6.QtWidgets import QPrintDialog

        dialog = QPrintDialog(printer)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return

    doc = QTextDocument()
    doc.setDefaultFont(QFont("Consolas", 8))
    doc.setPlainText(text)
    doc.print_(printer)


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
        """Imprime el ticket de una venta.

        Devuelve (éxito, mensaje). En modo `raw` adjunta logo/corte/cajón vía
        ESC/POS; en `qprinter` imprime el texto monoespaciado. Si falla la
        ruta RAW, reintenta automáticamente por QPrinter.
        """
        method = str(self.settings.get("ticket.print_method", "auto"))
        printer_name = self.current_printer()

        if method in ("auto", "raw") and HAS_WIN32PRINT and printer_name:
            data = self._build_escpos(ticket_text, logo_path)
            try:
                print_raw_windows(printer_name, data)
                return True, "Ticket enviado por RAW/ESC-POS."
            except RuntimeError as exc:
                # Fallback automático a la ruta gráfica de Qt
                try:
                    print_text_qt(ticket_text, printer_name=printer_name)
                    return True, f"Impreso por QPrinter (RAW falló: {exc})"
                except Exception:
                    return False, str(exc)

        # Ruta Qt (Linux, macOS o impresoras sin soporte RAW)
        try:
            print_text_qt(
                ticket_text,
                printer_name=printer_name or None,
                ask_printer=not printer_name,
            )
            return True, "Ticket enviado por QPrinter."
        except Exception as exc:
            return False, f"Error al imprimir: {exc}"

    def _build_escpos(self, ticket_text: str, logo_path: Optional[str]) -> bytes:
        from app.printing.escpos import build_escpos

        width = int(self.settings.get("ticket.width_chars", 48))
        return build_escpos(
            ticket_text,
            logo_path=logo_path,
            width_chars=width,
            show_logo=bool(self.settings.get("ticket.show_logo", True)),
            auto_cut=bool(self.settings.get("ticket.auto_cut", True)),
            open_drawer=bool(self.settings.get("ticket.open_drawer", False)),
        )
