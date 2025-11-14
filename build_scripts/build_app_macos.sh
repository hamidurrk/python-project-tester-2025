#!/bin/bash
# Build script for macOS
# Run this script on macOS to create the .app bundle

set -e  # Exit on error

echo "========================================"
echo "  Project Tester - macOS Build Script"
echo "========================================"
echo ""

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script must be run on macOS"
    exit 1
fi

# Navigate to project root
cd "$(dirname "$0")/.."

echo "Step 1: Checking Python environment..."
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

python_version=$(python3 --version)
echo "Found: $python_version"
echo ""

echo "Step 2: Installing/updating dependencies..."
pip3 install -r requirements-macos.txt
pip3 install pyinstaller
echo ""

echo "Step 3: Cleaning previous build..."
rm -rf build dist
echo "Cleaned build and dist directories"
echo ""

echo "Step 4: Building macOS app bundle..."
pyinstaller build_scripts/ProjectTester_macOS.spec
echo ""

if [ -d "dist/ProjectTester.app" ]; then
    echo "========================================"
    echo "  Build Successful!"
    echo "========================================"
    echo ""
    echo "Application created: dist/ProjectTester.app"
    echo ""
    
    # Get app size
    app_size=$(du -sh dist/ProjectTester.app | cut -f1)
    echo "App size: $app_size"
    echo ""
    
    echo "Next steps:"
    echo "1. Test the app: open dist/ProjectTester.app"
    echo "2. Move to Applications: cp -r dist/ProjectTester.app /Applications/"
    echo "3. Create DMG (optional): See BUILD_INSTRUCTIONS_macOS.md"
    echo ""
    echo "Note: On first run, you may need to:"
    echo "  - Right-click the app and select 'Open'"
    echo "  - Go to System Preferences > Security & Privacy to allow the app"
    echo ""
else
    echo "========================================"
    echo "  Build Failed!"
    echo "========================================"
    echo "Please check the error messages above."
    exit 1
fi
