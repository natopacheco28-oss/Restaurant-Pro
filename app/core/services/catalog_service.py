"""Servicio del CATÁLOGO: categorías, productos y recetas.

Reglas:
- Nombre obligatorio y sin duplicados (comparación sin distinguir mayúsculas).
- Precio numérico ≥ 0.
- Receta opcional: insumos del inventario que consume cada producto.
- Toda operación emite señales para que las tablas se actualicen sin reiniciar.
"""
from __future__ import annotations

from typing import Optional

from app.core.database import Database
from app.core.services.validators import ValidationError
from app.signals import SignalBus


class CatalogService:
    """CRUD de categorías, productos y recetas."""

    def __init__(self, db: Database, bus: SignalBus):
        self.db = db
        self.bus = bus

    # ==================================================================
    # Categorías
    # ==================================================================

    def list_categories(self) -> list[dict]:
        """Categorías ordenadas por `sort` y nombre."""
        return self.db.query(
            """
            SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id)
                       AS product_count
            FROM categories c
            ORDER BY c.sort, c.name
            """
        )

    def get_category(self, category_id: int) -> Optional[dict]:
        return self.db.one("SELECT * FROM categories WHERE id = ?", (category_id,))

    def add_category(self, name: str, sort: int = 0) -> int:
        name = self._clean_name(name)
        self._ensure_category_name_free(name)
        row_id = self.db.execute(
            "INSERT INTO categories (name, sort) VALUES (?, ?)", (name, sort)
        )
        self.bus.categoriesChanged.emit()
        return row_id

    def update_category(self, category_id: int, name: str, sort: int = 0) -> None:
        name = self._clean_name(name)
        self._ensure_category_name_free(name, exclude_id=category_id)
        self.db.execute(
            "UPDATE categories SET name = ?, sort = ? WHERE id = ?",
            (name, sort, category_id),
        )
        self.bus.categoriesChanged.emit()

    def delete_category(self, category_id: int) -> None:
        """Elimina la categoría; sus productos quedan sin categoría (FK SET NULL)."""
        self.db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        self.bus.categoriesChanged.emit()
        self.bus.productsChanged.emit()

    def _ensure_category_name_free(self, name: str, exclude_id: int = 0) -> None:
        dup = self.db.one(
            "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND id != ?",
            (name, exclude_id),
        )
        if dup:
            raise ValidationError(f"Ya existe una categoría llamada «{name}».")

    # ==================================================================
    # Productos
    # ==================================================================

    def list_products(
        self,
        search: str = "",
        category_id: Optional[int] = None,
        only_available: bool = False,
    ) -> list[dict]:
        """Productos con su categoría, con filtros opcionales."""
        sql = """
            SELECT p.*, c.name AS category_name,
                   (SELECT COUNT(*) FROM recipes r
                     WHERE r.product_id = p.id) AS recipe_count
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE 1 = 1
        """
        params: list = []
        if search:
            sql += " AND p.name LIKE ?"
            params.append(f"%{search}%")
        if category_id is not None:
            sql += " AND p.category_id = ?"
            params.append(category_id)
        if only_available:
            sql += " AND p.available = 1"
        sql += " ORDER BY p.name COLLATE NOCASE"
        return self.db.query(sql, tuple(params))

    def get_product(self, product_id: int) -> Optional[dict]:
        return self.db.one("SELECT * FROM products WHERE id = ?", (product_id,))

    def add_product(
        self,
        name: str,
        price: float,
        category_id: Optional[int] = None,
        image: str = "",
        available: bool = True,
    ) -> int:
        name = self._clean_name(name)
        self._ensure_product_name_free(name)
        self._ensure_price(price)
        row_id = self.db.execute(
            """
            INSERT INTO products (name, price, category_id, image, available)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, round(float(price), 2), category_id, image, 1 if available else 0),
        )
        self.bus.productsChanged.emit()
        return row_id

    def update_product(
        self,
        product_id: int,
        name: str,
        price: float,
        category_id: Optional[int] = None,
        image: Optional[str] = None,
        available: Optional[bool] = None,
    ) -> None:
        name = self._clean_name(name)
        self._ensure_product_name_free(name, exclude_id=product_id)
        self._ensure_price(price)

        current = self.get_product(product_id)
        if current is None:
            raise ValidationError("El producto no existe.")
        if image is None:
            image = current["image"]
        if available is None:
            available = bool(current["available"])

        self.db.execute(
            """
            UPDATE products
               SET name = ?, price = ?, category_id = ?, image = ?, available = ?,
                   updated_at = datetime('now', 'localtime')
             WHERE id = ?
            """,
            (
                name,
                round(float(price), 2),
                category_id,
                image,
                1 if available else 0,
                product_id,
            ),
        )
        self.bus.productsChanged.emit()

    def set_product_available(self, product_id: int, available: bool) -> None:
        self.db.execute(
            "UPDATE products SET available = ?, updated_at = datetime('now','localtime')"
            " WHERE id = ?",
            (1 if available else 0, product_id),
        )
        self.bus.productsChanged.emit()

    def delete_product(self, product_id: int) -> None:
        """Elimina el producto y su receta (FK CASCADE)."""
        self.db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        self.bus.productsChanged.emit()

    # ==================================================================
    # Receta (insumos por producto)
    # ==================================================================

    def get_recipe(self, product_id: int) -> list[dict]:
        """Insumos de la receta con nombre y unidad para mostrar en UI."""
        return self.db.query(
            """
            SELECT r.ingredient_id, r.quantity, i.name AS ingredient_name,
                   i.unit, i.stock
              FROM recipes r
              JOIN ingredients i ON i.id = r.ingredient_id
             WHERE r.product_id = ?
             ORDER BY i.name
            """,
            (product_id,),
        )

    def set_recipe(self, product_id: int, items: list[tuple[int, float]]) -> None:
        """Reemplaza la receta completa: [(ingredient_id, cantidad), …]."""
        seen: set[int] = set()
        rows: list[tuple] = []
        for ingredient_id, quantity in items:
            if ingredient_id in seen:
                continue
            quantity = float(quantity)
            if quantity <= 0:
                raise ValidationError("La cantidad de cada insumo debe ser mayor a 0.")
            seen.add(ingredient_id)
            rows.append((product_id, ingredient_id, round(quantity, 4)))

        with self.db.transaction():
            self.db.execute("DELETE FROM recipes WHERE product_id = ?", (product_id,))
            for row in rows:
                self.db.execute(
                    "INSERT INTO recipes (product_id, ingredient_id, quantity)"
                    " VALUES (?, ?, ?)",
                    row,
                )
        self.bus.productsChanged.emit()

    # ==================================================================
    # Validaciones
    # ==================================================================

    @staticmethod
    def _clean_name(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValidationError("El nombre no puede estar vacío.")
        return name

    @staticmethod
    def _ensure_price(price: float) -> None:
        try:
            value = float(price)
        except (TypeError, ValueError) as exc:
            raise ValidationError("El precio debe ser un número.") from exc
        if value < 0:
            raise ValidationError("El precio no puede ser negativo.")

    def _ensure_product_name_free(self, name: str, exclude_id: int = 0) -> None:
        dup = self.db.one(
            "SELECT id FROM products WHERE name = ? COLLATE NOCASE AND id != ?",
            (name, exclude_id),
        )
        if dup:
            raise ValidationError(f"Ya existe un producto llamado «{name}».")
