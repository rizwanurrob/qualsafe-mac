"""
Building the `run_pipeline` config — the one implementation, shared by both builds.

The config dict is a **contract with `analyze_survey.run_pipeline`, not a
suggestion**: every key here exists because the pipeline reads it, and when two
front ends disagree about a single default they produce different analyses from
the same data and the same button.

That is exactly what had happened. `app/shared/data.build_general_config` read
every choice straight out of `st.session_state`, which made it unusable outside
Streamlit and untestable anywhere; the desktop fork therefore reimplemented it,
and `resolve_long_dataframe` — the code behind this project's worst shipped bug
(HANDOFF §7.1) — ended up with two copies that had to agree by hand.
`PORTED_BACK.md` §7 and §9 record the argument. This module is the collapse of
that duplication: driven by an explicit `RunSettings`, importable without a GUI,
and asserted against directly. Both front ends are now thin adapters over it.

The one thing worth reading twice is `resolve_long_dataframe`. Wide-form survey
data has to be melted before the pipeline sees it, and the melt mints a
per-answer `response_id` plus a `respondent_id` for grouping. Getting that wrong
detaches coding from responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from core.model_manager import DEFAULT_MODELS

#: Quick-preview sample size. Matches `app/shared/constants.PREVIEW_ROWS`.
PREVIEW_ROWS = 50

#: Starter label packs. Dict order is the picker's order, so the first pack is
#: the default: education leads because this tool's home audience is
#: institutional research on student data, and the pack matches the built-in
#: sample dataset so the sample path works out of the box.
#:
#: Re-exported from `core.label_packs`, which also owns the packs an analyst
#: saves — built-in and custom packs belong in one place.
from core.label_packs import BUILTIN_PACKS as SUGGESTED_LABEL_PACKS  # noqa: E402


def label_packs() -> Dict[str, List[str]]:
    """Built-in starter packs plus any the analyst saved."""
    from core.label_packs import all_packs

    return all_packs()


#: Fallback labels when the analyst has not written any. Matches upstream.
FALLBACK_LABELS = ["Usability issue", "Price concern", "Support feedback",
                   "Feature request"]


@dataclass
class RunSettings:
    """Every choice the pipeline needs, as plain data.

    Deliberately a dataclass rather than a dict: the pipeline config has forty-odd
    keys and a typo in one of them is a silently different analysis.
    """

    # -- ingestion / mapping --
    ingestion_mode: str = "long"            # "long" | "wide"
    text_column: str = ""
    text_columns: List[str] = field(default_factory=list)   # wide mode
    question_column: str = ""
    question_text_manual: str = ""
    question_label_overrides_text: str = ""
    id_column: str = ""
    descriptor_columns: List[str] = field(default_factory=list)
    analyze_one_question: bool = False
    question_filter_value: str = ""

    # -- themes --
    labels_text: str = ""
    per_question_labels_text: str = ""

    # -- engine --
    engine_type: str = "transformer"        # "transformer" | "llm"
    llm_model: str = "llama3.2:3b"
    llm_temperature: float = 0.1
    llm_seed: int = 42

    # -- stages --
    use_sentiment: bool = True
    use_zero_shot: bool = True
    use_question_theme: bool = True
    use_question_zero_shot: bool = False
    save_project_store: bool = True

    # -- strict coding, per engine (scores are not comparable across engines) --
    use_strict_global: bool = False
    use_strict_question: bool = False
    strict_top1_transformer: float = 0.55
    strict_margin_transformer: float = 0.10
    strict_top1_llm: float = 0.70
    strict_margin_llm: float = 0.10
    strict_top1_question: float = 0.60
    strict_margin_question: float = 0.12
    # The global zero-shot pass has its own pair. The desktop fork hardcoded
    # these at the same values; Streamlit exposed them, so they are fields here
    # and both builds keep what they had.
    strict_top1_global: float = 0.55
    strict_margin_global: float = 0.10

    # -- models and batching --
    embedding_model: str = DEFAULT_MODELS["embedding"]
    sentiment_model: str = DEFAULT_MODELS["sentiment"]
    zero_shot_model: str = DEFAULT_MODELS["zero-shot"]
    embedding_batch: int = 32
    inference_batch: int = 16
    min_k: int = 3
    max_k: int = 8

    # -- output --
    report_title: str = "Qualitative Analysis Report"

    # -- privacy: what was done to the working copy before this run --
    pii_masking_applied: bool = False
    pii_pseudonymised: bool = False


def parse_labels(text: str) -> List[str]:
    """One label per line, blanks dropped, order preserved, duplicates removed."""
    seen, out = set(), []
    for line in (text or "").splitlines():
        label = line.strip()
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return out


def parse_per_question_labels(text: str) -> Dict[str, List[str]]:
    """``Question :: Label A | Label B`` per line. Matches upstream's format."""
    out: Dict[str, List[str]] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        question, _sep, labels = line.partition("::")
        parsed = [label.strip() for label in labels.split("|") if label.strip()]
        if question.strip() and parsed:
            out[question.strip()] = parsed
    return out


