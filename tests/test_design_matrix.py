"""
The case-level design matrix (`V6_PLAN.md` §2, Phase A).

Every v6 model rests on this table, so an error here is an error in every result
built on it and invisible in all of them. These tests are therefore about the
four decisions that could go quietly wrong rather than about whether a frame
comes back.

**The unit.** One row per case, never one per coding. Getting this wrong weights
the sample by how much the analyst coded each person, which is an artifact of
the coding process and not a property of the data.

**Absent versus missing.** A code not applied is a real zero. A descriptor never
collected is unknown. Turning the second into the first invents data.

**Pooled coders.** Two coders in one matrix build a variable neither asserted,
and unlike a heatmap a regression reports a coefficient for it.

**Reference levels and near-constant columns.** An unstated baseline makes a
dummy coefficient uninterpretable; a column varying on two cases produces a
standard error that reads as a finding.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.design_matrix import (
    CODE_PREFIX, DESC_PREFIX, MIN_VARYING, build_design_matrix,
    matrix_from_project)
from core.model import Code, CodeApplication, Descriptor, Excerpt, Source
from core.project import Project


def coding(rows):
    """`rows` are (source_id, code_name) or (source_id, code_name, rater)."""
    out = []
    for row in rows:
        source, name = row[0], row[1]
        rater = row[2] if len(row) > 2 else "human_primary"
        out.append({"application_id": f"a{len(out)}",
                    "excerpt_id": f"e{len(out)}",
                    "source_id": str(source), "code_name": name,
                    "rater_id": rater, "respondent_id": f"r{source}"})
    return pd.DataFrame(out)


def descriptors(rows):
    return pd.DataFrame([{"source_id": str(s), "key": k, "value": v}
                         for s, k, v in rows])


def wide_coding(n_cases=40, code="Cost", every=2):
    """`n_cases` cases; `code` applied to every `every`-th one, plus a code
    everyone has so the matrix is never single-column."""
    rows = [(i, "Present") for i in range(n_cases)]
    rows += [(i, code) for i in range(0, n_cases, every)]
    return coding(rows)


class TestTheUnitIsTheCase:
    """One row per case. Not one per coding — that would weight the sample by
    how much the analyst coded each person."""

    def test_one_row_per_case_not_per_coding(self):
        table = coding([(1, "Cost"), (1, "Access"), (1, "Staff"), (2, "Cost")])

        matrix = build_design_matrix(table, drop_near_constant=False)

        assert matrix.n_cases == 2
        assert sorted(matrix.frame["case_id"]) == ["1", "2"]

    def test_a_heavily_coded_case_does_not_count_more(self):
        """The failure this module exists to prevent."""
        table = coding([(1, f"Code{i}") for i in range(8)] + [(2, "Code0")])

        matrix = build_design_matrix(table, drop_near_constant=False)

        assert len(matrix.frame) == 2
        assert (matrix.frame["case_id"] == "1").sum() == 1

    @staticmethod
    def _two_people_four_documents():
        """Each person answered two questions — the wide-form survey shape."""
        table = coding([(1, "Cost"), (2, "Access"), (3, "Cost"), (4, "Staff")])
        table["respondent_id"] = ["person_a", "person_a", "person_b", "person_b"]
        return table

    def test_grouping_by_respondent_is_available(self):
        matrix = build_design_matrix(self._two_people_four_documents(),
                                     unit="respondent_id",
                                     drop_near_constant=False)

        assert matrix.n_cases == 2

    def test_the_unit_changes_the_answer_and_so_must_be_declared(self):
        """A fixture where the choice matters, so it cannot silently regress.

        Per document, person A's two answers are two cases and each carries one
        code. Per person, they are one case carrying both — which is the
        difference between "these themes appear in the same answer" and "the
        same person raised both".
        """
        table = self._two_people_four_documents()

        by_document = build_design_matrix(table, unit="source_id",
                                          drop_near_constant=False)
        by_person = build_design_matrix(table, unit="respondent_id",
                                        drop_near_constant=False)

        assert by_document.n_cases == 4
        assert by_person.n_cases == 2

        person_a = by_person.frame.set_index("case_id").loc["person_a"]
        assert person_a[f"{CODE_PREFIX}Cost"] == 1
        assert person_a[f"{CODE_PREFIX}Access"] == 1

    def test_a_single_case_is_refused_rather_than_modelled(self):
        """One respondent is not a sample, whatever the document count."""
        table = coding([(1, "Cost"), (2, "Cost")])
        table["respondent_id"] = "person_a"

        matrix = build_design_matrix(table, unit="respondent_id",
                                     drop_near_constant=False)

        assert not matrix.usable
        assert "cases to compare" in matrix.refusal

    def test_an_unknown_unit_is_refused_loudly(self):
        with pytest.raises(ValueError, match="unit must be one of"):
            build_design_matrix(coding([(1, "Cost")]), unit="excerpt_id")

    def test_the_document_unit_says_what_it_assumes(self):
        matrix = build_design_matrix(coding([(1, "Cost"), (2, "Access")]),
                                     drop_near_constant=False)

        assert any("case is the document" in note for note in matrix.caveats())


class TestAbsentIsZeroAndMissingIsMissing:

    def test_a_code_not_applied_is_a_real_zero(self):
        table = coding([(1, "Cost"), (2, "Access")])

        frame = build_design_matrix(table, drop_near_constant=False).frame
        row = frame.set_index("case_id").loc["2"]

        assert row[f"{CODE_PREFIX}Cost"] == 0
        assert row[f"{CODE_PREFIX}Access"] == 1

    def test_no_code_column_is_ever_null(self):
        table = coding([(i, "Cost") for i in range(6)]
                       + [(0, "Access"), (1, "Access")])

        frame = build_design_matrix(table, drop_near_constant=False).frame
        code_columns = [c for c in frame.columns if c.startswith(CODE_PREFIX)]

        assert not frame[code_columns].isna().to_numpy().any()

    def test_an_uncollected_descriptor_stays_missing(self):
        """Zero would be a measurement nobody made."""
        table = coding([(1, "Cost"), (2, "Cost"), (3, "Cost")])
        desc = descriptors([(1, "age", "20"), (2, "age", "22")])   # case 3 absent

        frame = build_design_matrix(table, desc, drop_near_constant=False).frame
        ages = frame.set_index("case_id")[f"{DESC_PREFIX}age"]

        assert ages["1"] == 20
        assert pd.isna(ages["3"])

    def test_a_missing_categorical_does_not_become_a_zero_dummy(self):
        table = coding([(i, "Cost") for i in range(4)])
        desc = descriptors([(0, "program", "A"), (1, "program", "B"),
                            (2, "program", "B")])       # case 3 has none

        frame = build_design_matrix(table, desc, drop_near_constant=False).frame
        dummy = frame.set_index("case_id")[f"{DESC_PREFIX}program=B"]

        assert dummy["1"] == 1
        assert dummy["0"] == 0
        assert pd.isna(dummy["3"]), "an unknown program became 'not B'"


class TestEncoding:

    def test_binary_is_the_default(self):
        table = coding([(1, "Cost"), (1, "Cost"), (1, "Cost"), (2, "Cost")])

        frame = build_design_matrix(table, drop_near_constant=False).frame

        assert frame.set_index("case_id").at["1", f"{CODE_PREFIX}Cost"] == 1

    def test_counts_are_available_when_asked_for(self):
        table = coding([(1, "Cost"), (1, "Cost"), (1, "Cost"), (2, "Cost")])

        frame = build_design_matrix(table, encoding="count",
                                    drop_near_constant=False).frame

        assert frame.set_index("case_id").at["1", f"{CODE_PREFIX}Cost"] == 3

    def test_an_unknown_encoding_is_refused_loudly(self):
        with pytest.raises(ValueError, match="encoding must be one of"):
            build_design_matrix(coding([(1, "Cost")]), encoding="tf-idf")

    def test_how_much_a_case_was_coded_is_offered_as_a_control(self):
        """Otherwise a theme's coefficient can be picking up "wrote a lot"."""
        table = coding([(1, "Cost"), (1, "Access"), (2, "Cost")])

        frame = build_design_matrix(table, drop_near_constant=False).frame

        assert frame.set_index("case_id").at["1", "n_codes"] == 2


