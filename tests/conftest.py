"""Fixture compartida: base de datos temporal con migraciones aplicadas.

También crea una QApplication de sesión (plataforma offscreen): los servicios
emiten señales Qt (SignalBus) y una QApplication viva garantiza el orden
correcto de destrucción de los objetos Qt al terminar el proceso.
"""
from __future__ import annotations

import os

import pytest


# Referencia global para que la QApplication viva hasta el final del
# proceso (si el GC la recolecta antes, la finalización de Qt se rompe).
_KEEP_APP: list = []


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """QApplication de sesión (offscreen) para las señales Qt de los servicios."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    _KEEP_APP.append(app)
    return app


@pytest.fixture()
def db(tmp_path):
    from app.core.database import Database
    from app.core.migrations import run_migrations

    database = Database(tmp_path / "test.db").connect()
    run_migrations(database, log=lambda msg: None)
    yield database
    database.close()


@pytest.fixture()
def bus():
    from app.signals import SignalBus

    return SignalBus()


@pytest.fixture()
def settings(tmp_path):
    from app.core.settings import Settings

    return Settings(tmp_path / "config.json")


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    """Deja que los demás hooks impriman el resumen y sale sin finalizar Qt.

    PySide6/shiboken 6.12 puede abortar (SIGABRT) al recolectar objetos Qt
    durante la finalización del intérprete cuando no hubo event loop. Al
    terminar este hook el reporte ya está generado: se vacían los búferes y
    se sale de forma controlada conservando salida y código de resultado.
    """
    yield
    import sys

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(exitstatus))
