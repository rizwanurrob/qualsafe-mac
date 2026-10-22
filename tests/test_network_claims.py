"""The program uses the internet in two places the person starts (the engine install and a model download).
No screen or document may say a model download is the only one."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["INSTALL_DESKTOP.md", "app/settings_page.py", "app/shared/models.py",
         "qualsafe_qt/views/help_view.py", "core/ux/help/troubleshooting.md", "app/model_manager.py",
         "app/__init__.py", "qualsafe_qt/main.py", "core/model_readiness.py"]
#: 'the only step / time / network activity ... model' with no engine in the same sentence.
CLAIM = re.compile(r"only (?:step|time|network)[^.]{0,140}?(?:download|model)[^.]*\.", re.IGNORECASE | re.DOTALL)


def test_nothing_says_a_model_download_is_the_only_use_of_the_internet():
    bad = []
    for name in FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        for found in CLAIM.finditer(text):
            sentence = found.group(0)
            if "engine" not in sentence.lower():
                bad.append(f"{name}: {' '.join(sentence.split())[:120]}")
    assert not bad, bad


def test_the_web_model_panel_sends_a_person_without_the_engine_to_install_it_first(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from core import engine_install
    import app.shared.models as models

    monkeypatch.setattr(engine_install, "installed", lambda: False)         # restored after the test
    monkeypatch.setattr(models, "model_cache_status",
                        lambda names: [{"model": "x/y", "cached": False, "size_bytes": 0}])
    script = "import app.shared.models as m\nm.render_model_status_panel()\n"
    at = AppTest.from_string(script, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert any("Install the analysis engine" in i.value for i in at.info)
    assert not [b for b in at.button if b.key == "download_models_btn"]
