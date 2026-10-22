"""
Model cache status, downloads, and Ollama setup panels.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from typing import List
import pandas as pd
import streamlit as st
from app.shared.layout import stretch
from core.offline import human_size, model_cache_status


def configured_model_names() -> List[str]:
    """The HF models the current settings would load (all three roles)."""
    from core.model_manager import DEFAULT_MODELS
    names = [
        st.session_state.get("adv_embedding_model", DEFAULT_MODELS["embedding"]),
        st.session_state.get("adv_sentiment_model", DEFAULT_MODELS["sentiment"]),
        st.session_state.get("adv_zero_shot_model", DEFAULT_MODELS["zero-shot"]),
    ]
    return sorted(set(names))


def render_model_status_panel() -> None:
    """Show which models are cached, and offer the one download path.

    Analysis runs with the model hub disabled, so a missing model is a hard stop.
    Without this panel the analyst would meet that as an opaque Hugging Face
    error mid-run; here they can see it and fix it before starting.
    """
    with st.expander("Model status (offline cache)", expanded=False):
        st.caption(
            "Analysis runs with model-hub access switched off — models are read from "
            "this machine's cache. Your survey text is never uploaded; the download "
            "below fetches model weights only."
        )
        rows = model_cache_status(configured_model_names())
        table = pd.DataFrame(
            [
                {
                    "model": r["model"],
                    "status": (
                        "unknown" if r["cached"] is None else ("cached" if r["cached"] else "MISSING")
                    ),
                    "size": human_size(float(r["size_bytes"])) if r["size_bytes"] else "—",
                }
                for r in rows
            ]
        )
        st.dataframe(table, **stretch())

        missing = [r["model"] for r in rows if r["cached"] is False]
        if missing:
            st.warning(
                f"**{len(missing)} model(s) not downloaded.** Analysis will stop with an error "
                f"until they are. Download them once, here."
            )
            from core import engine_install

            if not engine_install.installed():
                st.info(
                    "The models need the analysis engine first, and it is not installed. Open Settings, then "
                    "Models, and press **Install the analysis engine** (about 1 GB, once). Then come back here."
                )
            else:
                st.caption(
                    "This contacts Hugging Face to fetch model weights (~1.6 GB for the zero-shot model); "
                    "installing the analysis engine is the only other time this program uses the internet. "
                    "None of your text is sent."
                )
                if st.button("Download missing models", key="download_models_btn"):
                    _download_models_in_app(missing)
        else:
            st.success("All required models are cached. The tool can run fully offline.")


def _download_models_in_app(missing: List[str]) -> None:
    """Fetch missing models via the download subprocess (never un-pins this process).

    The download runs in `tools/download_models.py` as a separate process, so the
    app's offline flags are never lifted — analysis can't reach the hub as a side
    effect of a download. Roles are resolved from the current settings (so a custom
    model downloads for its correct role), not guessed from the model name.
    """
    from core.model_manager import configured_role_models, download_model

    role_of = {name: role for role, name in configured_role_models(st.session_state.get).items()}
    for name in missing:
        role = role_of.get(name, "embedding")
        with st.spinner(f"Downloading {name} … (one-time; may take several minutes)"):
            result = download_model(name, role)
        if not result["ok"]:
            st.error(f"{name}: {result['message']}")
            st.caption("If you are behind a proxy, set HTTPS_PROXY before launching the app.")
            return
    st.success("Models downloaded. Analysis can now run offline.")


def render_ollama_setup_panel(model: str) -> None:
    """Guided Ollama setup: detect state, instruct, pull the model with progress."""
    from engines.ollama_setup import (
        install_instructions, installation_status, recommended_models, start_server_command)

    with st.expander("Ollama setup", expanded=False):
        status = installation_status()
        state = status["state"]

        if state == "ready":
            st.success(f"Ollama is running (v{status['version']}).")
        elif state == "installed_not_running":
            st.warning("Ollama is installed but its server isn't running.")
            st.caption("Start it, then re-check:")
            st.code(start_server_command(), language="bash")
        else:  # not_installed
            info = install_instructions()
            st.warning(f"Ollama isn't installed. {info['headline']} ({info['os']}).")
            for i, step in enumerate(info["steps"], 1):
                st.markdown(f"{i}. {step}")
            if info["command"]:
                st.code(info["command"], language="bash")
            st.markdown(f"[Open the Ollama download page]({info['url']})")
            st.caption("Installing system software runs in your terminal, not in this app. "
                       "The Transformer engine needs none of this and is the default.")

        if st.button("Re-check Ollama", key="ollama_recheck"):
            st.rerun()

        # Model pull — only meaningful once the server is up.
        if state == "ready":
            from engines.ollama_client import OllamaClient
            client = OllamaClient()
            pulled = client.list_models()
            st.caption(f"Downloaded models: {', '.join(pulled) if pulled else '(none)'}")
            if model not in pulled:
                st.info(f"The selected model '{model}' isn't downloaded yet.")
                recs = ", ".join(m["tag"] for m in recommended_models())
                st.caption(f"Small models that work well: {recs}")
                if st.button(f"Download '{model}' (one-time)", key="ollama_pull"):
                    bar = st.progress(0.0, text=f"Downloading {model}…")

                    def _on_progress(evt):
                        total = evt.get("total") or 0
                        done = evt.get("completed") or 0
                        if total:
                            bar.progress(min(done / total, 1.0),
                                         text=f"Downloading {model}… {int(done/total*100)}%")
                    try:
                        client.pull(model, on_progress=_on_progress)
                        bar.progress(1.0, text="Download complete.")
                        st.success(f"Downloaded '{model}'. You can run the local language model now.")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Pull failed: {exc}")
            else:
                st.success(f"Model '{model}' is downloaded and ready.")