class TestPooledCoders:

    def test_filtering_to_one_coder_changes_the_matrix(self):
        table = coding([(1, "Cost", "human_primary"), (1, "Access", "transformer"),
                        (2, "Cost", "human_primary")])

        pooled = build_design_matrix(table, drop_near_constant=False)
        human = build_design_matrix(table, rater_id="human_primary",
                                    drop_near_constant=False)

        assert f"{CODE_PREFIX}Access" in pooled.frame.columns
        assert f"{CODE_PREFIX}Access" not in human.frame.columns

    def test_pooling_is_reported_not_assumed_harmless(self):
        table = coding([(1, "Cost", "human_primary"), (2, "Cost", "transformer")])

        blob = " ".join(build_design_matrix(
            table, drop_near_constant=False).caveats())

        assert "pool" in blob.lower()
        assert "human_primary" in blob and "transformer" in blob

    def test_one_coder_gets_no_pooling_caveat(self):
        table = coding([(1, "Cost"), (2, "Access")])

        blob = " ".join(build_design_matrix(
            table, drop_near_constant=False).caveats())

        assert "pool" not in blob.lower()

    def test_machine_coded_variables_are_flagged_as_estimates(self):
        """Error in a predictor pulls its coefficient toward zero. A reader has
        to know which columns are estimates."""
        table = coding([(1, "Cost", "transformer"), (2, "Access", "transformer")])

        blob = " ".join(build_design_matrix(
            table, rater_id="transformer", drop_near_constant=False).caveats())

        assert "not measurements" in blob or "estimates, not measurements" in blob

    def test_an_all_human_matrix_is_not_flagged(self):
        table = coding([(1, "Cost", "human_primary"), (2, "Access", "human_primary")])

        blob = " ".join(build_design_matrix(
            table, rater_id="human_primary", drop_near_constant=False).caveats())

        assert "estimates" not in blob


