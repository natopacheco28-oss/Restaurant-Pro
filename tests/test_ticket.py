"""Pruebas del constructor de tickets térmicos."""
from __future__ import annotations

from app.core.settings import Settings
from app.printing.ticket_builder import (
    build_test_ticket_text,
    build_ticket_text,
    fmt_qty,
    money,
)

SALE = {
    "folio": 42,
    "datetime": "2025-06-15 13:45:00",
    "order_type": "mesa",
    "payment_method": "efectivo",
    "subtotal": 145.0,
    "discount": 5.0,
    "tax": 16.0,
    "tip": 20.0,
    "total": 176.0,
    "paid": 200.0,
    "change": 24.0,
    "waiter": "Ana",
    "customer": "",
}

ITEMS = [
    {"product_name": "Hamburguesa clásica con queso extra", "unit_price": 120.0,
     "quantity": 1, "note": "sin cebolla"},
    {"product_name": "Coca 500 ml", "unit_price": 25.0, "quantity": 1, "note": ""},
]


def _settings(tmp_path):
    return Settings(tmp_path / "config.json")


def test_lines_respect_width(tmp_path):
    settings = _settings(tmp_path)
    for width in (32, 48):
        text = build_ticket_text(SALE, ITEMS, settings, width)
        for line in text.splitlines():
            assert len(line) <= width, f"Línea demasiado larga ({width}): {line!r}"


def test_ticket_contains_key_data(tmp_path):
    settings = _settings(tmp_path)
    text = build_ticket_text(SALE, ITEMS, settings, 48)
    assert "#000042" in text                 # folio formateado
    assert "2025-06-15" in text              # fecha de la venta
    assert "Mesero: Ana" in text
    assert "sin cebolla" in text             # nota por producto
    assert "TOTAL" in text
    assert "$176.00" in text                 # total formateado
    assert "$24.00" in text                  # cambio
    assert "Impuesto (16%)" in text
    assert "Descuento" in text


def test_ticket_restaurant_header(tmp_path):
    settings = _settings(tmp_path)
    settings.set("restaurant.name", "Mi Fonda")
    settings.set("restaurant.phone", "961 123 4567")
    text = build_ticket_text(SALE, ITEMS, settings, 48)
    assert "MI FONDA" in text.upper()
    assert "961 123 4567" in text


def test_ticket_footer_and_policies(tmp_path):
    settings = _settings(tmp_path)
    settings.set("ticket.footer", "¡Gracias por su compra!")
    settings.set("restaurant.policies", "Precios en pesos mexicanos.")
    text = build_ticket_text(SALE, ITEMS, settings, 48)
    assert "¡Gracias por su compra!" in text
    assert "Precios en pesos" in text


def test_test_ticket(tmp_path):
    settings = _settings(tmp_path)
    text = build_test_ticket_text(settings, 32)
    assert "TOTAL" in text
    for line in text.splitlines():
        assert len(line) <= 32


def test_helpers():
    assert money(1234.5) == "$1,234.50"
    assert money(-1) == "$-1.00"
    assert fmt_qty(2) == "2"
    assert fmt_qty(1.5) == "1.5"
    assert fmt_qty(2.0) == "2"
