"""Pruebas de los servicios: catálogo, inventario, ventas y estadísticas."""
from __future__ import annotations

import pytest

from app.core.services.catalog_service import CatalogService
from app.core.services.inventory_service import InventoryService
from app.core.services.sales_service import SalesService
from app.core.services.stats_service import StatsService
from app.core.services.validators import ValidationError


@pytest.fixture()
def catalog(db, bus):
    return CatalogService(db, bus)


@pytest.fixture()
def inventory(db, bus):
    return InventoryService(db, bus)


@pytest.fixture()
def sales(db, bus, settings):
    return SalesService(db, bus, settings)


@pytest.fixture()
def stats(db, settings):
    return StatsService(db, settings)


# ======================================================================
# Catálogo
# ======================================================================

class TestCatalog:
    def test_category_crud(self, catalog):
        cat_id = catalog.add_category("Bebidas")
        catalog.update_category(cat_id, "Bebidas frías")
        categories = catalog.list_categories()
        assert categories[0]["name"] == "Bebidas frías"
        catalog.delete_category(cat_id)
        assert catalog.list_categories() == []

    def test_category_duplicate_rejected(self, catalog):
        catalog.add_category("Bebidas")
        with pytest.raises(ValidationError):
            catalog.add_category("bebidas")  # mismo nombre, mayúsculas distintas

    def test_category_empty_name_rejected(self, catalog):
        with pytest.raises(ValidationError):
            catalog.add_category("   ")

    def test_product_crud(self, catalog):
        cat_id = catalog.add_category("Comidas")
        product_id = catalog.add_product("Hamburguesa", 99.5, cat_id)
        product = catalog.get_product(product_id)
        assert product["price"] == 99.5
        assert product["available"] == 1

        catalog.update_product(product_id, "Hamburguesa doble", 120, cat_id)
        assert catalog.get_product(product_id)["name"] == "Hamburguesa doble"

        catalog.delete_product(product_id)
        assert catalog.get_product(product_id) is None

    def test_product_validation(self, catalog):
        catalog.add_product("Tacos", 50)
        with pytest.raises(ValidationError):
            catalog.add_product("tacos", 50)   # duplicado
        with pytest.raises(ValidationError):
            catalog.add_product("", 50)        # nombre vacío
        with pytest.raises(ValidationError):
            catalog.add_product("Sin precio", -5)  # precio negativo

    def test_recipe_roundtrip(self, catalog, inventory):
        ing = inventory.add_ingredient("Pan", "pza", stock=10, min_stock=2, cost=5)
        product = catalog.add_product("Hamburguesa", 100)
        catalog.set_recipe(product, [(ing, 1.0)])
        recipe = catalog.get_recipe(product)
        assert len(recipe) == 1
        assert recipe[0]["ingredient_name"] == "Pan"


# ======================================================================
# Inventario
# ======================================================================

class TestInventory:
    def test_add_and_list(self, inventory):
        inventory.add_ingredient("Leche", "L", stock=10, min_stock=2, cost=20)
        ingredients = inventory.list_ingredients()
        assert len(ingredients) == 1
        assert ingredients[0]["stock"] == 10
        assert not ingredients[0]["is_low"]

    def test_duplicate_rejected(self, inventory):
        inventory.add_ingredient("Leche", "L")
        with pytest.raises(ValidationError):
            inventory.add_ingredient("leche", "ml")

    def test_entry_and_exit(self, inventory):
        ing = inventory.add_ingredient("Arroz", "kg", stock=5)
        inventory.register_movement(ing, "entrada", 3)
        assert inventory.get_ingredient(ing)["stock"] == 8

        inventory.register_movement(ing, "salida", 2.5)
        assert inventory.get_ingredient(ing)["stock"] == 5.5

        # Salida mayor al stock → error
        with pytest.raises(ValidationError):
            inventory.register_movement(ing, "salida", 100)

    def test_low_stock_alert(self, inventory):
        ing = inventory.add_ingredient("Queso", "kg", stock=5, min_stock=3)
        movement = inventory.register_movement(ing, "salida", 3)
        assert movement["is_low"] is True
        assert inventory.get_ingredient(ing)["stock"] == 2
        assert inventory.low_stock_ingredients()

    def test_movement_history(self, inventory):
        ing = inventory.add_ingredient("Carne", "kg", stock=10, min_stock=0)
        inventory.register_movement(ing, "entrada", 5, note="compra")
        inventory.register_movement(ing, "salida", 1, note="merma")
        movements = inventory.list_movements()
        assert len(movements) == 3  # stock inicial + entrada + salida
        assert movements[0]["note"] == "merma"
        assert movements[0]["stock_after"] == 14


# ======================================================================
# Ventas / caja
# ======================================================================