class TestReferenceLevels:

    def test_a_categorical_descriptor_gets_dummies_minus_one(self):
        table = coding([(i, "Cost") for i in range(6)])
        desc = descriptors([(i, "program", ["A", "B", "C"][i % 3]) for i in range(6)])

        matrix = build_design_matrix(table, desc, drop_near_constant=False)
        dummies = [c for c in matrix.frame.columns if c.startswith(f"{DESC_PREFIX}program=")]

        assert len(dummies) == 2, "should be levels minus the reference"

    def test_the_reference_level_is_named_not_implicit(self):
        table = coding([(i, "Cost") for i in range(6)])
        desc = descriptors([(i, "program", ["A", "B", "C"][i % 3]) for i in range(6)])

        matrix = build_design_matrix(table, desc, drop_near_constant=False)

        assert matrix.reference_levels["program"] == "A"
        assert any("reference level" in note for note in matrix.caveats())

    def test_the_reference_is_deterministic(self):
        table = coding([(i, "Cost") for i in range(6)])
        desc = descriptors([(i, "program", ["C", "B", "A"][i % 3]) for i in range(6)])

        first = build_design_matrix(table, desc, drop_near_constant=False)
        second = build_design_matrix(table, desc.iloc[::-1],
                                     drop_near_constant=False)

        assert first.reference_levels == second.reference_levels

    def test_a_numeric_descriptor_stays_numeric(self):
        table = coding([(i, "Cost") for i in range(4)])
        desc = descriptors([(i, "age", str(20 + i)) for i in range(4)])

        matrix = build_design_matrix(table, desc, drop_near_constant=False)

        assert f"{DESC_PREFIX}age" in matrix.frame.columns
        assert matrix.reference_levels == {}

    def test_one_stray_non_number_does_not_null_a_numeric_column(self):
        """A column of ages with a single "n/a" is still a column of ages."""
        table = coding([(i, "Cost") for i in range(20)])
        rows = [(i, "age", str(20 + i)) for i in range(19)] + [(19, "age", "n/a")]

        matrix = build_design_matrix(table, descriptors(rows),
                                     drop_near_constant=False)

        column = matrix.frame[f"{DESC_PREFIX}age"]
        assert column.notna().sum() == 19

    def test_a_mostly_text_column_becomes_dummies_rather_than_nulls(self):
        table = coding([(i, "Cost") for i in range(6)])
        rows = [(i, "site", ["north", "south"][i % 2]) for i in range(6)]

        matrix = build_design_matrix(table, descriptors(rows),
                                     drop_near_constant=False)

        assert "site" in matrix.reference_levels


