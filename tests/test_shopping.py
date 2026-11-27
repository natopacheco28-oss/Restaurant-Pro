"""Pruebas de las listas de compras sugeridas y su conversión a entradas."""
from __future__ import annotations

import pytest

from app.core.services.inventory_service import InventoryService
from app.core.services.shopping_service import ShoppingService
from app.core.services.validators import ValidationError


@pytest.fixture()
def inventory(db, bus, settings):
    return InventoryService(db, bus, settings)


@pytest.fixture()
def shopping(db, bus, inventory):
    return ShoppingService(db, bus, inventory)


class TestSuggestedItems:
    def test_with_ideal_stock(self, shopping, inventory):
        # stock 4 ≤ mínimo 8 → está bajo; sugerencia = ideal 15 − 4 = 11
        inventory.add_ingredient("Café", "kg", stock=4, min_stock=8,
                                 ideal_stock=15, cost=100)
        items = shopping.suggested_items()
        assert len(items) == 1
        item = items[0]
        assert item["quantity"] == 11            # 15 − 4
        assert item["estimated_cost"] == 1100.0  # 11 × 100
        assert item["unit"] == "kg"

    def test_without_ideal_uses_min_times_two(self, shopping, inventory):
        inventory.add_ingredient("Azúcar", "kg", stock=1, min_stock=3, cost=20)
        items = shopping.suggested_items()
        assert items[0]["quantity"] == 5         # (3 × 2) − 1

    def test_out_of_stock_without_minimum(self, shopping, inventory):
        inventory.add_ingredient("Sal", "pza", stock=0, min_stock=0, cost=5)
        items = shopping.suggested_items()
        assert items[0]["quantity"] == 1         # sugerencia mínima

    def test_normal_stock_not_suggested(self, shopping, inventory):
        inventory.add_ingredient("Arroz", "kg", stock=10, min_stock=2)
        assert shopping.suggested_items() == []


class TestListPersistence:
    @staticmethod
    def _by_name(header, name):
        return next(it for it in header["items"] if it["name"] == name)

    def test_create_add_update_remove(self, shopping):
        list_id = shopping.create_list([
            {"ingredient_id": None, "name": "Servilletas", "quantity": 5,
             "unit": "caja", "estimated_cost": 100, "supplier": "Limpieza"},
        ])
        header = shopping.get_list(list_id)
        assert header["status"] == "pendiente"
        assert len(header["items"]) == 1

        item = self._by_name(header, "Servilletas")
        shopping.update_item(item["id"], quantity=8, checked=False)
        shopping.add_item(list_id, {"name": "Bolsas", "quantity": 2,
                                    "unit": "pza", "estimated_cost": 30})
        header = shopping.get_list(list_id)
        assert len(header["items"]) == 2
        servilletas = self._by_name(header, "Servilletas")
        assert servilletas["quantity"] == 8
        assert servilletas["checked"] == 0

        shopping.remove_item(self._by_name(header, "Bolsas")["id"])
        assert len(shopping.get_list(list_id)["items"]) == 1

    def test_item_requires_name_and_quantity(self, shopping):
        list_id = shopping.create_list([])
        with pytest.raises(ValidationError):
            shopping.add_item(list_id, {"name": "  ", "quantity": 1})
        with pytest.raises(ValidationError):
            shopping.add_item(list_id, {"name": "X", "quantity": 0})

    def test_latest_and_status(self, shopping):
        shopping.create_list([], note="uno")
        b = shopping.create_list([], note="dos")
        assert shopping.latest_list()["id"] == b
        shopping.set_status(b, ShoppingService.STATUS_BOUGHT)
        assert shopping.get_list(b)["status"] == "comprada"

    def test_grouping_and_total(self, shopping):
        items = [
            {"name": "A", "quantity": 1, "estimated_cost": 10, "supplier": "P1"},
            {"name": "B", "quantity": 2, "estimated_cost": 20, "supplier": "P1"},
            {"name": "C", "quantity": 1, "estimated_cost": 5, "supplier": ""},
        ]
        groups = shopping.group_by_supplier(items)
        assert set(groups.keys()) == {"P1", "Sin proveedor"}
        assert len(groups["P1"]) == 2
        assert shopping.total_cost(items) == 35.0


class TestConversionToEntries:
    def test_convert_creates_entries_and_marks_bought(self, shopping, inventory):
        ing = inventory.add_ingredient("Café", "kg", stock=2, min_stock=5,
                                       ideal_stock=12, cost=100,
                                       supplier="Importadora")
        items = shopping.suggested_items()
        assert items[0]["quantity"] == 10      # 12 − 2
        list_id = shopping.create_list(items, note="semana 1")

        result = shopping.convert_to_entries(list_id, user="nacho")
        assert result["created"] == 1

        # El stock subió a 12 y la entrada quedó en el kardex con lote
        assert inventory.get_ingredient(ing)["stock"] == 12
        movements = inventory.list_movements(ingredient_id=ing, mtype="entrada")
        assert any("lista #" + str(list_id) in (m["note"] or "")
                   for m in movements)
        assert movements[0]["supplier"] == "Importadora"
        assert movements[0]["user"] == "nacho"
        assert movements[0]["unit_cost"] == 100.0

        # La lista quedó comprada y no se puede convertir de nuevo
        assert shopping.get_list(list_id)["status"] == "comprada"
        with pytest.raises(ValidationError):
            shopping.convert_to_entries(list_id)

    def test_free_rows_are_skipped_and_reported(self, shopping):
        list_id = shopping.create_list([
            {"ingredient_id": None, "name": "Servilletas", "quantity": 3,
             "unit": "caja", "estimated_cost": 30},
        ])
        result = shopping.convert_to_entries(list_id)
        assert result["created"] == 0
        assert result["skipped"] == 1

    def test_conversion_is_atomic(self, shopping, inventory, monkeypatch):
        """Si una entrada falla, nada se registra (todo o nada)."""
        good = inventory.add_ingredient("Bien", "pza", stock=0, min_stock=1)
        other = inventory.add_ingredient("Otro", "pza", stock=0, min_stock=1)
        list_id = shopping.create_list([
            {"ingredient_id": good, "name": "Bien", "quantity": 2,
             "unit": "pza", "estimated_cost": 0},
            {"ingredient_id": other, "name": "Otro", "quantity": 1,
             "unit": "pza", "estimated_cost": 0},
        ])

        # La segunda entrada falla dentro de la transacción de conversión
        original = inventory.register_movement
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("fallo simulado")
            return original(*args, **kwargs)

        monkeypatch.setattr(shopping.inventory, "register_movement", flaky)

        with pytest.raises(RuntimeError):
            shopping.convert_to_entries(list_id)

        # Todo o nada: la primera entrada NO quedó registrada
        assert inventory.get_ingredient(good)["stock"] == 0
        assert inventory.get_ingredient(other)["stock"] == 0
        assert shopping.get_list(list_id)["status"] == "pendiente"
