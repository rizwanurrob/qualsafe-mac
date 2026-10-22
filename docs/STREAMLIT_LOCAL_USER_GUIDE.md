# Streamlit Local User Guide (Beginner Friendly)

## Who This Is For
This guide is written for people who may have never used:
- Python
- Streamlit
- Thematic analysis

## What This App Does
The app helps you analyze open-text survey responses locally on your own machine.

Main capabilities:
1. Load your own file or a sample file.
2. Choose suggested theme labels and edit them.
3. Run machine-assisted qualitative analysis.
4. Download reports and CSV outputs.
5. Run an iterative supervised workflow (sample -> label -> train -> discover new themes).

## Step 1: Install and Launch

### Prerequisite: Python
Install Python 3.10+ first if not already installed:
1. Go to `https://www.python.org/downloads/`
2. Install Python 3.10 or newer
3. On Windows, ensure the `py` launcher is available

If `py` command is missing, Python is not installed correctly yet.

### Windows PowerShell
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

### What to expect
- A browser tab should open automatically.
- If it does not open, copy the local URL shown in terminal (usually `http://localhost:8501`).

## Step 2: Data Setup
Open **Data Setup** page.

You have multiple choices:
1. **Drag-and-drop upload** (`.csv`, `.xlsx`, `.json`)
2. **Load from local source folder**
   - choose Home folder (with explicit confirmation), or
   - choose a custom folder path
3. **Load Synthetic Sample** (recommended first run)
4. **Download public sample** (one-click from Zenodo sources)

Then map columns:
- `Text column` (required)
- `Question column` (optional but recommended)
- `ID column` (optional)

### If your file has multiple questions/prompts
Enable **Analyze one question at a time** and pick one question value.

The question picker is searchable:
- click the dropdown
- type part of the question text
- select the desired question

## Included Sample Files

### 1) Synthetic qualitative sample
- File: `data/synthetic_customer_experience_feedback.csv`
- Contains plausible, generated open-text responses.
- Good for onboarding and testing.

### 2) Public datasets (download in app)
- GitHub Open Source Survey 2017:
  - https://zenodo.org/records/806811
- Science4Policy Kit Survey Responses:
  - https://zenodo.org/records/14275894

These sources are free/public and useful for testing qualitative workflows.

## Step 3: Theme Setup
Open **Theme Setup** page.

1. Pick a suggested label pack.
2. Click **Load Suggested Labels**.
3. Edit labels in the text box (one label per line).

### Suggested starting labels (example)
- Ease of use issue
- Reliability bug
- Speed/performance concern
- Support quality feedback
- Pricing/value concern
- Feature request
- Positive experience
- Trust or privacy concern

Use labels that match your question context and stakeholder goals.

## Step 4: Run Analysis
Open **Run Analysis** page.

Choose options:
- sentiment analysis
- global zero-shot labels
- question-level unsupervised themes
- question-level zero-shot labels

Then click **Run General Pipeline**.

## Step 5: Iterative Supervised Workflow
Open **Iterative Labeling Lab** page:

1. Choose one question value.
2. Choose sample size (`10` or `20`).
3. Click **Create Iterative Coding Sample**.
4. Edit labels directly in the app table.
5. Fill `human_labels` with one or more labels per row.
   - Use `|` between labels, e.g. `Price concern|Usability issue`
6. Click **Save Coding Edits**.
7. Click **Run Iterative Train**.

Note:
- You can still edit `output_iterative/coding_sample.csv` manually if preferred.

## Step 6: Results and Downloads
Open **Results & Downloads** page to:
- preview summaries
- download CSV outputs
- download report files
- download iterative workflow files

## Optional: Data Charts

The **Data Charts** page charts any CSV or Excel file (not only open-text surveys) and
does not need a project or a run. Upload a file, or press **Try it with sample survey
data**, choose a question, and the chart updates as you change things. Export the
picture (PNG, SVG or PDF) and the table behind it. Your file is never changed.
Full guide: `docs/CHART_BUILDER_GUIDE.md`.

## Estimated Time

Typical local runtime estimates:
1. 100-500 rows: ~2-6 minutes
2. 500-2,000 rows: ~6-20 minutes
3. Larger datasets: depends heavily on CPU/GPU and enabled options

Notes:
- First run is slower because model files may download.
- Later runs are usually faster due to local cache.

## Troubleshooting

### 1) `ModuleNotFoundError`
Cause: dependencies not installed in active environment.
Fix:
```powershell
pip install -r requirements.txt
```

### 2) Wrong columns or blank results
Cause: column mapping mismatch.
Fix: re-check `Text column` and `Question column` in Data Setup.

### 3) Too many `UNCERTAIN_REVIEW` rows
Cause: strict thresholds too high.
Fix: lower strict thresholds gradually.

### 4) Public dataset download fails
Cause: internet or remote availability issue.
Fix:
1. Retry later.
2. Use synthetic sample or local upload.

### 5) Analysis too slow
Fixes:
1. Reduce data size for pilot run.
2. Disable optional modes.
3. Keep labels focused and short.

## Beginner Interpretation Tips
1. Treat machine themes as draft hypotheses, not final truth.
2. Always read representative quotes before reporting.
3. Keep an analyst review pass for uncertain rows.
4. Iterate labels and rerun.

## Project Progress Files
Implementation progress is tracked in:
- `project_progress/00_master_plan.md`
- `project_progress/01_phase1_implementation_log.md`
