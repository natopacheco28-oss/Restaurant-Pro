"""Restaurante Pro — punto de entrada.

Ejecutar en desarrollo:  python main.py
El .exe de Windows se genera con GitHub Actions + PyInstaller
(ver .github/workflows/build.yml y restaurante_pro.spec).
"""
from app.application import run

if __name__ == "__main__":
    raise SystemExit(run())