def mapping_is_ready(df: Optional[pd.DataFrame], settings: RunSettings) -> bool:
    """True when the mapping is complete enough to run."""
    if df is None or df.empty:
        return False
    if settings.ingestion_mode == "wide":
        cols = settings.text_columns or []
        return bool(cols) and all(c in df.columns for c in cols)
    return bool(settings.text_column and settings.text_column in df.columns)


def resolve_long_dataframe(
    df: pd.DataFrame, settings: RunSettings,
) -> Tuple[pd.DataFrame, str, str, str, List[str]]:
    """Reshape to LONG form. Mirrors `app/shared/data.resolve_long_dataframe`.

    Returns ``(long_df, text_column, question_column, id_column, descriptors)``.

    Wide mode melts the selected question columns, and the melt mints a unique
    per-answer `response_id` (respondent + question) plus a `respondent_id` for
    grouping. The unique `response_id` becomes the id column so coding,
    agreement, and store joins cannot collide — the failure that produced this
    project's worst shipped bug.
    """
    from core.ingest import parse_label_overrides, reshape_wide_to_long

    frame = df.copy()
    descriptors = [c for c in settings.descriptor_columns if c in frame.columns]
    id_column = settings.id_column or ""

    if settings.ingestion_mode == "wide":
        question_columns = [c for c in settings.text_columns if c in frame.columns]
        if not question_columns:
            raise ValueError(
                "Wide format: select at least one question column in Data.")
        overrides = parse_label_overrides(settings.question_label_overrides_text)
        long_df = reshape_wide_to_long(
            frame, question_columns, id_column=id_column or None,
            descriptor_columns=descriptors, question_labels=overrides)
        return long_df, "response_text", "question_text", "response_id", descriptors

    if not settings.text_column or settings.text_column not in frame.columns:
        raise ValueError("Select a valid text column in Data.")

    question_column = settings.question_column or ""
    long_df = frame
    if not question_column:
        label = (settings.question_text_manual or "").strip() or "All Responses"
        long_df = frame.copy()
        long_df["question_text"] = label
        question_column = "question_text"
    return long_df, settings.text_column, question_column, id_column, descriptors


def question_values(df: Optional[pd.DataFrame], settings: RunSettings) -> List[str]:
    """Question values available for one-question-at-a-time scope, per mode."""
    from core.ingest import parse_label_overrides

    if df is None or df.empty:
        return []
    if settings.ingestion_mode == "wide":
        overrides = parse_label_overrides(settings.question_label_overrides_text)
        return [overrides.get(c, c) for c in settings.text_columns if c in df.columns]
    column = settings.question_column
    if column and column in df.columns:
        return sorted(df[column].dropna().astype(str).unique().tolist())
    return []


