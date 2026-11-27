"""Validación de negocio compartida por los servicios."""
from __future__ import annotations


class ValidationError(Exception):
    """Error de validación con mensaje listo para mostrar al usuario."""