class TestSales:
    def _cart(self, catalog, inventory):
        ing = inventory.add_ingredient("Pan", "pza", stock=10)
        product = catalog.add_product("Hamburguesa", 100)
        catalog.set_recipe(product, [(ing, 2)])  # 2 panes por venta
        return product, ing

    def test_open_and_close_session(self, sales):
        session = sales.open_session(500)
        assert sales.current_session()["id"] == session["id"]
        with pytest.raises(ValidationError):
            sales.open_session(100)  # ya hay caja abierta

        summary = sales.close_session(session["id"], 500)
        assert summary["difference"] == 0
        assert sales.current_session() is None

    def test_checkout_requires_open_session(self, sales, catalog):
        product = catalog.add_product("Café", 30)
        with pytest.raises(ValidationError):
            sales.checkout(
                [{"product_id": product, "name": "Café", "unit_price": 30,
                  "quantity": 1, "note": ""}],
                "mesa", "efectivo",
            )

    def test_checkout_math_and_inventory(self, sales, catalog, inventory, settings):
        settings.set("ticket.tax_rate", 16.0)
        self._cart(catalog, inventory)
        sales.open_session(0)

        result = sales.checkout(
            [{"product_id": 1, "name": "Hamburguesa", "unit_price": 100,
              "quantity": 2, "note": "sin cebolla"}],
            "mesa", "efectivo", discount=10, tip=5, paid=300,
        )
        sale = result["sale"]
        assert sale["folio"] == 1
        # subtotal 200 − descuento 10 = 190 · impuesto 16% = 30.4 · +propina 5
        assert sale["total"] == 225.4
        assert sale["change"] == 74.6

        # El inventario se descontó por receta: 2 ventas × 2 panes = 4
        assert inventory.get_ingredient(1)["stock"] == 6
        # El movimiento quedó en el historial ligado a la venta
        movements = inventory.list_movements()
        assert any(m["type"] == "venta" for m in movements)
        assert result["items"][0]["note"] == "sin cebolla"

    def test_folio_is_consecutive(self, sales, catalog, inventory):
        sales.open_session(0)
        product = catalog.add_product("Refresco", 25)
        cart = [{"product_id": product, "name": "Refresco", "unit_price": 25,
                 "quantity": 1, "note": ""}]
        assert sales.checkout(cart, "llevar", "tarjeta")["sale"]["folio"] == 1
        assert sales.checkout(cart, "llevar", "tarjeta")["sale"]["folio"] == 2

    def test_cash_below_total_rejected(self, sales, catalog):
        sales.open_session(0)
        product = catalog.add_product("Café", 30)
        with pytest.raises(ValidationError):
            sales.checkout(
                [{"product_id": product, "name": "Café", "unit_price": 30,
                  "quantity": 1, "note": ""}],
                "mesa", "efectivo", paid=10,
            )

    def test_close_session_totals(self, sales, catalog, settings):
        settings.set("ticket.tax_rate", 0)  # totales redondos para el corte
        sales.open_session(100)
        product = catalog.add_product("Café", 30)
        cart = [{"product_id": product, "name": "Café", "unit_price": 30,
                 "quantity": 1, "note": ""}]
        sales.checkout(cart, "mesa", "efectivo")
        sales.checkout(cart, "mesa", "tarjeta")

        session = sales.current_session()
        summary = sales.close_session(session["id"], 130)
        assert summary["cash_expected"] == 130  # fondo 100 + 30 efectivo
        assert summary["totals"]["methods"]["tarjeta"]["total"] == 30
        assert summary["difference"] == 0


# ======================================================================
# Estadísticas
# ======================================================================

class TestStats:
    def test_summary_groups(self, sales, catalog, stats, settings):
        settings.set("ticket.tax_rate", 0)  # totales redondos
        sales.open_session(0)
        product = catalog.add_product("Café", 30)
        cart = [{"product_id": product, "name": "Café", "unit_price": 30,
                 "quantity": 2, "note": ""}]
        sales.checkout(cart, "mesa", "efectivo")
        sales.checkout(cart, "llevar", "tarjeta")

        from datetime import date

        today = date.today().isoformat()
        summary = stats.summary(today, today)

        assert summary["kpi"]["total_sales"] == 120   # 2 ventas × (30 × 2)
        assert summary["kpi"]["ticket_count"] == 2
        assert summary["kpi"]["avg_ticket"] == 60
        assert summary["kpi"]["items_sold"] == 4
        assert summary["by_day"][0]["total"] == 120
        assert summary["by_method"][0]["bucket"] in ("efectivo", "tarjeta")
        assert summary["top_products"][0]["name"] == "Café"

    def test_empty_summary_is_safe(self, stats):
        from datetime import date

        today = date.today().isoformat()
        summary = stats.summary(today, today)
        assert summary["kpi"]["total_sales"] == 0
        assert summary["kpi"]["avg_ticket"] == 0
        assert summary["by_day"] == []
