"""
Tests for `core/run_config.py` — the one pipeline-config implementation.

This module exists because there were two. `app/shared/data.build_general_config`
read every choice out of `st.session_state`, so it could not be imported outside
Streamlit and could not be tested anywhere; the desktop build reimplemented it,
and `resolve_long_dataframe` — the melt that mints `response_id`, and the code
behind this project's worst shipped bug — ended up with two copies that had to
agree by hand (`PORTED_BACK.md` §7 and §9).

So the assertions here are not decoration. **The config dict is a contract with
`analyze_survey.run_pipeline`**: a key that silently changes shape is a silently
different analysis, from the same data and the same button.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.label_packs import BUILTIN_PACKS, all_packs
from core.run_config import (
    FALLBACK_LABELS, PREVIEW_ROWS, RunSettings, build_config, label_packs,
    mapping_is_ready, parse_labels, parse_per_question_labels, question_values,
    resolve_long_dataframe)


@pytest.fixture()
def long_frame():
    return pd.DataFrame({
        "id": ["r1", "r2", "r3"],
        "answer": ["too expensive", "advisor helped", "hard to belong"],
        "year": ["First", "Senior", "First"],
    })


@pytest.fixture()
def wide_frame():
    return pd.DataFrame({
        "id": ["r1", "r2"],
        "Q1 What went well?": ["the advising", "the library"],
        "Q2 What was hard?": ["the cost", "the commute"],
        "year": ["First", "Senior"],
    })


class TestParsing:

    def test_labels_are_one_per_line_deduped_and_ordered(self):
        assert parse_labels("Cost\n\nAdvising\nCost\n  Belonging  ") == [
            "Cost", "Advising", "Belonging"]

    def test_empty_label_text_is_empty_not_none(self):
        assert parse_labels("") == []
        assert parse_labels(None) == []

    def test_per_question_labels_use_the_documented_format(self):
        parsed = parse_per_question_labels(
            "Q1 :: Cost | Advising\nnot a mapping line\nQ2::Belonging")
        assert parsed == {"Q1": ["Cost", "Advising"], "Q2": ["Belonging"]}

    def test_a_mapping_line_with_no_labels_is_dropped(self):
        assert parse_per_question_labels("Q1 :: ") == {}


class TestResolveLongDataframe:
    """The melt that mints `response_id`. Two implementations of this was the
    risk; one is the point."""

    def test_long_data_passes_through_with_its_own_columns(self, long_frame):
        settings = RunSettings(text_column="answer", id_column="id",
                               descriptor_columns=["year"])

        frame, text, question, ident, descriptors = resolve_long_dataframe(
            long_frame, settings)

        assert text == "answer" and ident == "id" and descriptors == ["year"]
        assert question == "question_text", "a manual label column is stamped on"
        assert set(frame["question_text"]) == {"All Responses"}

    def test_a_manual_question_label_is_used_when_given(self, long_frame):
        settings = RunSettings(text_column="answer",
                               question_text_manual="  Entry survey  ")

        frame, _text, _q, _id, _d = resolve_long_dataframe(long_frame, settings)

        assert set(frame["question_text"]) == {"Entry survey"}

    def test_wide_data_melts_and_mints_a_unique_response_id(self, wide_frame):
        settings = RunSettings(
            ingestion_mode="wide", id_column="id",
            text_columns=["Q1 What went well?", "Q2 What was hard?"],
            descriptor_columns=["year"])

        frame, text, question, ident, _descriptors = resolve_long_dataframe(
            wide_frame, settings)

        assert (text, question, ident) == ("response_text", "question_text", "response_id")
        assert len(frame) == 4, "two respondents x two questions"
        assert frame["response_id"].nunique() == 4, \
            "a per-answer id, or coding detaches from responses"
        assert frame["respondent_id"].nunique() == 2, "and a grouping id"

    def test_wide_mode_honours_question_label_overrides(self, wide_frame):
        settings = RunSettings(
            ingestion_mode="wide", id_column="id",
            text_columns=["Q1 What went well?"],
            question_label_overrides_text="Q1 What went well? :: Strengths")

        frame, _t, _q, _i, _d = resolve_long_dataframe(wide_frame, settings)

        assert set(frame["question_text"]) == {"Strengths"}

    def test_a_missing_text_column_is_refused_with_a_sentence(self, long_frame):
        with pytest.raises(ValueError, match="text column"):
            resolve_long_dataframe(long_frame, RunSettings(text_column="nope"))

    def test_wide_mode_with_no_question_columns_is_refused(self, wide_frame):
        with pytest.raises(ValueError, match="at least one question column"):
            resolve_long_dataframe(wide_frame, RunSettings(ingestion_mode="wide"))

    def test_a_descriptor_that_is_not_a_column_is_dropped_quietly(self, long_frame):
        settings = RunSettings(text_column="answer",
                               descriptor_columns=["year", "ghost"])

        _f, _t, _q, _i, descriptors = resolve_long_dataframe(long_frame, settings)

        assert descriptors == ["year"]


class TestBuildConfig:

    def _config(self, frame, tmp_path, **kwargs):
        settings = RunSettings(text_column="answer", id_column="id", **kwargs)
        return build_config(frame, settings, tmp_path)

    def test_the_input_points_at_a_snapshot_inside_the_run_directory(
            self, long_frame, tmp_path):
        """The run's input lives and dies with the outputs it produced."""
        config = self._config(long_frame, tmp_path)

        written = Path(config["input"]["file_path"])
        assert written.name == "run_input_filtered.csv"
        assert written.parent == tmp_path.resolve()
        assert len(pd.read_csv(written)) == 3

    def test_labels_fall_back_when_the_analyst_wrote_none(self, long_frame, tmp_path):
        config = self._config(long_frame, tmp_path)
        assert config["zero_shot"]["labels"] == list(FALLBACK_LABELS)

    def test_the_analysts_labels_reach_both_zero_shot_passes(self, long_frame, tmp_path):
        config = self._config(long_frame, tmp_path, labels_text="Cost\nAdvising")

        assert config["zero_shot"]["labels"] == ["Cost", "Advising"]
        assert (config["thematic_analysis"]["by_question_zero_shot"]["default_labels"]
                == ["Cost", "Advising"])

    def test_one_question_mode_filters_the_rows(self, wide_frame, tmp_path):
        settings = RunSettings(
            ingestion_mode="wide", id_column="id",
            text_columns=["Q1 What went well?", "Q2 What was hard?"],
            analyze_one_question=True, question_filter_value="Q2 What was hard?")

        config = build_config(wide_frame, settings, tmp_path)

        assert len(pd.read_csv(config["input"]["file_path"])) == 2

    def test_filtering_to_nothing_is_refused_rather_than_running_empty(
            self, long_frame, tmp_path):
        settings = RunSettings(text_column="answer", analyze_one_question=True,
                               question_filter_value="a question nobody asked")
        with pytest.raises(ValueError, match="No rows left"):
            build_config(long_frame, settings, tmp_path)

    def test_a_preview_caps_rows_and_refuses_to_be_the_project_of_record(
            self, long_frame, tmp_path):
        settings = RunSettings(text_column="answer", save_project_store=True)

        config = build_config(long_frame, settings, tmp_path, preview=True)

        assert config["preprocessing"]["max_rows"] == PREVIEW_ROWS
        assert config["output"]["project_store_path"] is None

    def test_a_real_run_writes_a_project_store_unless_told_not_to(
            self, long_frame, tmp_path):
        on = self._config(long_frame, tmp_path, save_project_store=True)
        off = self._config(long_frame, tmp_path, save_project_store=False)

        assert on["output"]["project_store_path"].endswith("project.qnw")
        assert off["output"]["project_store_path"] is None

    def test_per_engine_strict_thresholds_stay_apart(self, long_frame, tmp_path):
        """Transformer scores are NLI entailment, LLM scores are self-report.
        They are not comparable, which is why they are stored separately."""
        config = self._config(long_frame, tmp_path, strict_top1_transformer=0.61,
                              strict_top1_llm=0.77)

        assert config["strict_thresholds"]["transformer"]["top1_min_score"] == 0.61
        assert config["strict_thresholds"]["llm"]["top1_min_score"] == 0.77

    def test_the_global_strict_pair_is_settable(self, long_frame, tmp_path):
        """The desktop build hardcoded these; Streamlit exposed them. The shared
        version keeps what each had, so it has to be a field."""
        config = self._config(long_frame, tmp_path, strict_top1_global=0.66,
                              strict_margin_global=0.22)

        strict = config["zero_shot"]["strict_coding"]
        assert strict["top1_min_score"] == 0.66
        assert strict["min_margin_over_second"] == 0.22

    def test_the_config_carries_every_section_the_pipeline_reads(
            self, long_frame, tmp_path):
        """A missing section is a crash mid-run, after the models have loaded."""
        config = self._config(long_frame, tmp_path)

        assert {"input", "preprocessing", "models", "pipeline", "clustering",
                "sentiment", "zero_shot", "thematic_analysis", "engine",
                "strict_thresholds", "output", "report"} <= set(config)


