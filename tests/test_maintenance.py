"""Regresión del borrado operativo (menú oculto Ctrl+P).

`reset_operational_data` debe eliminar ventas, órdenes, caja, kardex,
lotes, listas de compras y alertas atendidas — en orden seguro de claves
foráneas y en una sola transacción — reiniciando el stock a 0 y
conservando catálogo, insumos y ajustes.
"""
from __future__ import annotations

from app.core.services.catalog_service import CatalogService
from app.core.services.inventory_service import InventoryService
from app.core.services.maintenance_service import reset_operational_data
from app.core.services.shopping_service import ShoppingService


def _populate(db, bus, settings) -> dict:
    """Crea datos operativos completos: catálogo, inventario, venta y listas."""
    catalog = CatalogService(db, bus)
    inventory = InventoryService(db, bus, settings)
    shopping = ShoppingService(db, bus, inventory)

    category = catalog.add_category("Bebidas")
    db.execute(
        "INSERT INTO products (category_id, name, price) VALUES (?, ?, ?)",
        (category, "Refresco", 25.0),
    )
    # add_ingredient ya registra la entrada con lote y stock
    ing = inventory.add_ingredient("Refresco caja", "pza", stock=24, cost=12.0)

    db.execute(
        "INSERT INTO cash_sessions (status, opened_by) VALUES ('abierta', 'nacho')")
    sale_id = db.execute(
        "INSERT INTO sales (folio, order_type, payment_method, subtotal, total,"
        " paid, change, cash_session_id) VALUES (1, 'mesa', 'efectivo',"
        " 25.0, 25.0, 50.0, 25.0, 1)")
    db.execute(
        "INSERT INTO sale_items (sale_id, product_id, product_name, unit_price,"
        " quantity, line_total) VALUES (?, 1, 'Refresco', 25.0, 1, 25.0)",
        (sale_id,),
    )
    shopping.create_list(
        [{"ingredient_id": ing, "name": "Refresco caja", "quantity": 5}],
        note="prueba de borrado")

    return {
        "catalog": catalog,
        "inventory": inventory,
        "shopping": shopping,
        "category": category,
        "ingredient": ing,
    }


def test_reset_elimina_operativo_conserva_catalogo(db, bus, settings):
    data = _populate(db, bus, settings)

    # Antes del borrado hay datos en todas las tablas operativas
    for table in ("movements", "lots", "sales", "sale_items",
                  "cash_sessions", "shopping_lists", "shopping_list_items"):
        assert db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] > 0, table
    assert db.one("SELECT stock FROM ingredients WHERE id = ?",
                  (data["ingredient"],))["stock"] == 24

    counts = reset_operational_data(db)

    # Todo lo operativo quedó en cero
    assert all(v >= 0 for v in counts.values())
    for table in ("movements", "lots", "sales", "sale_items", "cash_sessions",
                  "shopping_lists", "shopping_list_items", "alert_dismissals"):
        assert db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0, table

    # El stock vuelve a 0 (el kardex era su fuente de verdad)
    assert db.one("SELECT stock FROM ingredients WHERE id = ?",
                  (data["ingredient"],))["stock"] == 0

    # El catálogo y los insumos (definición) se conservan
    assert db.one("SELECT COUNT(*) AS n FROM categories")["n"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM products")["n"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM ingredients")["n"] == 1


def test_reset_es_atómico_y_repetible(db, bus, settings):
    _populate(db, bus, settings)
    assert reset_operational_data(db)  # primera pasada
    assert reset_operational_data(db)  # segunda pasada sin datos: sin error
    assert db.one("SELECT COUNT(*) AS n FROM sales")["n"] == 0


def test_menu_oculto_y_dialogos_importan(qapp):
    """El diálogo del menú oculto se construye sin errores."""
    from PySide6.QtWidgets import QWidget

    from app.ui.dialogs.hidden_menu_dialog import ConfirmWipeBox

    host = QWidget()                              # mantener vivo mientras dura
    box = ConfirmWipeBox(host)
    assert not box.yesButton.isEnabled()          # exige escribir BORRAR
    box.input.setText("otra cosa")
    assert not box.yesButton.isEnabled()
    box.input.setText("BORRAR")
    assert box.yesButton.isEnabled()
    assert box.validate()
