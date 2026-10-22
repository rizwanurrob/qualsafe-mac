<#
Reusable helper script for Windows users.

Usage examples:
1) First-time setup + run
   powershell -ExecutionPolicy Bypass -File .\run_pipeline.ps1 -ConfigPath ".\config\config.example.yaml" -InstallDeps

2) Run only (dependencies already installed)
   powershell -ExecutionPolicy Bypass -File .\run_pipeline.ps1 -ConfigPath ".\config\my_project.yaml"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,

    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' not found. Install Python 3.10+ first, then rerun this script."
}

if ($InstallDeps) {
    Write-Host "[1/3] Creating virtual environment (.venv)..."
    py -3 -m venv "$ProjectRoot\.venv"

    Write-Host "[2/3] Installing requirements..."
    & "$ProjectRoot\.venv\Scripts\python.exe" -m pip install --upgrade pip
    & "$ProjectRoot\.venv\Scripts\python.exe" -m pip install -r "$ProjectRoot\requirements.txt"
}

if (-not (Test-Path "$ProjectRoot\.venv\Scripts\python.exe")) {
    throw "Virtual environment not found. Re-run with -InstallDeps or create .venv first."
}

Write-Host "[3/3] Running survey NLP pipeline..."
& "$ProjectRoot\.venv\Scripts\python.exe" "$ProjectRoot\analyze_survey.py" --config $ConfigPath

Write-Host "Done. Check your configured output folder for results."
