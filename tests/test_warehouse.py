"""Pruebas del almacén: lotes/FEFO, kardex, caducidades, estancados y alertas."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.services.alerts_service import AlertsService
from app.core.services.inventory_service import InventoryService

from app.core.services.validators import ValidationError


@pytest.fixture()
def inventory(db, bus, settings):
    return InventoryService(db, bus, settings)


@pytest.fixture()
def alerts(db, inventory, settings):
    return AlertsService(db, inventory, settings)


def _lots(inventory, ingredient_id):
    return {lot["id"]: lot for lot in inventory.list_lots(ingredient_id)}


# ======================================================================
# Lotes y PEPS/FEFO
# ======================================================================

class TestLotsFefo:
    def test_entry_creates_lot_with_expiration(self, inventory):
        ing = inventory.add_ingredient("Leche", "L", stock=0)
        expiration = (date.today() + timedelta(days=10)).isoformat()
        inventory.register_movement(ing, "entrada", 5, lot_number="A1",
                                    expiration=expiration, supplier="Lácteos SA")
        lots = inventory.list_lots(ing)
        assert len(lots) == 1
        assert lots[0]["lot_number"] == "A1"
        assert lots[0]["quantity"] == 5
        assert lots[0]["expiration_date"] == expiration
        assert lots[0]["supplier"] == "Lácteos SA"

    def test_expiration_cannot_be_in_the_past(self, inventory):
        ing = inventory.add_ingredient("Queso", "kg")
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with pytest.raises(ValidationError):
            inventory.register_movement(ing, "entrada", 3, expiration=yesterday)

    def test_salida_consumes_earliest_expiring_lot_first(self, inventory):
        ing = inventory.add_ingredient("Leche", "L", stock=0)
        soon = (date.today() + timedelta(days=3)).isoformat()
        later = (date.today() + timedelta(days=30)).isoformat()
        inventory.register_movement(ing, "entrada", 5, lot_number="PRÓXIMO",
                                    expiration=soon)
        inventory.register_movement(ing, "entrada", 5, lot_number="LEJANO",
                                    expiration=later)

        inventory.register_movement(ing, "salida", 6)

        # only_active=False incluye los lotes agotados (quantity = 0)
        lots = {lot["lot_number"]: lot
                for lot in inventory.list_lots(ing, only_active=False)}
        assert lots["PRÓXIMO"]["quantity"] == 0      # se agotó primero
        assert lots["LEJANO"]["quantity"] == 4       # resto del consumo
        assert inventory.get_ingredient(ing)["stock"] == 4

    def test_salida_without_expiration_follows_fifo(self, inventory):
        ing = inventory.add_ingredient("Arroz", "kg", stock=0)
        inventory.register_movement(ing, "entrada", 5, lot_number="L1")
        inventory.register_movement(ing, "entrada", 5, lot_number="L2")
        inventory.register_movement(ing, "salida", 3)
        lots = {lot["lot_number"]: lot
                for lot in inventory.list_lots(ing, only_active=False)}
        assert lots["L1"]["quantity"] == 2
        assert lots["L2"]["quantity"] == 5

    def test_forced_lot_merma_consumes_only_that_lot(self, inventory):
        ing = inventory.add_ingredient("Leche", "L", stock=0)
        soon = (date.today() + timedelta(days=2)).isoformat()
        later = (date.today() + timedelta(days=20)).isoformat()
        inventory.register_movement(ing, "entrada", 4, lot_number="A",
                                    expiration=soon)
        inventory.register_movement(ing, "entrada", 4, lot_number="B",
                                    expiration=later)
        lot_a = next(l for l in inventory.list_lots(ing)
                     if l["lot_number"] == "A")
        inventory.register_movement(ing, "merma", 2, reason="Caducado",
                                    force_lot_id=lot_a["id"])
        lots = {lot["lot_number"]: lot
                for lot in inventory.list_lots(ing, only_active=False)}
        assert lots["A"]["quantity"] == 2
        assert lots["B"]["quantity"] == 4

    def test_sale_consumes_by_fefo(self, db, inventory):
        ing = inventory.add_ingredient("Jamón", "kg", stock=0)
        soon = (date.today() + timedelta(days=1)).isoformat()
        later = (date.today() + timedelta(days=15)).isoformat()
        inventory.register_movement(ing, "entrada", 3, lot_number="A",
                                    expiration=soon)
        inventory.register_movement(ing, "entrada", 3, lot_number="B",
                                    expiration=later)
        # Venta simulada (consume_for_sale es llamado por SalesService)
        from app.core.services.inventory_service import consume_for_sale

        result = consume_for_sale(db, ing, 4, sale_id=0, folio=1)
        assert result["stock_after"] == 2
        lots = {lot["lot_number"]: lot
                for lot in inventory.list_lots(ing, only_active=False)}
        assert lots["A"]["quantity"] == 0
        assert lots["B"]["quantity"] == 2
        movements = inventory.list_movements(ingredient_id=ing, mtype="venta")
        assert len(movements) == 2  # una fila por lote consumido
        assert "folio #000001" in movements[0]["note"]


# ======================================================================
# Kardex (inmutable, filtrable)
# ======================================================================

class TestKardex:
    def test_merma_records_reason_and_user(self, inventory):
        ing = inventory.add_ingredient("Tomate", "kg", stock=10)
        inventory.register_movement(ing, "merma", 2, reason="Dañado o derrame",
                                    user="nacho")
        movements = inventory.list_movements(ingredient_id=ing, mtype="merma")
        assert movements[0]["reason"] == "Dañado o derrame"
        assert movements[0]["user"] == "nacho"
        assert movements[0]["quantity"] == -2
        assert inventory.get_ingredient(ing)["stock"] == 8

    def test_filters_by_type_date_and_reason(self, inventory):
        ing = inventory.add_ingredient("Carne", "kg", stock=10)
        inventory.register_movement(ing, "entrada", 5, note="compra proveedor")
        inventory.register_movement(ing, "merma", 1, reason="Degustación")

        assert all(m["type"] == "merma" for m in
                   inventory.list_movements(mtype="merma"))
        today = date.today().isoformat()
        assert all(m["datetime"][:10] >= today for m in
                   inventory.list_movements(since=today))
        assert any("Degustación" in (m["reason"] or "") for m in
                   inventory.list_movements(reason_search="Degust"))
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert inventory.list_movements(since=tomorrow) == []

    def test_adjust_sets_exact_stock(self, inventory):
        ing = inventory.add_ingredient("Café", "kg", stock=5)
        movement = inventory.register_movement(ing, "ajuste", 3,
                                               reason="Corrección de conteo")
        assert movement["stock_after"] == 3
        assert inventory.get_ingredient(ing)["stock"] == 3

    def test_movement_cost_defaults_to_lot_cost(self, inventory):
        ing = inventory.add_ingredient("Pan", "pza", stock=0)
        inventory.register_movement(ing, "entrada", 10, unit_cost=1.5)
        inventory.register_movement(ing, "salida", 2)
        salida = inventory.list_movements(ingredient_id=ing, mtype="salida")[0]
        assert salida["unit_cost"] == 1.5  # costo heredado del lote


# ======================================================================
# Insumos: estado, ideal, proveedor
# ======================================================================

class TestIngredientState:
    def test_estado_normal_bajo_agotado(self, inventory):
        ing = inventory.add_ingredient("Azúcar", "kg", stock=10, min_stock=2)
        assert inventory.get_ingredient(ing)["estado"] == "normal"

        inventory.register_movement(ing, "salida", 9)  # queda 1 ≤ mínimo
        assert inventory.get_ingredient(ing)["estado"] == "bajo"

        inventory.register_movement(ing, "salida", 1)
        assert inventory.get_ingredient(ing)["estado"] == "agotado"

    def test_ideal_stock_and_supplier(self, inventory):
        ing = inventory.add_ingredient("Café", "kg", stock=4, min_stock=2,
                                       ideal_stock=15, supplier="Importadora")
        updated = inventory.get_ingredient(ing)
        assert updated["ideal_stock"] == 15
        assert updated["supplier"] == "Importadora"

        inventory.update_ingredient(ing, "Café", "kg", min_stock=2, cost=100,
                                    ideal_stock=20, warning_days=5)
        updated = inventory.get_ingredient(ing)
        assert updated["ideal_stock"] == 20
        assert updated["warning_days"] == 5

    def test_list_ingredients_search_by_supplier(self, inventory):
        inventory.add_ingredient("Café", "kg", supplier="Importadora MX")
        inventory.add_ingredient("Azúcar", "kg", supplier="Otro")
        names = {row["name"] for row in inventory.list_ingredients("Importadora")}
        assert names == {"Café"}


# ======================================================================
# Sin movimiento (stock estancado)
# ======================================================================

class TestStale:
    def test_stale_detection(self, db, inventory):
        ing = inventory.add_ingredient("Salsa", "L", stock=6, cost=40)
        # Simular el paso del tiempo: la entrada fue hace 40 días
        db.execute(
            "UPDATE movements SET datetime = datetime('now', '-40 days')"
            " WHERE ingredient_id = ?",
            (ing,),
        )
        stale = inventory.stale_ingredients(days=30)
        assert any(row["id"] == ing for row in stale)
        row = next(r for r in stale if r["id"] == ing)
        assert row["value"] == 240.0            # 6 × 40
        assert row["last_out"] is None          # nunca tuvo salidas
        assert row["days_stale"] == 40

        # Una salida reciente lo saca de la lista
        inventory.register_movement(ing, "salida", 1)
        stale = inventory.stale_ingredients(days=30)
        assert not any(r["id"] == ing for r in stale)

    def test_fresh_ingredient_is_not_stale(self, inventory):
        """Un insumo creado hoy sin salidas aún NO es estancado."""
        ing = inventory.add_ingredient("Salsa nueva", "L", stock=6, cost=40)
        assert not any(r["id"] == ing for r in inventory.stale_ingredients(days=30))

    def test_stale_uses_days_window(self, inventory):
        ing = inventory.add_ingredient("Harina", "kg", stock=5)
        # Con ventana de 0 días no hay estancados (salida de hoy cuenta)
        inventory.register_movement(ing, "salida", 1)
        assert not any(r["id"] == ing for r in inventory.stale_ingredients(days=0))


# ======================================================================
# Alertas: detección, atendida, pospuesta
# ======================================================================

class TestAlerts:
    def test_low_and_expiring_alerts(self, inventory, alerts):
        ing = inventory.add_ingredient("Leche", "L", stock=5, min_stock=6)
        soon = (date.today() + timedelta(days=3)).isoformat()
        inventory.register_movement(ing, "entrada", 4, expiration=soon)
        # stock 9... salida para dejarlo bajo
        inventory.register_movement(ing, "salida", 5)  # queda 4 ≤ mínimo 6

        found = alerts.collect()
        kinds = [a["key"] for a in found]
        assert f"low:{ing}" in kinds

    def test_dismiss_suppresses_until_condition_changes(self, inventory, alerts):
        ing = inventory.add_ingredient("Leche", "L", stock=5, min_stock=6)
        first = [a for a in alerts.collect() if a["key"] == f"low:{ing}"]
        assert first

        alerts.dismiss(first[0])
        assert alerts.collect() == []          # suprimida (misma condición)

        # La condición cambia (el stock baja más) → vuelve a notificar
        inventory.register_movement(ing, "salida", 1)  # 5 → 4
        again = [a for a in alerts.collect() if a["key"] == f"low:{ing}"]
        assert again and again[0]["snapshot"] == f"{4.0:.3f}"

    def test_snooze_hides_temporarily(self, inventory, alerts):
        ing = inventory.add_ingredient("Arroz", "kg", stock=0, min_stock=2)
        alert = next(a for a in alerts.collect() if a["key"] == f"low:{ing}")
        alerts.snooze(alert, minutes=60)
        assert alerts.collect() == []

    def test_summary_text(self, inventory, alerts):
        inventory.add_ingredient("A", "pza", stock=0, min_stock=1)
        inventory.add_ingredient("B", "pza", stock=0, min_stock=1)
        found = alerts.collect()
        text = alerts.summary(found)
        assert "Hoy:" in text
        assert "agotados" in text

    def test_expired_lot_detected(self, db, inventory, alerts):
        ing = inventory.add_ingredient("Pescado", "kg", stock=0)
        # Lote ya vencido insertado directo (simula el paso del tiempo)
        db.execute(
            "INSERT INTO lots (ingredient_id, lot_number, expiration_date,"
            " quantity) VALUES (?, 'VIEJO', date('now', '-2 days'), 3)",
            (ing,),
        )
        keys = [a["key"] for a in alerts.collect()]
        assert any(k.startswith("exp:") for k in keys)
        vencido = next(a for a in alerts.collect() if a["kind"] == "expiry")
        assert vencido["severity"] == "vencido"

    def test_expiring_within_warning_days(self, inventory, alerts):
        ing = inventory.add_ingredient("Leche", "L", stock=0)
        soon = (date.today() + timedelta(days=3)).isoformat()
        inventory.register_movement(ing, "entrada", 4, expiration=soon)
        alerts_list = alerts.collect()
        expiring = [a for a in alerts_list if a["kind"] == "expiry"]
        assert expiring and expiring[0]["severity"] == "por_caducar"

    def test_notify_disabled_by_settings(self, db, inventory, settings):
        settings.set("inventory.notify_stale", False)
        service = InventoryService(db, None, settings)
        alerts = AlertsService(db, service, settings)
        inventory.add_ingredient("Estancado", "pza", stock=5, cost=10)
        assert not any(a["kind"] == "stale" for a in alerts.collect())
