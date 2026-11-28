"""Constructor del texto del ticket térmico (58 mm / 80 mm).

Genera un ticket alineado por caracteres para impresoras de matriz/thermal:
32 caracteres de ancho para papel de 58 mm y 48 para 80 mm. El mismo texto
se usa para la vista previa en pantalla y para la impresión ESC/POS.
"""
from __future__ import annotations

from typing import Any, Optional

# Anchos de papel soportados
PAPER_WIDTHS = {58: 32, 80: 48}

SEP_MAIN = "="   # separador fuerte
SEP_THIN = "-"   # separador ligero


def money(value: float, currency: str = "$") -> str:
    """Formatea un importe: $1,234.50"""
    return f"{currency}{(value or 0):,.2f}"


def fmt_qty(quantity: float) -> str:
    """Cantidad legible: 1 → '1', 1.5 → '1.5', 2.0 → '2'."""
    text = f"{quantity:.2f}".rstrip("0").rstrip(".")
    return text or "0"


# ----------------------------------------------------------------------
# Utilidades de alineación por caracteres
# ----------------------------------------------------------------------

def _center(text: str, width: int) -> str:
    text = text.strip()
    if len(text) >= width:
        return text[:width]
    pad = (width - len(text)) // 2
    return " " * pad + text


def _split_lr(left: str, right: str, width: int) -> str:
    """Texto a la izquierda + importe a la derecha, truncando si no cabe."""
    right = right.strip()
    left = left.strip()
    space = width - len(right)
    if space <= 0:
        return (left + " " + right)[:width]
    if len(left) > space - 1:
        left = left[: space - 1]
    return left + " " * (space - len(left)) + right


def _wrap(text: str, width: int) -> list[str]:
    """Divide un texto en líneas de `width` caracteres sin cortar palabras."""
    text = (text or "").strip()
    if not text:
        return []
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            while len(word) > width:  # palabra larguísima (URL, etc.)
                lines.append(word[:width])
                word = word[width:]
            current = word
    if current:
        lines.append(current)
    return lines


# ----------------------------------------------------------------------
# Ticket completo
# ----------------------------------------------------------------------

