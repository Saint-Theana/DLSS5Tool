# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['frozen_entry.py'],
    pathex=['F:/project/DLSS5Tool'],
    binaries=[],
    datas=[],
    hiddenimports=['dlss5tool.adapter_inventory'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'torch', 'dlss5tool.gui', 'scripts', 'tests'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AdapterProbeFixtureFinal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AdapterProbeFixtureFinal',
)
