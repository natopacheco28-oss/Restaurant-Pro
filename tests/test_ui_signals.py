"""Regresión: señales Qt (clicked/toggled) que entregan un bool al handler.

qfluentwidgets conecta el `onClick` de SegmentedWidget/Pivot a una señal
`itemClicked(bool)` que emite `True` al hacer clic. Si el lambda del onClick
deja caer ese bool en la variable de la clave (patrón `lambda k=key: …`, que
NO descarta argumentos posicionales: el bool sobreescribe el default), el
handler recibe `True` en lugar de la clave:

- Inventario → `ValueError: True is not in list` en `_switch`
- POS → `int(True) == 1` (categoría silenciosamente incorrecta) y
  `order_type = True`
"""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QStackedWidget, QWidget

from app.core.services.sales_service import ORDER_TYPES
from app.ui.common import make_segmented


def test_segmented_onclick_entrega_clave_no_bool(qapp):
    """El clic en un segmento entrega la clave (str) al handler, no True."""
    recibido = []
    seg = make_segmented([("a", "A"), ("b", "B")], "a", recibido.append)
    seg.items["b"].itemClicked.emit(True)  # así emite qfluentwidgets al hacer clic
    assert recibido == ["b"]


def test_segmented_clave_actual_desconocida_no_falla(qapp):
    """`current` inexistente en los ítems → no debe elevar (se ignora)."""
    recibido = []
    seg = make_segmented([("a", "A"), ("b", "B")], "no-existe", recibido.append)
    assert seg is not None
    assert recibido == []


def test_inventory_switch_tolera_bool(qapp):
    """`_switch` con clave inválida (p. ej. True) regresa a la primera pestaña."""
    from app.ui.modules.inventory_module import InventoryModule

    stack = QStackedWidget()
    stack.addWidget(QWidget())  # pestaña 0: insumos
    stack.addWidget(QWidget())  # pestaña 1: kardex
    dummy = SimpleNamespace(TABS=InventoryModule.TABS, _stack=stack)

    InventoryModule._switch(dummy, True)  # antes: ValueError True is not in list
    assert stack.currentIndex() == 0
    InventoryModule._switch(dummy, "kardex")
    assert stack.currentIndex() == 1
    InventoryModule._switch(dummy, "clave-invalida")
    assert stack.currentIndex() == 0


def test_pos_category_change_tolera_bool(qapp):
    """Categoría inválida (bool) → 'Todo' (None); '3' → id 3."""
    from app.ui.modules.pos_module import PosModule

    dummy = SimpleNamespace(_category_id=99, _reload_products=lambda: None)
    PosModule._on_category_change(dummy, True)  # antes: int(True) == 1
    assert dummy._category_id is None
    PosModule._on_category_change(dummy, "3")
    assert dummy._category_id == 3
    PosModule._on_category_change(dummy, "all")
    assert dummy._category_id is None


def test_pos_order_type_tolera_bool(qapp):
    """Tipo de pedido inválido → el primero del catálogo ('mesa')."""
    from app.ui.modules.pos_module import CartPanel

    dummy = SimpleNamespace(pos=SimpleNamespace(order_type=None))
    CartPanel._on_order_type(dummy, True)  # antes: order_type = True
    assert dummy.pos.order_type == next(iter(ORDER_TYPES))
    CartPanel._on_order_type(dummy, "domicilio")
    assert dummy.pos.order_type == "domicilio"
