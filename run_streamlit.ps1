<#
Local launcher for Streamlit app (Windows).

Examples:
1) First-time setup + launch:
   powershell -ExecutionPolicy Bypass -File .\run_streamlit.ps1 -InstallDeps

2) Launch only:
   powershell -ExecutionPolicy Bypass -File .\run_streamlit.ps1
#>

param(
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

Write-Host "[3/3] Starting Streamlit app..."
& "$ProjectRoot\.venv\Scripts\python.exe" -m streamlit run "$ProjectRoot\streamlit_app.py"
