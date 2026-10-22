#!/usr/bin/env python
"""
Local qualitative survey analysis pipeline using BERT-style transformer tooling.

What this script does:
1) Loads a survey file (CSV/TSV/Excel/JSON).
2) Builds semantic embeddings with a local SentenceTransformer model.
3) Clusters responses to discover themes.
4) Optionally runs sentiment classification.
5) Optionally runs zero-shot thematic tagging with your custom labels.
6) Exports response-level and summary outputs.

This is intentionally verbose and commented so it can be reused as a template.

Beginner glossary:
- Embedding: numeric representation of a response's meaning.
- Clustering: unsupervised grouping of semantically similar responses.
- Zero-shot labels: user-defined theme labels assigned by an NLI model.
- Strict coding: confidence rules that route ambiguous responses to a review bucket.

Recommended first run for beginners:
1) Use the sample data and default config.
2) Open output/run_report.md and cluster_summary.csv.
3) Enable question-level thematic analysis.
4) Enable strict coding to create an analyst review queue.

v2 changes vs v1:
- Pandas chained-assignment patterns replaced throughout (pandas 3.x safe).
- k-selection loop now emits TQDM progress so CPU users see it is running.
- run_question_level_zero_shot raises a visible warning (not silent skip) when
  a question has no labels configured.
- post-run question coding summary returned from run_pipeline for callers.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import yaml
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from tqdm import tqdm


LOGGER = logging.getLogger("survey_nlp")


# ---------------------------------------------------------------------------#
# Deferred heavy imports                                                      #
# ---------------------------------------------------------------------------#
# sentence_transformers and transformers pull in torch (slow, and only needed
# when a model actually runs). They also read the HF_HUB_OFFLINE /
# TRANSFORMERS_OFFLINE environment at import time, so importing them at module
# scope would freeze those settings before an entry point can call
# core.offline.enforce_local_mode(). Both names stay module-level attributes
# because tests monkeypatch `analyze_survey.SentenceTransformer` and
# `analyze_survey.pipeline` as their single mock point.
SentenceTransformer = None
pipeline = None


def _get_sentence_transformer():
    """Resolve SentenceTransformer, importing on first real use."""
    global SentenceTransformer
    if SentenceTransformer is None:
        from sentence_transformers import SentenceTransformer as _SentenceTransformer

        SentenceTransformer = _SentenceTransformer
    return SentenceTransformer


def _get_pipeline():
    """Resolve the transformers pipeline factory, importing on first real use."""
    global pipeline
    if pipeline is None:
        from transformers import pipeline as _pipeline

        pipeline = _pipeline
    return pipeline


class ModelNotDownloadedError(RuntimeError):
    """A model isn't in the local cache and offline mode forbids fetching it."""

    def __init__(self, model_name: str):
        super().__init__(
            f"The model '{model_name}' is not in your local cache, and this tool "
            f"does not download models while analyzing your data.\n\n"
            f"Run the one-time model setup step (which is the only part of this "
            f"tool that touches the network):\n"
            f"    python tools/download_models.py\n\n"
            f"In the app, use the 'Model status' panel on the Run Analysis page. "
            f"See README section 'Model setup' for details."
        )
        self.model_name = model_name


def _is_missing_model_error(exc: BaseException) -> bool:
    """True when an exception looks like 'model absent from the offline cache'.

    huggingface_hub raises LocalEntryNotFoundError (an OSError subclass) here,
    but the class has moved between versions, so match on the message instead of
    importing it — a wrong guess would turn a real error into a confusing one.
    """
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "cannot find the requested files in the cached path",
            "localentrynotfounderror",
            "offline mode is enabled",
            "couldn't connect to",
            "we couldn't connect",
            "is not a local folder and is not a valid model identifier",
        )
    )


def _load_model(model_name: str, loader):
    """Call `loader()`, translating a missing-cache failure into a fixable message."""
    try:
        return loader()
    except ModelNotDownloadedError:
        raise
    except (OSError, ValueError) as exc:
        if _is_missing_model_error(exc):
            raise ModelNotDownloadedError(model_name) from exc
        raise


# ------------------------------#
# Configuration + IO Utilities  #
# ------------------------------#

def load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file into a dictionary."""
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must load to a dictionary: {path}")
    return data


def ensure_output_dir(path: Path) -> None:
    """Create output directory if missing."""
    path.mkdir(parents=True, exist_ok=True)


def read_input_table(config: Dict[str, Any]) -> pd.DataFrame:
    """
    Read tabular data according to config.

    Supported extensions:
    - .csv
    - .tsv
    - .xlsx / .xls
    - .json (records-friendly)
    """
    input_cfg = config["input"]
    file_path = Path(input_cfg["file_path"]).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    ext = file_path.suffix.lower()
    encoding = input_cfg.get("encoding", "utf-8")

    # Not a bare `pd.read_csv`. Excel on Windows writes cp1252 unless the user
    # picked "CSV UTF-8", and the config's `encoding:` key says utf-8 because
    # the shipped example says so and nobody edits it — so the configured value
    # is tried first and the fallback still catches the common case.
    #
    # Found by running the pipeline against an Excel-written file. The fallback
    # had reached `core.run_config.load_table` and `app.shared.io` and NOT this
    # one, which is the loader the pipeline actually uses — while a test whose
    # docstring said otherwise passed.
    from core.encodings import read_csv as read_csv_with_fallback

    if ext in {".csv", ".tsv"}:
        found = read_csv_with_fallback(
            file_path, preferred=encoding,
            sep="\t" if ext == ".tsv" else ",")
        df = found.frame
        if found.note():
            LOGGER.warning(found.note())
    elif ext in {".xlsx", ".xls"}:
        sheet_name = input_cfg.get("sheet_name", 0)
        df = pd.read_excel(file_path, sheet_name=sheet_name)
    elif ext == ".json":
        df = pd.read_json(file_path)
    else:
        raise ValueError(f"Unsupported file type '{ext}' for {file_path}")

    return df


# ----------------------------------#
# Data Preparation + Preprocessing  #
# ----------------------------------#

def clean_text(text: str) -> str:
    """
    Minimal text normalization for survey responses.

    We intentionally keep this lightweight so that meaning-rich phrasing
    remains intact for embedding and clustering.
    """
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_for_csv(value: str) -> str:
    """
    Prevent CSV formula injection (also called CSV injection or Excel injection).

    When a cell value begins with =, +, -, or @, spreadsheet applications like
    Excel or Google Sheets may interpret it as a formula. An attacker or
    accidental response like '=CMD|"/C calc"!A1' could execute on the analyst's
    machine when opened.

    Fix: prefix dangerous-leading characters with a single quote so the value
    is treated as plain text. The quote is invisible in most spreadsheet views.

    References: OWASP CSV Injection
    """
    if not isinstance(value, str):
        return value
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def clean_id_str(value: Any) -> str:
    """Normalize one id value to a stable string. Missing → "".

    Response ids are the join key between the coding CSV, the model output, and the
    project store, so they must survive a CSV round-trip unchanged. The trap:
    pandas reads a numeric-looking id column as float, so 101 becomes 101.0 and
    `str()` yields "101.0" — a different key than the "101" written elsewhere.
    Whole-number floats are therefore rendered without the ".0". Sentinels that
    pandas produces for missing cells ("nan"/"None") collapse to "" so the caller
    can substitute a real id.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none", "") else text


def clean_id_series(series: "pd.Series") -> "pd.Series":
    """Vectorized `clean_id_str` over a column, preserving the index."""
    return series.map(clean_id_str)


