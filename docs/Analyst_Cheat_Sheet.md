# Qualitative Analysis Cheat Sheet

## Who This Is For
- First-time analysts doing survey thematic analysis.
- Teams using the local pipeline in this project.

## 1) Quick Start
1. Put your file in `data/` (CSV, TSV, XLSX, or JSON).
2. Edit `config/config.example.yaml` or copy it to `config/my_project.yaml`.
3. Set:
   - `input.file_path`
   - `input.text_column`
   - `input.question_column` (recommended)
4. Run:
   - VS Code task: `Survey NLP: Run (pick config)`, or
   - `python analyze_survey.py --config config/my_project.yaml`
5. Open outputs in `output/`.

## 2) Analysis Modes

### General Qualitative Analysis
- Global clustering across all responses.
- Best when you want overall themes.
- Key outputs:
  - `cluster_summary.csv`
  - `responses_scored.csv`

### Thematic Analysis By Question (Unsupervised)
- Discovers themes separately inside each question.
- Enable:
  - `thematic_analysis.by_question.enabled: true`
- Key output:
  - `question_theme_summary.csv`

### Thematic Coding By Question (Supervised)
- Applies question-specific label sets with zero-shot classification.
- Enable:
  - `thematic_analysis.by_question_zero_shot.enabled: true`
- Configure:
  - `labels_by_question` in YAML.
- Key output:
  - `question_label_summary.csv`

## 3) Strict Coding Mode (Recommended)
- Purpose: send ambiguous responses to manual review.
- Enable:
  - `zero_shot.strict_coding.enabled: true` (global)
  - `thematic_analysis.by_question_zero_shot.strict_coding.enabled: true` (by question)

### Suggested Starting Thresholds
- `top1_min_score: 0.60`
- `min_margin_over_second: 0.12`
- `uncertain_label: "UNCERTAIN_REVIEW"`

### Strict Mode Outputs
- `strict_review_queue_global.csv`
- `strict_review_queue_question.csv`

## 4) How To Read Results
1. Start with `run_report.md`.
2. Review `cluster_summary.csv` for major themes.
3. Validate themes with representative quotes.
4. If strict mode is on, manually review all `UNCERTAIN_REVIEW` rows.
5. Adjust labels and thresholds, then rerun.

## 5) Common Mistakes To Avoid
- Treating clusters as final truth without quote review.
- Using vague labels (example: "Other issue") too early.
- Setting strict thresholds too high on small datasets.
- Comparing themes across questions without using question-level mode.

## 6) Troubleshooting
- Error: column not found
  - Check exact text in `input.text_column` and `input.question_column`.
- Too many uncertain rows
  - Lower `top1_min_score` slightly (example: 0.60 -> 0.55).
- Themes look mixed
  - Increase label quality or use question-level analysis.

## 7) Deliverable Checklist
- `run_report.md` shared with stakeholders.
- Theme table exported (`cluster_summary.csv` or `question_theme_summary.csv`).
- Uncertain queue reviewed and resolved.
- Final coding rules documented for repeatability.
