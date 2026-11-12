# -*- mode: python ; coding: utf-8 -*-
import os

datas = [("config.yaml", ".")]
vosk_model = os.path.join("models", "vosk-model-vn-0.4")
if os.path.isdir(vosk_model):
    datas.append((vosk_model, vosk_model))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uiautomation",
        "comtypes",
        "rapidocr_onnxruntime",
        "vosk",
        "sounddevice",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "scripts.auto_dev"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TieuVu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
