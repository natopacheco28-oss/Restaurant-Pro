# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller para Restaurante Pro (Windows).

Genera una carpeta portable `dist/RestaurantePro/` con:
    RestaurantePro.exe
    _internal/            (runtime de Python + Qt + assets)
Los datos del usuario se crean JUNTO al exe (carpetas data/ y backups/),
por eso se usa modo onedir y no onefile.

Comando:  pyinstaller restaurante_pro.spec --noconfirm
"""

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    # El logo y el icono viajan dentro del paquete
    datas=[("assets", "assets")],
    # win32print/win32api solo se usan en Windows (impresión RAW ESC/POS)
    # QtPrintSupport queda incluido explícitamente (QPrinter/QPrintDialog)
    hiddenimports=[
        "win32print",
        "win32api",
        "win32con",
        "pywintypes",
        "PySide6.QtPrintSupport",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc_data",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DQuick",
        "PySide6.QtWebSockets",
        "PySide6.QtNetworkAuth",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RestaurantePro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # app de escritorio sin consola
    icon="assets/icon.ico",      # icono del ejecutable
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RestaurantePro",
)
