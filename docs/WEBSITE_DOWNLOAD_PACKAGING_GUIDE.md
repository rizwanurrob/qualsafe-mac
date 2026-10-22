# Website Download Packaging Guide

## Goal
Create a zip file that users can download from your website, extract anywhere, and run locally.

## Build the Package
From project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_release_package.ps1
```

This produces:
1. Installation folder under `dist/`
2. Timestamped ZIP file under `dist/`

## What Is Included
1. Streamlit app (`streamlit_app.py`)
2. Pipeline scripts
3. Config templates
4. Sample datasets (including synthetic qualitative CSV)
5. User guides and progress docs
6. Launch scripts (`run_streamlit.ps1`, `launch_streamlit.bat`, `launch_streamlit.sh`)

## User Install Experience
After user downloads and extracts zip:
1. Install Python 3.10+ from `https://www.python.org/downloads/` (one-time prerequisite).
2. Open extracted folder.
3. Run:
   - `powershell -ExecutionPolicy Bypass -File .\run_streamlit.ps1 -InstallDeps`
4. Open `http://localhost:8501`

## Why It Is Portable
Launch scripts use script-relative paths (`$PSScriptRoot` on PowerShell), so the extracted folder can be moved anywhere.

## Suggested Website Copy
"Download the Local Qualitative NLP App (ZIP). Extract anywhere, run one command, and start analyzing survey text with a guided Streamlit interface."
