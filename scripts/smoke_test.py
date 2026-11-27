"""Prueba de humo de importación para CI.

Importa todos los módulos de la aplicación (UI incluida) para detectar
errores de importación, nombres inválidos o dependencias faltantes antes de
llegar a Windows. Se ejecuta con QT_QPA_PLATFORM=offscreen.
"""
import importlib
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Asegurar que la raíz del proyecto esté en sys.path (el script vive en scripts/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODULES = [
    "app.version",
    "app.signals",
    "app.context",
    "app.core.paths",
    "app.core.settings",
    "app.core.database",
    "app.core.migrations",
    "app.core.security",
    "app.core.backup",
    "app.core.services",
    "app.printing.ticket_builder",
    "app.printing.escpos",
    "app.printing.printer",
    "app.ui.common",
    "app.ui.splash",
    "app.ui.first_run",
    "app.ui.main_window",
    "app.ui.dialogs.security_dialogs",
    "app.ui.dialogs.payment_dialog",
    "app.ui.dialogs.cash_dialogs",
    "app.ui.dialogs.ticket_dialogs",
    "app.ui.dialogs.catalog_dialogs",
    "app.ui.dialogs.inventory_dialogs",
    "app.ui.modules.pos_module",
    "app.ui.modules.catalog_module",
    "app.ui.modules.inventory_module",
    "app.ui.modules.stats_module",
    "app.ui.modules.settings_module",
    "app.application",
    "main",
]


def main() -> int:
    failures = []
    for module in MODULES:
        try:
            importlib.import_module(module)
            print(f"OK      {module}")
        except Exception as exc:
            failures.append((module, exc))
            print(f"FALLO   {module}: {type(exc).__name__}: {exc}")

    if failures:
        print(f"\n{len(failures)} módulo(s) con errores")
        return 1
    print("\nTodos los módulos importan correctamente ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
