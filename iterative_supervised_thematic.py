#!/usr/bin/env python
"""
Iterative supervised + unsupervised thematic analysis workflow.

Why this exists:
- Analysts often want to start with a small human-coded sample.
- Labels are usually NOT mutually exclusive in qualitative work.
- After supervised coding, analysts still want unsupervised discovery
  to identify emerging themes and edge cases.

Two-step process:
1) sample: create a random coding sheet (10/20 rows) for one question.
2) train: read completed coding sheet, train multi-label classifier,
          predict labels on all rows for that question, then run
          unsupervised clustering for theme discovery.

v2 changes:
- Embedding cache: embeddings for a question subset are hashed and saved to
  disk. Subsequent train runs reuse the cache if the source texts have not
  changed, avoiding the full re-encode penalty on each iteration.
- Pandas chained-assignment patterns replaced throughout (pandas 3.x safe).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer

from analyze_survey import (
    build_embeddings,
    extract_top_terms_by_cluster,
    fit_clusters,
    load_yaml,
    make_cluster_summary,
    prepare_dataset,
    read_input_table,
    representative_examples,
)


LOGGER = logging.getLogger("iterative_thematic")
_CACHE_VERSION = "v2"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_question_subset(work_df: pd.DataFrame, question_value: str) -> pd.DataFrame:
    subset = work_df[work_df["question_text"] == question_value].copy()
    if subset.empty:
        raise ValueError(
            f"No rows found for question '{question_value}'. "
            "Check spelling or available question text values."
        )
    subset.reset_index(drop=True, inplace=True)
    return subset


def parse_multilabel_cell(value: Any, delimiter: str) -> List[str]:
    if value is None or pd.isna(value):
        return []
    txt = str(value).strip()
    if not txt:
        return []
    labels = [x.strip() for x in txt.split(delimiter)]
    labels = [x for x in labels if x]
    seen = set()
    unique: List[str] = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            unique.append(label)
    return unique


def write_sample_instructions(path: Path, sample_size: int, delimiter: str) -> None:
    text = f"""# Coding Instructions

You are coding a random sample for one specific survey question.

How to code:
1. Open the Iterative Labeling Lab in the Streamlit app (or open `coding_sample.csv`).
2. Fill `human_labels` for each row using one or more labels.
3. Use `{delimiter}` between multiple labels (example: `Price concern{delimiter}Usability issue`).
4. Save edits.
5. Run train step:
   `python iterative_supervised_thematic.py --config config/iterative_supervised.example.yaml --step train`

