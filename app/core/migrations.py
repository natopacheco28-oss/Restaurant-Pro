"""Migraciones versionadas del esquema de la base de datos.

Cada versión del esquema vive en `MIGRATIONS[version]` y se aplica en orden
usando `PRAGMA user_version`, de modo que las actualizaciones nunca pierden
datos: un usuario con la v1 que instale la v2 solo ejecuta la migración 2.

Para añadir cambios en el futuro:
    1. Agregar la sentencia nueva a MIGRATIONS con la versión siguiente.
    2. NO modificar migraciones ya publicadas (deben quedar intactas).
"""
from __future__ import annotations

from typing import Callable

from app.core.database import Database

# --- Esquema inicial (v1) -------------------------------------------------
SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    sort        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    name        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    price       REAL    NOT NULL CHECK (price >= 0),
    image       TEXT,
    available   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS ingredients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    unit       TEXT    NOT NULL DEFAULT 'pza',
    stock      REAL    NOT NULL DEFAULT 0,
    min_stock  REAL    NOT NULL DEFAULT 0,
    cost       REAL    NOT NULL DEFAULT 0,
    updated_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Receta: insumos del inventario que consume cada producto
CREATE TABLE IF NOT EXISTS recipes (
    product_id    INTEGER NOT NULL REFERENCES products(id)    ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    quantity      REAL    NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (product_id, ingredient_id)
);

-- Sesiones de caja (apertura / corte)
CREATE TABLE IF NOT EXISTS cash_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    closed_at    TEXT,
    initial_fund REAL NOT NULL DEFAULT 0,
    counted      REAL,
    expected     REAL,
    difference   REAL,
    status       TEXT NOT NULL DEFAULT 'abierta',
    opened_by    TEXT,
    closed_by    TEXT,
    note         TEXT
);

-- Ventas (folio consecutivo por instalación)
CREATE TABLE IF NOT EXISTS sales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    folio           INTEGER NOT NULL UNIQUE,
    datetime        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    order_type      TEXT    NOT NULL,           -- mesa | llevar | domicilio
    payment_method  TEXT    NOT NULL,           -- efectivo | tarjeta | transferencia
    subtotal        REAL    NOT NULL,
    discount        REAL    NOT NULL DEFAULT 0,
    tax             REAL    NOT NULL DEFAULT 0,
    tip             REAL    NOT NULL DEFAULT 0,
    total           REAL    NOT NULL,
    paid            REAL    NOT NULL DEFAULT 0,
    change          REAL    NOT NULL DEFAULT 0,
    waiter          TEXT,
    customer        TEXT,
    cashier         TEXT,
    note            TEXT,
    cash_session_id INTEGER REFERENCES cash_sessions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS sale_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id      INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id   INTEGER REFERENCES products(id) ON DELETE SET NULL,
    product_name TEXT    NOT NULL,
    unit_price   REAL    NOT NULL,
    quantity     REAL    NOT NULL DEFAULT 1,
    note         TEXT,                        -- ej. "sin cebolla"
    line_total   REAL    NOT NULL
);

-- Historial de movimientos de inventario (entradas, salidas, ventas, ajustes)
CREATE TABLE IF NOT EXISTS movements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    datetime      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    type          TEXT    NOT NULL,           -- entrada | salida | venta | ajuste
    quantity      REAL    NOT NULL,           -- con signo (+ entra / − sale)
    stock_after   REAL    NOT NULL,           -- stock resultante (auditoría)
    unit_cost     REAL,
    note          TEXT,
    sale_id       INTEGER REFERENCES sales(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category  ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_sales_datetime     ON sales(datetime);
CREATE INDEX IF NOT EXISTS idx_sales_session      ON sales(cash_session_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_sale    ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_movements_ing      ON movements(ingredient_id);
CREATE INDEX IF NOT EXISTS idx_movements_datetime ON movements(datetime);
"""

# Cada migración: {versión: [sentencias SQL]} — solo añadir versiones nuevas
MIGRATIONS: dict[int, list[str]] = {
    1: [SCHEMA_V1],
}


def run_migrations(db: Database, log: Callable[[str], None] | None = None) -> int:
    """Aplica las migraciones pendientes y devuelve la versión final.

    Es idempotente: si la base ya está actualizada, no hace nada.

    Nota técnica: `executescript` de sqlite3 hace COMMIT implícito antes de
    ejecutar, por lo que la atomicidad se logra incluyendo BEGIN/COMMIT
    DENTRO del propio script (una transacción por versión de migración).
    """
    logger = log or (lambda msg: print(f"[migraciones] {msg}"))
    current = db.user_version()
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        logger(f"Aplicando migración v{version}…")
        script = (
            "BEGIN IMMEDIATE;\n"
            + "\n".join(MIGRATIONS[version])
            + f"\nPRAGMA user_version = {version};\n"
            + "COMMIT;"
        )
        try:
            db.execute_script(script)
        except Exception:
            # Si falla, la transacción queda abierta: revertir y propagar
            try:
                db.conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        logger(f"Migración v{version} aplicada.")
    return db.user_version()
