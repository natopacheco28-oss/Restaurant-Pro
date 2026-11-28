"""Splash de arranque estilo bootlogo.

Muestra el logo de Restaurante Pro centrado sobre un fondo limpio oscuro,
con animación de aparición (fundido) y barra indeterminada mientras cargan
los servicios. Al estar listo, se funde y cede el paso a la ventana principal.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import CaptionLabel, IndeterminateProgressBar

from app.ui.common import load_logo_pixmap, placeholder_logo
from app.version import APP_NAME, APP_VERSION

# Duraciones de la animación (ms)
FADE_IN_MS = 650
FADE_OUT_MS = 350


class BootSplash(QWidget):
    """Ventana frameless con el logo centrado y fade-in al arrancar."""

    finished = Signal()

    def __init__(self, settings=None):
        super().__init__(None)
        self.settings = settings
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(560, 560)

        # Fondo limpio oscuro que integra el logo (mismo fondo del bootlogo)
        self.setStyleSheet("background-color: #0d0d0d;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 48)
        layout.setSpacing(18)

        # Logo centrado
        self._logo = QLabel()
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = load_logo_pixmap(settings, 340) if settings else placeholder_logo(340)
        self._logo.setPixmap(pixmap)
        self._logo.setStyleSheet("background: transparent;")
        layout.addStretch(1)
        layout.addWidget(self._logo)
        layout.addStretch(1)

        # Nombre y versión
        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #ffffff; background: transparent;")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        version = CaptionLabel(f"Versión {APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: #98989d; background: transparent;")
        layout.addWidget(title)
        layout.addWidget(version)

        # Barra de progreso indeterminada
        self._progress = IndeterminateProgressBar(self)
        self._progress.setFixedWidth(280)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._progress)
        row.addStretch(1)
        layout.addSpacing(6)
        layout.addLayout(row)

        # Efecto de opacidad para la animación de aparición
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(FADE_IN_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ------------------------------------------------------------------

    def show_and_fade_in(self) -> None:
        """Centra, muestra y anima la aparición del bootlogo."""
        self._center_on_screen()
        self.show()
        self.raise_()
        self._fade.start()

    def close_now(self) -> None:
        """Cierra el bootlogo de inmediato, sin fundido de salida.

        Se usa antes del asistente de primer arranque: como el splash es
        «siempre visible» (StaysOnTop), quedaría ENCIMA del formulario de
        configuración impidiendo escribir hasta moverlo a un lado.
        """
        self._fade.stop()
        self.close()
        self.deleteLater()
        self.finished.emit()

    def finish(self, main_window: QWidget) -> None:
        """Fundido de salida y cierre cuando la app ya está lista."""
        self._fade.stop()
        out = QPropertyAnimation(self._opacity, b"opacity", self)
        out.setDuration(FADE_OUT_MS)
        out.setStartValue(1.0)
        out.setEndValue(0.0)
        out.setEasingCurve(QEasingCurve.Type.InQuad)
        out.finished.connect(self._on_finished)
        out.start()
        self._out_anim = out  # conservar referencia (evita GC)
        self._main = main_window

    def _on_finished(self) -> None:
        if getattr(self, "_main", None) is not None:
            self._main.show()
            self._main.raise_()
            self._main.activateWindow()
        self.close()
        self.deleteLater()
        self.finished.emit()

    def _center_on_screen(self) -> None:
        screen = self.screen() or self.windowHandle().screen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )
