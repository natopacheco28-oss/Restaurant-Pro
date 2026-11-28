"""Diálogos de las listas de compras.

- `ShoppingItemDialog`: agrega/edita un renglón (insumo existente o libre)
  con cantidad, unidad, costo estimado y proveedor.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QWidget

from app.ui.components.spinboxes import AppDoubleSpinBox
from qfluentwidgets import (
    ComboBox,
    EditableComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    SubtitleLabel,
)

from app.core.services.inventory_service import UNITS
from app.ui.common import currency_of


class ShoppingItemDialog(MessageBoxBase):
    """Alta/edición de un renglón de la lista de compras."""

    def __init__(self, ctx, parent: QWidget, item: Optional[dict] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.item = item  # renglón existente (edición) o None (nuevo)

        self.viewLayout.addWidget(SubtitleLabel(
            "Editar renglón" if item else "Agregar renglón"
        ))

        # Insumo existente (para que la conversión a entradas funcione)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ingredient_combo = ComboBox()
        self._ingredients = ctx.inventory.list_ingredients()
        self._ingredient_combo.addItem("— Insumo libre (sin ligar) —", userData=None)
        for ing in self._ingredients:
            self._ingredient_combo.addItem(
                f"{ing['name']} ({ing['unit']})", userData=ing["id"])
        if item and item["ingredient_id"]:
            index = self._ingredient_combo.findData(item["ingredient_id"])
            self._ingredient_combo.setCurrentIndex(max(index, 0))
        form.addRow("Insumo:", self._ingredient_combo)

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("Nombre del renglón libre o del insumo")
        if item:
            self._name_edit.setText(item["name"])
        form.addRow("Nombre:", self._name_edit)

        self._qty_edit = AppDoubleSpinBox()
        self._qty_edit.setRange(0.001, 999999.0)
        self._qty_edit.setDecimals(3)
        self._qty_edit.setValue(float(item["quantity"]) if item else 1.0)
        form.addRow("Cantidad:", self._qty_edit)

        # EditableComboBox permite escribir una unidad personalizada
        self._unit_combo = EditableComboBox()
        for unit in UNITS:
            self._unit_combo.addItem(unit)
        self._unit_combo.setText(item["unit"] if item else "pza")
        form.addRow("Unidad:", self._unit_combo)

        currency = currency_of(ctx.settings)
        self._cost_edit = AppDoubleSpinBox()
        self._cost_edit.setRange(0.0, 999999.0)
        self._cost_edit.setDecimals(2)
        self._cost_edit.setPrefix(f"{currency} ")
        self._cost_edit.setToolTip("Costo estimado TOTAL del renglón")
        self._cost_edit.setValue(float(item["estimated_cost"]) if item else 0.0)
        form.addRow("Costo estimado:", self._cost_edit)

        self._supplier_edit = LineEdit()
        self._supplier_edit.setPlaceholderText("Opcional — agrupa la lista")
        if item and item["supplier"]:
            self._supplier_edit.setText(item["supplier"])
        form.addRow("Proveedor:", self._supplier_edit)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Guardar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(400)

        # Autocompletar nombre y unidad al elegir insumo
        self._ingredient_combo.currentIndexChanged.connect(self._autofill)

    def _autofill(self, index: int) -> None:
        data = self._ingredient_combo.itemData(index)
        if not data:
            return
        ing = next((i for i in self._ingredients if i["id"] == data), None)
        if ing is None:
            return
        if not self._name_edit.text().strip():
            self._name_edit.setText(ing["name"])
        self._unit_combo.setText(ing["unit"])

    def result_item(self) -> dict:
        """Renglón resultante (llamar tras accept())."""
        ingredient_id = self._ingredient_combo.currentData()
        name = self._name_edit.text().strip()
        if not name and ingredient_id:
            ing = next((i for i in self._ingredients if i["id"] == ingredient_id), None)
            name = ing["name"] if ing else ""
        return {
            "ingredient_id": ingredient_id,
            "name": name,
            "quantity": self._qty_edit.value(),
            "unit": self._unit_combo.currentText().strip() or "pza",
            "estimated_cost": self._cost_edit.value(),
            "supplier": self._supplier_edit.text().strip(),
            "checked": bool(item_checked(self.item)),
        }


def item_checked(item: Optional[dict]) -> int:
    return int(item["checked"]) if item and item.get("checked") is not None else 1


def warn_invalid(parent, message: str) -> None:
    InfoBar.error(title="Datos inválidos", content=message, parent=parent,
                  position=InfoBarPosition.TOP, duration=4000)
