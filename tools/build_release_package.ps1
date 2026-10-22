<#
Build a website-ready distribution folder and ZIP package.

Usage:
  powershell -ExecutionPolicy Bypass -File .\tools\build_release_package.ps1
#>

param(
    [string]$Version = "v1.0.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$DistRoot = Join-Path $ProjectRoot "dist"
$PackageFolderName = "qualitative-nlp-local-app-$Version"
$PackageRoot = Join-Path $DistRoot $PackageFolderName
$ZipPath = Join-Path $DistRoot "$PackageFolderName-$Timestamp.zip"

Write-Host "Project root: $ProjectRoot"
Write-Host "Preparing distribution folder..."

if (Test-Path $PackageRoot) {
    Remove-Item -Recurse -Force -LiteralPath $PackageRoot
}
if (-not (Test-Path $DistRoot)) {
    New-Item -ItemType Directory -Path $DistRoot | Out-Null
}

New-Item -ItemType Directory -Path $PackageRoot | Out-Null

$itemsToCopy = @(
    ".streamlit",
    "config",
    "data",
    "docs",
    "notebooks",
    "project_progress",
    "tools",
    "analyze_survey.py",
    "iterative_supervised_thematic.py",
    "streamlit_app.py",
    "requirements.txt",
    "README.md",
    "run_streamlit.ps1",
    "run_pipeline.ps1",
    "launch_streamlit.bat",
    "launch_streamlit.sh"
)

foreach ($item in $itemsToCopy) {
    $src = Join-Path $ProjectRoot $item
    if (Test-Path $src) {
        Copy-Item -Recurse -Force -LiteralPath $src -Destination $PackageRoot
    }
}

# Remove transient caches from copied package.
Get-ChildItem -Path $PackageRoot -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

# Add a concise install note at package root.
$installNotePath = Join-Path $PackageRoot "INSTALL_FIRST.txt"
$installText = @"
Qualitative NLP Local App - Quick Start

Prerequisite:
- Install Python 3.10+ first: https://www.python.org/downloads/

1) Open PowerShell in this folder.
2) Run:
   powershell -ExecutionPolicy Bypass -File .\run_streamlit.ps1 -InstallDeps
3) Wait for setup, then open:
   http://localhost:8501

You can extract this folder anywhere on your machine.
Paths are script-relative, so the app is portable after extraction.
"@
$installText | Set-Content -Encoding UTF8 -Path $installNotePath

Write-Host "Creating ZIP package..."
if (Test-Path $ZipPath) {
    Remove-Item -Force -LiteralPath $ZipPath
}
Compress-Archive -Path "$PackageRoot\*" -DestinationPath $ZipPath -Force

Write-Host "Done."
Write-Host "Folder package: $PackageRoot"
Write-Host "ZIP package:    $ZipPath"
