# Qualitative Analysis Cheat Sheet

## Who This Is For
- First-time analysts who do thematic analysis of surveys.
- Teams that use the local pipeline in this project.

## 1) Quick Start
1. Put your file in `data/`. The file can be CSV, TSV, XLSX, or JSON.
2. Edit `config/config.example.yaml`. Or copy it to `config/my_project.yaml`.
3. Set these items:
   - `input.file_path`
   - `input.text_column`
   - `input.question_column` (recommended)
4. Run the analysis with one of these:
   - The VS Code task `Survey NLP: Run (pick config)`.
   - The command `python analyze_survey.py --config config/my_project.yaml`.
5. Open the results in `output/`.

## 2) Analysis Modes

### General Qualitative Analysis
- It makes one global clustering across all responses.
- Use it when you want the overall themes.
- Key results:
  - `cluster_summary.csv`
  - `responses_scored.csv`

### Thematic Analysis By Question (Unsupervised)
- It finds themes separately inside each question.
- To switch it on, set `thematic_analysis.by_question.enabled: true`.
- Key result:
  - `question_theme_summary.csv`

### Thematic Coding By Question (Supervised)
- It applies a separate label set to each question. It uses zero-shot classification.
- To switch it on, set `thematic_analysis.by_question_zero_shot.enabled: true`.
- Set `labels_by_question` in the YAML file.
- Key result:
  - `question_label_summary.csv`

## 3) Strict Coding Mode (Recommended)
- Purpose: it sends unclear responses to manual review.
- To switch it on, set these items:
  - `zero_shot.strict_coding.enabled: true` (global)
  - `thematic_analysis.by_question_zero_shot.strict_coding.enabled: true` (by question)

### Suggested Starting Thresholds
- `top1_min_score: 0.60`
- `min_margin_over_second: 0.12`
- `uncertain_label: "UNCERTAIN_REVIEW"`

### Strict Mode Results
- `strict_review_queue_global.csv`
- `strict_review_queue_question.csv`

## 4) How To Read Results
1. Start with `run_report.md`.
2. Read `cluster_summary.csv` for the major themes.
3. Check each theme against quotes that represent it.
4. If strict mode is on, review all `UNCERTAIN_REVIEW` rows by hand.
5. Change the labels and thresholds. Then run the analysis again.

## 5) Common Mistakes To Avoid
- Do not accept clusters as final truth before you read the quotes.
- Do not use vague labels too early. An example is "Other issue".
- Do not set strict thresholds too high on a small dataset.
- Do not compare themes across questions unless you use question-level mode.

## 6) Troubleshooting
- Error: column not found
  - Check the exact text in `input.text_column` and `input.question_column`.
- Too many uncertain rows
  - Lower `top1_min_score` a little. For example, change 0.60 to 0.55.
- Themes look mixed
  - Make the labels better, or use question-level analysis.

## 7) Deliverable Checklist
- Give `run_report.md` to the stakeholders.
- Export the theme table (`cluster_summary.csv` or `question_theme_summary.csv`).
- Review the uncertain queue and resolve each row.
- Write down the final coding rules, so that others can repeat the work.
