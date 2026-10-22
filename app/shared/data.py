"""
Turning the loaded frame + column mapping into pipeline inputs.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import streamlit as st
from core.label_packs import BUILTIN_PACKS
from core.model_manager import DEFAULT_MODELS as _DEFAULT_MODELS
from core.run_config import (
    RunSettings,
    build_config,
    estimate_runtime_minutes as core_estimate_runtime_minutes,
    parse_labels,
    question_values,
    resolve_long_dataframe as core_resolve_long_dataframe,
)

from app.shared.constants import LABEL_DELIMITER, MIN_ITERATIVE_LABELED_ROWS


def make_suggested_labels() -> Dict[str, List[str]]:
    """Starter label sets for zero-shot thematic coding.

    The content moved to `core.label_packs.BUILTIN_PACKS` — it is a literal with
    no UI in it, and keeping it behind a Streamlit import meant the desktop build
    had to carry a second copy that would drift (PORTED_BACK.md §7).
    """
    return dict(BUILTIN_PACKS)


def parse_labels_from_text(text: str) -> List[str]:
    """One label per line, blanks dropped, order preserved, duplicates removed."""
    return parse_labels(text)


def parse_multilabel_value(value: Any, delimiter: str = LABEL_DELIMITER) -> List[str]:
    """Parse one cell like 'A|B|C' into clean unique labels."""
    if value is None:
        return []
    txt = str(value).strip()
    if not txt:
        return []
    parts = [p.strip() for p in txt.split(delimiter)]
    parts = [p for p in parts if p]
    seen = set()
    out: List[str] = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            out.append(part)
    return out


def estimate_runtime_minutes(
    n_rows: int,
    use_sentiment: bool,
    use_zero_shot: bool,
    use_question_theme: bool,
    use_question_zero_shot: bool,
    n_labels: int = 6,
) -> Dict[str, str]:
    """Approximate local runtime — rough, for expectation setting.

    `n_labels` matters more than anything else here: zero-shot runs the NLI
    model once per (response, label), so doubling the label set doubles the run.
    """
    return core_estimate_runtime_minutes(
        n_rows, use_sentiment=use_sentiment, use_zero_shot=use_zero_shot,
        use_question_theme=use_question_theme,
        use_question_zero_shot=use_question_zero_shot, n_labels=n_labels)


def dataframe_is_ready() -> bool:
    return isinstance(st.session_state.get("df"), pd.DataFrame) and not st.session_state["df"].empty


def mapping_is_ready() -> bool:
    """True when required mapping fields exist for running analysis."""
    if not dataframe_is_ready():
        return False
    df = st.session_state["df"]
    if st.session_state.get("ingestion_mode", "long") == "wide":
        cols = st.session_state.get("text_columns", []) or []
        return bool(cols) and all(c in df.columns for c in cols)
    text_col = st.session_state.get("text_column", "")
    return bool(text_col and text_col in df.columns)


def settings_from_session() -> RunSettings:
    """Everything the pipeline needs, lifted out of `st.session_state` in one place.

    This is the whole of the Streamlit layer's job now. Reading session state
    scattered through the config construction is what made that construction
    untestable and forced the desktop build to reimplement it
    (PORTED_BACK.md §9); confining the reads to one function makes the rest
    ordinary code.
    """
    get = st.session_state.get
    return RunSettings(
        ingestion_mode=get("ingestion_mode", "long"),
        text_column=get("text_column", "") or "",
        text_columns=list(get("text_columns", []) or []),
        question_column=get("question_column", "") or "",
        question_text_manual=get("question_text_manual", "") or "",
        question_label_overrides_text=get("question_label_overrides_text", "") or "",
        id_column=get("id_column", "") or "",
        descriptor_columns=list(get("descriptor_columns", []) or []),
        analyze_one_question=bool(get("analyze_one_question", False)),
        question_filter_value=str(get("question_filter_value", "") or ""),
        labels_text=get("theme_labels_text", "") or "",
        per_question_labels_text=get("adv_per_question_labels_text", "") or "",
        engine_type=get("engine_type", "transformer"),
        llm_model=get("llm_model", "llama3.2:3b"),
        llm_temperature=float(get("llm_temperature", 0.1)),
        llm_seed=int(get("llm_seed", 42)),
        use_sentiment=bool(get("use_sentiment", True)),
        use_zero_shot=bool(get("use_zero_shot", True)),
        use_question_theme=bool(get("use_question_theme", False)),
        use_question_zero_shot=bool(get("use_question_zero_shot", False)),
        save_project_store=bool(get("save_project_store", True)),
        use_strict_global=bool(get("use_strict_global", False)),
        use_strict_question=bool(get("use_strict_question", False)),
        strict_top1_global=float(get("strict_top1_global", 0.55)),
        strict_margin_global=float(get("strict_margin_global", 0.10)),
        strict_top1_transformer=float(get("strict_top1_transformer", 0.55)),
        strict_margin_transformer=float(get("strict_margin_transformer", 0.10)),
        strict_top1_llm=float(get("strict_top1_llm", 0.70)),
        strict_margin_llm=float(get("strict_margin_llm", 0.10)),
        strict_top1_question=float(get("strict_top1_question", 0.60)),
        strict_margin_question=float(get("strict_margin_question", 0.12)),
        embedding_model=get("adv_embedding_model", _DEFAULT_MODELS["embedding"]),
        sentiment_model=get("adv_sentiment_model", _DEFAULT_MODELS["sentiment"]),
        zero_shot_model=get("adv_zero_shot_model", _DEFAULT_MODELS["zero-shot"]),
        embedding_batch=int(get("adv_embedding_batch", 32)),
        inference_batch=int(get("adv_inference_batch", 16)),
        min_k=int(get("adv_min_k", 3)),
        max_k=int(get("adv_max_k", 8)),
        report_title="Streamlit Qualitative Analysis Report",
        pii_masking_applied=bool(get("pii_masking_applied", False)),
        pii_pseudonymised=bool(get("pii_pseudonymised", False)),
    )


def resolve_long_dataframe():
    """Resolve the loaded DataFrame + mapping into LONG shape for the pipeline.

    Returns ``(long_df, text_column, question_column, id_column, descriptors)``.
    The reshaping itself is `core.run_config.resolve_long_dataframe`; this reads
    the mapping out of session state and calls it. Having two implementations of
    the melt that mints `response_id` is the risk PORTED_BACK.md §9 names, and
    this is the collapse of it.
    """
    return core_resolve_long_dataframe(st.session_state["df"], settings_from_session())


def current_question_values() -> List[str]:
    """The question values available for one-question-at-a-time scope, per mode."""
    return question_values(st.session_state.get("df"), settings_from_session())


def build_general_config(output_dir: Path) -> Dict[str, Any]:
    """Build the runtime config for `analyze_survey.run_pipeline`."""
    return build_config(st.session_state["df"], settings_from_session(), output_dir)


def write_config_snapshot(config: Dict[str, Any], output_dir: Path) -> None:
    """Save runtime config for reproducibility."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "config_snapshot.json").write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )


