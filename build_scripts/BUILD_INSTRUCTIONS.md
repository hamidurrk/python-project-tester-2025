# Building Project Tester Executable

## Quick Build

Run the build script from the project root in PowerShell:

```powershell
.\build_scripts\build_exe.ps1
```

The executable will be created at: `dist\ProjectTester.exe`

## Manual Build

If you prefer to build manually from the project root:

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Build with PyInstaller
python -m PyInstaller build_scripts\ProjectTester.spec --clean
```

## About the Executable

- **Name:** Project Tester
- **Version:** 1.0.0
- **Author:** Hamidur
- **Type:** Single-file executable (onefile)
- **Icon:** Custom icon from assets/icon.png
- **Console:** Hidden (GUI only)

## Antivirus False Positives

To minimize Windows Defender false positives:

1. ✅ **Proper metadata included** - The exe has full version info and author details
2. ✅ **No admin rights required** - Runs as normal user
3. ✅ **Legitimate icon** - Uses your custom icon.png
4. ✅ **Excludes unnecessary modules** - Reduced file size and complexity

### If Windows Defender Still Flags It:

1. **Add exclusion to Windows Defender:**
   - Open Windows Security
   - Go to Virus & threat protection
   - Manage settings → Exclusions
   - Add folder: `dist` folder

2. **For production/distribution:**
   - Consider code signing with a certificate (costs money but eliminates false positives)
   - Submit to Microsoft for analysis: https://www.microsoft.com/en-us/wdsi/filesubmission

## File Structure After Build

```
project-root/
├── dist/
│   └── ProjectTester.exe    ← Your standalone executable
├── build/                    ← Temporary build files (can be deleted)
├── ProjectTester.spec        ← PyInstaller configuration
├── version_info.txt          ← Windows version info
└── build_exe.ps1            ← Build script
```

## Running the Executable

Double-click `dist\ProjectTester.exe` or run from command line:

```powershell
.\dist\ProjectTester.exe
```

**Note:** The exe is completely standalone and doesn't need Python installed!

## Distributing

To distribute your app:

1. Copy `ProjectTester.exe` from the `dist` folder
2. Users can run it directly without any installation
3. The app will create its own `data` folder for configuration files when first run

## Troubleshooting

### "Windows protected your PC" warning

This is SmartScreen, not a virus detection. Click "More info" → "Run anyway"

### Antivirus quarantines the file

- Add the file to exclusions temporarily
- Or get a code signing certificate for production use

### Missing icon in exe

- Ensure `assets/icon.png` exists before building
- Rebuild with `--clean` flag

## Size Optimization

The current spec file already:
- Excludes heavy modules (matplotlib, numpy, pandas, scipy)
- Uses UPX compression
- Bundles only necessary dependencies

Current size: ~10-15 MB (depending on dependencies)