class TestMappingReadiness:

    def test_long_mode_needs_a_text_column_that_exists(self, long_frame):
        assert mapping_is_ready(long_frame, RunSettings(text_column="answer"))
        assert not mapping_is_ready(long_frame, RunSettings(text_column="ghost"))
        assert not mapping_is_ready(long_frame, RunSettings())

    def test_wide_mode_needs_every_chosen_column_to_exist(self, wide_frame):
        good = RunSettings(ingestion_mode="wide", text_columns=["Q1 What went well?"])
        bad = RunSettings(ingestion_mode="wide",
                          text_columns=["Q1 What went well?", "ghost"])
        assert mapping_is_ready(wide_frame, good)
        assert not mapping_is_ready(wide_frame, bad)

    def test_no_dataframe_is_never_ready(self):
        assert not mapping_is_ready(None, RunSettings(text_column="answer"))
        assert not mapping_is_ready(pd.DataFrame(), RunSettings(text_column="answer"))


class TestQuestionValues:

    def test_long_mode_lists_the_values_in_the_question_column(self):
        frame = pd.DataFrame({"q": ["B", "A", "B"], "answer": ["x", "y", "z"]})
        values = question_values(frame, RunSettings(question_column="q"))
        assert values == ["A", "B"]

    def test_wide_mode_lists_the_chosen_columns_with_overrides_applied(self, wide_frame):
        settings = RunSettings(
            ingestion_mode="wide",
            text_columns=["Q1 What went well?", "Q2 What was hard?"],
            question_label_overrides_text="Q1 What went well? :: Strengths")

        assert question_values(wide_frame, settings) == ["Strengths", "Q2 What was hard?"]


