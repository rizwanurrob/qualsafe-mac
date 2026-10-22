"""
Re-exports of the shared pipeline config. Nothing is defined here any more.

This module used to hold the whole thing: `RunSettings`, `resolve_long_dataframe`,
`build_config`, the starter label packs. It existed because
`app/shared/data.build_general_config` read every choice out of
`st.session_state`, so it could not be imported into a process that must not
depend on Streamlit — and reimplementing it here was the only way to have a
desktop pipeline at all.

That was always a duplication with a cost, and `PORTED_BACK.md` §7 and §9 said
so: two copies of `resolve_long_dataframe` — the melt that mints `response_id` —
had to agree by hand, and the config dict governing every analysis had no test
anywhere upstream.

The fix landed upstream. `core/run_config.py` is that same construction, and both
front ends are now thin adapters over it, so a default cannot drift between the
builds and produce different analyses from the same data and the same button.

The names stay importable from here because two modules ask for them at this
path, and moving a caller is a change with no benefit. Import either way; they
are the same objects.
"""

from __future__ import annotations

from core.run_config import (  # noqa: F401 - re-exported for this package's callers
    FALLBACK_LABELS,
    PREVIEW_ROWS,
    SUGGESTED_LABEL_PACKS,
    SUPPORTED_TABLE_SUFFIXES,
    RunSettings,
    build_config,
    estimate_runtime_minutes,
    label_packs,
    load_table,
    mapping_is_ready,
    parse_labels,
    parse_per_question_labels,
    question_values,
    resolve_long_dataframe,
    write_config_snapshot,
)

__all__ = [
    "FALLBACK_LABELS",
    "PREVIEW_ROWS",
    "SUGGESTED_LABEL_PACKS",
    "SUPPORTED_TABLE_SUFFIXES",
    "RunSettings",
    "build_config",
    "estimate_runtime_minutes",
    "label_packs",
    "load_table",
    "mapping_is_ready",
    "parse_labels",
    "parse_per_question_labels",
    "question_values",
    "resolve_long_dataframe",
    "write_config_snapshot",
]