class TestParsingAsANumberIsNotBeingANumber:
    """Found by building a realistic matrix and reading it, not by a test.

    `class_year` held 2024–2027, parsed as a number, and became a continuous
    predictor — silently asserting that the step from 2024 to 2025 means the
    same as 2025 to 2026. That is a modelling decision made by a type check.
    """

    @staticmethod
    def _with_class_year(n=40):
        table = coding([(i, "Cost") for i in range(n)]
                       + [(i, "Access") for i in range(0, n, 2)])
        desc = descriptors([(i, "class_year", str(2024 + (i % 4)))
                            for i in range(n)])
        return table, desc

    def test_a_numeric_descriptor_is_reported_as_such(self):
        table, desc = self._with_class_year()

        matrix = build_design_matrix(table, desc)

        assert matrix.numeric_descriptors["class_year"] == 4

    def test_a_suspiciously_low_cardinality_number_is_flagged(self):
        table, desc = self._with_class_year()

        blob = " ".join(build_design_matrix(table, desc).caveats())

        assert "class_year" in blob
        assert "steps between those values are equal" in blob

    def test_a_genuinely_continuous_number_is_not_flagged(self):
        """Age has many distinct values and really is a number."""
        table = coding([(i, "Cost") for i in range(40)]
                       + [(i, "Access") for i in range(0, 40, 2)])
        desc = descriptors([(i, "age", str(18 + i)) for i in range(40)])

        blob = " ".join(build_design_matrix(table, desc).caveats())

        assert "steps between those values" not in blob

    def test_the_analyst_can_force_it_categorical(self):
        table, desc = self._with_class_year()

        matrix = build_design_matrix(table, desc, categorical=["class_year"])

        assert f"{DESC_PREFIX}class_year" not in matrix.frame.columns
        assert matrix.reference_levels["class_year"] == "2024"
        assert "class_year" not in matrix.numeric_descriptors

    def test_forcing_it_changes_the_columns_not_just_the_label(self):
        table, desc = self._with_class_year()

        forced = build_design_matrix(table, desc, categorical=["class_year"])
        dummies = [c for c in forced.frame.columns
                   if c.startswith(f"{DESC_PREFIX}class_year=")]

        assert len(dummies) == 3, "four levels should give three dummies"

    def test_the_threshold_is_a_stated_number(self):
        from analysis.design_matrix import SUSPICIOUS_NUMERIC_LEVELS

        assert isinstance(SUSPICIOUS_NUMERIC_LEVELS, int)
        assert SUSPICIOUS_NUMERIC_LEVELS > 1


class TestNearConstantColumns:

    def test_a_code_on_two_of_two_hundred_cases_is_dropped(self):
        rows = [(i, "Present") for i in range(200)]
        rows += [(0, "Rare"), (1, "Rare")]

        matrix = build_design_matrix(coding(rows))

        assert f"{CODE_PREFIX}Rare" not in matrix.frame.columns
        assert f"{CODE_PREFIX}Rare" in matrix.dropped

    def test_the_drop_is_reported_with_a_reason(self):
        rows = [(i, "Present") for i in range(200)] + [(0, "Rare")]

        matrix = build_design_matrix(coding(rows))

        assert "varies on only 1 case" in matrix.dropped[f"{CODE_PREFIX}Rare"]
        assert any("too little variation" in note for note in matrix.caveats())

    def test_a_code_on_everything_is_dropped_too(self):
        """No variation is no variation, in either direction."""
        matrix = build_design_matrix(wide_coding(40))

        assert f"{CODE_PREFIX}Present" in matrix.dropped

    def test_a_well_populated_code_survives(self):
        matrix = build_design_matrix(wide_coding(40, every=2))

        assert f"{CODE_PREFIX}Cost" in matrix.frame.columns

    def test_the_floor_scales_with_the_sample(self):
        """Five of five thousand is still nothing."""
        rows = [(i, "Present") for i in range(500)]
        rows += [(i, "Rare") for i in range(6)]        # 6 > MIN_VARYING, < 2%

        matrix = build_design_matrix(coding(rows))

        assert f"{CODE_PREFIX}Rare" in matrix.dropped

    def test_the_floor_can_be_overridden_deliberately(self):
        rows = [(i, "Present") for i in range(200)] + [(0, "Rare"), (1, "Rare")]

        matrix = build_design_matrix(coding(rows), min_varying=1)

        assert f"{CODE_PREFIX}Rare" in matrix.frame.columns

    def test_dropping_can_be_turned_off_entirely(self):
        rows = [(i, "Present") for i in range(200)] + [(0, "Rare")]

        matrix = build_design_matrix(coding(rows), drop_near_constant=False)

        assert f"{CODE_PREFIX}Rare" in matrix.frame.columns

    def test_min_varying_is_a_stated_number(self):
        assert isinstance(MIN_VARYING, int) and MIN_VARYING > 1


