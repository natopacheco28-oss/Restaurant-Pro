"""Diálogos del inventario: insumos y movimientos (entrada/salida)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGridLayout, QLabel, QWidget

from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    SubtitleLabel,
)

from app.core.services.inventory_service import UNITS
from app.ui.common import currency_of


class IngredientDialog(MessageBoxBase):
    """Alta/edición de insumo.

    Al crear permite capturar el stock inicial (queda registrado como
    «entrada» en el historial). Al editar, el stock se modifica SOLO con
    movimientos para conservar la trazabilidad.
    """

    def __init__(self, ctx, parent: QWidget, ingredient: Optional[dict] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.ingredient = ingredient
        currency = currency_of(ctx.settings)

        self.viewLayout.addWidget(SubtitleLabel(
            "Editar insumo" if ingredient else "Nuevo insumo"
        ))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("Ej. Pan brioche, Carne 90/20…")
        if ingredient:
            self._name_edit.setText(ingredient["name"])
        form.addRow("Nombre:", self._name_edit)

        self._unit_combo = ComboBox()
        self._unit_combo.setEditable(True)
        for unit in UNITS:
            self._unit_combo.addItem(unit)
        self._unit_combo.setCurrentText(ingredient["unit"] if ingredient else "pza")
        form.addRow("Unidad:", self._unit_combo)

        self._min_edit = DoubleSpinBox()
        self._min_edit.setRange(0.0, 999999.0)
        self._min_edit.setDecimals(3)
        self._min_edit.setValue(float(ingredient["min_stock"]) if ingredient else 0.0)
        form.addRow("Stock mínimo:", self._min_edit)

        self._cost_edit = DoubleSpinBox()
        self._cost_edit.setRange(0.0, 999999.0)
        self._cost_edit.setDecimals(2)
        self._cost_edit.setPrefix(f"{currency} ")
        self._cost_edit.setValue(float(ingredient["cost"]) if ingredient else 0.0)
        form.addRow("Costo unitario:", self._cost_edit)

        # Stock: editable solo al crear
        self._stock_edit = DoubleSpinBox()
        self._stock_edit.setRange(0.0, 999999.0)
        self._stock_edit.setDecimals(3)
        if ingredient:
            self._stock_edit.setValue(float(ingredient["stock"]))
            self._stock_edit.setEnabled(False)
            self._stock_edit.setToolTip(
                "El stock se modifica con movimientos (Entrada/Salida) para "
                "conservar el historial.")
        form.addRow("Stock actual:", self._stock_edit)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Guardar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(380)

    @property
    def initial_stock(self) -> float:
        return 0.0 if self.ingredient else self._stock_edit.value()

    def validate(self) -> bool:
        try:
            name = self._name_edit.text()
            unit = self._unit_combo.currentText().strip() or "pza"
            if self.ingredient:
                self.ctx.inventory.update_ingredient(
                    self.ingredient["id"], name, unit,
                    self._min_edit.value(), self._cost_edit.value(),
                )
            else:
                self.ctx.inventory.add_ingredient(
                    name, unit, self.initial_stock,
                    self._min_edit.value(), self._cost_edit.value(),
                )
            return True
        except Exception as exc:
            InfoBar.error(title="Datos inválidos", content=str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
            return False


class MovementDialog(MessageBoxBase):
    """Entrada o salida manual de inventario."""

    def __init__(self, ctx, ingredient: dict, movement_type: str, parent: QWidget):
        super().__init__(parent)
        self.ctx = ctx
        self.ingredient = ingredient
        self.movement_type = movement_type  # 'entrada' | 'salida'

        title = "Entrada de insumo" if movement_type == "entrada" else "Salida de insumo"
        self.viewLayout.addWidget(SubtitleLabel(title))
        self.viewLayout.addWidget(CaptionLabel(
            f"«{ingredient['name']}» · Stock actual: "
            f"{ingredient['stock']:g} {ingredient['unit']}"
        ))

        grid = QGridLayout()
        grid.addWidget(QLabel("Cantidad:"), 0, 0)
        self._qty_edit = DoubleSpinBox()
        self._qty_edit.setRange(0.001, 999999.0)
        self._qty_edit.setDecimals(3)
        self._qty_edit.setValue(1.0)
        grid.addWidget(self._qty_edit, 0, 1)
        grid.addWidget(QLabel(ingredient["unit"]), 0, 2)
        grid.addWidget(QLabel("Nota:"), 1, 0)
        self._note_edit = LineEdit()
        self._note_edit.setPlaceholderText(
            "Ej. compra proveedor" if movement_type == "entrada" else "Ej. merma, consumo interno"
        )
        grid.addWidget(self._note_edit, 1, 1, 1, 2)
        self.viewLayout.addLayout(grid)

        self.yesButton.setText("Registrar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(400)

    def validate(self) -> bool:
        try:
            movement = self.ctx.inventory.register_movement(
                self.ingredient["id"], self.movement_type,
                self._qty_edit.value(), self._note_edit.text(),
            )
            if movement["is_low"]:
                InfoBar.warning(
                    title="Stock bajo",
                    content=f"«{movement['ingredient_name']}» quedó en o por debajo "
                            f"de su stock mínimo.",
                    parent=self.window(), position=InfoBarPosition.TOP, duration=5000,
                )
            return True
        except Exception as exc:
            InfoBar.error(title="Movimiento inválido", content=str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
            return False
