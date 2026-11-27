"""Exportación de datos a CSV, Excel y PDF.

Utilidades compartidas por el kardex del inventario y las listas de compras.
- CSV con BOM UTF-8 (abre bien en Excel con acentos).
- Excel con openpyxl (encabezado en negrita y anchos razonables).
- PDF vía QTextDocument + QPrinter (sin dependencias extra).
"""
from __future__ import annotations

import csv
from typing import Sequence

from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtPrintSupport import QPrinter


def rows_to_csv(path: str, headers: Sequence[str], rows: Sequence[Sequence]) -> None:
    """Guarda filas en CSV (utf-8-sig para compatibilidad con Excel)."""
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(headers))
        for row in rows:
            writer.writerow(list(row))


def rows_to_excel(path: str, sheet_name: str, headers: Sequence[str],
                  rows: Sequence[Sequence]) -> None:
    """Guarda filas en una hoja de Excel con encabezado en negrita."""
    import openpyxl
    from openpyxl.styles import Font

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = sheet_name[:31]
    sheet.append(list(headers))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(list(row))

    # Ancho básico por columna según el contenido
    from openpyxl.utils import get_column_letter

    for column in range(1, len(headers) + 1):
        values = [str(headers[column - 1])] + [
            str(row[column - 1]) if column <= len(row) else "" for row in rows
        ]
        width = min(max(len(v) for v in values) + 2, 42)
        sheet.column_dimensions[get_column_letter(column)].width = width
    workbook.save(path)


def rows_to_pdf(path: str, title: str, headers: Sequence[str],
                rows: Sequence[Sequence]) -> None:
    """Guarda filas en un PDF sencillo (tabla) con QPrinter en modo PDF."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)

    def esc(value) -> str:
        text = "" if value is None else str(value)
        return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    head = "".join(f"<th align='left'>{esc(h)}</th>" for h in headers)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    html = (
        f"<h2>{esc(title)}</h2>"
        f"<table border='0.5' cellspacing='0' cellpadding='3' width='100%'>"
        f"<tr>{head}</tr>{body_rows}</table>"
    )
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Segoe UI", 8))
    doc.setHtml(html)
    doc.print_(printer)
