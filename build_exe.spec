# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for StreamSwitcher Pro.

Build with:
    pyinstaller build_exe.spec

Result: dist/StreamSwitcher/ folder with StreamSwitcher.exe inside.
Copy the whole folder to any Windows PC — no Python needed.
"""

import sys
from pathlib import Path

block_cipher = None

# Find the bundled ffmpeg from imageio-ffmpeg.
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    ffmpeg_exe = None

binaries_list = []
if ffmpeg_exe:
    binaries_list.append((ffmpeg_exe, '.'))

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries_list,
    datas=[
        ('docs', 'docs'),
        ('icon.ico', '.'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'sounddevice',
        'soundfile',
        'numpy',
        'scipy',
        'scipy.signal',
        'requests',
        'flask',
        'lameenc',
        'imageio_ffmpeg',
        'pydub',
        'mutagen',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'cv2',
        'IPython',
        'jupyter',
        'pytest',
        'torch',
        'torchvision',
        'torchaudio',
        'tensorflow',
        'keras',
        'pandas',
        'pygame',
        'tensorboard',
        'sympy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StreamSwitcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # no console window
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='StreamSwitcher',
)