def build_ticket_text(
    sale: dict,
    items: list[dict],
    settings: Any,
    width: Optional[int] = None,
) -> str:
    """Construye el texto del ticket de una venta.

    `sale`: fila de `sales` (folio, datetime, order_type, payment_method,
            subtotal, discount, tax, tip, total, paid, change, waiter, customer)
    `items`: filas de `sale_items` (product_name, quantity, unit_price, note)
    `settings`: SettingsManager con las claves `restaurant.*` y `ticket.*`.
    """
    if width is None:
        width = int(settings.get("ticket.width_chars", 48))
    currency = settings.get("ticket.currency", "$")
    tax_rate = float(settings.get("ticket.tax_rate", 0) or 0)

    # Etiquetas legibles (se importa aquí para evitar ciclos de importación)
    from app.core.services.sales_service import ORDER_TYPES, PAYMENT_METHODS

    order_label = ORDER_TYPES.get(sale.get("order_type"), sale.get("order_type", ""))
    payment_label = PAYMENT_METHODS.get(
        sale.get("payment_method"), sale.get("payment_method", "")
    )
    restaurant = settings.get("restaurant.name", "Restaurante Pro")

    lines: list[str] = []

    # --- Encabezado: datos del restaurante ---
    for raw in (restaurant, settings.get("restaurant.slogan", "")):
        for ln in _wrap(str(raw or ""), width):
            lines.append(_center(ln, width))
    for field_name in ("phone", "address", "tax_id", "social"):
        value = settings.get(f"restaurant.{field_name}", "")
        for ln in _wrap(str(value or ""), width):
            lines.append(_center(ln, width))

    lines.append(SEP_MAIN * width)

    # --- Datos de la venta ---
    lines.append(_split_lr(f"Folio: #{int(sale.get('folio', 0)):06d}", "", width))
    lines.append(f"Fecha: {sale.get('datetime', '')}")
    lines.append(f"Pedido: {order_label}")
    if sale.get("waiter"):
        lines.append(f"Mesero: {sale['waiter']}")
    if sale.get("customer"):
        lines.append(f"Cliente: {sale['customer']}")

    lines.append(SEP_THIN * width)

    # --- Partidas: cantidad x producto + importe ---
    for item in items:
        qty = fmt_qty(float(item.get("quantity", 1)))
        name = str(item.get("product_name", ""))
        amount = money(float(item.get("unit_price", 0)) * float(item.get("quantity", 0)),
                       currency)
        lines.append(_split_lr(f"{qty} x {name}", amount, width))
        note = (item.get("note") or "").strip()
        for ln in _wrap(f"» {note}", width - 2):
            lines.append(f"  {ln}")

    lines.append(SEP_THIN * width)

    # --- Totales ---
    subtotal = float(sale.get("subtotal", 0))
    discount = float(sale.get("discount", 0))
    tax = float(sale.get("tax", 0))
    tip = float(sale.get("tip", 0))
    total = float(sale.get("total", 0))

    lines.append(_split_lr("Subtotal", money(subtotal, currency), width))
    if discount > 0:
        lines.append(_split_lr("Descuento", f"-{money(discount, currency)}", width))
    if tax_rate > 0:
        lines.append(_split_lr(f"Impuesto ({tax_rate:g}%)", money(tax, currency), width))
    if tip > 0:
        lines.append(_split_lr("Propina", money(tip, currency), width))
    lines.append(_split_lr("TOTAL", money(total, currency), width))

    # --- Pago y cambio ---
    paid = float(sale.get("paid", 0))
    change = float(sale.get("change", 0))
    lines.append(_split_lr(f"Pago ({payment_label})", money(paid, currency), width))
    if sale.get("payment_method") == "efectivo":
        lines.append(_split_lr("Cambio", money(change, currency), width))

    lines.append(SEP_MAIN * width)

    # --- Pie personalizado ---
    for ln in _wrap(str(settings.get("ticket.footer", "") or ""), width):
        lines.append(_center(ln, width))
    policies = str(settings.get("restaurant.policies", "") or "")
    if policies:
        lines.append(SEP_THIN * width)
        for ln in _wrap(policies, width):
            lines.append(_center(ln, width))

    return "\n".join(lines)


def build_test_ticket_text(settings: Any, width: Optional[int] = None) -> str:
    """Ticket de PRUEBA con datos de demostración verosímiles.

    Se genera como si el programa ya estuviera configurado y en operación:
    fecha y hora actuales, mesero, varias partidas con notas, descuento,
    propina, pago en efectivo y cambio — usando la moneda y el impuesto
    configurados — para demostrar cómo se imprime y cómo se ven los datos.
    """
    from datetime import datetime

    tax_rate = float(settings.get("ticket.tax_rate", 0) or 0)
    items = [
        {"product_name": "Tacos de pastor (orden)", "unit_price": 96.0,
         "quantity": 2, "note": "Sin cilantro, con todo"},
        {"product_name": "Quesadilla de chicharrón", "unit_price": 55.0,
         "quantity": 1, "note": "Queso extra"},
        {"product_name": "Agua de horchata 1 L", "unit_price": 45.0,
         "quantity": 1, "note": ""},
        {"product_name": "Refresco en lata", "unit_price": 25.0,
         "quantity": 3, "note": "Bien fríos"},
    ]
    subtotal = round(sum(float(i["unit_price"]) * float(i["quantity"])
                         for i in items), 2)
    discount = round(subtotal * 0.10, 2)   # descuento de demostración (10 %)
    taxable = subtotal - discount
    tax = round(taxable * tax_rate / 100.0, 2)
    tip = round(taxable * 0.10, 2)         # propina sugerida (10 %)
    total = round(taxable + tax + tip, 2)
    paid = 1000.0
    sale = {
        "folio": 77,
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "order_type": "mesa",
        "payment_method": "efectivo",
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "tip": tip,
        "total": total,
        "paid": paid,
        "change": round(paid - total, 2),
        "waiter": "Ana (demostración)",
        "customer": "",
    }
    return build_ticket_text(sale, items, settings, width)
