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
# Tamaño del logo impreso (cuadrado, px) por formato — ABCell Pro
LOGO_PX = {32: 128, 44: 148, 48: 148}

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

def raster_logo(image_path, logo_px: int) -> bytes:
    """Convierte el logo a un bitmap 1-bit pequeño (cuadrado `logo_px`)
    listo para `GS v 0`, con ancho múltiplo de 8.

    - `ImageOps.contain` a (logo_px, logo_px) manteniendo proporción —
      el tamaño impreso queda contenido en logo_px × logo_px puntos.
    - Umbral estilo ABCell Pro: el píxel oscuro se imprime (bit = 1).
    """
    from PIL import Image, ImageOps

    logo = Image.open(image_path)
    logo = ImageOps.exif_transpose(logo).convert("L")

    img = ImageOps.contain(logo, (logo_px, logo_px), Image.Resampling.LANCZOS)
    # Ancho múltiplo de 8 para empaquetar bytes limpio (relleno blanco)
    width = ((img.width + 7) // 8) * 8
    canvas = Image.new("L", (width, img.height), 255)
    canvas.paste(img, ((width - img.width) // 2, 0))
    # Oscuro (p<128) → 255 → bit 1 → se imprime (inversión correcta ESC/POS)
    bw = canvas.point(lambda p: 255 if p < 128 else 0).convert("1")

    height = bw.height
    row_bytes = width // 8
    raw = bw.tobytes("raw", "1")
    if len(raw) != row_bytes * height:          # seguridad ante padding raro
        raw = (raw + b"\x00" * (row_bytes * height))[:row_bytes * height]

    x_l = width & 0xFF
    x_h = (width >> 8) & 0xFF
    y_l = height & 0xFF
    y_h = (height >> 8) & 0xFF

    header = GS + b"v0\x00" + bytes([x_l, x_h, y_l, y_h])
    return header + raw


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

    # Logo PEQUEÑO y centrado, tamaño contenido por formato (ABCell Pro):
    # 58 mm → 128 px · 80 mm → 148 px (antes se estiraba a todo el ancho)
    if show_logo and logo_path:
        try:
            logo_px = LOGO_PX.get(width_chars, 148)
            builder.align_center()
            builder.raw(raster_logo(logo_path, logo_px))
            builder.align_left()
        except Exception:
            # Un logo problemático nunca debe impedir imprimir el ticket
            builder.align_left()
    for line in ticket_text.splitlines():
        builder.text(line)

    builder.feed(3)
    if open_drawer:
        builder.drawer()
    if auto_cut:
        builder.cut(partial=True)

    return builder.to_bytes()
