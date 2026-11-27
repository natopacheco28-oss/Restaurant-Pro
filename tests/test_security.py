"""Pruebas de seguridad: hash, desbloqueo y retraso progresivo."""
from __future__ import annotations

from app.core.security import (
    SecurityManager,
    hash_password,
    verify_password,
)

FAST_ITERATIONS = 1000  # para que las pruebas corran rápido


def test_hash_roundtrip():
    encoded = hash_password("mi-clave-segura", iterations=FAST_ITERATIONS)
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("mi-clave-segura", encoded)
    assert not verify_password("otra-clave", encoded)
    # La clave jamás aparece en el hash almacenado
    assert "mi-clave-segura" not in encoded


def test_hash_uses_random_salt():
    a = hash_password("clave", iterations=FAST_ITERATIONS)
    b = hash_password("clave", iterations=FAST_ITERATIONS)
    assert a != b  # sal aleatoria distinta en cada hash


def test_first_run_and_unlock(tmp_path):
    manager = SecurityManager(tmp_path / "sec.json", iterations=FAST_ITERATIONS)
    assert not manager.is_configured()

    manager.configure("clave123")
    assert manager.is_configured()

    assert not manager.is_unlocked
    result = manager.unlock("clave123")
    assert result.ok
    assert manager.is_unlocked

    # Bloqueo manual
    manager.lock()
    assert not manager.is_unlocked


def test_progressive_delay_on_failures(tmp_path):
    manager = SecurityManager(tmp_path / "sec.json", iterations=FAST_ITERATIONS)
    manager.configure("clave-correcta")

    first = manager.unlock("mala")
    assert not first.ok
    manager._fails.lock_until = 0  # simular que se esperó el retraso

    second = manager.unlock("mala2")
    assert not second.ok
    # El retraso crece con cada fallo (1s, 2s, 4s…)
    assert second.wait_seconds > first.wait_seconds

    manager._fails.lock_until = 0
    third = manager.unlock("mala3")
    assert not third.ok
    assert third.wait_seconds > second.wait_seconds

    # Mientras el retraso esté activo, ni la clave correcta pasa
    blocked = manager.unlock("clave-correcta")
    assert not blocked.ok
    assert blocked.wait_seconds > 0

    # Al acertar tras el bloqueo se resetea el contador
    manager._fails.lock_until = 0  # simular espera completada
    ok = manager.unlock("clave-correcta")
    assert ok.ok
    assert manager.failed_attempts == 0


def test_change_password(tmp_path):
    manager = SecurityManager(tmp_path / "sec.json", iterations=FAST_ITERATIONS)
    manager.configure("vieja123")

    # Clave actual incorrecta
    result = manager.change_password("incorrecta", "nueva123", "nueva123")
    assert not result.ok

    # Confirmación no coincide
    result = manager.change_password("vieja123", "nueva123", "otra")
    assert not result.ok

    # Simular que ya transcurrió el retraso por los dos intentos fallidos
    manager._fails.lock_until = 0

    # Cambio correcto
    result = manager.change_password("vieja123", "nueva123", "nueva123")
    assert result.ok
    assert verify_password("nueva123", manager._read())
    assert not verify_password("vieja123", manager._read())
    assert manager.is_unlocked


def test_change_password_min_length(tmp_path):
    manager = SecurityManager(tmp_path / "sec.json", iterations=FAST_ITERATIONS)
    manager.configure("clave123")
    result = manager.change_password("clave123", "abc", "abc")
    assert not result.ok