Notes:
- Labels are NOT mutually exclusive.
- Recommended sample size is 10-20 rows for first pass.
- You can rerun `sample` to create a new batch and iterate.
- Subsequent train runs reuse cached embeddings if texts have not changed (faster).
"""
    path.write_text(text, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Embedding cache helpers (v2)
# ─────────────────────────────────────────────────────────────────────────────

def _texts_hash(texts: List[str], model_name: str) -> str:
    """Stable hash of the text list + model name — used as cache key."""
    h = hashlib.sha256()
    h.update(_CACHE_VERSION.encode())
    h.update(model_name.encode())
    for t in texts:
        h.update(t.encode("utf-8", errors="replace"))
    return h.hexdigest()[:16]


def load_or_build_embeddings(
    texts: List[str],
    model_name: str,
    batch_size: int,
    cache_dir: Path,
) -> np.ndarray:
    """Return cached embeddings if valid, else build + cache them.

    Thin wrapper kept for back-compat; the implementation moved to
    `core/embedding_cache.py` so the main survey pipeline shares one cache with
    this workflow (v3.1.1, Phase 1.5). This path always normalizes, as before.
    """
    from core.embedding_cache import load_or_build_embeddings as _shared

    return _shared(
        texts=texts, model_name=model_name, batch_size=batch_size,
        cache_dir=Path(cache_dir), normalize_embeddings=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core workflow
# ─────────────────────────────────────────────────────────────────────────────

def _previously_coded_ids(output_dir: Path, delimiter: str) -> List[str]:
    """response_ids the analyst has already hand-coded in a prior round."""
    prior = output_dir / "coding_sample.csv"
    if not prior.exists():
        return []
    try:
        from core.encodings import read_csv_as_text

        # The analyst's own coded sample: text, so ids match what they coded.
        df = read_csv_as_text(prior).frame
    except Exception:  # noqa: BLE001
        return []
    if "human_labels" not in df.columns or "response_id" not in df.columns:
        return []
    coded = df[df["human_labels"].map(lambda v: bool(parse_multilabel_cell(v, delimiter)))]
    return coded["response_id"].astype(str).tolist()


def _uncertainty_order_from_predictions(output_dir: Path, already_coded: List[str]) -> List[str]:
    """Most-uncertain-first response ids from a prior train run's predictions.

    Reads `iterative_predictions.csv` (written by train_and_apply), which carries
    a per-row probability JSON. Returns [] if no prior predictions exist (round 0).
    """
    from analysis.sampling import order_ids_by_uncertainty

    preds = output_dir / "iterative_predictions.csv"
    if not preds.exists():
        return []
    try:
        df = pd.read_csv(preds)
    except Exception:  # noqa: BLE001
        return []
    if "supervised_all_probabilities_json" not in df.columns:
        return []
    prob_by_id: Dict[str, Dict[str, float]] = {}
    for _, row in df.iterrows():
        rid = str(row["response_id"])
        try:
            prob_by_id[rid] = {k: float(v) for k, v in json.loads(row["supervised_all_probabilities_json"]).items()}
        except Exception:  # noqa: BLE001
            prob_by_id[rid] = {}
    return order_ids_by_uncertainty(prob_by_id, already_coded=already_coded)


def create_coding_sample(config: Dict[str, Any]) -> None:
    from analysis.sampling import SAMPLING_CAVEATS, stratified_sample_indices

    input_df = read_input_table(config)
    work_df = prepare_dataset(input_df, config)

    cfg = config["iterative_supervised"]
    question_value = str(cfg["question_value"])
    sample_size = int(cfg.get("sample_size", 20))
    random_state = int(cfg.get("random_state", 42))
    delimiter = str(cfg.get("label_delimiter", "|"))
    # "auto" (default): uncertainty once a model exists, else random. Explicit
    # values force a strategy. "random" is the escape hatch that keeps prevalence
    # estimates unbiased — pure uncertainty sampling biases them.
    strategy = str(cfg.get("sampling", "auto")).lower()
    output_dir = Path(cfg.get("output_dir", "./output_iterative")).resolve()
    ensure_dir(output_dir)

    subset = get_question_subset(work_df, question_value)
    n = min(sample_size, len(subset))

    already_coded = _previously_coded_ids(output_dir, delimiter)
    used_strategy = "random"

    if strategy in ("auto", "uncertainty"):
        ordered = _uncertainty_order_from_predictions(output_dir, already_coded)
        if ordered:
            # Keep only ids that are in this question's subset, most-uncertain first.
            id_set = set(subset["response_id"].astype(str))
            ordered = [rid for rid in ordered if rid in id_set][:n]
            if ordered:
                sample_df = subset[subset["response_id"].astype(str).isin(ordered)].copy()
                used_strategy = "uncertainty"
        elif strategy == "uncertainty":
            LOGGER.warning(
                "sampling='uncertainty' but no prior predictions found — run a train "
                "step first. Falling back to stratified random for this seed round."
            )

    if used_strategy != "uncertainty" and strategy in ("auto", "stratified"):
        # Cluster-stratified seed round, so the first model sees the whole space.
        # Embeds the subset — the one place round-0 sampling pays for clustering.
        try:
            from core.embedding_cache import load_or_build_embeddings
            embeddings = load_or_build_embeddings(
                texts=subset["response_text"].tolist(),
                model_name=str(cfg.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")),
                batch_size=int(cfg.get("embedding_batch_size", 32)),
                cache_dir=output_dir / ".embedding_cache",
            )
            cluster_labels, _, _ = fit_clusters(
                embeddings=embeddings,
                cluster_cfg={"fixed_k": None, "min_k": 2,
                             "max_k": min(6, max(2, len(subset) // 3)),
                             "random_state": random_state,
                             "top_terms_per_cluster": 5, "sample_quotes_per_cluster": 2},
            )
            idx = stratified_sample_indices(cluster_labels, n, random_state=random_state)
            sample_df = subset.iloc[idx].copy()
            used_strategy = "stratified"
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Stratified sampling unavailable (%s); using plain random.", exc)

    if used_strategy == "random":
        sample_df = subset.sample(n=n, random_state=random_state).copy()

    # Human coders fill these columns.
    sample_df = sample_df.assign(human_labels="", coder_notes="")

    keep_cols = ["response_id", "question_text", "response_text", "human_labels", "coder_notes"]
    sample_out = sample_df[keep_cols].sort_values("response_id")

    sample_path = output_dir / "coding_sample.csv"
    sample_out.to_csv(sample_path, index=False)
    write_sample_instructions(
        path=output_dir / "coding_instructions.md",
        sample_size=sample_size,
        delimiter=delimiter,
    )
    # The caveat travels with the sample: whoever reads agreement/prevalence off
    # it needs to know how it was selected.
    (output_dir / "sampling_note.txt").write_text(
        f"Sampling strategy: {used_strategy}\n\n{SAMPLING_CAVEATS[used_strategy]}\n",
        encoding="utf-8",
    )

    LOGGER.info("Created coding sample: %s (strategy=%s)", sample_path, used_strategy)
    LOGGER.info("Rows sampled: %s (question=%s)", len(sample_out), question_value)
    LOGGER.info("Sampling caveat: %s", SAMPLING_CAVEATS[used_strategy])


def fit_multilabel_model(
    X: np.ndarray,
    y_labels: Sequence[Sequence[str]],
    threshold: float,
    uncertain_label: str,
    random_state: int,
) -> Tuple[MultiLabelBinarizer, OneVsRestClassifier, List[str], np.ndarray]:
    mlb = MultiLabelBinarizer()
    Y = mlb.fit_transform(y_labels)
    if Y.shape[1] == 0:
        raise ValueError("No valid labels found in coding sample.")

    clf = OneVsRestClassifier(
        LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            random_state=random_state,
        )
    )
    clf.fit(X, Y)

    probs = clf.predict_proba(X)
    predicted: List[str] = []
    for row in probs:
        assigned = [label for label, p in zip(mlb.classes_, row) if p >= threshold]
        if not assigned:
            assigned = [uncertain_label]
        predicted.append("|".join(assigned))

    return mlb, clf, predicted, probs


def train_and_apply(config: Dict[str, Any]) -> None:
    input_df = read_input_table(config)
    work_df = prepare_dataset(input_df, config)

    cfg = config["iterative_supervised"]
    question_value = str(cfg["question_value"])
    output_dir = Path(cfg.get("output_dir", "./output_iterative")).resolve()
    ensure_dir(output_dir)

    sample_path = output_dir / "coding_sample.csv"
    if not sample_path.exists():
        raise FileNotFoundError(
            f"Coding sample not found at {sample_path}. Run --step sample first."
        )

    subset = get_question_subset(work_df, question_value)
    delimiter = str(cfg.get("label_delimiter", "|"))
    min_labeled = int(cfg.get("minimum_labeled_rows", 8))
    threshold = float(cfg.get("probability_threshold", 0.45))
    uncertain_label = str(cfg.get("uncertain_label", "UNCERTAIN_REVIEW"))
    random_state = int(cfg.get("random_state", 42))
    embedding_model = str(cfg.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"))
    batch_size = int(cfg.get("embedding_batch_size", 32))

    # All-text read: numeric response_ids would otherwise be inferred as float
    # ("101" -> 101.0 -> "101.0"), breaking the join to the embedded subset so the
    # human-coded rows silently fail to match and training reports zero labels.
    # And the encoding fallback, because this is the one file in the whole
    # program the analyst is *asked* to open in Excel and save back: they type
    # labels into it, Excel re-encodes it as cp1252, and reading it as UTF-8
    # then fails on the first curly apostrophe in a response they were labelling.
    from core.encodings import read_csv as read_csv_with_fallback

    sample_df = read_csv_with_fallback(
        sample_path, dtype=str, keep_default_na=False).frame
    if "human_labels" not in sample_df.columns:
        raise ValueError("coding_sample.csv must include a 'human_labels' column.")
    sample_df = sample_df.assign(response_id=sample_df["response_id"].astype(str))

    sample_df = sample_df.assign(
        parsed_labels=sample_df["human_labels"].apply(
            lambda x: parse_multilabel_cell(x, delimiter=delimiter)
        )
    )
    labeled = sample_df[sample_df["parsed_labels"].map(len) > 0].copy()
    if len(labeled) < min_labeled:
        raise ValueError(
            f"Need at least {min_labeled} labeled rows, found {len(labeled)}. "
            "Please code more rows in coding_sample.csv."
        )

    # v2: use cache-aware embedding builder.
    cache_dir = output_dir / ".embedding_cache"
    embeddings = load_or_build_embeddings(
        texts=subset["response_text"].tolist(),
        model_name=embedding_model,
        batch_size=batch_size,
        cache_dir=cache_dir,
    )

    idx_by_id = {rid: i for i, rid in enumerate(subset["response_id"].astype(str).tolist())}
    labeled = labeled[labeled["response_id"].astype(str).isin(idx_by_id)].copy()
    labeled = labeled.assign(subset_idx=labeled["response_id"].astype(str).map(idx_by_id))

    X_train = embeddings[labeled["subset_idx"].to_numpy()]
    y_train = labeled["parsed_labels"].tolist()

    mlb, clf, _, _ = fit_multilabel_model(
        X=X_train,
        y_labels=y_train,
        threshold=threshold,
        uncertain_label=uncertain_label,
        random_state=random_state,
    )

    all_probs = clf.predict_proba(embeddings)
    predicted_labels: List[str] = []
    top_label: List[str] = []
    top_score: List[float] = []
    reason: List[str] = []
    proba_json: List[str] = []

    for row in all_probs:
        row_pairs = list(zip(mlb.classes_, [float(p) for p in row]))
        row_pairs_sorted = sorted(row_pairs, key=lambda x: x[1], reverse=True)
        above = [label for label, p in row_pairs_sorted if p >= threshold]

        if above:
            predicted_labels.append("|".join(above))
            reason.append("predicted_above_threshold")
        else:
            predicted_labels.append(uncertain_label)
            reason.append("no_label_above_threshold")

        if row_pairs_sorted:
            top_label.append(str(row_pairs_sorted[0][0]))
            top_score.append(float(row_pairs_sorted[0][1]))
        else:
            top_label.append("")
            top_score.append(float("nan"))

        proba_json.append(json.dumps({k: v for k, v in row_pairs_sorted}, ensure_ascii=True))

    # v2: build result_df via assign, not in-place mutation.
    # in_training_sample (Phase 2.2): the model was fit on these rows, so its
    # prediction on them is not held-out evidence. The Agreement tab excludes them
    # from kappa by default, and quality CV must not score on them either.
    training_ids = set(labeled["response_id"].astype(str))
    result_df = subset.assign(
        response_id=subset["response_id"].astype(str),
        supervised_labels=predicted_labels,
        supervised_top_label=top_label,
        supervised_top_score=top_score,
        supervised_reason=reason,
        supervised_all_probabilities_json=proba_json,
        in_training_sample=subset["response_id"].astype(str).isin(training_ids),
    )

    us_cfg = cfg.get("unsupervised", {})
    cluster_labels, clusterer, silhouette_scores = fit_clusters(
        embeddings=embeddings,
        cluster_cfg={
            "fixed_k": us_cfg.get("fixed_k"),
            "min_k": us_cfg.get("min_k", 2),
            "max_k": us_cfg.get("max_k", 6),
            "random_state": us_cfg.get("random_state", random_state),
            "top_terms_per_cluster": us_cfg.get("top_terms_per_cluster", 8),
            "sample_quotes_per_cluster": us_cfg.get("sample_quotes_per_cluster", 3),
        },
    )
    result_df = result_df.assign(cluster_id=cluster_labels)

    terms = extract_top_terms_by_cluster(
        texts=result_df["response_text"].tolist(),
        labels=cluster_labels,
        max_terms=int(us_cfg.get("top_terms_per_cluster", 8)),
    )
    reps = representative_examples(
        texts=result_df["response_text"].tolist(),
        labels=cluster_labels,
        embeddings=embeddings,
        centers=clusterer.cluster_centers_,
        per_cluster=int(us_cfg.get("sample_quotes_per_cluster", 3)),
    )
    cluster_summary_df = make_cluster_summary(result_df, terms, reps)

    exploded = result_df.copy()
    exploded = exploded.assign(
        supervised_label_single=exploded["supervised_labels"].str.split("|")
    )
    exploded = exploded.explode("supervised_label_single")
    label_summary_df = (
        exploded.groupby("supervised_label_single", dropna=False)
        .size()
        .reset_index(name="response_count")
        .sort_values("response_count", ascending=False)
    )

    label_cluster_df = (
        exploded.groupby(["supervised_label_single", "cluster_id"], dropna=False)
        .size()
        .reset_index(name="response_count")
        .sort_values(["supervised_label_single", "response_count"], ascending=[True, False])
    )

    # Phase 2.3: cross-validated quality, matched to the (usually small) sample
    # size, instead of a single 30% holdout that on 15 rows tests on ~4 items.
    quality_path = output_dir / "supervised_training_quality.txt"
    try:
        from analysis.quality import cross_val_per_code, format_quality_report
        quality = cross_val_per_code(
            X_train, y_train, classes=list(mlb.classes_), random_state=random_state
        )
        quality_text = format_quality_report(quality)
    except Exception as exc:  # noqa: BLE001
        quality_text = f"Training quality report not generated: {exc}\n"
    quality_path.write_text(quality_text, encoding="utf-8")

    result_df.to_csv(output_dir / "iterative_predictions.csv", index=False)
    cluster_summary_df.to_csv(output_dir / "iterative_cluster_summary.csv", index=False)
    label_summary_df.to_csv(output_dir / "iterative_label_summary.csv", index=False)
    label_cluster_df.to_csv(output_dir / "iterative_label_cluster_matrix.csv", index=False)
    (output_dir / "iterative_silhouette_scores.json").write_text(
        json.dumps(silhouette_scores, indent=2),
        encoding="utf-8",
    )
    # Save the full embeddings for reference (separate from the hash-keyed cache).
    np.save(output_dir / "iterative_embeddings.npy", embeddings)

    sample_join = sample_df.merge(
        result_df[
            [
                "response_id",
                "supervised_labels",
                "supervised_top_label",
                "supervised_top_score",
                "cluster_id",
            ]
        ],
        on="response_id",
        how="left",
    )
    sample_join.to_csv(output_dir / "coding_sample_with_model_suggestions.csv", index=False)

    LOGGER.info("Train step completed. Output directory: %s", output_dir)
    LOGGER.info("Predictions file: %s", output_dir / "iterative_predictions.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Iterative supervised+unsupervised thematic workflow for one survey question."
    )
    parser.add_argument("--config", required=True, help="Path to iterative YAML config file.")
    parser.add_argument(
        "--step",
        required=True,
        choices=["sample", "train"],
        help="sample=create coding sample, train=fit/apply model + unsupervised pass",
    )
    return parser.parse_args()


def main() -> None:
    from core.offline import enforce_local_mode

    # Same local-cache guarantee as the main pipeline (see core/offline.py).
    enforce_local_mode()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = parse_args()
    cfg = load_yaml(Path(args.config).expanduser().resolve())

    if "iterative_supervised" not in cfg:
        raise KeyError("Config must include 'iterative_supervised' section.")

    if args.step == "sample":
        create_coding_sample(cfg)
    elif args.step == "train":
        train_and_apply(cfg)
    else:
        raise ValueError(f"Unsupported step: {args.step}")


if __name__ == "__main__":
    main()