def build_iterative_config(
    input_csv_path: Path,
    question_value: str,
    sample_size: int,
    text_column: str,
    question_column: str,
    id_column: str = "",
) -> Dict[str, Any]:
    """Build config dictionary for iterative supervised workflow.

    Mapping is passed in explicitly (resolved via resolve_long_dataframe) so the
    lab operates on the same long/reshaped data as the main pipeline.
    """
    labels = parse_labels_from_text(st.session_state.get("theme_labels_text", ""))
    cfg: Dict[str, Any] = {
        "input": {
            "file_path": str(input_csv_path.resolve()),
            "text_column": text_column,
            "question_column": question_column,
            "id_column": id_column,
            "encoding": "utf-8",
            "sheet_name": 0,
        },
        "preprocessing": {
            "min_chars": 3,
            "drop_duplicates": False,
            "max_rows": None,
        },
        "iterative_supervised": {
            "question_value": question_value,
            "sample_size": int(sample_size),
            "random_state": 42,
            "label_delimiter": LABEL_DELIMITER,
            "minimum_labeled_rows": MIN_ITERATIVE_LABELED_ROWS,
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "embedding_batch_size": 32,
            "probability_threshold": 0.45,
            "uncertain_label": "UNCERTAIN_REVIEW",
            "output_dir": st.session_state["iterative_output_dir"],
            "unsupervised": {
                "fixed_k": None,
                "min_k": 2,
                "max_k": 5,
                "random_state": 42,
                "top_terms_per_cluster": 8,
                "sample_quotes_per_cluster": 3,
            },
        },
    }
    if labels:
        cfg["iterative_supervised"]["seed_labels"] = labels
    return cfg


def load_coding_sample_df(iterative_output_dir: Path) -> pd.DataFrame:
    """Load coding sample CSV as all-text, so ids and labels survive round-trips.

    Read as strings with NA filtering off. This fixes a data-corruption bug: with
    default inference, a `response_id` column of numbers is read as float, so
    "101" comes back as 101.0 → "101.0" — a different key than the widgets and the
    save mapping use, which made codes vanish and duplicated ids as "nan". Reading
    everything as text keeps ids stable and empty label cells as "" (not NaN).
    """
    sample_path = iterative_output_dir / "coding_sample.csv"
    if not sample_path.exists():
        return pd.DataFrame()
    from core.encodings import read_csv_as_text

    # With the encoding fallback too: the analyst may have edited it in Excel.
    return read_csv_as_text(sample_path).frame


def summarize_coding_progress(coding_df: pd.DataFrame) -> Dict[str, Any]:
    """Compute progress metrics from human_labels."""
    if coding_df.empty or "human_labels" not in coding_df.columns:
        return {
            "total_rows": 0,
            "labeled_rows": 0,
            "unlabeled_rows": 0,
            "label_counts": {},
        }

    label_lists = coding_df["human_labels"].apply(parse_multilabel_value)
    labeled_mask = label_lists.apply(lambda x: len(x) > 0)
    labeled_rows = int(labeled_mask.sum())
    total_rows = int(len(coding_df))
    unlabeled_rows = int(total_rows - labeled_rows)

    counts: Dict[str, int] = {}
    for labels in label_lists:
        for label in labels:
            counts[label] = counts.get(label, 0) + 1

    return {
        "total_rows": total_rows,
        "labeled_rows": labeled_rows,
        "unlabeled_rows": unlabeled_rows,
        "label_counts": counts,
    }


def build_saved_sample(coding_df: pd.DataFrame, labels_map: Dict[str, List[str]],
                       notes_map: Dict[str, str]) -> pd.DataFrame:
    """The coding sample with the analyst's current labels/notes applied.

    One serialization used by BOTH the autosave write-through and the manual save
    button, so what's on disk never depends on which path wrote it.
    """
    out = coding_df.copy()
    out["human_labels"] = out["response_id"].map(
        lambda r: LABEL_DELIMITER.join(labels_map.get(r, [])))
    out["coder_notes"] = out["response_id"].map(lambda r: notes_map.get(r, ""))
    return out
