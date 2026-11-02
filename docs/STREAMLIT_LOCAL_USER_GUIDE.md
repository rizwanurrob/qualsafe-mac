# Streamlit Local User Guide (Beginner Friendly)

## Who This Is For
This guide is for people who have never used these items:
- Python
- Streamlit
- Thematic analysis

## What This App Does
The app helps you analyse the open-text answers of a survey. It runs on your own computer.

The app has these main functions:
1. Load your own file or a sample file.
2. Choose suggested theme labels and edit them.
3. Run a machine-assisted qualitative analysis.
4. Download reports and CSV files.
5. Run an iterative supervised workflow (sample, label, train, find new themes).

## Step 1: Install and Start

### Prerequisite: Python
Install Python 3.10 or newer if it is not installed:
1. Go to `https://www.python.org/downloads/`.
2. Install Python 3.10 or newer.
3. On Windows, make sure that the `py` launcher is available.

If the `py` command is missing, Python is not installed correctly.

### Windows PowerShell
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

### What to expect
- A browser tab opens by itself.
- If it does not open, copy the local URL from the terminal. It is usually `http://localhost:8501`.

## Step 2: Data Setup
Open the **Data Setup** page.

You have these choices:
1. **Drag-and-drop upload** (`.csv`, `.xlsx`, `.json`)
2. **Load from local source folder**
   - Choose the Home folder (you must confirm), or
   - choose a custom folder path.
3. **Load Synthetic Sample** (recommended for the first run)
4. **Download public sample** (one click, from Zenodo sources)

Then map the columns:
- `Text column` (required)
- `Question column` (optional, but recommended)
- `ID column` (optional)

### If your file has several questions or prompts
Switch on **Analyze one question at a time**. Pick one question value.

You can search the question picker:
- Click the dropdown.
- Type part of the text of the question.
- Select the question that you want.

## Included Sample Files

### 1) Synthetic qualitative sample
- File: `data/synthetic_customer_experience_feedback.csv`
- It contains generated open-text responses that look real.
- Use it to learn the app and to test it.

### 2) Public datasets (download in the app)
- GitHub Open Source Survey 2017:
  - https://zenodo.org/records/806811
- Science4Policy Kit Survey Responses:
  - https://zenodo.org/records/14275894

These sources are free and public. Use them to test qualitative workflows.

## Step 3: Theme Setup
Open the **Theme Setup** page.

1. Pick a suggested label pack.
2. Click **Load Suggested Labels**.
3. Edit the labels in the text box. Put one label on each line.

### Suggested starting labels (example)
- Ease of use issue
- Reliability bug
- Speed/performance concern
- Support quality feedback
- Pricing/value concern
- Feature request
- Positive experience
- Trust or privacy concern

Use labels that fit the context of your question and the goals of your stakeholders.

## Step 4: Run Analysis
Open the **Run Analysis** page.

Choose the options:
- sentiment analysis
- global zero-shot labels
- question-level unsupervised themes
- question-level zero-shot labels

Then click **Run General Pipeline**.

## Step 5: Iterative Supervised Workflow
Open the **Iterative Labeling Lab** page:

1. Choose one question value.
2. Choose the sample size (`10` or `20`).
3. Click **Create Iterative Coding Sample**.
4. Edit the labels in the table in the app.
5. In `human_labels`, enter one or more labels for each row.
   - Put `|` between the labels. For example: `Price concern|Usability issue`
6. Click **Save Coding Edits**.
7. Click **Run Iterative Train**.

Note:
- You can also edit `output_iterative/coding_sample.csv` by hand.

## Step 6: Results and Downloads
Open the **Results & Downloads** page. There you can:
- preview the summaries
- download CSV files
- download report files
- download iterative workflow files

## Optional: Data Charts

The **Data Charts** page makes charts from any CSV or Excel file. The file does not need to be a survey with open text. This page does not need a project or a run. Upload a file, or press **Try it with sample survey data**. Choose a question. The chart changes when you change a setting.

Export the picture (PNG, SVG, or PDF) and the table behind it. The app never changes your file. The full guide is `docs/CHART_BUILDER_GUIDE.md`.

## Estimated Time

These are typical run times on a local computer:
1. 100 to 500 rows: about 2 to 6 minutes
2. 500 to 2,000 rows: about 6 to 20 minutes
3. Larger datasets: the time depends on the CPU or GPU and on the options that you switch on

Notes:
- The first run is slower because the app can download model files.
- Later runs are usually faster because the files are in the local cache.

## Troubleshooting

### 1) `ModuleNotFoundError`
Cause: The active environment does not have the dependencies.
Fix:
```powershell
pip install -r requirements.txt
```

### 2) Wrong columns or blank results
Cause: The column mapping is wrong.
Fix: Check `Text column` and `Question column` again in Data Setup.

### 3) Too many `UNCERTAIN_REVIEW` rows
Cause: The strict thresholds are too high.
Fix: Lower the strict thresholds in small steps.

### 4) The public dataset download fails
Cause: The internet connection is down, or the remote file is not available.
Fix:
1. Try again later.
2. Use the synthetic sample or a local upload.

### 5) The analysis is too slow
Fixes:
1. Use less data for a pilot run.
2. Switch off the optional modes.
3. Keep the labels focused and short.

## Tips for Beginners: How to Read Results
1. Treat machine themes as draft hypotheses. They are not final truth.
2. Read representative quotes before you report.
3. Have an analyst review the uncertain rows.
4. Improve the labels. Then run the analysis again.

## Project Progress Files
The progress of the implementation is in these files:
- `project_progress/00_master_plan.md`
- `project_progress/01_phase1_implementation_log.md`