def build_config(
    df: pd.DataFrame,
    settings: RunSettings,
    output_dir: Path,
    *,
    preview: bool = False,
) -> Dict[str, Any]:
    """The `run_pipeline` config for this dataset and these settings.

    Writes the reshaped, filtered frame to ``output_dir/run_input_filtered.csv``
    and points the config at it — the pipeline reads its input from a path, and
    keeping the snapshot inside the run directory means it lives and dies with
    the outputs it produced rather than accumulating in a global folder nobody
    looks at.

    `preview=True` caps the rows and refuses to write a project store, so a quick
    look can never become the project of record.
    """
    labels = parse_labels(settings.labels_text) or list(FALLBACK_LABELS)
    working, text_col, question_col, id_col, descriptors = resolve_long_dataframe(
        df, settings)

    if (settings.analyze_one_question and question_col
            and question_col in working.columns and settings.question_filter_value):
        chosen = str(settings.question_filter_value)
        working = working[working[question_col].astype(str) == chosen].copy()
        if working.empty:
            raise ValueError(
                f"No rows left after filtering for question: '{chosen}'. "
                "Turn off one-question mode or choose another question.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_input = output_dir / "run_input_filtered.csv"
    working.to_csv(run_input, index=False)

    config: Dict[str, Any] = {
        "input": {
            "file_path": str(run_input.resolve()),
            "text_column": text_col,
            "question_column": question_col,
            "id_column": id_col,
            "descriptor_columns": descriptors,
            "encoding": "utf-8",
            "sheet_name": 0,
        },
        "preprocessing": {
            "min_chars": 3,
            "drop_duplicates": False,
            "max_rows": PREVIEW_ROWS if preview else None,
        },
        "models": {
            "embedding_model": settings.embedding_model,
            "sentiment_model": settings.sentiment_model,
            "zero_shot_model": settings.zero_shot_model,
        },
        "pipeline": {
            "embedding_batch_size": int(settings.embedding_batch),
            "inference_batch_size": int(settings.inference_batch),
            "normalize_embeddings": True,
        },
        "clustering": {
            "fixed_k": None,
            "min_k": int(settings.min_k),
            "max_k": int(settings.max_k),
            "random_state": 42,
            "top_terms_per_cluster": 10,
            "sample_quotes_per_cluster": 3,
        },
        "sentiment": {"enabled": bool(settings.use_sentiment)},
        "zero_shot": {
            "enabled": bool(settings.use_zero_shot),
            "multi_label": True,
            "labels": labels,
            "strict_coding": {
                "enabled": bool(settings.use_strict_global),
                "uncertain_label": "UNCERTAIN_REVIEW",
                "top1_min_score": float(settings.strict_top1_global),
                "min_margin_over_second": float(settings.strict_margin_global),
                "allow_multilabel_output": False,
                "min_multilabel_score": 0.50,
                "max_multilabel_labels": 3,
            },
        },
        "thematic_analysis": {
            "by_question": {
                "enabled": bool(settings.use_question_theme),
                "min_responses_per_question": 3,
                "clustering": {
                    "fixed_k": None, "min_k": 2, "max_k": 5, "random_state": 42,
                    "top_terms_per_cluster": 8, "sample_quotes_per_cluster": 2,
                },
            },
            "by_question_zero_shot": {
                "enabled": bool(settings.use_question_zero_shot),
                "multi_label": True,
                "default_labels": labels,
                "labels_by_question": parse_per_question_labels(
                    settings.per_question_labels_text),
                "strict_coding": {
                    "enabled": bool(settings.use_strict_question),
                    "uncertain_label": "UNCERTAIN_REVIEW",
                    "top1_min_score": float(settings.strict_top1_question),
                    "min_margin_over_second": float(settings.strict_margin_question),
                    "allow_multilabel_output": False,
                    "min_multilabel_score": 0.55,
                    "max_multilabel_labels": 2,
                },
            },
        },
        "engine": {
            "type": settings.engine_type,
            "llm": {
                "provider": "ollama",
                "model": settings.llm_model,
                "temperature": float(settings.llm_temperature),
                "seed": int(settings.llm_seed),
                "timeout_seconds": 120,
            },
        },
        # Per-engine strict thresholds. The active engine's pair is overlaid onto
        # strict_coding at run time and both are recorded in the manifest.
        # Transformer scores are NLI entailment; LLM scores are self-report.
        # They are not comparable, which is exactly why they are stored apart.
        "strict_thresholds": {
            "transformer": {
                "top1_min_score": float(settings.strict_top1_transformer),
                "min_margin_over_second": float(settings.strict_margin_transformer),
            },
            "llm": {
                "top1_min_score": float(settings.strict_top1_llm),
                "min_margin_over_second": float(settings.strict_margin_llm),
            },
        },
        "output": {
            "output_dir": str(Path(output_dir).resolve()),
            "save_embeddings": False,
            # A preview must never become the project of record.
            "project_store_path": (
                None if preview or not settings.save_project_store
                else str((Path(output_dir) / "project.qnw").resolve())),
        },
        "report": {"title": settings.report_title},
        # Carried into the run summary and the manifest. Before 4.13 the gate
        # set a flag that nothing carried, so every manifest said no masking
        # had been applied, including after it had.
        "privacy": {"masking_applied": bool(settings.pii_masking_applied),
                    "pseudonymised": bool(settings.pii_pseudonymised)},
    }
    return config


def write_config_snapshot(config: Dict[str, Any], output_dir: Path) -> Path:
    """Record the exact config a run used, beside its outputs (reproducibility)."""
    import json

    path = Path(output_dir) / "run_config.json"
    path.write_text(json.dumps(config, indent=2, default=str), encoding="utf-8")
    return path


#: Seconds per response, MEASURED on a 12-core CPU with the shipped models.
#: These replaced guesses that were wrong by more than an order of magnitude —
#: see `estimate_runtime_minutes`.
SECONDS_PER_ROW_EMBEDDING = 0.012
SECONDS_PER_ROW_SENTIMENT = 0.075

#: Zero-shot is per response **per label**: the NLI model runs once for each
#: pairing. Measured at 3, 6 and 12 labels as 0.259 / 0.245 / 0.236 s per row per
#: label — near enough constant to model as linear, and the single largest cost
#: in the pipeline by a wide margin.
SECONDS_PER_ROW_PER_LABEL_ZERO_SHOT = 0.24

#: One-off model loading, cold. Dominates a small run and is invisible in a
#: per-row figure, which is why a tiny corpus feels slower than the arithmetic
#: suggests.
MODEL_LOAD_SECONDS = 45.0

#: How much faster a CUDA GPU is. **Not measured** — no GPU was available — and
#: labelled as an assumption wherever it is shown.
GPU_SPEEDUP = 6.0


def estimate_runtime_minutes(
    n_rows: int, *, use_sentiment: bool, use_zero_shot: bool,
    use_question_theme: bool, use_question_zero_shot: bool,
    n_labels: int = 6,
) -> Dict[str, str]:
    """Rough CPU/GPU runtime estimate, for the "is this a coffee break" question.

    A range, deliberately: the honest answer depends on the machine, and a
    precise-looking number that is wrong is worse than a range.

    **The constants were guesses and were badly wrong.** The old model charged a
    flat 0.12 s per row for zero-shot regardless of how many labels were being
    applied. Measured on a 12-core CPU with the shipped `bart-large-mnli`, the
    real cost is about **0.24 s per row per label** — because zero-shot runs the
    NLI model once for every (response, label) pairing, so the label count is
    the dominant term and the old estimate ignored it entirely.

    With six labels that is 1.44 s per row against a predicted 0.12: **twelve
    times optimistic**, and worse as labels grow. At five thousand responses the
    old estimate said "about 9-26 minutes" for a run that takes over two hours.
    A researcher reads that, starts the run before a meeting, and comes back to
    a job that is nowhere near done — which is exactly the interrupted long run
    that crash-safe checkpointing exists to survive.

    Erring high is deliberate now: a run that finishes early is a pleasant
    surprise, and one that overruns by an afternoon is a lost afternoon.
    """
    cpu_minutes = max(0.5, estimate_runtime_seconds(
        n_rows, use_sentiment=use_sentiment, use_zero_shot=use_zero_shot,
        use_question_theme=use_question_theme,
        use_question_zero_shot=use_question_zero_shot,
        n_labels=n_labels) / 60.0)
    return {
        "cpu": f"about {_round_range(cpu_minutes)}",
        "gpu": f"about {_round_range(cpu_minutes / GPU_SPEEDUP)}",
    }


def estimate_runtime_seconds(
    n_rows: int, *, use_sentiment: bool, use_zero_shot: bool,
    use_question_theme: bool, use_question_zero_shot: bool,
    n_labels: int = 6,
) -> float:
    """The point estimate the displayed range is built around.

    Separated from the wording because the two are tested differently: the
    number has properties worth pinning (it is monotone in rows, it brackets the
    runs actually observed), and the wording has one property worth pinning,
    which is that a human can read it.
    """
    seconds = MODEL_LOAD_SECONDS + n_rows * SECONDS_PER_ROW_EMBEDDING
    if use_sentiment:
        seconds += n_rows * SECONDS_PER_ROW_SENTIMENT
    labels = max(1, int(n_labels))
    if use_zero_shot:
        seconds += n_rows * labels * SECONDS_PER_ROW_PER_LABEL_ZERO_SHOT
    if use_question_theme:
        seconds += n_rows * SECONDS_PER_ROW_EMBEDDING
    if use_question_zero_shot:
        seconds += n_rows * labels * SECONDS_PER_ROW_PER_LABEL_ZERO_SHOT
    return seconds


#: Above this, the range is quoted in hours. Nobody plans an afternoon in
#: minutes, and "about 77–230 minute(s)" is arithmetic the reader should not
#: have to do while deciding whether to start a run before a meeting.
HOURS_THRESHOLD_MINUTES = 120.0


def _round_range(minutes: float) -> str:
    """A range around the point estimate, in whichever unit reads honestly.

    The multipliers are asymmetric on purpose (0.6x to 1.8x): a run that
    finishes early is a pleasant surprise, and one that overruns by an afternoon
    is a lost afternoon.
    """
    low = max(0.5, minutes * 0.6)
    high = max(1.0, minutes * 1.8)
    if high >= HOURS_THRESHOLD_MINUTES:
        return f"{low / 60.0:.1f}–{high / 60.0:.1f} hours"
    fmt = (lambda v: f"{v:.0f}") if high >= 2 else (lambda v: f"{v:.1f}")
    return f"{fmt(low)}–{fmt(high)} minute(s)"


def load_table(path: Path) -> pd.DataFrame:
    """Load a table, discarding any note about how it was decoded.

    `load_table_with_note` is the variant that keeps the note. This wrapper
    exists because most callers only want the frame, but a caller that shows the
    file to an analyst should use the other one: a cp1252 fallback that nobody
    is told about is exactly the silent-mojibake case `core/encodings.py` exists
    to prevent.
    """
    return load_table_with_note(path)[0]


def load_table_with_note(path: Path) -> Tuple[pd.DataFrame, str]:
    """Load a CSV / Excel / JSON / SPSS file, then strip Qualtrics metadata rows.

    Mirrors `app/shared/io.load_file_from_path` + `postprocess_loaded_df`. The
    Qualtrics strip matters: those header rows are question text and ImportIds,
    and coding them as responses silently pollutes an analysis.
    """
    from core.ingest import strip_qualtrics_metadata

    from core.encodings import read_csv, read_json

    path = Path(path)
    suffix = path.suffix.lower()
    note = ""
    if suffix == ".csv":
        # Not `pd.read_csv`: Excel on Windows writes cp1252 unless the user
        # picks "CSV UTF-8", and a curly apostrophe then raises
        # UnicodeDecodeError on the first screen. See core/encodings.py.
        found = read_csv(path)
        frame, note = found.frame, found.note()
    elif suffix in (".xlsx", ".xls"):
        frame = pd.read_excel(path)
    elif suffix == ".json":
        found = read_json(path)
        frame, note = found.frame, found.note()
    elif suffix == ".sav":
        import pyreadstat

        frame, _meta = pyreadstat.read_sav(str(path))
    else:
        raise ValueError(
            f"Unsupported file type: {suffix} (use .csv, .xlsx, .json, or .sav)")
    stripped, _removed = strip_qualtrics_metadata(frame)
    return stripped, note


SUPPORTED_TABLE_SUFFIXES = (".csv", ".xlsx", ".xls", ".json", ".sav")
