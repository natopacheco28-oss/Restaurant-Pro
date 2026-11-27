"""Seguridad de la clave maestra de Restaurante Pro.

- La clave se configura en el primer arranque y se guarda SOLO como hash
  PBKDF2-HMAC-SHA256 con sal aleatoria (nunca en texto plano).
- `SecurityManager` controla el "modo edición" (una sola vez por sesión),
  el bloqueo automático al cerrar y el retraso progresivo ante intentos
  fallidos de la clave.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from PySide6.QtCore import QObject, Signal

# Parámetros de derivación (costo razonable para PC de escritorio)
ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 200_000
SALT_BYTES = 16
KEY_LENGTH = 32

MIN_PASSWORD_LEN = 4

# Retraso progresivo ante intentos fallidos: 1s, 2s, 4s… máx. 60 s
MAX_FAIL_DELAY = 60.0


# ----------------------------------------------------------------------
# Hash y verificación (funciones puras, fáciles de probar)
# ----------------------------------------------------------------------

def hash_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Genera `algoritmo$iteraciones$sal$hash` (base64) con sal aleatoria."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=KEY_LENGTH
    )
    return "$".join(
        (
            ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verifica la clave contra el hash almacenado (tiempo constante)."""
    try:
        algorithm, iters_b64, salt_b64, hash_b64 = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(iters_b64)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected)
        )
        return secrets.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


class UnlockResult(NamedTuple):
    """Resultado de un intento de desbloqueo."""

    ok: bool
    message: str
    wait_seconds: float = 0.0  # segundos a esperar antes de reintentar


@dataclass
class _FailTracker:
    """Contador de fallos consecutivos + instante hasta el que se bloquea."""

    attempts: int = 0
    lock_until: float = 0.0  # time.monotonic()

    def register_fail(self) -> float:
        """Registra un fallo y devuelve el retraso a esperar."""
        self.attempts += 1
        delay = min(2.0 ** (self.attempts - 1), MAX_FAIL_DELAY)
        self.lock_until = time.monotonic() + delay
        return delay

    def remaining(self) -> float:
        return max(0.0, self.lock_until - time.monotonic())

    def reset(self) -> None:
        self.attempts = 0
        self.lock_until = 0.0


class SecurityManager(QObject):
    """Clave maestra + modo edición por sesión.

    Señales:
        editModeChanged(bool): True al desbloquear, False al bloquear.
    """

    editModeChanged = Signal(bool)

    def __init__(self, file_path: Path, iterations: int = DEFAULT_ITERATIONS):
        super().__init__()
        self.file_path = Path(file_path)
        self._iterations = iterations
        self._unlocked = False
        self._fails = _FailTracker()

    # ------------------------------------------------------------------
    # Configuración inicial (primer arranque)
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """True si ya existe una clave maestra configurada."""
        return self.file_path.exists()

    def configure(self, password: str, confirm: str | None = None) -> None:
        """Guarda el hash de la clave maestra (primer arranque)."""
        confirm = password if confirm is None else confirm
        self._validate_new(password, confirm)
        self._write(hash_password(password, self._iterations))
        self._fails.reset()

    # ------------------------------------------------------------------
    # Desbloqueo / bloqueo (modo edición)
    # ------------------------------------------------------------------

    def unlock(self, password: str) -> UnlockResult:
        """Intenta activar el modo edición con la clave maestra."""
        wait = self._fails.remaining()
        if wait > 0:
            return UnlockResult(False, "Demasiados intentos fallidos. Espere.", wait)

        if not self.is_configured():
            return UnlockResult(False, "Aún no hay clave maestra configurada.", 0)

        encoded = self._read()
        if encoded and verify_password(password, encoded):
            self._fails.reset()
            self._unlocked = True
            self.editModeChanged.emit(True)
            return UnlockResult(True, "Modo edición activado.", 0)

        delay = self._fails.register_fail()
        return UnlockResult(False, "Clave incorrecta.", delay)

    def lock(self) -> None:
        """Desactiva el modo edición (botón manual o cierre del programa)."""
        if self._unlocked:
            self._unlocked = False
            self.editModeChanged.emit(False)

    def reset_session(self) -> None:
        """Bloquea y limpia intentos (se llama al cerrar la aplicación)."""
        self.lock()
        self._fails.reset()

    @property
    def is_unlocked(self) -> bool:
        return self._unlocked

    @property
    def failed_attempts(self) -> int:
        return self._fails.attempts

    # ------------------------------------------------------------------
    # Cambio de clave (menú oculto Ctrl+P)
    # ------------------------------------------------------------------

    def change_password(self, current: str, new: str, confirm: str) -> UnlockResult:
        """Cambia la clave maestra tras verificar la actual."""
        wait = self._fails.remaining()
        if wait > 0:
            return UnlockResult(False, "Demasiados intentos fallidos. Espere.", wait)

        encoded = self._read()
        if not encoded or not verify_password(current, encoded):
            delay = self._fails.register_fail()
            return UnlockResult(False, "La clave actual es incorrecta.", delay)

        try:
            self._validate_new(new, confirm)
        except ValueError as exc:
            return UnlockResult(False, str(exc), 0)

        self._write(hash_password(new, self._iterations))
        self._fails.reset()
        self._unlocked = True  # si la cambió, sabía la clave: queda desbloqueado
        self.editModeChanged.emit(True)
        return UnlockResult(True, "Clave maestra actualizada.", 0)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_new(password: str, confirm: str) -> None:
        if len(password) < MIN_PASSWORD_LEN:
            raise ValueError(f"La clave debe tener al menos {MIN_PASSWORD_LEN} caracteres.")
        if password != confirm:
            raise ValueError("La clave y su confirmación no coinciden.")

    def _read(self) -> str | None:
        try:
            with open(self.file_path, encoding="utf-8") as fh:
                data: dict[str, Any] = json.load(fh)
            return data.get("password_hash")
        except (OSError, json.JSONDecodeError):
            return None

    def _write(self, password_hash: str) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"algorithm": ALGORITHM, "password_hash": password_hash}
        tmp = self.file_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        tmp.replace(self.file_path)
