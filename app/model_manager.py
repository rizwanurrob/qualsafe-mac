"""
Download and choose the local models for each role.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from app.shared.layout import stretch
from core import engine_install
from core.offline import human_size, model_cache_status

from app.shared.models import configured_model_names
from app.shared.state import maybe_persist_settings


def render_model_manager() -> None:
    """First-class page to download and choose the local models (v3.9.7, F4)."""
    from core.model_manager import (
        DEFAULT_MODELS, ROLE_GUIDANCE, ROLE_LABELS, ROLE_SESSION_KEY, ROLES,
        download_model, remove_from_cache,
    )

    st.header("Model Manager")
    st.caption(
        "Download and choose the local models QualSafe uses. Downloads run in a "
        "**separate process**, so analysis itself always stays offline — your data is "
        "never uploaded, only model weights are fetched. You can point any role at a "
        "different model, not just the defaults."
    )

    _render_engine_installer()

    # ── Cache status (read-only; scanning the cache needs no network) ──────────
    st.subheader("Cache status")
    rows = model_cache_status(configured_model_names())
    st.dataframe(
        pd.DataFrame([{
            "model": r["model"],
            "status": ("unknown" if r["cached"] is None else ("cached" if r["cached"] else "MISSING")),
            "size": human_size(float(r["size_bytes"])) if r["size_bytes"] else "—",
        } for r in rows]),
        **stretch(), hide_index=True,
    )

    # ── Per-role model selection + download ───────────────────────────────────
    st.subheader("Models by role")
    st.caption("Change the model id and download it, or point at one already cached.")
    for role in ROLES:
        key = ROLE_SESSION_KEY[role]
        current = st.session_state.get(key, DEFAULT_MODELS[role])
        with st.container(border=True):
            st.markdown(f"**{ROLE_LABELS[role]}**  \n{ROLE_GUIDANCE[role]}")
            st.caption(f"Currently using: `{current}`")
            new_id = st.text_input("Model id (Hugging Face repo)", value=current,
                                   key=f"mm_id_{role}", label_visibility="collapsed")
            c1, c2, c3 = st.columns([2, 2, 3])
            if c1.button("Download & use", key=f"mm_dl_{role}"):
                with st.spinner(f"Downloading {new_id} … (one-time; may take several minutes)"):
                    result = download_model(new_id, role)
                if result["ok"]:
                    st.session_state[key] = new_id.strip()
                    maybe_persist_settings()
                    st.success(f"{ROLE_LABELS[role]} model set to `{new_id}` and cached.")
                    st.rerun()
                else:
                    st.error(result["message"])
            if c2.button("Use (already cached)", key=f"mm_use_{role}",
                         help="Select this model without downloading — only works if it "
                              "is already in the cache."):
                st.session_state[key] = new_id.strip()
                maybe_persist_settings()
                st.success(f"{ROLE_LABELS[role]} model set to `{new_id}`.")
                st.rerun()
            if c3.button("Reset to default", key=f"mm_def_{role}"):
                st.session_state[key] = DEFAULT_MODELS[role]
                maybe_persist_settings()
                st.rerun()

    # ── Cache maintenance ─────────────────────────────────────────────────────
    st.subheader("Cache maintenance")
    st.caption("Remove a model from this machine's Hugging Face cache to reclaim disk. "
               "It can always be downloaded again.")
    rm = st.text_input("Model id to remove", key="mm_rm", placeholder="e.g. facebook/bart-large-mnli")
    if st.button("Remove from cache", key="mm_rm_btn", disabled=not rm.strip()):
        try:
            freed = remove_from_cache(rm.strip())
            if freed:
                st.success(f"Removed `{rm}` — {human_size(float(freed))} freed.")
            else:
                st.info(f"`{rm}` was not in the cache (nothing removed).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Remove failed: {exc}")


def _render_engine_installer() -> None:
    """Offer to install the analysis engine (PyTorch and friends) when it is missing, with live progress."""
    if engine_install.installed():
        return
    folder = engine_install.engine_dir()
    st.subheader("The analysis engine")
    st.info(
        "Automatic suggested codes need the analysis engine (PyTorch, transformers and "
        "sentence-transformers). It is not part of the installer. QualSafe downloads it **once** "
        f"(about 1 GB, 10 to 30 minutes, internet needed) into a folder of your own outside the program: `{folder}`. "
        "Everything else works without it."
    )
    if not st.button("Install the analysis engine", key="engine_install_btn"):
        return
    with st.status("Installing the analysis engine…", expanded=True) as status:
        line_box = st.empty()
        try:
            engine_install.install(progress=lambda line: line_box.caption(line[:200]))
        except engine_install.EngineInstallError as error:
            status.update(label="The analysis engine did not install", state="error")
            st.error(str(error) + " Nothing is broken: press the button again and it carries on from where it stopped.")
            if error.log:
                st.code(error.log[-1500:])
            return
        status.update(label="The analysis engine is installed", state="complete")
    st.success("Done. Download the models below, then run automatic suggested codes.")
