"""Diálogos del inventario: insumos y movimientos del kardex.

- `IngredientDialog`: alta/edición con stock mínimo, IDEAL de reposición,
  días de aviso de caducidad propios (0 = usa el global de Ajustes) y
  proveedor habitual. El stock se modifica SOLO con movimientos.
- `MovementDialog`: registro de movimientos del kardex:
    · entrada  → cantidad, costo, proveedor, LOTE y CADUCIDAD (opcional,
      validada: no anterior a hoy); crea el lote.
    · salida   → descuenta por PEPS/FEFO; motivo y usuario.
    · merma    → igual que salida, con motivo sugerido y obligatorio.
    · ajuste   → deja el stock exactamente en el valor capturado.
  El usuario por defecto es el usuario de Windows (sin sistema de sesiones).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,

    QWidget,
)

from app.ui.components.spinboxes import AppDoubleSpinBox
from qfluentwidgets import (
    CaptionLabel,
    EditableComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    SubtitleLabel,
)

from app.core.services.inventory_service import MERMA_REASONS, UNITS
from app.ui.common import currency_of

def getpass_user() -> str:
    """Usuario de Windows como autor por defecto del movimiento."""
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        return ""

def _make_date_picker():
    """CalendarPicker de qfluentwidgets (con respaldo QDateEdit)."""
    try:
        from qfluentwidgets import CalendarPicker

        return CalendarPicker()
    except ImportError:  # pragma: no cover
        from PySide6.QtWidgets import QDateEdit

        picker = QDateEdit()
        picker.setCalendarPopup(True)
        return picker

def picker_date(picker) -> Optional[date]:
    """Lee la fecha del picker; None si está vacío."""
    value = picker.getDate()
    if value is None or not value.isValid():
        return None
    return date(value.year(), value.month(), value.day())

def picker_set_date(picker, value: Optional[date]) -> None:
    if value is None:
        return
    picker.setDate(QDate(value.year, value.month, value.day))

class IngredientDialog(MessageBoxBase):
    """Alta/edición de insumo con mínimo, ideal, aviso de caducidad y proveedor."""

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

        # EditableComboBox permite escribir una unidad personalizada
        self._unit_combo = EditableComboBox()
        for unit in UNITS:
            self._unit_combo.addItem(unit)
        self._unit_combo.setText(ingredient["unit"] if ingredient else "pza")
        form.addRow("Unidad:", self._unit_combo)

        self._min_edit = AppDoubleSpinBox()
        self._min_edit.setRange(0.0, 999999.0)
        self._min_edit.setDecimals(3)
        self._min_edit.setValue(float(ingredient["min_stock"]) if ingredient else 0.0)
        form.addRow("Stock mínimo:", self._min_edit)

        self._ideal_edit = AppDoubleSpinBox()
        self._ideal_edit.setRange(0.0, 999999.0)
        self._ideal_edit.setDecimals(3)
        self._ideal_edit.setValue(
            float(ingredient["ideal_stock"] or 0) if ingredient else 0.0)
        self._ideal_edit.setToolTip("Stock ideal de reposición (0 = no se usa)")
        form.addRow("Stock ideal:", self._ideal_edit)

        self._warn_edit = AppDoubleSpinBox()
        self._warn_edit.setRange(0, 365)
        self._warn_edit.setDecimals(0)
        default_warn = int(ctx.settings.get("inventory.expiry_warning_days", 7) or 7)
        self._warn_edit.setValue(
            float(ingredient["warning_days"] or 0) if ingredient else 0.0)
        self._warn_edit.setToolTip(
            f"Días de aviso previo de caducidad para este insumo "
            f"(0 = usa el global: {default_warn} días)")
        form.addRow("Días de aviso:", self._warn_edit)

        self._cost_edit = AppDoubleSpinBox()
        self._cost_edit.setRange(0.0, 999999.0)
        self._cost_edit.setDecimals(2)
        self._cost_edit.setPrefix(f"{currency} ")
        self._cost_edit.setValue(float(ingredient["cost"]) if ingredient else 0.0)
        form.addRow("Costo unitario:", self._cost_edit)

        self._supplier_edit = LineEdit()
        self._supplier_edit.setPlaceholderText("Ej. Distribuidora del Centro")
        if ingredient and ingredient["supplier"]:
            self._supplier_edit.setText(ingredient["supplier"])
        form.addRow("Proveedor:", self._supplier_edit)

        # Stock: editable solo al crear (queda registrado como entrada)
        self._stock_edit = AppDoubleSpinBox()
        self._stock_edit.setRange(0.0, 999999.0)
        self._stock_edit.setDecimals(3)
        if ingredient:
            self._stock_edit.setValue(float(ingredient["stock"]))
            self._stock_edit.setEnabled(False)
            self._stock_edit.setToolTip(
                "El stock se modifica con movimientos (Entrada/Salida) para "
                "conservar el kardex.")
        form.addRow("Stock actual:", self._stock_edit)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Guardar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(400)

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
                    ideal_stock=self._ideal_edit.value(),
                    warning_days=int(self._warn_edit.value()),
                    supplier=self._supplier_edit.text().strip(),
                )
            else:
                self.ctx.inventory.add_ingredient(
                    name, unit, self.initial_stock,
                    self._min_edit.value(), self._cost_edit.value(),
                    ideal_stock=self._ideal_edit.value(),
                    warning_days=int(self._warn_edit.value()),
                    supplier=self._supplier_edit.text().strip(),
                )
            return True
        except Exception as exc:
            InfoBar.error(title="Datos inválidos", content=str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
            return False

class MovementDialog(MessageBoxBase):
    """Registro de movimientos del kardex (entrada/salida/merma/ajuste).

    Requiere el modo edición activo (la vista lo verifica antes de abrir).
    """

    def __init__(self, ctx, ingredient: dict, movement_type: str,
                 parent: QWidget, default_quantity: float = 1.0,
                 force_lot_id: Optional[int] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.ingredient = ingredient
        self.movement_type = movement_type  # entrada | salida | merma | ajuste
        self.force_lot_id = force_lot_id    # salida/merma de un lote concreto
        currency = currency_of(ctx.settings)

        titles = {
            "entrada": "Entrada de insumo",
            "salida": "Salida de insumo",
            "merma": "Merma / desperdicio",
            "ajuste": "Ajuste de inventario",
        }
        self.viewLayout.addWidget(SubtitleLabel(titles.get(movement_type, movement_type)))

        lot_hint = f" · Lote {force_lot_id}" if force_lot_id else ""
        self.viewLayout.addWidget(CaptionLabel(
            f"«{ingredient['name']}» · Stock actual: "
            f"{ingredient['stock']:g} {ingredient['unit']}{lot_hint}"
        ))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        if movement_type == "ajuste":
            form.addWidget(CaptionLabel("Dejar el stock exactamente en:"))
        else:
            form.addWidget(CaptionLabel("Cantidad:"))
        self._qty_edit = AppDoubleSpinBox()
        self._qty_edit.setRange(0.001, 999999.0)
        self._qty_edit.setDecimals(3)
        self._qty_edit.setValue(default_quantity)
        if movement_type == "salida":
            self._qty_edit.setMaximum(max(float(ingredient["stock"]), 0.001))
        form.addRow(self._qty_edit)
        form.addWidget(CaptionLabel(ingredient["unit"]))

        if movement_type == "entrada":
            self._cost_edit = AppDoubleSpinBox()
            self._cost_edit.setRange(0.0, 999999.0)
            self._cost_edit.setDecimals(2)
            self._cost_edit.setPrefix(f"{currency} ")
            self._cost_edit.setValue(float(ingredient["cost"] or 0))
            form.addRow("Costo unitario:", self._cost_edit)

            self._supplier_edit = LineEdit()
            self._supplier_edit.setPlaceholderText("Ej. Distribuidora del Centro")
            if ingredient.get("supplier"):
                self._supplier_edit.setText(ingredient["supplier"])
            form.addRow("Proveedor:", self._supplier_edit)

            self._lot_edit = LineEdit()
            self._lot_edit.setPlaceholderText("Automático si se deja vacío")
            form.addRow("Lote:", self._lot_edit)

            self._expiry_check = QCheckBox("Este lote lleva fecha de caducidad")
            form.addRow(self._expiry_check)
            self._expiry_picker = _make_date_picker()
            row = QGridLayout()
            row.addWidget(self._expiry_picker, 0, 0)
            row.addWidget(CaptionLabel("no puede ser anterior a hoy"), 0, 1)
            form.addRow(row)
            self._expiry_check.toggled.connect(self._expiry_picker.setVisible)
            self._expiry_picker.setVisible(False)

        if movement_type in ("salida", "merma", "ajuste"):
            if movement_type == "merma":
                self._reason_combo = EditableComboBox()
                for reason in MERMA_REASONS:
                    self._reason_combo.addItem(reason)
                self._reason_combo.setText(MERMA_REASONS[0])
                form.addRow("Motivo:", self._reason_combo)
            else:
                self._reason_combo = EditableComboBox()
                for reason in ("Consumo interno", "Promoción", "Cortesía",
                               "Corrección de conteo", "Otro"):
                    self._reason_combo.addItem(reason)
                form.addRow("Motivo:", self._reason_combo)

        self._user_edit = LineEdit()
        self._user_edit.setText(getpass_user())
        form.addRow("Usuario:", self._user_edit)

        self._note_edit = LineEdit()
        self._note_edit.setPlaceholderText(
            "Nota libre (opcional)"
            if movement_type != "entrada"
            else "Nota (ej. compra proveedor)")
        form.addRow("Nota:", self._note_edit)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Registrar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(420)

    def validate(self) -> bool:
        try:
            expiration = None
            if self.movement_type == "entrada" and self._expiry_check.isChecked():
                picked = picker_date(self._expiry_picker)
                if picked is None:
                    InfoBar.error(title="Falta la caducidad",
                                  content="Active la casilla solo si va a "
                                          "capturar la fecha.",
                                  parent=self, position=InfoBarPosition.TOP,
                                  duration=4000)
                    return False
                expiration = picked.isoformat()

            reason = ""
            if hasattr(self, "_reason_combo"):
                reason = self._reason_combo.currentText().strip()
                if self.movement_type == "merma" and not reason:
                    InfoBar.error(title="Falta el motivo",
                                  content="Indique el motivo de la merma.",
                                  parent=self, position=InfoBarPosition.TOP,
                                  duration=4000)
                    return False

            movement = self.ctx.inventory.register_movement(
                self.ingredient["id"],
                self.movement_type,
                self._qty_edit.value(),
                note=self._note_edit.text().strip(),
                supplier=self._supplier_edit.text().strip()
                if self.movement_type == "entrada" else "",
                user=self._user_edit.text().strip(),
                reason=reason,
                expiration=expiration,
                lot_number=self._lot_edit.text().strip()
                if self.movement_type == "entrada" else "",
                force_lot_id=self.force_lot_id,
            )
            if movement["is_low"]:
                InfoBar.warning(
                    title="Stock bajo",
                    content=f"«{movement['ingredient_name']}» quedó en o por "
                            f"debajo de su stock mínimo.",
                    parent=self.window(), position=InfoBarPosition.TOP,
                    duration=5000,
                )
            return True
        except Exception as exc:
            InfoBar.error(title="Movimiento inválido", content=str(exc),
                          parent=self, position=InfoBarPosition.TOP, duration=4500)
            return False