def sanitize_frame_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with every string cell sanitized against CSV injection.

    Column selection is by exclusion, not inclusion. The previous version picked
    columns with `select_dtypes(include="object")`, which silently misses text
    held in pandas' newer `StringDtype` — and pandas 3 makes that dtype the
    default for string columns, so the guard would have quietly stopped covering
    the response text it exists to protect. Naming the dtypes that *cannot* hold a
    string is a much smaller, more stable set than naming the ones that can.

    The per-value isinstance check does the real work, so an unrecognized
    extension dtype is handled correctly rather than skipped. Numeric columns are
    left untouched (both by the skip and by the guard) — coercing them to strings
    would break numeric parsing in Excel.
    """
    from pandas.api.types import (
        is_bool_dtype,
        is_datetime64_any_dtype,
        is_numeric_dtype,
        is_timedelta64_dtype,
    )

    out = df.copy()
    for col in out.columns:
        dtype = out[col].dtype
        if (
            is_numeric_dtype(dtype)
            or is_bool_dtype(dtype)
            or is_datetime64_any_dtype(dtype)
            or is_timedelta64_dtype(dtype)
        ):
            continue
        out[col] = out[col].map(lambda v: sanitize_for_csv(v) if isinstance(v, str) else v)
    return out


def prepare_dataset(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Select the configured text column and produce standardized fields:
    - response_id
    - response_text
    """
    input_cfg = config["input"]
    prep_cfg = config.get("preprocessing", {})

    text_col = input_cfg["text_column"]
    id_col = input_cfg.get("id_column")
    question_col = input_cfg.get("question_column")

    if text_col not in df.columns:
        raise KeyError(
            f"Configured text column '{text_col}' is not in input columns: {list(df.columns)}"
        )

    # Build response_id even if a column is not provided.
    if id_col and id_col in df.columns:
        response_ids = clean_id_series(df[id_col])
        # A blank/missing id would stringify to "nan"/"None" and collide across
        # rows, so those rows get a unique positional id instead. Without this a
        # single missing id silently duplicates, and the CSV/agreement join keys
        # on it break downstream.
        missing = response_ids == ""
        if missing.any():
            positional = pd.Series([f"row_{i}" for i in range(len(df))], index=df.index)
            response_ids = response_ids.where(~missing, positional)
            LOGGER.warning(
                "ID column '%s' had %d missing/blank value(s); those rows were given "
                "positional ids (row_N) so every response stays uniquely addressable.",
                id_col, int(missing.sum()),
            )
        # Auto-generated ids are positional and therefore unique; a user-supplied
        # column carries no such guarantee. response_id is the join key for the
        # agreement module and for the project store, where a collision silently
        # merges two respondents' codes. Warn at ingestion, where it is still
        # cheap to fix, rather than letting it surface as a wrong kappa later.
        duplicated = response_ids.duplicated()
        if duplicated.any():
            examples = response_ids[duplicated].unique()[:5].tolist()
            LOGGER.warning(
                "ID column '%s' has %d duplicate value(s) across %d rows (e.g. %s). "
                "Response ids are used to join human codes to model codes; duplicates "
                "can merge distinct respondents. Consider using a unique id column, or "
                "leaving id_column unset to auto-generate positional ids.",
                id_col,
                int(response_ids.duplicated().sum()),
                len(response_ids),
                ", ".join(examples),
            )
    else:
        response_ids = pd.Series(np.arange(len(df)), index=df.index).astype(str)

    work = pd.DataFrame({
        "response_id": response_ids,
        "response_text": df[text_col].fillna("").astype(str),
    })

    # Optional question column.
    if question_col and question_col in df.columns:
        work = work.assign(question_text=df[question_col].fillna("Unspecified Question").astype(str))
    else:
        work = work.assign(question_text="All Responses")

    # Optional descriptor columns (v3): carry designated non-text columns through
    # so every response stays tagged with its source's metadata (program, class
    # year, etc.) for downstream code x descriptor analysis. Added before the
    # row filters below so descriptors ride along through filtering/dedup.
    # No-op when unset, so default behavior (and v2.1 outputs) is unchanged.
    descriptor_cols = input_cfg.get("descriptor_columns", []) or []
    for col in descriptor_cols:
        if col in df.columns and col not in work.columns:
            work[col] = df[col].to_numpy()

    # Carry respondent_id through when present (wide-form ingestion emits it), so a
    # person's answers across questions can be grouped downstream (Feature B). It
    # is distinct from response_id, which is unique per answer. No-op when absent,
    # so long-format / v2.1 behavior is unchanged.
    if "respondent_id" in df.columns and "respondent_id" not in work.columns:
        work["respondent_id"] = df["respondent_id"].astype(str).to_numpy()

    # Basic cleaning.
    work = work.assign(
        response_text=work["response_text"].map(clean_text),
        question_text=work["question_text"].map(clean_text),
    )

    # Remove blank or too-short responses.
    min_chars = int(prep_cfg.get("min_chars", 3))
    work = work[work["response_text"].str.len() >= min_chars].copy()

    # v2 fix: deduplicate on (response_text + question_text) so that common
    # short answers like "N/A", "None", or "Yes" are not dropped when they
    # appear under different survey questions. Default changed to False because
    # in multi-question surveys deduplication is almost never the right default.
    if prep_cfg.get("drop_duplicates", False):
        work = work.drop_duplicates(subset=["response_text", "question_text"]).copy()

    max_rows = prep_cfg.get("max_rows")
    if max_rows is not None:
        work = work.head(int(max_rows)).copy()

    work.reset_index(drop=True, inplace=True)
    return work


# ------------------------#
# Embeddings + Clustering #
# ------------------------#

def count_unique_texts(texts: Sequence[str]) -> Tuple[int, int]:
    """Return (total, unique) text counts — reported so duplicate mass is visible."""
    items = list(texts)
    return len(items), len(set(items))


# Provisional per-engine strict-coding defaults (Phase 2.4). LLM self-report
# scores cluster high, so its top-1 floor starts higher than the NLI entailment
# floor. Marked provisional pending calibration data.
DEFAULT_STRICT_THRESHOLDS = {
    "transformer": {"top1_min_score": 0.55, "min_margin_over_second": 0.10},
    "llm": {"top1_min_score": 0.70, "min_margin_over_second": 0.10},
}


def apply_engine_strict_thresholds(config: Dict[str, Any], engine_type: str) -> None:
    """Overlay the active engine's strict thresholds onto the strict_coding blocks.

    Config may carry a per-engine block::

        strict_thresholds:
          transformer: {top1_min_score: 0.55, min_margin_over_second: 0.10}
          llm:         {top1_min_score: 0.70, min_margin_over_second: 0.10}

    When present, the active engine's values are written into
    `zero_shot.strict_coding` (and the question-level block) so the existing gate
    reads the right pair, and the manifest records it. This is deliberately
    idempotent and in-place.

    Back-compat: a legacy flat `zero_shot.strict_coding` with no `strict_thresholds`
    is left untouched — those values apply to whichever engine runs (with a note).
    Mutates `config`.
    """
    per_engine = config.get("strict_thresholds")
    if not per_engine:
        return  # legacy flat shape: nothing to overlay
    active = per_engine.get(engine_type) or DEFAULT_STRICT_THRESHOLDS.get(engine_type, {})
    if not active:
        return

    def _overlay(block: Optional[Dict[str, Any]]) -> None:
        if isinstance(block, dict) and block.get("enabled"):
            for key in ("top1_min_score", "min_margin_over_second"):
                if key in active:
                    block[key] = active[key]

    _overlay((config.get("zero_shot", {}) or {}).get("strict_coding"))
    qz = ((config.get("thematic_analysis", {}) or {})
          .get("by_question_zero_shot", {}) or {})
    _overlay(qz.get("strict_coding"))


def build_embeddings(
    texts: Sequence[str],
    model_name: str,
    batch_size: int,
    normalize_embeddings: bool,
    dedupe: bool = False,
) -> np.ndarray:
    """
    Generate sentence embeddings using a local model, one row per input text.

    Models are read from the local cache (see core/offline.py); the one-time
    download is a separate setup step.

    `dedupe` encodes each distinct text once and broadcasts the vector back to
    every row holding that text. On a dataset where one answer repeats heavily
    ("None" x 80) that is a large compute saving for an identical result — in
    theory. It is **off by default**, deliberately:

    Encoding ["a", "a", "b"] and encoding ["a", "b"] are not guaranteed to
    produce bit-identical vectors. Batch composition changes padding, and
    floating-point addition is not associative, so vectors can differ in their
    last few bits. That is normally irrelevant, but k-means assigns a point
    sitting almost equidistant between two centroids by a hair — so a last-bit
    difference can move a response into a different theme. For a tool whose
    outputs get written up in reports, a run that silently produces different
    themes depending on an optimization flag is a credibility problem worth more
    than the saved seconds.

    So: correctness-preserving in expectation, not guaranteed reproducible.
    Analysts who want the speedup on large, duplicate-heavy datasets can opt in
    via `pipeline.dedupe_embeddings: true`, and the choice is recorded in the run
    manifest.
    """
    items = list(texts)
    LOGGER.info("Loading embedding model: %s", model_name)
    model = _load_model(model_name, lambda: _get_sentence_transformer()(model_name))

    if not dedupe:
        return model.encode(
            items,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=normalize_embeddings,
            convert_to_numpy=True,
        )

    # np.unique would sort and coerce dtypes; this keeps first-seen order and
    # leaves the strings alone.
    seen: Dict[str, int] = {}
    inverse: List[int] = []
    unique_texts: List[str] = []
    for text in items:
        if text not in seen:
            seen[text] = len(unique_texts)
            unique_texts.append(text)
        inverse.append(seen[text])

    LOGGER.info(
        "Embedding %d unique texts for %d responses (dedupe enabled).",
        len(unique_texts),
        len(items),
    )
    unique_embeddings = model.encode(
        unique_texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=normalize_embeddings,
        convert_to_numpy=True,
    )
    return np.asarray(unique_embeddings)[np.asarray(inverse, dtype=int)]


