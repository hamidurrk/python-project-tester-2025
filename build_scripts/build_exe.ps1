# Build script for Project Tester executable
# Run this script to create the standalone .exe file

Write-Host "Building Project Tester executable..." -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
& .\.venv\Scripts\Activate.ps1

# Clean previous builds
if (Test-Path "build") {
    Write-Host "Cleaning build directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force build
}

if (Test-Path "dist") {
    Write-Host "Cleaning dist directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force dist
}

# Build the executable
Write-Host "Building executable with PyInstaller..." -ForegroundColor Green
& python -m PyInstaller ProjectTester.spec --clean

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Build completed successfully!" -ForegroundColor Green
    Write-Host "Executable location: dist\ProjectTester.exe" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "To reduce false positives from antivirus:" -ForegroundColor Yellow
    Write-Host "1. The executable is now built with proper version info and metadata" -ForegroundColor White
    Write-Host "2. Add the dist folder to Windows Defender exclusions if needed" -ForegroundColor White
    Write-Host "3. Consider code signing the executable for production use" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "Build failed! Check the error messages above." -ForegroundColor Red
}
