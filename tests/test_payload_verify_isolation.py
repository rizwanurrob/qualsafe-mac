"""The desktop payload check must not leave its own session in the payload (a stray progress.json shipped in ux5)."""

from __future__ import annotations

from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "packaging" / "build_payload.py").read_text(encoding="utf-8")


def test_the_payload_check_runs_with_a_throwaway_settings_folder_and_refuses_strays():
    verify = SOURCE[SOURCE.index("def verify(payload_python"):SOURCE.index("def _assert_versions_agree")]
    assert "QNW_SETTINGS_DIR" in verify and "env=env" in verify
    assert "progress.json" in verify and "app_settings.json" in verify
