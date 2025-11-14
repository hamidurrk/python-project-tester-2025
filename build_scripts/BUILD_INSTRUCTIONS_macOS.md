# macOS Build Instructions

## Prerequisites

### System Requirements
- macOS 10.13 (High Sierra) or later
- Python 3.8 or higher
- Xcode Command Line Tools

### Install Xcode Command Line Tools
```bash
xcode-select --install
```

### Install Python Dependencies
```bash
pip3 install -r requirements-macos.txt
pip3 install pyinstaller
```

## Building the Application

### Method 1: Using the Build Script (Recommended)

1. **Make the script executable:**
   ```bash
   chmod +x build_scripts/build_app_macos.sh
   ```

2. **Run the build script:**
   ```bash
   ./build_scripts/build_app_macos.sh
   ```

3. **The app will be created in the `dist` folder:**
   ```
   dist/ProjectTester.app
   ```

### Method 2: Manual Build

```bash
# Clean previous builds
rm -rf build dist

# Build the application
pyinstaller build_scripts/ProjectTester_macOS.spec

# The app will be in dist/ProjectTester.app
```

## Running the Application

### First Time Setup

On macOS, apps from unidentified developers are blocked by default (Gatekeeper).

**Option 1: Right-click to open**
1. Right-click (or Control+click) on `ProjectTester.app`
2. Select "Open" from the menu
3. Click "Open" in the dialog that appears

**Option 2: System Preferences**
1. Try to open the app normally (it will be blocked)
2. Go to System Preferences > Security & Privacy > General
3. Click "Open Anyway" next to the message about ProjectTester
4. Click "Open" in the confirmation dialog

**Option 3: Remove quarantine attribute (advanced)**
```bash
xattr -cr dist/ProjectTester.app
```

### Moving to Applications Folder

```bash
cp -r dist/ProjectTester.app /Applications/
```

## Creating a DMG (Disk Image) for Distribution

### Using create-dmg (Recommended)

1. **Install create-dmg:**
   ```bash
   brew install create-dmg
   ```

2. **Create the DMG:**
   ```bash
   create-dmg \
     --volname "Project Tester" \
     --volicon "assets/icon.png" \
     --window-pos 200 120 \
     --window-size 800 400 \
     --icon-size 100 \
     --icon "ProjectTester.app" 200 190 \
     --hide-extension "ProjectTester.app" \
     --app-drop-link 600 185 \
     "ProjectTester-macOS.dmg" \
     "dist/"
   ```

3. **The DMG will be created in the project root:**
   ```
   ProjectTester-macOS.dmg
   ```

### Using hdiutil (Built-in)

```bash
# Create a temporary directory
mkdir -p dist/dmg

# Copy the app
cp -r dist/ProjectTester.app dist/dmg/

# Create Applications symlink
ln -s /Applications dist/dmg/Applications

# Create DMG
hdiutil create -volname "Project Tester" \
  -srcfolder dist/dmg \
  -ov -format UDZO \
  ProjectTester-macOS.dmg

# Clean up
rm -rf dist/dmg
```

## Code Signing (Optional)

For proper distribution, you should sign your application with an Apple Developer ID.

### Prerequisites
- Apple Developer Program membership ($99/year)
- Developer ID Application certificate installed

### Sign the Application

```bash
# Sign the app bundle
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name (TEAM_ID)" \
  dist/ProjectTester.app

# Verify the signature
codesign --verify --deep --strict --verbose=2 dist/ProjectTester.app

# Notarize with Apple (requires Xcode 13+)
xcrun notarytool submit ProjectTester-macOS.dmg \
  --apple-id "your@email.com" \
  --password "app-specific-password" \
  --team-id "TEAM_ID" \
  --wait

# Staple the notarization ticket
xcrun stapler staple dist/ProjectTester.app
```

## Platform-Specific Notes

### Icon Format
- macOS uses `.icns` format for app icons
- You can convert PNG to ICNS using:
  ```bash
  # Create iconset folder
  mkdir MyIcon.iconset
  
  # Copy and resize your PNG (requires imagemagick)
  brew install imagemagick
  
  for size in 16 32 128 256 512; do
    sips -z $size $size assets/icon.png --out MyIcon.iconset/icon_${size}x${size}.png
    sips -z $((size*2)) $((size*2)) assets/icon.png --out MyIcon.iconset/icon_${size}x${size}@2x.png
  done
  
  # Convert to icns
  iconutil -c icns MyIcon.iconset
  ```

### Python Path
The app includes Python environment paths in the Info.plist to ensure Python executables can be found.

### File Permissions
The build script automatically sets the app as executable. If needed manually:
```bash
chmod +x dist/ProjectTester.app/Contents/MacOS/ProjectTester
```

## Troubleshooting

### App won't open
- Check Console.app for error messages
- Ensure all dependencies are included in the spec file
- Try removing quarantine: `xattr -cr dist/ProjectTester.app`

### "Application is damaged" message
- This usually means Gatekeeper is blocking the app
- Use the right-click > Open method
- Or remove quarantine attribute

### Missing Python modules
- Ensure they're listed in `hiddenimports` in the spec file
- Check the build output for warnings about missing modules

### App size too large
- Review the `excludes` list in the spec file
- Remove unused dependencies from requirements.txt
- Consider using `--onefile` mode (not recommended for macOS)

## Build Output Structure

```
dist/
└── ProjectTester.app/
    └── Contents/
        ├── MacOS/
        │   └── ProjectTester         ← Executable
        ├── Resources/
        │   ├── icon.png
        │   ├── assets/
        │   ├── data/
        │   └── ...
        ├── Frameworks/               ← Python and libraries
        └── Info.plist               ← App metadata
```

## Distribution Checklist

- [ ] Build completes without errors
- [ ] App opens and runs correctly
- [ ] All features work (file browsing, terminal, etc.)
- [ ] Icon displays correctly
- [ ] Test on clean macOS system
- [ ] Code signed (for public distribution)
- [ ] Notarized by Apple (for public distribution)
- [ ] DMG created and tested
- [ ] README includes macOS instructions

## System Requirements for Users

- **Operating System**: macOS 10.13 (High Sierra) or later
- **Architecture**: x86_64 (Intel) or arm64 (Apple Silicon)
- **RAM**: 4GB minimum
- **Disk Space**: 100MB for application

## Notes

- The app bundle includes its own Python interpreter
- Users don't need Python installed
- The app will create data folder in `~/Documents/Project Tester/`
- Configuration and data files are stored per-user

## Universal Binary (Intel + Apple Silicon)

To create a universal binary that works on both Intel and Apple Silicon Macs:

```bash
# Build for both architectures
pyinstaller build_scripts/ProjectTester_macOS.spec --target-arch universal2

# Or use lipo to combine two separate builds
lipo -create -output dist/ProjectTester.app/Contents/MacOS/ProjectTester_universal \
  dist_intel/ProjectTester.app/Contents/MacOS/ProjectTester \
  dist_arm/ProjectTester.app/Contents/MacOS/ProjectTester
```
