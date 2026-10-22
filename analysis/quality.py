#!/usr/bin/env python
"""
Honest quality estimation for small hand-coded samples (v3.2, Phase 2.3).

The iterative workflow used to estimate model quality with a single 30% holdout.
On the sample sizes this tool actually runs on (often 10–30 coded rows) that is
close to meaningless: the test set is 3–9 items, one lucky or unlucky split
swings every metric, and per-code numbers are computed on codes that appear once
or twice.

This module replaces the single split with cross-validation matched to the sample
size, and reports per-code metrics only where the code has enough support to mean
anything:

- **n < 30 labeled: leave-one-out.** Cheap at 384-dim embeddings, and it uses
  every item for both training and testing without a wasteful holdout.
- **30 ≤ n < 100: 5-fold.** Folds are not multilabel-stratified unless the
  optional `iterstrat` dependency is present; when it isn't, we say so rather than
  implying a stratification we didn't do.
- **n ≥ 100: 5-fold** as well (the single-holdout regime is never the right call
  here).

Two correctness details that bite in this regime:

1. **Fit the label binarizer once, on the full label set, with fixed classes.**
   If each fold refits `MultiLabelBinarizer`, a code that is absent from a fold's
   training labels shifts the column layout, and per-code metrics stop aligning
   across folds. Classes are fixed up front.
2. **Report per-code metrics only where support ≥ threshold**, reusing the
   `insufficient_support(<N)` convention from `analysis/agreement.py` so the two
   rigor surfaces speak the same language.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

DEFAULT_MIN_SUPPORT = 5


def choose_cv_scheme(n_labeled: int) -> Dict[str, Any]:
    """Pick a CV scheme from the labeled-sample size. Pure — easy to test."""
    if n_labeled < 5:
        return {"scheme": "too_small", "n_splits": 0,
                "note": "Fewer than 5 labeled rows — no reliable quality estimate is possible."}
    if n_labeled < 30:
        return {"scheme": "leave_one_out", "n_splits": n_labeled,
                "note": "Leave-one-out CV (small sample)."}
    return {"scheme": "k_fold", "n_splits": 5,
            "note": "5-fold CV. Folds are not multilabel-stratified unless 'iterstrat' is installed."}


def _fold_indices(n: int, n_splits: int, random_state: int) -> List[np.ndarray]:
    """Row indices for each test fold (LOO when n_splits == n)."""
    rng = np.random.default_rng(random_state)
    order = rng.permutation(n)
    return [np.sort(fold) for fold in np.array_split(order, n_splits)]


def cross_val_per_code(
    X: np.ndarray,
    label_sets: Sequence[Sequence[str]],
    classes: Sequence[str],
    *,
    threshold: float = 0.5,
    min_support: int = DEFAULT_MIN_SUPPORT,
    random_state: int = 42,
    fit_fn=None,
) -> Dict[str, Any]:
    """Cross-validated per-code precision/recall/F1 over a small coded sample.

    Parameters
    ----------
    X : (n, d) feature matrix (embeddings).
    label_sets : per-row lists of applied labels.
    classes : the fixed, full label universe (binarizer columns).
    fit_fn : optional (X_train, Y_train) -> predict(X_test)->Y_pred, injected for
        testing. Defaults to a one-vs-rest logistic regression matching the
        workflow's model.

    Returns a dict with the CV scheme used and a per-code metrics list. Codes with
    support < min_support are reported with a note and no unstable metric.
    """
    from sklearn.preprocessing import MultiLabelBinarizer

    n = len(label_sets)
    scheme = choose_cv_scheme(n)
    classes = list(classes)

    # Fit the binarizer ONCE with fixed classes so columns never shift per fold.
    mlb = MultiLabelBinarizer(classes=classes)
    Y = mlb.fit_transform([list(s) for s in label_sets])

    result: Dict[str, Any] = {"scheme": scheme["scheme"], "n_splits": scheme["n_splits"],
                              "n_labeled": n, "note": scheme["note"], "codes": []}
    if scheme["scheme"] == "too_small":
        return result

    if fit_fn is None:
        fit_fn = _default_fit_fn(random_state)

    # Accumulate out-of-fold predictions for every item, then score per code.
    y_pred = np.zeros_like(Y)
    X = np.asarray(X)
    for test_idx in _fold_indices(n, scheme["n_splits"], random_state):
        train_idx = np.setdiff1d(np.arange(n), test_idx)
        if len(train_idx) == 0:
            continue
        predict = fit_fn(X[train_idx], Y[train_idx])
        pred = predict(X[test_idx])
        y_pred[test_idx] = (np.asarray(pred) >= threshold).astype(int)

    for j, code in enumerate(classes):
        support = int(Y[:, j].sum())
        if support < min_support:
            result["codes"].append({
                "code": code, "support": support,
                "precision": None, "recall": None, "f1": None,
                "note": f"insufficient_support(<{min_support})",
            })
            continue
        tp = int(((Y[:, j] == 1) & (y_pred[:, j] == 1)).sum())
        fp = int(((Y[:, j] == 0) & (y_pred[:, j] == 1)).sum())
        fn = int(((Y[:, j] == 1) & (y_pred[:, j] == 0)).sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        result["codes"].append({
            "code": code, "support": support,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "note": "",
        })
    return result


def _default_fit_fn(random_state: int):
    """One-vs-rest logistic regression, matching the iterative workflow's model."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.multiclass import OneVsRestClassifier

    def fit(X_train, Y_train):
        # A code absent from this fold's training rows can't be learned; predict it
        # as always-absent rather than letting the fit choke on a single class.
        clf = OneVsRestClassifier(
            LogisticRegression(max_iter=1000, class_weight="balanced", random_state=random_state)
        )
        present = Y_train.sum(axis=0) > 0
        if present.all():
            clf.fit(X_train, Y_train)
            full_predict = clf.predict_proba

            def predict(X_test):
                return full_predict(X_test)
        else:
            # Fit only on columns with at least one positive; zero-fill the rest.
            cols = np.where(present)[0]
            clf.fit(X_train, Y_train[:, cols])

            def predict(X_test):
                out = np.zeros((len(X_test), Y_train.shape[1]))
                out[:, cols] = clf.predict_proba(X_test)
                return out
        return predict

    return fit


def format_quality_report(result: Dict[str, Any]) -> str:
    """Human-readable text report (written next to the model outputs)."""
    lines = [
        "Supervised training quality (cross-validated)",
        "=" * 46,
        f"Labeled rows: {result['n_labeled']}",
        f"Scheme: {result['note']}",
        "",
    ]
    if result["scheme"] == "too_small":
        return "\n".join(lines)
    lines.append(f"{'code':<32} {'support':>7} {'prec':>6} {'recall':>7} {'f1':>6}")
    lines.append("-" * 62)
    for c in result["codes"]:
        if c["note"]:
            lines.append(f"{c['code']:<32} {c['support']:>7}   (insufficient support)")
        else:
            lines.append(f"{c['code']:<32} {c['support']:>7} {c['precision']:>6} "
                         f"{c['recall']:>7} {c['f1']:>6}")
    lines.append("")
    lines.append("Per-code metrics shown only where support >= "
                 f"{DEFAULT_MIN_SUPPORT}; smaller codes are too rare to score reliably.")
    return "\n".join(lines)
