Write-Host "Building Project Tester executable..." -ForegroundColor Cyan
Write-Host ""

$scriptDir = Split-Path -Parent $PSCommandPath
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

& .\.venv\Scripts\Activate.ps1

if (Test-Path "build") {
    Write-Host "Cleaning build directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force build
}

if (Test-Path "dist") {
    Write-Host "Cleaning dist directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force dist
}

Write-Host "Building executable with PyInstaller..." -ForegroundColor Green
& python -m PyInstaller build_scripts\ProjectTester.spec --clean

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