def choose_cluster_k(
    embeddings: np.ndarray,
    min_k: int,
    max_k: int,
    random_state: int,
    progress=None,
) -> Tuple[int, Dict[int, float]]:
    """
    Automatically choose k using silhouette score.

    v2: uses TQDM so users can see progress during the search loop.

    Returns:
    - best_k
    - all tested scores by k
    """
    n_samples = len(embeddings)
    upper_k = max(2, min(max_k, n_samples - 1))
    lower_k = max(2, min(min_k, upper_k))

    if n_samples < 3 or lower_k > upper_k:
        return 2, {}

    scores: Dict[int, float] = {}
    k_range = list(range(lower_k, upper_k + 1))
    for i, k in enumerate(tqdm(k_range, desc="Searching cluster k", unit="k")):
        model = KMeans(n_clusters=k, n_init=10, random_state=random_state)
        labels = model.fit_predict(embeddings)
        if len(np.unique(labels)) >= 2:
            score = silhouette_score(embeddings, labels)
            scores[k] = float(score)
        if progress is not None:
            # Per-k movement for the GUI: this loop (silhouette is O(n²)) is the
            # slow, formerly-frozen stage on larger datasets.
            progress(i + 1, len(k_range))

    if not scores:
        return lower_k, {}

    best_k = max(scores, key=scores.get)
    return best_k, scores


def fit_clusters(
    embeddings: np.ndarray,
    cluster_cfg: Dict[str, Any],
    progress=None,
) -> Tuple[np.ndarray, KMeans, Dict[int, float]]:
    """Fit clustering and return labels, model, and silhouette-by-k diagnostics."""
    min_k = int(cluster_cfg.get("min_k", 3))
    max_k = int(cluster_cfg.get("max_k", 8))
    random_state = int(cluster_cfg.get("random_state", 42))
    fixed_k = cluster_cfg.get("fixed_k")

    if fixed_k is None:
        best_k, scores = choose_cluster_k(embeddings, min_k, max_k, random_state, progress=progress)
    else:
        best_k = int(fixed_k)
        scores = {}

    LOGGER.info("Clustering with k=%s", best_k)
    clusterer = KMeans(n_clusters=best_k, n_init=15, random_state=random_state)
    labels = clusterer.fit_predict(embeddings)
    return labels, clusterer, scores


def extract_top_terms_by_cluster(
    texts: Sequence[str],
    labels: Sequence[int],
    max_terms: int,
    ngram_range: Tuple[int, int] = (1, 2),
) -> Dict[int, List[str]]:
    """
    Extract top TF-IDF terms within each cluster for quick human-readable theme hints.
    """
    labels_arr = np.array(labels)
    unique_ids = [int(x) for x in sorted(np.unique(labels_arr))]

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=ngram_range,
        min_df=2,
        max_df=0.9,
    )
    try:
        matrix = vectorizer.fit_transform(texts)
        features = np.array(vectorizer.get_feature_names_out())
    except ValueError:
        return {cluster_id: [] for cluster_id in unique_ids}

    top_terms: Dict[int, List[str]] = {}
    for cluster_id in unique_ids:
        cluster_mask = labels_arr == cluster_id
        if cluster_mask.sum() == 0:
            top_terms[int(cluster_id)] = []
            continue
        mean_scores = np.asarray(matrix[cluster_mask].mean(axis=0)).ravel()
        best_idx = mean_scores.argsort()[::-1][:max_terms]
        top_terms[int(cluster_id)] = [features[i] for i in best_idx if mean_scores[i] > 0]
    return top_terms


def representative_examples(
    texts: Sequence[str],
    labels: Sequence[int],
    embeddings: np.ndarray,
    centers: np.ndarray,
    per_cluster: int,
) -> Dict[int, List[str]]:
    """
    Pick representative quotes closest to each cluster centroid.
    """
    labels_arr = np.array(labels)
    reps: Dict[int, List[str]] = {}

    for cluster_id in sorted(np.unique(labels_arr)):
        cluster_idx = np.where(labels_arr == cluster_id)[0]
        if len(cluster_idx) == 0:
            reps[int(cluster_id)] = []
            continue

        cluster_vectors = embeddings[cluster_idx]
        centroid = centers[int(cluster_id)]
        dists = np.linalg.norm(cluster_vectors - centroid, axis=1)
        best_local = np.argsort(dists)[:per_cluster]
        reps[int(cluster_id)] = [texts[cluster_idx[i]] for i in best_local]

    return reps


