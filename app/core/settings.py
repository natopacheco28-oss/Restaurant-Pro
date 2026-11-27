"""Gestor de configuración de Restaurante Pro (JSON portable).

Guarda los datos del restaurante, preferencias del ticket, apariencia y
rutas de respaldo en `data/config.json`, junto al ejecutable. Los valores
nuevos que aparezcan en actualizaciones se fusionan con los predeterminados,
de modo que la configuración nunca se rompe al actualizar.
"""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

# Valores predeterminados: se usan si la clave no existe en el JSON
DEFAULT_SETTINGS: dict[str, Any] = {
    "restaurant": {
        "name": "Restaurante Pro",
        "slogan": "¡Cocina hecha con amor!",
        "phone": "",
        "address": "",
        "tax_id": "",          # RFC o dato fiscal
        "social": "",          # Redes sociales
        "logo_path": "",       # ruta portable del logo personalizado
    },
    "ticket": {
        "currency": "$",
        "tax_rate": 16.0,        # % de impuesto aplicado al subtotal
        "tip_suggested": 10.0,   # % de propina sugerida al cobrar
        "footer": "¡Gracias por su preferencia! Vuelva pronto.",
        "policies": "",
        "width_chars": 48,       # 32 → papel 58 mm · 48 → papel 80 mm
        "printer_name": "",      # impresora instalada de Windows
        "print_method": "auto",  # auto | raw (ESC/POS) | qprinter
        "show_logo": True,
        "auto_cut": True,        # corte de papel
        "open_drawer": False,    # apertura de cajón monetario
        "auto_print": True,      # imprimir ticket automáticamente al cobrar
    },
    "ui": {
        "theme": "auto",         # auto | light | dark
        "accent": "#ff7a1a",     # color de acento (naranja del logo)
    },
    "paths": {
        "backup_dir": "",        # carpeta de respaldos configurable
    },
    "pos": {
        "default_order_type": "mesa",
    },
    # Almacén: caducidades, estancados y notificaciones
    "inventory": {
        "expiry_warning_days": 7,     # días de aviso previo por defecto
        "stale_days": 30,             # días sin salidas = "sin movimiento"
        "alert_interval_min": 30,     # frecuencia de revisión de alertas
        "notify_low": True,           # notificar stock bajo / agotado
        "notify_expiry": True,        # notificar por caducar / vencidos
        "notify_stale": True,         # notificar insumos sin movimiento
        "system_notifications": False,  # bandeja de Windows si está minimizado
    },
}


def _deep_merge(base: dict, extra: dict) -> dict:
    """Fusiona `extra` sobre `base` sin perder claves faltantes."""
    result = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    """Acceso a la configuración con claves punteadas: `ticket.tax_rate`."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULT_SETTINGS)
        self.load()

    # ------------------------------------------------------------------
    # Carga / guardado
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Carga el JSON y lo fusiona con los valores predeterminados."""
        with self._lock:
            if self.path.exists():
                try:
                    with open(self.path, encoding="utf-8") as fh:
                        stored = json.load(fh)
                    self._data = _deep_merge(DEFAULT_SETTINGS, stored)
                except (OSError, json.JSONDecodeError):
                    # Archivo dañado: se conservan los valores por defecto
                    self._data = copy.deepcopy(DEFAULT_SETTINGS)
            else:
                self._data = copy.deepcopy(DEFAULT_SETTINGS)

    def save(self) -> None:
        """Guarda de forma atómica (escritura temporal + reemplazo)."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            tmp.replace(self.path)

    # ------------------------------------------------------------------
    # Acceso
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Obtiene un valor con clave punteada, ej. `ticket.tax_rate`."""
        with self._lock:
            node: Any = self._data
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    def set(self, key: str, value: Any, save: bool = True) -> None:
        """Asigna un valor (y persiste salvo que `save=False`)."""
        with self._lock:
            node = self._data
            parts = key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
        if save:
            self.save()

    def update(self, values: dict[str, Any]) -> None:
        """Asigna varios valores punteados y guarda una sola vez."""
        for key, value in values.items():
            self.set(key, value, save=False)
        self.save()

    def as_dict(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)
