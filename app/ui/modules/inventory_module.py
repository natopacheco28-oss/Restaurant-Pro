"""Módulo INVENTARIO: insumos, entradas/salidas y movimientos.

- Tabla de insumos con unidad, stock, mínimo y costo; los renglones con
  stock bajo se pintan en rojo y hay alerta visual (banner).
- Entradas y salidas manuales con historial completo de movimientos.
- Las ediciones requieren el modo edición (clave maestra por sesión).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    TableWidget,
    TitleLabel,
    TransparentToolButton,
)

from app.printing.ticket_builder import money
from app.ui.common import EditModeBanner, confirm, currency_of, fi
from app.ui.dialogs.inventory_dialogs import IngredientDialog, MovementDialog

# Renglón con stock bajo: fondo rojo translúcido
LOW_STOCK_BG = QColor(255, 82, 82, 46)


class InventoryModule(QWidget):
    """Página del inventario."""

    def __init__(self, ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("InventoryModule")
        self._search_text = ""
        self._period_filter = "all"
        self._build_ui()
        self._reload_ingredients()
        self._reload_movements()

        self.ctx.bus.ingredientsChanged.connect(self._reload_ingredients)
        self.ctx.bus.movementsChanged.connect(self._reload_movements)

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(TitleLabel("Inventario"))
        header.addStretch(1)
        self._banner = EditModeBanner(self.ctx)
        header.addWidget(self._banner)
        root.addLayout(header)

        self._low_stock_label = CaptionLabel("")
        self._low_stock_label.setStyleSheet("color: #d13438; font-weight: 600;")
        self._low_stock_label.setVisible(False)
        root.addWidget(self._low_stock_label)

        # ---------------- Insumos ----------------
        ingredients_card = CardWidget()
        ing_layout = QVBoxLayout(ingredients_card)
        ing_layout.setContentsMargins(14, 14, 14, 14)
        ing_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self._search = SearchLineEdit()
        self._search.setPlaceholderText("Buscar insumo…")
        self._search.textChanged.connect(self._on_search)
        toolbar.addWidget(self._search, 1)

        self._add_button = PrimaryPushButton("Agregar insumo")
        self._add_button.setIcon(fi("ADD"))
        self._add_button.clicked.connect(self._add_ingredient)
        toolbar.addWidget(self._add_button)

        self._edit_button = PushButton("Editar")
        self._edit_button.setIcon(fi("EDIT"))
        self._edit_button.clicked.connect(self._edit_ingredient)
        toolbar.addWidget(self._edit_button)

        self._in_button = PushButton("Entrada")
        self._in_button.setIcon(fi("DOWNLOAD", "ADD"))
        self._in_button.setToolTip("Registrar entrada de mercancía")
        self._in_button.clicked.connect(lambda: self._movement("entrada"))
        toolbar.addWidget(self._in_button)

        self._out_button = PushButton("Salida")
        self._out_button.setIcon(fi("UPLOAD", "REMOVE"))
        self._out_button.setToolTip("Registrar salida (merma, consumo…)")
        self._out_button.clicked.connect(lambda: self._movement("salida"))
        toolbar.addWidget(self._out_button)

        self._delete_button = TransparentToolButton(fi("DELETE"))
        self._delete_button.setToolTip("Eliminar insumo")
        self._delete_button.clicked.connect(self._delete_ingredient)
        toolbar.addWidget(self._delete_button)
        ing_layout.addLayout(toolbar)

        self._ingredients_table = TableWidget()
        self._ingredients_table.setColumnCount(6)
        self._ingredients_table.setHorizontalHeaderLabels(
            ["Insumo", "Unidad", "Stock", "Mínimo", "Costo", "Estado"]
        )
        self._ingredients_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._ingredients_table.setSelectionBehavior(
            TableWidget.SelectionBehavior.SelectRows)
        self._ingredients_table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self._ingredients_table.verticalHeader().setVisible(False)
        self._ingredients_table.setWordWrap(False)
        self._ingredients_table.setBorderVisible(True)
        self._ingredients_table.setBorderRadius(8)
        self._ingredients_table.setMinimumHeight(220)
        ing_layout.addWidget(self._ingredients_table, 1)
        root.addWidget(ingredients_card, 5)

        # ---------------- Movimientos ----------------
        movements_card = CardWidget()
        mov_layout = QVBoxLayout(movements_card)
        mov_layout.setContentsMargins(14, 14, 14, 14)
        mov_layout.setSpacing(8)

        mov_toolbar = QHBoxLayout()
        mov_toolbar.addWidget(StrongBodyLabel("Historial de movimientos"))
        mov_toolbar.addStretch(1)
        self._period_combo = ComboBox()
        self._period_combo.addItems(["Todos", "Hoy", "Últimos 7 días"])
        self._period_combo.currentIndexChanged.connect(self._on_period)
        mov_toolbar.addWidget(self._period_combo)
        mov_layout.addLayout(mov_toolbar)

        self._movements_table = TableWidget()
        self._movements_table.setColumnCount(6)
        self._movements_table.setHorizontalHeaderLabels(
            ["Fecha", "Insumo", "Tipo", "Cantidad", "Stock resultante", "Nota"]
        )
        self._movements_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self._movements_table.setSelectionBehavior(
            TableWidget.SelectionBehavior.SelectRows)
        self._movements_table.verticalHeader().setVisible(False)
        self._movements_table.setWordWrap(False)
        self._movements_table.setBorderVisible(True)
        self._movements_table.setBorderRadius(8)
        mov_layout.addWidget(self._movements_table, 1)
        root.addWidget(movements_card, 4)

    # ==================================================================
    # Insumos
    # ==================================================================

    def _on_search(self, text: str) -> None:
        self._search_text = text.strip()
        self._reload_ingredients()

    def _reload_ingredients(self) -> None:
        ingredients = self.ctx.inventory.list_ingredients(self._search_text)
        self._ingredients = ingredients
        table = self._ingredients_table
        table.setRowCount(len(ingredients))
        currency = currency_of(self.ctx.settings)

        low_names = []
        for row, ing in enumerate(ingredients):
            is_low = bool(ing["is_low"])
            if is_low and ing["min_stock"] > 0:
                low_names.append(f"{ing['name']} ({ing['stock']:g}/{ing['min_stock']:g})")

            values = [
                ing["name"], ing["unit"], f"{ing['stock']:g}",
                f"{ing['min_stock']:g}", money(ing["cost"], currency),
                "⚠ Stock bajo" if is_low else "OK",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if is_low and ing["min_stock"] > 0:
                    item.setBackground(LOW_STOCK_BG)
                if col in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, col, item)

        # Banner de alertas de stock bajo
        if low_names:
            self._low_stock_label.setText(
                "⚠ Stock bajo: " + ", ".join(low_names)
            )
            self._low_stock_label.setVisible(True)
        else:
            self._low_stock_label.setVisible(False)

    def _selected_ingredient(self) -> Optional[dict]:
        row = self._ingredients_table.currentRow()
        if row < 0 or not getattr(self, "_ingredients", None):
            return None
        if row < len(self._ingredients):
            return self._ingredients[row]
        return None

    def _require_unlock(self) -> bool:
        """El modo edición se pide al intentar modificar el inventario."""
        if self.ctx.security.is_unlocked:
            return True
        from app.ui.dialogs.security_dialogs import UnlockDialog

        UnlockDialog(self.ctx, self.window()).exec()
        return self.ctx.security.is_unlocked

    def _add_ingredient(self) -> None:
        if not self._require_unlock():
            return
        IngredientDialog(self.ctx, self.window()).exec()

    def _edit_ingredient(self) -> None:
        if not self._require_unlock():
            return
        ingredient = self._selected_ingredient()
        if ingredient is None:
            InfoBar.warning(title="Sin selección",
                            content="Seleccione un insumo de la tabla.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        IngredientDialog(self.ctx, self.window(), ingredient).exec()

    def _movement(self, movement_type: str) -> None:
        if not self._require_unlock():
            return
        ingredient = self._selected_ingredient()
        if ingredient is None:
            InfoBar.warning(title="Sin selección",
                            content="Seleccione el insumo para el movimiento.",
                            parent=self, position=InfoBarPosition.TOP, duration=2500)
            return
        MovementDialog(self.ctx, ingredient, movement_type, self.window()).exec()

    def _delete_ingredient(self) -> None:
        if not self._require_unlock():
            return
        ingredient = self._selected_ingredient()
        if ingredient is None:
            return
        if confirm(self, "Eliminar insumo",
                   f"¿Eliminar «{ingredient['name']}»? Los productos que lo usan "
                   f"en su receta dejarán de descontarlo."):
            self.ctx.inventory.delete_ingredient(ingredient["id"])

    # ==================================================================
    # Movimientos
    # ==================================================================

    def _on_period(self, index: int) -> None:
        self._period_filter = ["all", "today", "week"][index]
        self._reload_movements()

    def _reload_movements(self) -> None:
        since = None
        if self._period_filter == "today":
            from datetime import date

            since = date.today().isoformat()
        elif self._period_filter == "week":
            from datetime import date, timedelta

            since = (date.today() - timedelta(days=7)).isoformat()

        movements = self.ctx.inventory.list_movements(limit=200, since=since)
        table = self._movements_table
        table.setRowCount(len(movements))

        type_labels = {"entrada": "Entrada", "salida": "Salida",
                       "venta": "Venta", "ajuste": "Ajuste"}
        for row, mov in enumerate(movements):
            qty = f"{mov['quantity']:+g} {mov['unit']}"
            values = [
                str(mov["datetime"]), mov["ingredient_name"],
                type_labels.get(mov["type"], mov["type"]), qty,
                f"{mov['stock_after']:g}", mov["note"] or "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if mov["type"] == "venta":
                    item.setForeground(QColor(0xE6, 0xA2, 0x3C))
                table.setItem(row, col, item)
