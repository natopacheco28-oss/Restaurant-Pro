"""Pruebas del gestor de configuración JSON."""
from __future__ import annotations

from app.core.settings import DEFAULT_SETTINGS, Settings


def test_defaults_are_available(tmp_path):
    settings = Settings(tmp_path / "config.json")
    assert settings.get("restaurant.name") == DEFAULT_SETTINGS["restaurant"]["name"]
    assert settings.get("ticket.currency") == "$"
    assert settings.get("ui.theme") == "auto"
    assert settings.get("no.existe.clave") is None


def test_set_and_persistence(tmp_path):
    path = tmp_path / "config.json"
    settings = Settings(path)
    settings.set("ticket.tax_rate", 8.0)
    settings.set("restaurant.name", "Mi Fonda")

    # Releer desde disco
    reloaded = Settings(path)
    assert reloaded.get("ticket.tax_rate") == 8.0
    assert reloaded.get("restaurant.name") == "Mi Fonda"


def test_unknown_keys_fall_back_to_defaults(tmp_path):
    """Configuraciones viejas se fusionan con los valores nuevos."""
    import json

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"restaurant": {"name": "Viejo"}}), encoding="utf-8")

    settings = Settings(path)
    assert settings.get("restaurant.name") == "Viejo"          # dato conservado
    assert settings.get("ticket.auto_print") is True            # default añadido
    assert settings.get("ui.accent") == DEFAULT_SETTINGS["ui"]["accent"]