def flag_outliers(
    embeddings: np.ndarray,
    labels: Sequence[int],
    centers: np.ndarray,
    percentile: float = 90.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Flag responses that sit far from their assigned cluster centroid.

    A cheap, dependency-free stand-in for noise-aware clustering (HDBSCAN): k-means
    forces every response into *some* theme, but a response can be far from all of
    them — genuinely off-topic, or a theme of its own. Distance to the assigned
    centroid is a usable "how well does this belong?" signal. A response is flagged
    when its distance exceeds the `percentile` of distances *within its own
    cluster*, so the threshold adapts to each cluster's tightness rather than one
    global cutoff.

    Returns ``(distances, is_outlier)`` aligned to the input rows. The flagged rows
    are the "belongs to no theme?" review list — often the most interesting cases.
    """
    labels_arr = np.asarray(labels)
    n = len(labels_arr)
    distances = np.zeros(n, dtype=float)
    is_outlier = np.zeros(n, dtype=bool)
    if n == 0:
        return distances, is_outlier

    for cluster_id in np.unique(labels_arr):
        idx = np.where(labels_arr == cluster_id)[0]
        centroid = centers[int(cluster_id)]
        d = np.linalg.norm(embeddings[idx] - centroid, axis=1)
        distances[idx] = d
        if len(d) >= 5:  # a threshold on 1–4 points is meaningless
            cutoff = np.percentile(d, percentile)
            is_outlier[idx] = d > cutoff
    return distances, is_outlier


# --------------------------#
# Optional Transformer Heads#
# --------------------------#

def run_sentiment(
    texts: Sequence[str],
    model_name: str,
    batch_size: int,
    cache: Any = None,
) -> List[Dict[str, Any]]:
    """
    Run sentiment classification.

    `cache`, when given, is a `core.inference_cache.InferenceCache`. Responses
    already scored by this model are served from it and only the rest are sent
    to the model, so a re-run, a resumed run, or a run over a lightly edited
    file pays for what changed rather than for everything.
    """
    texts = list(texts)
    if cache is None or not getattr(cache, "enabled", False):
        return _run_sentiment_uncached(texts, model_name, batch_size)

    from core.inference_cache import sentiment_key

    keys = [sentiment_key(model_name, text) for text in texts]
    found = cache.get_many(keys)
    todo = [i for i, key in enumerate(keys) if key not in found]
    if todo:
        LOGGER.info("Sentiment: %d cached, %d to compute.",
                    len(texts) - len(todo), len(todo))
        fresh = _run_sentiment_uncached(
            [texts[i] for i in todo], model_name, batch_size)
        cache.put_many("sentiment",
                       ((keys[i], fresh[n]) for n, i in enumerate(todo)))
        for n, i in enumerate(todo):
            found[keys[i]] = fresh[n]
    else:
        LOGGER.info("Sentiment: all %d responses served from cache.", len(texts))
    return [dict(found[key]) for key in keys]


def _run_sentiment_uncached(
    texts: Sequence[str],
    model_name: str,
    batch_size: int,
) -> List[Dict[str, Any]]:
    """The model call itself, unchanged from v2.1."""
    texts = list(texts)
    if not texts:
        return []
    LOGGER.info("Loading sentiment model: %s", model_name)
    clf = _load_model(
        model_name,
        lambda: _get_pipeline()(
            "sentiment-analysis",
            model=model_name,
            truncation=True,
        ),
    )
    results = clf(list(texts), batch_size=batch_size)
    return [dict(r) for r in results]


def run_zero_shot(
    texts: Sequence[str],
    labels: Sequence[str],
    model_name: str,
    multi_label: bool,
    batch_size: int,
) -> List[Dict[str, Any]]:
    """
    Run zero-shot classification using user-specified label set.
    """
    LOGGER.info("Loading zero-shot model: %s", model_name)
    if not labels:
        raise ValueError("zero_shot.labels is empty. Add labels or disable zero-shot.")

    zsc = _load_model(
        model_name,
        lambda: _get_pipeline()(
            "zero-shot-classification",
            model=model_name,
            truncation=True,
        ),
    )
    return run_zero_shot_with_pipeline(
        zsc=zsc,
        texts=texts,
        labels=labels,
        multi_label=multi_label,
        batch_size=batch_size,
    )


def run_zero_shot_with_pipeline(
    zsc: Any,
    texts: Sequence[str],
    labels: Sequence[str],
    multi_label: bool,
    batch_size: int,
    progress=None,
    cache: Any = None,
    resume_callback=None,
    model_id: Optional[str] = None,
    zsc_builder: Any = None,
) -> List[Dict[str, Any]]:
    """Run zero-shot using an already-loaded pipeline (faster for repeated calls).

    `progress(done, total)`, when given, drives a per-response progress bar. Each
    text is classified independently (NLI per text × label), so processing the
    list in chunks and concatenating is identical to one call — chunking only
    exists to report progress between chunks. With `progress=None` and no cache
    the original single call is used unchanged, so the default/CLI path stays
    byte-identical.

    `cache`, when given, is a `core.inference_cache.InferenceCache`. This is the
    stage worth caching: on a 5,000-response run with six labels it is roughly
    94% of the wall clock, and it was the one stage that had no cache at all.
    """
    texts = list(texts)
    if not labels:
        raise ValueError("candidate label list is empty")

    if cache is not None and getattr(cache, "enabled", False):
        return _run_zero_shot_cached(
            zsc, texts, list(labels), multi_label, batch_size, progress, cache,
            resume_callback, model_id, zsc_builder)

    zsc = _resolve_pipeline(zsc, zsc_builder)

    if progress is None:
        results = zsc(
            texts,
            candidate_labels=list(labels),
            multi_label=multi_label,
            batch_size=batch_size,
        )
        if isinstance(results, dict):
            results = [results]
        return [dict(r) for r in results]

    total = len(texts)
    step = max(int(batch_size), 1)
    out: List[Dict[str, Any]] = []
    for start in range(0, total, step):
        chunk = texts[start:start + step]
        res = zsc(
            chunk,
            candidate_labels=list(labels),
            multi_label=multi_label,
            batch_size=batch_size,
        )
        if isinstance(res, dict):
            res = [res]
        out.extend(dict(r) for r in res)
        progress(min(start + len(chunk), total), total)
    return out


def _run_zero_shot_cached(
    zsc: Any,
    texts: List[str],
    labels: List[str],
    multi_label: bool,
    batch_size: int,
    progress,
    cache: Any,
    resume_callback=None,
    model_id: Optional[str] = None,
    zsc_builder: Any = None,
) -> List[Dict[str, Any]]:
    """Zero-shot, paying only for the (response, label) pairs not already known.

    Under `multi_label=True` the outstanding work is per label, so extending a
    codebook from six labels to seven costs one label's worth of inference
    rather than seven. That matters because iterating the codebook *is* the
    method — an analyst who has to choose between a better codebook and a
    two-hour wait will choose the wait once and then stop refining.

    Results are committed as each group finishes, so an interrupted run keeps
    everything it had already computed. That is the difference between a laptop
    that slept through a long run costing five minutes and costing the run.
    """
    from core.inference_cache import (
        as_result, plan_zero_shot, zero_shot_key)

    # A codebook with the same label twice is a copy-paste away, and the cached
    # path keys scores by label — so a duplicate would collapse into one entry
    # and quietly change the shape of the output. Dropped here, loudly, rather
    # than allowed to differ from the uncached path in silence.
    deduped = list(dict.fromkeys(labels))
    if len(deduped) != len(labels):
        LOGGER.warning("Duplicate labels in the codebook were ignored: %s",
                       ", ".join(sorted(set(labels))))
        labels = deduped

    # Built at most once, and only if something actually needs it.
    resolved: List[Any] = []

    def pipeline() -> Any:
        if not resolved:
            resolved.append(_resolve_pipeline(zsc, zsc_builder))
        return resolved[0]

    # `model_id` lets the caller name the model without building it, which is
    # the whole reason a fully cached run can skip loading a 1.6 GB NLI model it
    # has no work for. Measured: 25.4 s of a 25.4 s warm run was that load.
    # Without it there is no way to key the cache except to ask the pipeline,
    # which means building it -- so the engine supplies the name.
    model_name = model_id or _pipeline_model_id(pipeline())
    keys: List[str] = []
    for text in texts:
        if multi_label:
            keys.extend(zero_shot_key(model_name, text, [label], True)
                        for label in labels)
        else:
            keys.append(zero_shot_key(model_name, text, labels, False))

    known, outstanding = plan_zero_shot(
        texts, labels, model_name, multi_label, cache.get_many(keys))

    total = len(texts)
    done_before = total - len(outstanding)
    LOGGER.info("Zero-shot: %d/%d responses fully cached, %d to compute.",
                done_before, total, len(outstanding))

    # Say so. A run that died at ninety minutes and silently restarts fast is
    # good; one that states what it is skipping is honest, and the difference
    # matters when the analyst is deciding whether to trust the output of a job
    # they did not watch. The LLM engine on the portable branch has announced
    # this since its checkpointing landed; this is the same message for the
    # transformer path.
    if done_before and resume_callback is not None:
        resume_callback(done_before, total)

    if progress is not None:
        progress(done_before, total)

    # Grouped by the labels still missing, because the pipeline takes one
    # candidate set per call. Responses missing the same labels — the common
    # case by far, since a codebook change affects every response alike — batch
    # together.
    groups: Dict[Tuple[str, ...], List[int]] = {}
    for index, missing in outstanding:
        groups.setdefault(tuple(missing), []).append(index)

    completed = done_before
    step = max(int(batch_size), 1)
    for missing_labels, indices in groups.items():
        for start in range(0, len(indices), step):
            chunk_indices = indices[start:start + step]
            # `pipeline()` builds on first use. With nothing outstanding this
            # loop never runs, so the model is never touched and a repeat run
            # costs seconds rather than the load it would pay for no reason.
            res = pipeline()(
                [texts[i] for i in chunk_indices],
                candidate_labels=list(missing_labels),
                multi_label=multi_label,
                batch_size=batch_size,
            )
            if isinstance(res, dict):
                res = [res]

            writes: List[Tuple[str, Any]] = []
            for offset, index in enumerate(chunk_indices):
                item = dict(res[offset])
                scores = dict(zip([str(x) for x in item.get("labels", [])],
                                  [float(x) for x in item.get("scores", [])]))
                known[index].update(scores)
                if multi_label:
                    writes.extend(
                        (zero_shot_key(model_name, texts[index], [label], True),
                         score)
                        for label, score in scores.items())
                else:
                    writes.append(
                        (zero_shot_key(model_name, texts[index], labels, False),
                         scores))
            cache.put_many("zero_shot", writes)

            completed += len(chunk_indices)
            if progress is not None:
                progress(min(completed, total), total)

    return [as_result(text, known[i]) for i, text in enumerate(texts)]


def _resolve_pipeline(zsc: Any, builder: Any = None) -> Any:
    """The loaded pipeline: the one passed in, or the one the builder makes.

    Deliberately explicit. The first version sniffed for a callable without a
    `model` attribute, and that broke immediately on a test double that *is* a
    bare function — a pipeline is itself callable, so there is no honest way to
    tell "a pipeline" from "a way to get one" by inspection. Separate parameters
    cost one argument and guess nothing.
    """
    if zsc is not None:
        return zsc
    if builder is None:
        raise ValueError("no zero-shot pipeline and no way to build one")
    return builder()


def _pipeline_model_id(zsc: Any) -> str:
    """The model behind a loaded pipeline, for the cache key.

    Serving a bart-large-mnli score to a run configured for a different NLI
    model would be a wrong answer rather than a slow one, so the identity has to
    come from the object actually doing the work — not from config, which the
    caller may have changed since the pipeline was built. Falls back to the
    class name when a test double has no model, which merely partitions the
    cache more finely than necessary.
    """
    for attr in ("name_or_path", "_name_or_path"):
        model = getattr(zsc, "model", None)
        config = getattr(model, "config", None)
        value = getattr(config, attr, None) or getattr(model, attr, None)
        if value:
            return str(value)
    return f"unknown:{type(zsc).__name__}"


def add_zero_shot_columns(
    df: pd.DataFrame,
    results: Sequence[Dict[str, Any]],
    prefix: str,
) -> pd.DataFrame:
    """
    Add flattened zero-shot outputs to a response dataframe.

    v2: accumulate into lists then assign once — avoids pandas chained-assignment.
    """
    top_label: List[str] = []
    top_score: List[float] = []
    full_labels: List[str] = []
    full_scores: List[str] = []

    for item in results:
        labels = item.get("labels", [])
        scores = item.get("scores", [])
        if labels:
            top_label.append(str(labels[0]))
            top_score.append(float(scores[0]))
        else:
            top_label.append("")
            top_score.append(math.nan)
        full_labels.append("|".join(map(str, labels)))
        full_scores.append("|".join(f"{float(s):.4f}" for s in scores))

    return df.assign(**{
        f"{prefix}_top_label": top_label,
        f"{prefix}_top_score": top_score,
        f"{prefix}_all_labels": full_labels,
        f"{prefix}_all_scores": full_scores,
    })


def assign_strict_labels_from_results(
    results: Sequence[Dict[str, Any]],
    strict_cfg: Dict[str, Any],
) -> Tuple[List[str], List[bool], List[str], List[float]]:
    """
    Apply strict qualitative coding rules to zero-shot outputs.

    Rules (all configurable):
    - top1 score must be >= top1_min_score
    - top1-top2 margin must be >= min_margin_over_second
    - optional multi-label output using min_multilabel_score
    """
    uncertain_label = str(strict_cfg.get("uncertain_label", "UNCERTAIN_REVIEW"))
    top1_min_score = float(strict_cfg.get("top1_min_score", 0.55))
    min_margin = float(strict_cfg.get("min_margin_over_second", 0.10))
    allow_multilabel = bool(strict_cfg.get("allow_multilabel_output", False))
    min_multilabel_score = float(strict_cfg.get("min_multilabel_score", top1_min_score))
    max_multilabel_labels = int(strict_cfg.get("max_multilabel_labels", 3))

    labels_out: List[str] = []
    confident_out: List[bool] = []
    reason_out: List[str] = []
    margin_out: List[float] = []

    for item in results:
        labels = item.get("labels", []) or []
        scores = [float(s) for s in (item.get("scores", []) or [])]
        if not labels or not scores:
            labels_out.append(uncertain_label)
            confident_out.append(False)
            reason_out.append("no_candidate_labels")
            margin_out.append(math.nan)
            continue

        top_score = scores[0]
        second_score = scores[1] if len(scores) > 1 else 0.0
        margin = top_score - second_score

        if top_score < top1_min_score:
            labels_out.append(uncertain_label)
            confident_out.append(False)
            reason_out.append(f"low_top1_score<{top1_min_score}")
            margin_out.append(margin)
            continue

        if margin < min_margin:
            labels_out.append(uncertain_label)
            confident_out.append(False)
            reason_out.append(f"low_margin<{min_margin}")
            margin_out.append(margin)
            continue

        if allow_multilabel:
            selected = [lbl for lbl, score in zip(labels, scores) if score >= min_multilabel_score]
            selected = selected[:max_multilabel_labels]
            if not selected:
                labels_out.append(uncertain_label)
                confident_out.append(False)
                reason_out.append(f"no_labels_above_multilabel_threshold<{min_multilabel_score}")
                margin_out.append(margin)
                continue
            labels_out.append("|".join(map(str, selected)))
            confident_out.append(True)
            reason_out.append("confident_multilabel")
            margin_out.append(margin)
            continue

        labels_out.append(str(labels[0]))
        confident_out.append(True)
        reason_out.append("confident_top1")
        margin_out.append(margin)

    return labels_out, confident_out, reason_out, margin_out


def add_strict_coding_columns(
    df: pd.DataFrame,
    results: Sequence[Dict[str, Any]],
    prefix: str,
    strict_cfg: Dict[str, Any],
) -> pd.DataFrame:
    """Attach strict coding outputs for a zero-shot result set."""
    labels_out, confident_out, reason_out, margin_out = assign_strict_labels_from_results(
        results=results,
        strict_cfg=strict_cfg,
    )
    return df.assign(**{
        f"{prefix}_strict_label": labels_out,
        f"{prefix}_strict_confident": confident_out,
        f"{prefix}_strict_reason": reason_out,
        f"{prefix}_strict_margin": margin_out,
    })


# --------------------#
# Reporting + Exports #
# --------------------#

def make_cluster_summary(
    response_df: pd.DataFrame,
    top_terms: Dict[int, List[str]],
    reps: Dict[int, List[str]],
) -> pd.DataFrame:
    """Build cluster summary table for quick interpretation."""
    rows: List[Dict[str, Any]] = []
    total = len(response_df)
    counts = response_df["cluster_id"].value_counts().to_dict()

    for cluster_id in sorted(counts):
        count = int(counts[cluster_id])
        pct = (count / total) * 100 if total else 0.0
        rows.append(
            {
                "cluster_id": int(cluster_id),
                "response_count": count,
                "response_percent": round(pct, 2),
                "top_terms": ", ".join(top_terms.get(int(cluster_id), [])),
                "example_quotes": " || ".join(reps.get(int(cluster_id), [])),
            }
        )
    return pd.DataFrame(rows).sort_values("response_count", ascending=False)


def make_question_theme_summary(
    question_df: pd.DataFrame,
    theme_col: str,
    top_terms_by_question_theme: Dict[Tuple[str, int], List[str]],
    reps_by_question_theme: Dict[Tuple[str, int], List[str]],
) -> pd.DataFrame:
    """Summarize theme counts per question."""
    rows: List[Dict[str, Any]] = []
    grouped = question_df.groupby("question_text", dropna=False)

    for question, q_df in grouped:
        question_total = len(q_df)
        counts = q_df[theme_col].value_counts().to_dict()
        for theme_id in sorted(counts):
            count = int(counts[theme_id])
            pct = (count / question_total) * 100 if question_total else 0.0
            key = (str(question), int(theme_id))
            rows.append(
                {
                    "question_text": str(question),
                    "question_total": question_total,
                    "theme_id": int(theme_id),
                    "response_count": count,
                    "response_percent_within_question": round(pct, 2),
                    "top_terms": ", ".join(top_terms_by_question_theme.get(key, [])),
                    "example_quotes": " || ".join(reps_by_question_theme.get(key, [])),
                }
            )
    return pd.DataFrame(rows).sort_values(
        by=["question_text", "response_count"],
        ascending=[True, False],
    )


def summarize_question_label_distribution(
    response_df: pd.DataFrame,
    label_col: str,
) -> pd.DataFrame:
    """Count top-label distribution within each question."""
    grouped = (
        response_df.groupby(["question_text", label_col], dropna=False)
        .size()
        .reset_index(name="response_count")
    )

    totals = (
        response_df.groupby("question_text", dropna=False)
        .size()
        .reset_index(name="question_total")
    )
    merged = grouped.merge(totals, on="question_text", how="left")
    merged["response_percent_within_question"] = (
        (merged["response_count"] / merged["question_total"]) * 100
    ).round(2)
    return merged.sort_values(
        by=["question_text", "response_count"],
        ascending=[True, False],
    )


def run_question_level_thematic_clustering(
    response_df: pd.DataFrame,
    embeddings: np.ndarray,
    thematic_cfg: Dict[str, Any],
    fallback_cluster_cfg: Dict[str, Any],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Discover themes independently inside each survey question.
    """
    by_question_cfg = thematic_cfg.get("by_question", {})
    if not by_question_cfg.get("enabled", False):
        return response_df, pd.DataFrame()

    min_responses = int(by_question_cfg.get("min_responses_per_question", 10))
    q_cluster_cfg = by_question_cfg.get("clustering", fallback_cluster_cfg)
    top_terms_n = int(
        q_cluster_cfg.get(
            "top_terms_per_cluster",
            fallback_cluster_cfg.get("top_terms_per_cluster", 10),
        )
    )
    quotes_n = int(
        q_cluster_cfg.get(
            "sample_quotes_per_cluster",
            fallback_cluster_cfg.get("sample_quotes_per_cluster", 3),
        )
    )

    # v2: collect per-row results into lists; assign once at the end.
    question_theme_ids: List[int] = [-1] * len(response_df)
    question_theme_methods: List[str] = ["unassigned"] * len(response_df)

    top_terms_map: Dict[Tuple[str, int], List[str]] = {}
    reps_map: Dict[Tuple[str, int], List[str]] = {}

    for question_text, q_df in response_df.groupby("question_text", dropna=False):
        q_idx = q_df.index.to_numpy()
        q_embeddings = embeddings[q_idx]
        q_texts = q_df["response_text"].tolist()
        question_key = str(question_text)

        if len(q_df) < min_responses or len(q_df) < 3:
            for i in q_idx:
                question_theme_ids[i] = 0
                question_theme_methods[i] = "single_bucket_small_sample"
            small_terms = extract_top_terms_by_cluster(
                texts=q_texts,
                labels=np.zeros(len(q_df), dtype=int),
                max_terms=top_terms_n,
            )
            top_terms_map[(question_key, 0)] = small_terms.get(0, [])
            reps_map[(question_key, 0)] = q_texts[:quotes_n]
            continue

        q_labels, q_clusterer, _ = fit_clusters(q_embeddings, q_cluster_cfg)
        for i, lbl in zip(q_idx, q_labels):
            question_theme_ids[i] = int(lbl)
            question_theme_methods[i] = "clustered"

        q_terms = extract_top_terms_by_cluster(
            texts=q_texts,
            labels=q_labels,
            max_terms=top_terms_n,
        )
        q_reps = representative_examples(
            texts=q_texts,
            labels=q_labels,
            embeddings=q_embeddings,
            centers=q_clusterer.cluster_centers_,
            per_cluster=quotes_n,
        )
        for theme_id, terms in q_terms.items():
            top_terms_map[(question_key, int(theme_id))] = terms
        for theme_id, quotes in q_reps.items():
            reps_map[(question_key, int(theme_id))] = quotes

    response_df = response_df.assign(
        question_theme_id=question_theme_ids,
        question_theme_method=question_theme_methods,
    )

    summary_df = make_question_theme_summary(
        question_df=response_df,
        theme_col="question_theme_id",
        top_terms_by_question_theme=top_terms_map,
        reps_by_question_theme=reps_map,
    )
    return response_df, summary_df


def run_question_level_zero_shot(
    response_df: pd.DataFrame,
    model_name: str,
    batch_size: int,
    cfg: Dict[str, Any],
    fallback_labels: Sequence[str],
    cache: Any = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Tag responses with question-specific label sets.

    v2 changes:
    - Returns a list of skipped question names so callers can surface warnings.
    - Uses list accumulation + df.assign instead of in-place chained assignment.

    Returns (updated_df, skipped_questions).
    """
    if not cfg.get("enabled", False):
        return response_df, []

    strict_cfg = cfg.get("strict_coding", {})
    strict_enabled = bool(strict_cfg.get("enabled", False))
    labels_by_question = cfg.get("labels_by_question", {}) or {}
    default_labels = cfg.get("default_labels", fallback_labels) or []
    multi_label = bool(cfg.get("multi_label", True))

    # Pre-allocate output columns as parallel lists.
    n = len(response_df)
    qzshot_top_label = [""] * n
    qzshot_top_score = [math.nan] * n
    qzshot_all_labels = [""] * n
    qzshot_all_scores = [""] * n
    qzshot_strict_label = [str(strict_cfg.get("uncertain_label", "UNCERTAIN_REVIEW"))] * n
    qzshot_strict_confident = [False] * n
    qzshot_strict_reason = ["not_scored"] * n
    qzshot_strict_margin = [math.nan] * n

    LOGGER.info("Loading question-level zero-shot model: %s", model_name)
    zsc = _load_model(
        model_name,
        lambda: _get_pipeline()(
            "zero-shot-classification",
            model=model_name,
            truncation=True,
        ),
    )

    skipped_questions: List[str] = []

    for question_text, q_df in response_df.groupby("question_text", dropna=False):
        q_idx = q_df.index.to_numpy()
        question_key = str(question_text)
        labels = labels_by_question.get(question_key, default_labels)

        if not labels:
            # v2: collect skipped questions rather than silently continuing.
            LOGGER.warning(
                "Skipping question-level zero-shot for question with no labels: %s",
                question_key,
            )
            skipped_questions.append(question_key)
            continue

        q_results = run_zero_shot_with_pipeline(
            zsc=zsc,
            texts=q_df["response_text"].tolist(),
            labels=labels,
            multi_label=multi_label,
            batch_size=batch_size,
            cache=cache,
        )

        for local_i, (global_i, item) in enumerate(zip(q_idx, q_results)):
            item_labels = item.get("labels", [])
            item_scores = item.get("scores", [])
            if item_labels:
                qzshot_top_label[global_i] = str(item_labels[0])
                qzshot_top_score[global_i] = float(item_scores[0])
            qzshot_all_labels[global_i] = "|".join(map(str, item_labels))
            qzshot_all_scores[global_i] = "|".join(f"{float(s):.4f}" for s in item_scores)

        if strict_enabled:
            s_labels, s_confident, s_reason, s_margin = assign_strict_labels_from_results(
                results=q_results,
                strict_cfg=strict_cfg,
            )
            for global_i, (sl, sc, sr, sm) in zip(q_idx, zip(s_labels, s_confident, s_reason, s_margin)):
                qzshot_strict_label[global_i] = sl
                qzshot_strict_confident[global_i] = sc
                qzshot_strict_reason[global_i] = sr
                qzshot_strict_margin[global_i] = sm

    assign_dict: Dict[str, Any] = {
        "qzshot_top_label": qzshot_top_label,
        "qzshot_top_score": qzshot_top_score,
        "qzshot_all_labels": qzshot_all_labels,
        "qzshot_all_scores": qzshot_all_scores,
    }
    if strict_enabled:
        assign_dict.update({
            "qzshot_strict_label": qzshot_strict_label,
            "qzshot_strict_confident": qzshot_strict_confident,
            "qzshot_strict_reason": qzshot_strict_reason,
            "qzshot_strict_margin": qzshot_strict_margin,
        })

    return response_df.assign(**assign_dict), skipped_questions


def build_strict_review_queue(
    response_df: pd.DataFrame,
    strict_label_col: str,
    uncertain_label: str,
    reason_col: str,
    margin_col: str,
) -> pd.DataFrame:
    """
    Build a manual-review queue of uncertain responses from strict coding.
    """
    if strict_label_col not in response_df.columns:
        return pd.DataFrame()

    review_df = response_df[response_df[strict_label_col] == uncertain_label].copy()
    if review_df.empty:
        return pd.DataFrame()

    cols = [
        c
        for c in [
            "response_id",
            "question_text",
            "response_text",
            strict_label_col,
            reason_col,
            margin_col,
            "zshot_top_label",
            "zshot_top_score",
            "qzshot_top_label",
            "qzshot_top_score",
            "zshot_all_labels",
            "zshot_all_scores",
            "qzshot_all_labels",
            "qzshot_all_scores",
        ]
        if c in review_df.columns
    ]
    return review_df[cols]


def write_markdown_report(
    output_path: Path,
    config: Dict[str, Any],
    response_df: pd.DataFrame,
    cluster_df: pd.DataFrame,
    silhouette_scores: Dict[int, float],
    question_theme_df: Optional[pd.DataFrame] = None,
    question_label_df: Optional[pd.DataFrame] = None,
    skipped_questions: Optional[List[str]] = None,
) -> None:
    """Write a human-readable run report.
    
    v2: includes skipped-question warnings if any were encountered.
    """
    title = config.get("report", {}).get("title", "Survey NLP Run Report")
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Run timestamp: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- Total analyzed responses: {len(response_df)}")
    if "response_text" in response_df.columns:
        total, unique = count_unique_texts(response_df["response_text"].tolist())
        if unique < total:
            # Duplicate mass is worth stating plainly: identical answers ("None"
            # x 80) are real data and are counted, but they also pull cluster
            # structure toward themselves, so an analyst reading the themes
            # should know how much of the corpus is repeats.
            lines.append(
                f"- Distinct response texts: {unique} "
                f"({total - unique} of {total} responses repeat an earlier answer)"
            )
    lines.append(f"- Clusters discovered: {cluster_df.shape[0]}")
    lines.append("")

    if skipped_questions:
        lines.append("## ⚠️ Questions Skipped During Zero-Shot Coding")
        lines.append("")
        lines.append("The following questions had no labels configured and were not coded:")
        for q in skipped_questions:
            lines.append(f"- {q}")
        lines.append("")
        lines.append("To fix: add entries to `thematic_analysis.by_question_zero_shot.labels_by_question` in your config.")
        lines.append("")

    if silhouette_scores:
        lines.append("## Silhouette Scores (k search)")
        lines.append("")
        for k, score in sorted(silhouette_scores.items()):
            lines.append(f"- k={k}: {score:.4f}")
        lines.append("")

    lines.append("## Cluster Summary")
    lines.append("")
    for _, row in cluster_df.sort_values("response_count", ascending=False).iterrows():
        lines.append(f"### Cluster {int(row['cluster_id'])}")
        lines.append(f"- Count: {int(row['response_count'])} ({row['response_percent']}%)")
        lines.append(f"- Top terms: {row['top_terms']}")
        lines.append(f"- Example quotes: {row['example_quotes']}")
        lines.append("")

    if question_theme_df is not None and not question_theme_df.empty:
        lines.append("## Question-Level Themes")
        lines.append("")
        for question, q_df in question_theme_df.groupby("question_text", dropna=False):
            lines.append(f"### Question: {question}")
            for _, row in q_df.sort_values("response_count", ascending=False).iterrows():
                lines.append(
                    f"- Theme {int(row['theme_id'])}: {int(row['response_count'])} responses "
                    f"({row['response_percent_within_question']}%)"
                )
                lines.append(f"  Top terms: {row['top_terms']}")
                lines.append(f"  Example quotes: {row['example_quotes']}")
            lines.append("")

    if question_label_df is not None and not question_label_df.empty:
        lines.append("## Question-Level Label Distribution")
        lines.append("")
        for question, q_df in question_label_df.groupby("question_text", dropna=False):
            lines.append(f"### Question: {question}")
            for _, row in q_df.sort_values("response_count", ascending=False).iterrows():
                label_value = row.get("qzshot_top_label", "")
                lines.append(
                    f"- {label_value}: {int(row['response_count'])} responses "
                    f"({row['response_percent_within_question']}%)"
                )
            lines.append("")

    if "zshot_strict_confident" in response_df.columns:
        uncertain_count = int((~response_df["zshot_strict_confident"]).sum())
        lines.append("## Strict Coding (Global Zero-Shot)")
        lines.append("")
        lines.append(f"- Uncertain responses flagged for review: {uncertain_count}")
        lines.append("")

    if "qzshot_strict_confident" in response_df.columns:
        uncertain_count = int((~response_df["qzshot_strict_confident"]).sum())
        lines.append("## Strict Coding (Question-Level Zero-Shot)")
        lines.append("")
        lines.append(f"- Uncertain responses flagged for review: {uncertain_count}")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def export_results(
    output_dir: Path,
    response_df: pd.DataFrame,
    cluster_df: pd.DataFrame,
    embeddings: np.ndarray,
    silhouette_scores: Dict[int, float],
    save_embeddings: bool,
) -> None:
    """Persist all outputs.

    v2: applies CSV formula injection sanitization to all string columns
    in user-originated DataFrames before writing, so outputs are safe to
    open in Excel and Google Sheets.
    """
    # Sanitize string columns that may contain user-supplied response text.
    sanitized_response = sanitize_frame_for_csv(response_df)
    sanitized_cluster = sanitize_frame_for_csv(cluster_df)

    sanitized_response.to_csv(output_dir / "responses_scored.csv", index=False)
    sanitized_cluster.to_csv(output_dir / "cluster_summary.csv", index=False)
    (output_dir / "silhouette_scores.json").write_text(
        json.dumps(silhouette_scores, indent=2), encoding="utf-8"
    )

    if save_embeddings:
        np.save(output_dir / "embeddings.npy", embeddings)


# ------------#
# Main Runner #
# ------------#

class _ProgressReporter:
    """Drives a UI progress callback across the pipeline's stages.

    UI contract (v3.3): ``callback(fraction: float in [0,1], message: str)``. The
    old ``(done, total)`` contract belonged to the per-item LLM callback; that
    still exists, but it is now an *engine-level* detail that this reporter adapts
    into a stage slice via `item_callback`, so a slow per-response engine moves the
    bar within its stage instead of freezing the whole run on it.

    None-safe: with no callback (the CLI), stages are still logged as ``[i/n]``
    banners so the terminal shows where the run is. Never lets a UI error abort a
    run — a broken progress bar must not lose an analysis.
    """

    def __init__(self, callback, n_stages: int):
        self._callback = callback
        self._n = max(int(n_stages), 1)
        self._completed = 0

    def stage(self, message: str) -> None:
        """Announce the stage about to run (and bank the previous one)."""
        self._emit(self._completed / self._n, message)
        LOGGER.info("[%d/%d] %s", self._completed + 1, self._n, message)
        self._completed += 1

    def note(self, message: str) -> None:
        """Say something without advancing the run.

        `stage()` banks a stage and moves the bar. A resume notice is not a
        stage: using `stage()` for it would consume a slot the plan does not
        contain, overshoot the final fraction, and — worse — shift
        `item_callback`'s base so the coding stage's own sub-progress mapped
        into the following stage's slice.
        """
        self._emit(self._completed / self._n, message)
        LOGGER.info("%s", message)

    def item_callback(self, message: str):
        """A ``(done, total)`` callback mapping into the current stage's slice.

        Returns None when there is no UI callback, so callers fall back to their
        single-shot path — keeping CLI/test runs on the exact code path whose
        outputs the byte-identity harness pins.
        """
        if self._callback is None:
            return None
        base = max(self._completed - 1, 0) / self._n
        span = 1.0 / self._n

        def cb(done, total):
            frac = base + span * (done / total if total else 1.0)
            self._emit(min(frac, 1.0), f"{message} ({done}/{total})")

        return cb

    def finish(self, message: str = "Complete") -> None:
        self._emit(1.0, message)

    def _emit(self, fraction: float, message: str) -> None:
        if self._callback is None:
            return
        try:
            self._callback(min(max(fraction, 0.0), 1.0), message)
        except Exception:  # noqa: BLE001 - progress UI must never break a run
            pass


def _plan_stages(config: Dict[str, Any]) -> List[str]:
    """The ordered stage list for this run's config — drives progress fractions."""
    thematic_cfg = config.get("thematic_analysis", {}) or {}
    stages = ["Building embeddings", "Discovering clusters"]
    if (config.get("sentiment", {}) or {}).get("enabled", True):
        stages.append("Analyzing sentiment")
    if (config.get("zero_shot", {}) or {}).get("enabled", False):
        stages.append("Coding themes")
    if (thematic_cfg.get("by_question", {}) or {}).get("enabled", False):
        stages.append("Per-question themes")
    if (thematic_cfg.get("by_question_zero_shot", {}) or {}).get("enabled", False):
        stages.append("Per-question coding")
    stages.append("Writing outputs")
    return stages


def run_pipeline(config: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
    """
    Main execution flow.

    v2: returns a run_summary dict with metadata (questions coded, skipped, etc.)
    so callers like the Streamlit app can surface diagnostics without re-reading files.

    v3.3: `progress_callback(fraction, message)` is invoked at each stage boundary
    (and continuously within the coding stage for the per-response LLM engine), so
    the GUI shows a moving bar and the terminal shows `[i/n]` stage banners instead
    of leaving the analyst unsure whether a slow CPU run has hung. None-safe.
    """
    # First, and before a single file or directory is created: does this machine
    # have the models this configuration will reach? Each model used to be
    # checked only when its stage first touched it, so a partial download failed
    # three times, each after more waiting -- measured at 9 progress steps and
    # 24.8 seconds on 45 responses before the second failure, and on a real
    # corpus the third lands after the sentiment stage has run for minutes.
    from core.model_readiness import check_models_ready
    check_models_ready(config)

    output_dir = Path(config["output"]["output_dir"]).expanduser().resolve()
    ensure_output_dir(output_dir)

    progress = _ProgressReporter(progress_callback, len(_plan_stages(config)))

    # Model outputs already computed for these responses, if any. Lives beside
    # the outputs so erasure can find it; opened before the first model call and
    # closed in the `finally` below so an interrupted run still commits what it
    # finished. Off by config for a run that must not leave derived data behind.
    from core.inference_cache import open_cache
    inference_cache = open_cache(
        output_dir,
        enabled=bool(config.get("pipeline", {}).get("use_inference_cache", True)))
    try:
        return _run_pipeline_inner(config, progress, output_dir, inference_cache)
    finally:
        if inference_cache is not None:
            inference_cache.close()


def _run_pipeline_inner(
    config: Dict[str, Any], progress, output_dir: Path, inference_cache,
) -> Dict[str, Any]:
    """The pipeline body. Split out so the cache has one place to be closed."""
    raw_df = read_input_table(config)
    work_df = prepare_dataset(raw_df, config)
    if work_df.empty:
        raise ValueError("No valid responses after preprocessing filters.")

    model_cfg = config["models"]
    pipeline_cfg = config["pipeline"]
    cluster_cfg = config["clustering"]

    total_texts, unique_texts = count_unique_texts(work_df["response_text"].tolist())
    progress.stage(f"Building embeddings for {total_texts} responses…")
    normalize = bool(pipeline_cfg.get("normalize_embeddings", True))
    dedupe = bool(pipeline_cfg.get("dedupe_embeddings", False))
    if pipeline_cfg.get("use_embedding_cache", True):
        # Reuse vectors across re-runs over the same responses. Cache lives beside
        # the outputs so erasure/purge can find it (core/erasure.py).
        from core.embedding_cache import load_or_build_embeddings
        embeddings = load_or_build_embeddings(
            texts=work_df["response_text"].tolist(),
            model_name=model_cfg["embedding_model"],
            batch_size=int(pipeline_cfg.get("embedding_batch_size", 32)),
            cache_dir=output_dir / ".embedding_cache",
            normalize_embeddings=normalize,
            dedupe=dedupe,
        )
    else:
        embeddings = build_embeddings(
            texts=work_df["response_text"].tolist(),
            model_name=model_cfg["embedding_model"],
            batch_size=int(pipeline_cfg.get("embedding_batch_size", 32)),
            normalize_embeddings=normalize,
            dedupe=dedupe,
        )

    progress.stage("Discovering clusters (searching for the best number of themes)…")
    cluster_labels, clusterer, silhouette_scores = fit_clusters(
        embeddings, cluster_cfg, progress=progress.item_callback("Discovering clusters — testing k"))
    work_df = work_df.assign(cluster_id=cluster_labels)

    # Noise-aware review signal (Phase 4.2): responses far from their assigned
    # centroid may belong to no theme. Off by default is not needed — it's a cheap
    # extra column, and the review list is opt-in in the UI.
    if bool(cluster_cfg.get("flag_outliers", True)):
        _dist, _outlier = flag_outliers(
            embeddings, cluster_labels, clusterer.cluster_centers_,
            percentile=float(cluster_cfg.get("outlier_percentile", 90.0)))
        work_df = work_df.assign(
            centroid_distance=_dist.round(4), possible_outlier=_outlier)

    top_terms = extract_top_terms_by_cluster(
        texts=work_df["response_text"].tolist(),
        labels=cluster_labels,
        max_terms=int(cluster_cfg.get("top_terms_per_cluster", 10)),
    )
    reps = representative_examples(
        texts=work_df["response_text"].tolist(),
        labels=cluster_labels,
        embeddings=embeddings,
        centers=clusterer.cluster_centers_,
        per_cluster=int(cluster_cfg.get("sample_quotes_per_cluster", 3)),
    )

    # Optional sentiment.
    sentiment_cfg = config.get("sentiment", {})
    if sentiment_cfg.get("enabled", True):
        progress.stage(f"Analyzing sentiment for {len(work_df)} responses…")
        sentiments = run_sentiment(
            texts=work_df["response_text"].tolist(),
            model_name=model_cfg["sentiment_model"],
            batch_size=int(pipeline_cfg.get("inference_batch_size", 16)),
            cache=inference_cache,
        )
        work_df = work_df.assign(
            sentiment_label=[r.get("label") for r in sentiments],
            sentiment_score=[float(r.get("score", math.nan)) for r in sentiments],
        )

    # Optional zero-shot theme coding (Mode 1). Routed through the engine
    # abstraction (v3): the transformer engine (default) or, when engine.type ==
    # "llm", a local-LLM engine via Ollama — selected by resolve_theme_engine,
    # which falls back to the transformer engine if Ollama is unavailable. The
    # transformer path is byte-identical to v2.1. Local imports break the
    # analyze_survey <-> engines import cycle.
    from engines.factory import resolve_theme_engine
    from engines.adapt import (
        add_zero_shot_columns_from_codings,
        add_strict_coding_columns_from_codings,
    )

    engine_type_used: Optional[str] = None
    engine_model_used: Optional[str] = None
    zero_cfg = config.get("zero_shot", {})
    strict_review_global_df = pd.DataFrame()
    if zero_cfg.get("enabled", False):
        theme_engine, engine_type = resolve_theme_engine(config)
        engine_type_used = engine_type
        # Per-engine strict thresholds (Phase 2.4): NLI entailment scores and LLM
        # self-report scores are not comparable, so the gate is stored per engine.
        # This overlays the active engine's thresholds onto strict_coding before
        # the gate reads them. No-op for legacy flat configs.
        apply_engine_strict_thresholds(config, engine_type)
        global_strict_cfg = zero_cfg.get("strict_coding", {})
        engine_model_used = getattr(theme_engine, "model", None) or model_cfg.get("zero_shot_model")
        coding_note = ("with the local LLM (slow — one pass per response)"
                       if engine_type == "llm" else "with the zero-shot model")
        progress.stage(f"Coding themes {coding_note}…")
        codings = theme_engine.code_responses(
            texts=work_df["response_text"].tolist(),
            labels=zero_cfg.get("labels", []),
            config={
                "multi_label": bool(zero_cfg.get("multi_label", True)),
                "inference_batch_size": int(pipeline_cfg.get("inference_batch_size", 16)),
                "strict_coding": global_strict_cfg,
                # LLM engine only: how many Ollama calls overlap. Low by default —
                # Ollama queues past its own parallelism, so more buys nothing.
                "max_workers": int((config.get("engine", {}).get("llm", {}) or {}).get("concurrency", 3)),
                # Per-item sub-progress maps into this stage's slice (LLM engine
                # reports per response; the transformer engine runs as one batch).
                "progress_callback": progress.item_callback("Coding themes"),
                # The stage this cache exists for: about 94% of a five-thousand
                # response run, and until now the only one without a cache.
                "inference_cache": inference_cache,
                # And say when it hits. A resumed run that is merely fast looks
                # like a run that did nothing.
                "resume_callback": (
                    lambda done, total: progress.note(
                        f"Resuming — {done} of {total} responses already coded, "
                        f"{total - done} left…")
                ),
            },
        )
        work_df = add_zero_shot_columns_from_codings(work_df, codings, prefix="zshot")
        if global_strict_cfg.get("enabled", False):
            work_df = add_strict_coding_columns_from_codings(work_df, codings, prefix="zshot")
            strict_review_global_df = build_strict_review_queue(
                response_df=work_df,
                strict_label_col="zshot_strict_label",
                uncertain_label=str(global_strict_cfg.get("uncertain_label", "UNCERTAIN_REVIEW")),
                reason_col="zshot_strict_reason",
                margin_col="zshot_strict_margin",
            )
        # LLM path only: surface the model's rationale (valuable for the review
        # queue) and its self-reported sentiment. Added only when engine == "llm"
        # so the transformer output stays byte-identical (no new columns).
        if engine_type == "llm":
            work_df = work_df.assign(
                zshot_rationale=[c.rationale for c in codings],
                zshot_llm_sentiment=[c.sentiment_label or "" for c in codings],
            )

    thematic_cfg = config.get("thematic_analysis", {})
    question_theme_summary_df = pd.DataFrame()
    question_label_summary_df = pd.DataFrame()
    skipped_questions: List[str] = []
    strict_review_question_df = pd.DataFrame()

    if (thematic_cfg.get("by_question", {}) or {}).get("enabled", False):
        progress.stage("Building per-question themes…")
    work_df, question_theme_summary_df = run_question_level_thematic_clustering(
        response_df=work_df,
        embeddings=embeddings,
        thematic_cfg=thematic_cfg,
        fallback_cluster_cfg=cluster_cfg,
    )

    qz_cfg = thematic_cfg.get("by_question_zero_shot", {})
    if qz_cfg.get("enabled", False):
        progress.stage("Coding themes per question…")
        work_df, skipped_questions = run_question_level_zero_shot(
            response_df=work_df,
            model_name=model_cfg["zero_shot_model"],
            batch_size=int(pipeline_cfg.get("inference_batch_size", 16)),
            cfg=qz_cfg,
            fallback_labels=zero_cfg.get("labels", []),
            cache=inference_cache,
        )
        question_label_summary_df = summarize_question_label_distribution(
            response_df=work_df,
            label_col="qzshot_top_label",
        )
        q_strict_cfg = qz_cfg.get("strict_coding", {})
        if q_strict_cfg.get("enabled", False):
            strict_review_question_df = build_strict_review_queue(
                response_df=work_df,
                strict_label_col="qzshot_strict_label",
                uncertain_label=str(q_strict_cfg.get("uncertain_label", "UNCERTAIN_REVIEW")),
                reason_col="qzshot_strict_reason",
                margin_col="qzshot_strict_margin",
            )

    progress.stage("Writing outputs…")
    cluster_summary_df = make_cluster_summary(work_df, top_terms, reps)

    export_results(
        output_dir=output_dir,
        response_df=work_df,
        cluster_df=cluster_summary_df,
        embeddings=embeddings,
        silhouette_scores=silhouette_scores,
        save_embeddings=bool(config["output"].get("save_embeddings", False)),
    )

    if not question_theme_summary_df.empty:
        question_theme_summary_df.to_csv(output_dir / "question_theme_summary.csv", index=False)
    if not question_label_summary_df.empty:
        question_label_summary_df.to_csv(output_dir / "question_label_summary.csv", index=False)
    if not strict_review_global_df.empty:
        strict_review_global_df.to_csv(output_dir / "strict_review_queue_global.csv", index=False)
    if not strict_review_question_df.empty:
        strict_review_question_df.to_csv(output_dir / "strict_review_queue_question.csv", index=False)

    write_markdown_report(
        output_path=output_dir / "run_report.md",
        config=config,
        response_df=work_df,
        cluster_df=cluster_summary_df,
        silhouette_scores=silhouette_scores,
        question_theme_df=question_theme_summary_df,
        question_label_df=question_label_summary_df,
        skipped_questions=skipped_questions,
    )

    LOGGER.info("Done. Outputs saved to: %s", output_dir)

    # Optional (v3): populate a portable .qnw project store from this run. Purely
    # additive — only runs when output.project_store_path is set, and is non-fatal
    # so an optional artifact can never break the analyst's CSV results. Local
    # import breaks any analyze_survey <-> core import concerns at module load.
    project_store_path = config["output"].get("project_store_path")
    written_store: Optional[str] = None
    if project_store_path:
        try:
            from core.populate import populate_project_store
            written_store = populate_project_store(work_df, config, project_store_path)
            LOGGER.info("Project store written: %s", written_store)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Project store population failed (non-fatal): %s", exc)

    # Build and return run summary for callers (e.g. Streamlit).
    all_questions = work_df["question_text"].unique().tolist() if "question_text" in work_df.columns else []
    coded_questions = [q for q in all_questions if q not in skipped_questions]
    run_summary = {
        "output_dir": str(output_dir),
        "total_responses": len(work_df),
        "unique_response_texts": unique_texts,
        "possible_outliers": int(work_df["possible_outlier"].sum())
                             if "possible_outlier" in work_df.columns else 0,
        "clusters_found": int(cluster_summary_df.shape[0]),
        "questions_total": len(all_questions),
        "questions_coded": len(coded_questions),
        "questions_skipped": skipped_questions,
        "project_store": written_store,
        "pii_masking_applied": bool((config.get("privacy") or {}).get("masking_applied", False)),
        "pii_pseudonymised": bool((config.get("privacy") or {}).get("pseudonymised", False)),
    }

    # Always-on audit manifest (FERPA/IRB trail) — written for every run, CLI or GUI.
    from core.manifest import write_run_manifest
    manifest_path = write_run_manifest(
        output_dir, config, run_summary,
        engine_type=(engine_type_used or "none"),
        engine_model=engine_model_used,
        mode="survey",
    )
    run_summary["manifest"] = str(manifest_path)
    progress.finish("Analysis complete.")
    return run_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Template: local BERT-style NLP pipeline for qualitative survey analysis."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML config file (example: config/config.example.yaml).",
    )
    return parser.parse_args()


def main() -> None:
    from core.offline import enforce_local_mode

    # Analysis never reaches the model hub; models come from the local cache that
    # tools/download_models.py fills. Safe here because this module's transformers
    # imports are deferred until a model is actually loaded.
    enforce_local_mode()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_yaml(config_path)
    run_summary = run_pipeline(config)
    if run_summary.get("questions_skipped"):
        LOGGER.warning(
            "Questions skipped (no labels configured): %s",
            run_summary["questions_skipped"],
        )


if __name__ == "__main__":
    main()
