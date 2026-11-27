"""Diálogos del catálogo: categorías y productos (con receta e imagen).

El editor de productos permite:
- Nombre, precio, categoría, disponibilidad e imagen opcional (se copia a
  `data/imgs` para mantener el sistema portable).
- Receta opcional: insumos del inventario + cantidad que consume cada venta.
Las validaciones las aplica `CatalogService` (nombre no vacío, precio ≥ 0,
sin duplicados) y los errores se muestran sin cerrar el diálogo.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PushButton,
    SubtitleLabel,
    SwitchButton,
)

from app.core.paths import images_dir, portable_path
from app.ui.common import currency_of, fi


class CategoryDialog(MessageBoxBase):
    """Alta/edición de categoría."""

    def __init__(self, ctx, parent: QWidget, category: Optional[dict] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.category = category

        self.viewLayout.addWidget(SubtitleLabel(
            "Editar categoría" if category else "Nueva categoría"
        ))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("Ej. Bebidas, Entradas, Postres…")
        if category:
            self._name_edit.setText(category["name"])
        form.addRow("Nombre:", self._name_edit)
        self._sort_edit = DoubleSpinBox()
        self._sort_edit.setRange(0, 999)
        self._sort_edit.setDecimals(0)
        self._sort_edit.setValue(float(category["sort"]) if category else 0.0)
        form.addRow("Orden:", self._sort_edit)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Guardar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(360)

    def validate(self) -> bool:
        try:
            if self.category:
                self.ctx.catalog.update_category(
                    self.category["id"], self._name_edit.text(),
                    int(self._sort_edit.value()),
                )
            else:
                self.ctx.catalog.add_category(
                    self._name_edit.text(), int(self._sort_edit.value())
                )
            return True
        except Exception as exc:  # ValidationError de la capa de servicios
            InfoBar.error(title="Datos inválidos", content=str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4000)
            return False


class ProductDialog(MessageBoxBase):
    """Alta/edición de producto con imagen y receta opcional."""

    def __init__(self, ctx, parent: QWidget, product: Optional[dict] = None,
                 default_category: Optional[int] = None):
        super().__init__(parent)
        self.ctx = ctx
        self.product = product
        self._image_path: Optional[str] = None  # ruta portable ya copiada
        self._picked_source: Optional[Path] = None

        currency = currency_of(ctx.settings)
        self.viewLayout.addWidget(SubtitleLabel(
            "Editar producto" if product else "Nuevo producto"
        ))

        # ---------------- Datos básicos ----------------
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("Ej. Hamburguesa clásica")
        if product:
            self._name_edit.setText(product["name"])
        form.addRow("Nombre:", self._name_edit)

        self._price_edit = DoubleSpinBox()
        self._price_edit.setRange(0.0, 999999.0)
        self._price_edit.setDecimals(2)
        self._price_edit.setPrefix(f"{currency} ")
        if product:
            self._price_edit.setValue(float(product["price"]))
        form.addRow("Precio:", self._price_edit)

        self._category_combo = ComboBox()
        self._categories = ctx.catalog.list_categories()
        self._category_combo.addItem("Sin categoría", userData=None)
        for cat in self._categories:
            self._category_combo.addItem(cat["name"], userData=cat["id"])
        if product:
            index = self._category_combo.findData(product["category_id"])
            self._category_combo.setCurrentIndex(max(index, 0))
        elif default_category is not None:
            index = self._category_combo.findData(default_category)
            self._category_combo.setCurrentIndex(max(index, 0))
        form.addRow("Categoría:", self._category_combo)

        self._available_switch = SwitchButton()
        self._available_switch.setChecked(bool(product["available"]) if product else True)
        form.addRow("Disponible:", self._available_switch)
        self.viewLayout.addLayout(form)

        # ---------------- Imagen ----------------
        image_row = QHBoxLayout()
        self._image_label = QLabel()
        self._image_label.setFixedSize(72, 72)
        self._image_label.setStyleSheet(
            "border: 1px dashed #98989d; border-radius: 8px;"
            "background: transparent;")

        buttons_box = QVBoxLayout()
        pick = PushButton("Elegir imagen…")
        pick.setIcon(fi("PHOTO", "IMAGE", "FOLDER"))
        pick.clicked.connect(self._pick_image)
        clear = PushButton("Quitar imagen")
        clear.clicked.connect(self._clear_image)
        buttons_box.addWidget(pick)
        buttons_box.addWidget(clear)
        buttons_box.addStretch(1)
        image_row.addWidget(self._image_label)
        image_row.addSpacing(12)
        image_row.addLayout(buttons_box, 1)
        self.viewLayout.addLayout(image_row)

        # ---------------- Receta ----------------
        heading = BodyLabel("Receta (insumos que consume cada unidad vendida)")
        heading.setFont(heading.font())
        heading.setStyleSheet("font-weight: 600;")
        self.viewLayout.addWidget(heading)

        self._recipe_list = QListWidget()
        self._recipe_list.setFixedHeight(110)
        self.viewLayout.addWidget(self._recipe_list)

        add_row = QHBoxLayout()
        self._ingredient_combo = ComboBox()
        self._load_ingredients()
        self._qty_edit = DoubleSpinBox()
        self._qty_edit.setRange(0.001, 99999.0)
        self._qty_edit.setDecimals(3)
        self._qty_edit.setValue(1.0)
        add_button = PushButton("Agregar insumo")
        add_button.setIcon(fi("ADD"))
        add_button.clicked.connect(self._add_recipe_row)
        add_row.addWidget(self._ingredient_combo, 2)
        add_row.addWidget(self._qty_edit, 1)
        add_row.addWidget(add_button)
        self.viewLayout.addLayout(add_row)

        self.yesButton.setText("Guardar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(520)

        # Cargar imagen y receta existentes
        if product:
            self._image_path = product["image"] or None
            self._refresh_image_preview()
            self._load_recipe(product["id"])

    # ------------------------------------------------------------------
    # Imagen
    # ------------------------------------------------------------------

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir imagen del producto", "",
            "Imágenes (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        # Se copia a data/imgs con nombre único (portable)
        images_dir().mkdir(parents=True, exist_ok=True)
        suffix = Path(path).suffix.lower() or ".png"
        dest = images_dir() / f"prod_{uuid.uuid4().hex[:10]}{suffix}"
        try:
            shutil.copy2(path, dest)
        except OSError as exc:
            InfoBar.error(title="No se pudo copiar la imagen", content=str(exc),
                          parent=self, position=InfoBarPosition.TOP, duration=4000)
            return
        self._picked_source = dest
        self._image_path = portable_path(dest)
        self._refresh_image_preview()

    def _clear_image(self) -> None:
        self._picked_source = None
        self._image_path = None
        self._refresh_image_preview()

    def _refresh_image_preview(self) -> None:
        if not self._image_path:
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("Sin imagen")
            return
        from app.core.paths import resolve_portable

        pixmap = QPixmap(str(resolve_portable(self._image_path)))
        if pixmap.isNull():
            self._image_label.setText("Sin imagen")
            return
        self._image_label.setPixmap(pixmap.scaled(
            72, 72, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    # ------------------------------------------------------------------
    # Receta
    # ------------------------------------------------------------------

    def _load_ingredients(self) -> None:
        self._ingredients = self.ctx.inventory.list_ingredients()
        self._ingredient_combo.clear()
        for ing in self._ingredients:
            self._ingredient_combo.addItem(
                f"{ing['name']} ({ing['unit']}) — stock {ing['stock']:g}",
                userData=ing["id"],
            )

    def _load_recipe(self, product_id: int) -> None:
        for row in self.ctx.catalog.get_recipe(product_id):
            self._add_recipe_row(row["ingredient_id"], row["quantity"])

    def _add_recipe_row(self, ingredient_id: Optional[int] = None,
                        quantity: float = 1.0) -> None:
        ingredient_id = ingredient_id or self._ingredient_combo.currentData()
        if ingredient_id is None:
            InfoBar.warning(title="Sin insumos",
                            content="Primero cree insumos en el módulo Inventario.",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        ing = next((i for i in self._ingredients if i["id"] == ingredient_id), None)
        if ing is None:
            return
        item = QListWidgetItem(f"{quantity:g} × {ing['name']} ({ing['unit']})")
        item.setData(Qt.ItemDataRole.UserRole, ingredient_id)
        item.setData(Qt.ItemDataRole.UserRole + 1, quantity)
        self._recipe_list.addItem(item)

    def _collect_recipe(self) -> list[tuple[int, float]]:
        rows = []
        for index in range(self._recipe_list.count()):
            item = self._recipe_list.item(index)
            rows.append((item.data(Qt.ItemDataRole.UserRole),
                         float(item.data(Qt.ItemDataRole.UserRole + 1))))
        return rows

    # ------------------------------------------------------------------
    # Guardado
    # ------------------------------------------------------------------

    def validate(self) -> bool:
        try:
            category_id = self._category_combo.currentData()
            if self.product:
                self.ctx.catalog.update_product(
                    self.product["id"],
                    name=self._name_edit.text(),
                    price=self._price_edit.value(),
                    category_id=category_id,
                    image=self._image_path,
                    available=self._available_switch.isChecked(),
                )
                product_id = self.product["id"]
            else:
                product_id = self.ctx.catalog.add_product(
                    name=self._name_edit.text(),
                    price=self._price_edit.value(),
                    category_id=category_id,
                    image=self._image_path or "",
                    available=self._available_switch.isChecked(),
                )
            self.ctx.catalog.set_recipe(product_id, self._collect_recipe())
            return True
        except Exception as exc:
            InfoBar.error(title="Datos inválidos", content=str(exc), parent=self,
                          position=InfoBarPosition.TOP, duration=4500)
            return False
