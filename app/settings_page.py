"""Settings: appearance, models, and project and backups (Update 3, phase 4b).

Not an activity. It holds what you set once: how the app looks, which language models are on this
computer, and what to do with a project file (back up, archive, erase a participant). The model and
project screens are the existing ones, moved here (`V8_PLAN.md` section 3.5).

Per `app/__init__`, this module imports only from `core/`, `analysis/`, `exports/`, `app.shared`
and Streamlit, never from the shell.
"""

from __future__ import annotations

import streamlit as st

from app.data_management import render_data_management
from app.model_manager import render_model_manager
from app.shared import nav
from app.shared.state import render_appearance_control


def render_settings() -> None:
    st.header("Settings")
    tab = st.radio("Settings", nav.SETTINGS_TABS, key="settings_tab", horizontal=True,
                   label_visibility="collapsed")
    if tab == "Models":
        render_model_manager()
    elif tab == "Project and backups":
        render_data_management()
    else:
        _render_general()


def _render_general() -> None:
    st.subheader("How it looks")
    render_appearance_control(container=st)
    st.subheader("Your name")
    st.text_input("Analyst name", key="analyst_name",
                  help="Shown on the reports you make and recorded with your coding.")
    st.subheader("Offline")
    st.write("QualSafe works without the internet. The only time it uses the internet is when "
             "you ask it to install the analysis engine or download a language model, under Models.")