class TestItRefusesWhenThereIsNothingToModel:

    def test_an_empty_coding_table(self):
        matrix = build_design_matrix(pd.DataFrame())

        assert not matrix.usable
        assert "Nothing is coded yet" in matrix.refusal

    def test_a_single_case_cannot_be_modelled(self):
        matrix = build_design_matrix(coding([(1, "Cost"), (1, "Access")]))

        assert not matrix.usable
        assert "cases to compare" in matrix.refusal

    def test_everything_constant_is_a_refusal_not_an_empty_frame(self):
        matrix = build_design_matrix(wide_coding(40, every=1))

        assert not matrix.usable
        assert "too little variation" in matrix.refusal

    def test_a_missing_column_is_named(self):
        matrix = build_design_matrix(pd.DataFrame({"source_id": ["1"]}))

        assert not matrix.usable
        assert "code_name" in matrix.refusal

    def test_filtering_to_a_coder_who_coded_nothing_refuses(self):
        matrix = build_design_matrix(coding([(1, "Cost")]), rater_id="nobody")

        assert not matrix.usable
        assert "nobody" in matrix.refusal


class TestReadingFromAProject:

    @pytest.fixture()
    def project(self, tmp_path):
        path = tmp_path / "p.qnw"
        with Project.create(path) as project:
            codes = {name: project.add_code(Code(code_id="", name=name))
                     for name in ("Cost", "Access")}
            for index in range(20):
                text = f"response {index}"
                source_id = project.add_source(Source(
                    source_id="", type="survey_response", raw_text=text,
                    label="Q1", metadata={"response_id": f"r{index}"}))
                excerpt = project.add_excerpt(Excerpt(
                    excerpt_id="", source_id=source_id, text=text,
                    char_start=0, char_end=len(text)))
                project.set_descriptor(Descriptor(
                    source_id=source_id, key="program",
                    value=["A", "B"][index % 2]))
                project.apply_code(CodeApplication(
                    application_id="", excerpt_id=excerpt,
                    code_id=codes["Cost"], rater_id="human_primary"))
                if index % 2 == 0:
                    project.apply_code(CodeApplication(
                        application_id="", excerpt_id=excerpt,
                        code_id=codes["Access"], rater_id="human_primary"))
        return path

    def test_it_builds_from_a_store(self, project):
        with Project.open(project) as proj:
            matrix = matrix_from_project(proj)

        assert matrix.usable
        assert matrix.n_cases == 20

    def test_codes_and_descriptors_both_arrive(self, project):
        with Project.open(project) as proj:
            matrix = matrix_from_project(proj)

        assert f"{CODE_PREFIX}Access" in matrix.frame.columns
        assert any(c.startswith(f"{DESC_PREFIX}program") for c in matrix.frame.columns)

    def test_a_constant_code_is_dropped_from_a_real_project(self, project):
        """Cost is on every case here."""
        with Project.open(project) as proj:
            matrix = matrix_from_project(proj)

        assert f"{CODE_PREFIX}Cost" in matrix.dropped

    def test_an_empty_project_refuses_rather_than_raising(self, tmp_path):
        path = tmp_path / "empty.qnw"
        Project.create(path).close()

        with Project.open(path) as proj:
            assert not matrix_from_project(proj).usable

    def test_describe_is_one_readable_line(self, project):
        with Project.open(project) as proj:
            line = matrix_from_project(proj).describe()

        assert "20 case(s)" in line and "applied or not" in line


def test_the_module_pulls_in_no_model_library():
    """Phase A commits to no model. The matrix is useful on its own — it is what
    a CSV export to R or Stata needs — and must import nothing that fits one."""
    import ast

    import analysis.design_matrix as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {(node.module or "").split(".")[0]
                for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name.split(".")[0]
                 for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}

    assert not ({"sklearn", "scipy", "statsmodels", "torch"} & imported)
