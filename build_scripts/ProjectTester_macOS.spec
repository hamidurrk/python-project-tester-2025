# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for macOS

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
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ProjectTester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI application
    disable_windowed_traceback=False,
    argv_emulation=False,  # Important for macOS
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ProjectTester',
)

app = BUNDLE(
    coll,
    name='ProjectTester.app',
    icon='../assets/icon.png',
    bundle_identifier='com.projecttester.app',
    info_plist={
        'CFBundleName': 'Project Tester',
        'CFBundleDisplayName': 'Project Tester',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': '????',
        'CFBundleExecutable': 'ProjectTester',
        'CFBundleIdentifier': 'com.projecttester.app',
        'LSMinimumSystemVersion': '10.13.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'LSApplicationCategoryType': 'public.app-category.developer-tools',
        'NSAppleScriptEnabled': False,
        'LSEnvironment': {
            'PATH': '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
        }
    },
)
