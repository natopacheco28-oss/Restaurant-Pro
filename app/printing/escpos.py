"""Comandos ESC/POS para impresoras térmicas (58 mm y 80 mm).

Genera el flujo de bytes RAW que se envía a la impresora con win32print en
Windows: inicialización, logo rasterizado en blanco y negro, texto, apertura
de cajón monetario y corte de papel.

Referencia rápida de comandos:
    ESC @   → inicializa la impresora
    ESC E n → negrita
    GS v 0  → imprime imagen rasterizada en blanco y negro
    ESC p   → pulso del cajón monetario
    GS V    → corte de papel (66 = parcial, 0 = completo)
"""
from __future__ import annotations

from typing import Optional

# Ancho imprimible en puntos por tamaño de papel:
# 32 caracteres → 58 mm · 44 → 80 mm (detectado) · 48 → 80 mm configurado
PRINTER_DOTS = {32: 384, 44: 512, 48: 576}

ESC = b"\x1b"
GS = b"\x1d"

# Tabla CP437: soporta vocales acentuadas y ñ de manera nativa en estas impresoras
TEXT_ENCODING = "cp437"


class EscposBuilder:
    """Acumula comandos ESC/POS en un buffer de bytes."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    # --- Control ------------------------------------------------------

    def reset(self) -> "EscposBuilder":
        """ESC @ — inicializa la impresora (márgenes y estilo por defecto)."""
        self._buffer += ESC + b"@"
        return self

    def align_center(self) -> "EscposBuilder":
        self._buffer += ESC + b"a\x01"
        return self

    def align_left(self) -> "EscposBuilder":
        self._buffer += ESC + b"a\x00"
        return self

    def bold(self, on: bool = True) -> "EscposBuilder":
        self._buffer += ESC + (b"E\x01" if on else b"E\x00")
        return self

    def feed(self, lines: int = 1) -> "EscposBuilder":
        self._buffer += b"\n" * max(lines, 0)
        return self

    def text(self, line: str = "") -> "EscposBuilder":
        """Añade una línea de texto (codificada CP437 para acentos)."""
        self._buffer += line.encode(TEXT_ENCODING, errors="replace") + b"\n"
        return self

    def raw(self, data: bytes) -> "EscposBuilder":
        self._buffer += data
        return self

    # --- Periféricos --------------------------------------------------

    def drawer(self) -> "EscposBuilder":
        """ESC p — abre el cajón monetario (pin 2, pulso de 100 ms)."""
        self._buffer += ESC + b"p\x00\x19\xfa"
        return self

    def cut(self, partial: bool = True) -> "EscposBuilder":
        """GS V — corte de papel (parcial por defecto, más seguro)."""
        if partial:
            self._buffer += GS + b"V\x42\x00"   # corte parcial con avance
        else:
            self._buffer += GS + b"V\x00"       # corte completo
        return self

    def to_bytes(self) -> bytes:
        return bytes(self._buffer)


# ----------------------------------------------------------------------
# Logo rasterizado en blanco y negro
# ----------------------------------------------------------------------

def raster_logo(image_path, dots: int) -> bytes:
    """Convierte el logo a un bitmap 1-bit listo para `GS v 0`.

    - Escala la imagen al ancho imprimible (384 pts para 58 mm, 576 para 80 mm)
      manteniendo la proporción.
    - Umbraliza a blanco y negro (dithering no: líneas más limpias para logos).
    """
    from PIL import Image

    img = Image.open(image_path).convert("L")

    # Escalar al ancho de puntos manteniendo proporción
    ratio = dots / img.width
    height = max(1, int(img.height * ratio))
    img = img.resize((dots, height), Image.LANCZOS)

    # Blanco y negro puro con umbral (el logo es oscuro sobre fondo claro)
    img = img.point(lambda px: 0 if px < 150 else 255, mode="1")

    # Pillow guarda el bitmap en filas de bytes alineadas por palabra
    raw = img.tobytes("raw", "1")
    row_bytes = (img.width + 7) // 8

    # Redistribuir por filas exactas (Pillow puede incluir padding)
    stride = len(raw) // img.height
    payload = bytearray()
    for row in range(img.height):
        payload += raw[row * stride: row * stride + row_bytes]

    x_l = dots & 0xFF
    x_h = (dots >> 8) & 0xFF
    y_l = img.height & 0xFF
    y_h = (img.height >> 8) & 0xFF

    header = GS + b"v0\x00" + bytes([x_l, x_h, y_l, y_h])
    return header + bytes(payload)


# ----------------------------------------------------------------------
# Ticket completo en bytes ESC/POS
# ----------------------------------------------------------------------

def build_escpos(
    ticket_text: str,
    logo_path: Optional[str] = None,
    width_chars: int = 48,
    show_logo: bool = True,
    auto_cut: bool = True,
    open_drawer: bool = False,
) -> bytes:
    """Construye el flujo ESC/POS final del ticket.

    El texto ya viene alineado por caracteres desde `ticket_builder`, así que
    se imprime tal cual; el logo y los periféricos se añaden por comando.
    """
    builder = EscposBuilder()
    builder.reset()

    # Logo en blanco y negro (si está configurado y existe)
    if show_logo and logo_path:
        try:
            dots = PRINTER_DOTS.get(width_chars, 576)
            builder.raw(raster_logo(logo_path, dots))
            builder.feed(1)
        except Exception:
            # Un logo problemático nunca debe impedir imprimir el ticket
            pass

    builder.align_left()
    for line in ticket_text.splitlines():
        builder.text(line)

    builder.feed(3)
    if open_drawer:
        builder.drawer()
    if auto_cut:
        builder.cut(partial=True)

    return builder.to_bytes()
