# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['../tester.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../assets/icon.png', 'assets'),
        ('../assets/copy.png', 'assets'),
        ('../data', 'data'),
        ('../config.json', '.'),
        ('../predefined_inputs.json', '.'),
        ('../feedback_template.txt', '.'),
    ],
    hiddenimports=[
        'pygments',
        'pygments.lexers',
        'pygments.lexers.python',
        'pygments.token',
        'watchdog',
        'watchdog.observers',
        'watchdog.events',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'pytest',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Project-Tester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='../build_scripts/version_info.txt',
    icon='../assets/icon.png',
    uac_admin=False,  # Don't require admin rights
    uac_uiaccess=False,
)
