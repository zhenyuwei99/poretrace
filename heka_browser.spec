# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Heka .dat browser -- onedir on all platforms.
#
# onedir (instead of onefile) removes the per-launch temp-extraction step,
# making startup ~3-8x faster and consistent between cold and warm launches.
# Each build script zips the output folder for distribution:
#   macOS:    dist/HekaBrowser.app  (+ HekaBrowser-mac.zip)
#   Windows:  dist/HekaBrowser/HekaBrowser.exe  (+ HekaBrowser-windows.zip)
#   Linux:    dist/HekaBrowser/HekaBrowser      (+ HekaBrowser-linux.zip)
# Build with:  python -m PyInstaller heka_browser.spec --noconfirm --clean

import platform

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'IPython', 'jedi'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,               # binaries/datas collected below
    name='HekaBrowser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # no terminal window on any OS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,              # unsigned: personal/lab use
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='HekaBrowser',
)

if platform.system() == 'Darwin':
    # Wrap the collected folder in a double-clickable .app bundle
    app = BUNDLE(
        coll,
        name='HekaBrowser.app',
        icon=None,
        bundle_identifier='org.lab.hekabrowser',
        info_plist={
            'CFBundleName': 'HekaBrowser',
            'CFBundleDisplayName': 'Heka Browser',
            'NSHighResolutionCapable': True,
        },
    )