class TestLabelPacks:

    def test_the_builtin_packs_are_reachable_without_a_front_end(self):
        """The content used to sit behind a Streamlit import, so the desktop
        build carried a second copy."""
        assert "Education / Student Experience" in BUILTIN_PACKS
        assert len(BUILTIN_PACKS) == 5

    def test_education_leads_because_the_sample_dataset_matches_it(self):
        assert list(BUILTIN_PACKS)[0] == "Education / Student Experience"

    def test_all_packs_includes_the_builtins(self):
        assert set(BUILTIN_PACKS) <= set(all_packs())

    def test_run_config_re_exports_the_same_object(self):
        assert label_packs()["Education / Student Experience"] == \
            BUILTIN_PACKS["Education / Student Experience"]


class TestBothFrontEndsAgree:
    """The reason this module exists: one button, one analysis.

    The Streamlit adapter reads session state and calls the same builder. If it
    ever stops producing what a plain `RunSettings` produces, the two front ends
    have drifted again.
    """

    def test_the_streamlit_adapter_is_a_call_into_this_module(self):
        import inspect

        from app.shared import data as streamlit_data

        for name in ("resolve_long_dataframe", "build_general_config",
                     "current_question_values"):
            source = inspect.getsource(getattr(streamlit_data, name))
            assert "st.session_state" in source, f"{name} should read session state"
            assert "settings_from_session()" in source, \
                f"{name} must delegate, not reimplement"

    def test_the_adapter_covers_every_setting(self):
        """A field added to RunSettings and not read from session state is a
        default silently overriding the analyst's choice."""
        import inspect

        from app.shared.data import settings_from_session

        source = inspect.getsource(settings_from_session)
        for field in RunSettings().__dataclass_fields__:
            assert f"{field}=" in source, f"settings_from_session ignores {field}"
