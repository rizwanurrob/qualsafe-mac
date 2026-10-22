"""Schema v7: structured-coding fields on `codes`, coding_decisions,
coding_run_configs, and the v6 -> v7 migration (Alt Survey Flow)."""

from __future__ import annotations

import sqlite3

from core.model import Code, CodeApplication, CodingDecision, CodingRunConfig, Excerpt, Source
from core.project import SCHEMA_VERSION, Project

V7_COLUMNS = ("inclusion_criteria", "exclusion_criteria", "examples_json",
             "decision_type", "rubric_levels_json")
V7_TABLES = ("coding_decisions", "coding_run_configs")


def _downgrade_to_v6(path):
    """Make a current store look like a v6 one: drop the v7 additions, stamp 6."""
    con = sqlite3.connect(path)
    for table in V7_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {table}")
    # SQLite (< 3.35, but also just simpler here) has no DROP COLUMN in one
    # step across versions used in CI; rebuild `codes` without the v7 columns.
    con.executescript("""
        CREATE TABLE codes_v6 (
            code_id TEXT PRIMARY KEY, name TEXT NOT NULL, definition TEXT DEFAULT '',
            parent_id TEXT, origin TEXT DEFAULT 'a_priori', created_by TEXT DEFAULT 'human',
            weight_kind TEXT, weight_min REAL, weight_max REAL
        );
        INSERT INTO codes_v6(code_id, name, definition, parent_id, origin, created_by,
            weight_kind, weight_min, weight_max)
            SELECT code_id, name, definition, parent_id, origin, created_by,
                   weight_kind, weight_min, weight_max FROM codes;
        DROP TABLE codes;
        ALTER TABLE codes_v6 RENAME TO codes;
    """)
    con.execute("UPDATE meta SET value='6' WHERE key='schema_version'")
    con.commit()
    con.close()


def _seed(proj: Project):
    src = Source(source_id="s1", type="survey_response", raw_text="Advising was hard to reach.",
                label="s1", metadata={})
    proj.add_source(src)
    exc = proj.add_whole_response_excerpt(src)
    code = proj.add_code(Code(code_id="", name="Advising access"))
    return src, exc, code


def test_new_store_is_v7_with_structured_coding_tables(tmp_path):
    path = tmp_path / "new.qnw"
    with Project.create(path):
        pass
    con = sqlite3.connect(path)
    version = int(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = {r[1] for r in con.execute("PRAGMA table_info(codes)")}
    con.close()
    assert version == SCHEMA_VERSION >= 7
    assert set(V7_TABLES) <= names
    assert set(V7_COLUMNS) <= columns


def test_v6_store_migrates_and_keeps_its_data(tmp_path):
    path = tmp_path / "old.qnw"
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Pre-existing code", definition="was here first"))
    _downgrade_to_v6(path)

    with Project.open(path) as proj:              # opening runs the migration
        codes = proj.get_codebook()
        assert [c.name for c in codes] == ["Pre-existing code"]
        # A pre-v7 code opens as a valid structured code with the defaults that
        # mean "behaves exactly as before": no criteria/examples, noul type.
        assert codes[0].inclusion_criteria == ""
        assert codes[0].exclusion_criteria == ""
        assert codes[0].examples == []
        assert codes[0].decision_type == "noul"
        assert codes[0].rubric_levels is None
        assert proj.list_coding_decisions() == []
        assert proj.list_coding_run_configs() == []
    con = sqlite3.connect(path)
    version = int(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    con.close()
    assert version == SCHEMA_VERSION


def test_migration_is_idempotent_on_a_store_already_at_v7(tmp_path):
    """Opening a v7 store a second time must not re-run the migration (ALTER
    TABLE ADD COLUMN on an existing column raises)."""
    path = tmp_path / "twice.qnw"
    with Project.create(path):
        pass
    with Project.open(path):
        pass  # would raise "duplicate column name" if the migration re-ran


# ── Code structured fields ──────────────────────────────────────────────────

def test_a_code_round_trips_its_structured_fields(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        cid = proj.add_code(Code(
            code_id="", name="Financial stress",
            inclusion_criteria="Response mentions difficulty affording tuition, housing, or books.",
            exclusion_criteria="Do not assign for general budgeting mentions with no hardship.",
            examples=["I almost dropped out because I couldn't pay rent."],
            decision_type="noul",
        ))
        code = proj.get_codebook()[0]
        assert code.code_id == cid
        assert code.inclusion_criteria.startswith("Response mentions difficulty")
        assert code.exclusion_criteria.startswith("Do not assign")
        assert code.examples == ["I almost dropped out because I couldn't pay rent."]


def test_a_score_type_code_carries_its_rubric(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        proj.add_code(Code(
            code_id="", name="Distress severity", decision_type="score",
            rubric_levels=["none", "mild", "moderate", "severe"],
        ))
        code = proj.get_codebook()[0]
        assert code.decision_type == "score"
        assert code.rubric_levels == ["none", "mild", "moderate", "severe"]


def test_set_code_structured_fields_updates_only_what_is_given(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        cid = proj.add_code(Code(code_id="", name="X", inclusion_criteria="original"))
        proj.set_code_structured_fields(cid, exclusion_criteria="new exclusion")
        code = proj.get_codebook()[0]
        assert code.inclusion_criteria == "original"     # untouched
        assert code.exclusion_criteria == "new exclusion"


def test_set_code_structured_fields_rejects_an_unknown_decision_type(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        cid = proj.add_code(Code(code_id="", name="X"))
        try:
            proj.set_code_structured_fields(cid, decision_type="ranking")
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_as_laya_instructions_composes_definition_criteria_and_examples():
    code = Code(
        code_id="c1", name="Advising access", definition="Trouble reaching an advisor.",
        inclusion_criteria="mentions waiting, no response, or being unable to book",
        exclusion_criteria="mentions a GOOD experience with advising",
        examples=["I emailed three times and never heard back."],
    )
    text = code.as_laya_instructions()
    assert "Trouble reaching an advisor." in text
    assert "Assign when: mentions waiting" in text
    assert "Do NOT assign when: mentions a GOOD experience" in text
    assert "I emailed three times" in text


def test_as_laya_instructions_has_a_sane_fallback_for_an_empty_code():
    code = Code(code_id="c1", name="Bare code")
    assert "Bare code" in code.as_laya_instructions()


# ── coding_decisions ─────────────────────────────────────────────────────────

def test_record_and_list_coding_decisions(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        ids = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.82, model_assigned=True),
        ])
        assert len(ids) == 1
        decisions = proj.list_coding_decisions(run_id="run1")
        assert len(decisions) == 1
        assert decisions[0].model_score == 0.82
        assert decisions[0].model_assigned is True
        assert decisions[0].review_status == "unreviewed"
        assert decisions[0].human_assigned is None


def test_re_recording_the_same_excerpt_code_run_replaces_not_duplicates(tmp_path):
    """Resuming/re-running a coding pass over the same item must not pile up
    rows -- the resumability the workflow promises depends on this."""
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.40, model_assigned=False),
        ])
        proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.91, model_assigned=True),
        ])
        decisions = proj.list_coding_decisions(run_id="run1")
        assert len(decisions) == 1
        assert decisions[0].model_score == 0.91


def test_review_coding_decision_confirms_when_human_agrees(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        [did] = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.9, model_assigned=True),
        ])
        proj.review_coding_decision(did, human_assigned=True, reviewer="Analyst")
        decision = proj.list_coding_decisions(run_id="run1")[0]
        assert decision.review_status == "confirmed"
        assert decision.human_assigned is True
        assert decision.reviewer == "Analyst"
        assert decision.reviewed_at != ""


def test_review_coding_decision_rejects_when_human_disagrees(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        [did] = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.9, model_assigned=True),
        ])
        proj.review_coding_decision(did, human_assigned=False, reviewer="Analyst")
        assert proj.list_coding_decisions(run_id="run1")[0].review_status == "rejected"


def test_review_coding_decision_can_be_told_to_flag_instead(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        [did] = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.5, model_assigned=False),
        ])
        proj.review_coding_decision(did, human_assigned=True, reviewer="Analyst",
                                    review_status="flagged", note="need a second opinion")
        decision = proj.list_coding_decisions(run_id="run1")[0]
        assert decision.review_status == "flagged"
        assert decision.note == "need a second opinion"


def test_confirming_a_decision_creates_a_code_application(tmp_path):
    """CodingDecision and CodeApplication are separate tables (see core/model.py)
    -- a human's confirmation must still land as a real application, or the
    existing frequency/co-occurrence/kappa functions never see it."""
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        [did] = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.4, model_assigned=False),   # model said no
        ])
        proj.review_coding_decision(did, human_assigned=True, reviewer="Analyst")  # human overrides
        apps = proj.list_applications()
        assert len(apps) == 1
        assert apps[0].excerpt_id == exc and apps[0].code_id == code
        assert apps[0].coder == "human"
        assert apps[0].rater_id == "human_primary"


def test_rejecting_a_decision_removes_the_code_application(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        [did] = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.9, model_assigned=True),
        ])
        # Simulate what run_coding_pass does: a confident_yes decision gets an
        # automatic machine application.
        proj.apply_code(CodeApplication(
            application_id="", excerpt_id=exc, code_id=code, coder="transformer",
            rater_id="laya_run1"))
        assert len(proj.list_applications()) == 1

        proj.review_coding_decision(did, human_assigned=False, reviewer="Analyst")
        # The human's own rater_id had no application to remove (the machine's
        # was under a different rater_id) -- nothing to delete there, but no
        # human application should have been created either.
        apps = proj.list_applications()
        assert all(a.rater_id != "human_primary" for a in apps)


def test_confirming_twice_does_not_duplicate_the_application(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        [did] = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.9, model_assigned=True),
        ])
        proj.review_coding_decision(did, human_assigned=True, reviewer="Analyst")
        proj.review_coding_decision(did, human_assigned=True, reviewer="Analyst",
                                    review_status="flagged", note="double-checked")
        assert len(proj.list_applications()) == 1


def test_review_coding_decision_accepts_a_custom_rater_id(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        [did] = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.9, model_assigned=True),
        ])
        proj.review_coding_decision(did, human_assigned=True, reviewer="Maria",
                                    rater_id="human_maria")
        apps = proj.list_applications()
        assert apps[0].rater_id == "human_maria"


def test_sync_machine_application_creates_one_application(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        aid = proj.sync_machine_application(
            excerpt_id=exc, code_id=code, rater_id="laya_run1", run_id="run1", confidence=0.9)
        assert aid is not None
        apps = proj.list_applications()
        assert len(apps) == 1
        assert apps[0].rater_id == "laya_run1" and apps[0].coder == "transformer"


def test_sync_machine_application_is_idempotent(tmp_path):
    """A resumed or forced-redo coding pass calling this twice for the same
    (excerpt, code, rater) must not create a second application."""
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code = _seed(proj)
        first = proj.sync_machine_application(
            excerpt_id=exc, code_id=code, rater_id="laya_run1", run_id="run1", confidence=0.9)
        second = proj.sync_machine_application(
            excerpt_id=exc, code_id=code, rater_id="laya_run1", run_id="run1", confidence=0.95)
        assert first == second
        assert len(proj.list_applications()) == 1


def test_review_coding_decision_raises_on_unknown_id(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        try:
            proj.review_coding_decision("nope", human_assigned=True, reviewer="x")
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_coding_decisions_table_includes_rejected_and_unassigned_candidates(tmp_path):
    """Unlike coding_table(), which only ever sees accepted codes."""
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, code_yes = _seed(proj)
        code_no = proj.add_code(Code(code_id="", name="Unrelated code"))
        proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code_yes, run_id="run1",
                           model_score=0.9, model_assigned=True),
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code_no, run_id="run1",
                           model_score=0.05, model_assigned=False),
        ])
        table = proj.coding_decisions_table("run1")
        assert len(table) == 2
        assert set(table["model_assigned"]) == {True, False}
        assert "excerpt_text" in table.columns


def test_review_queue_returns_only_unreviewed_items_in_the_ambiguous_band(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        _, exc, _ = _seed(proj)
        c_low = proj.add_code(Code(code_id="", name="Clearly no"))
        c_mid = proj.add_code(Code(code_id="", name="Ambiguous"))
        c_high = proj.add_code(Code(code_id="", name="Clearly yes"))
        c_reviewed = proj.add_code(Code(code_id="", name="Already reviewed, ambiguous score"))
        proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=c_low, run_id="run1",
                           model_score=0.10, model_assigned=False),
            CodingDecision(decision_id="", excerpt_id=exc, code_id=c_mid, run_id="run1",
                           model_score=0.50, model_assigned=False),
            CodingDecision(decision_id="", excerpt_id=exc, code_id=c_high, run_id="run1",
                           model_score=0.95, model_assigned=True),
        ])
        [reviewed_id] = proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=c_reviewed, run_id="run1",
                           model_score=0.50, model_assigned=False),
        ])
        proj.review_coding_decision(reviewed_id, human_assigned=False, reviewer="x")

        queue = proj.review_queue("run1", low=0.35, high=0.65)
        assert list(queue["code_id"]) == [c_mid]


def test_review_queue_on_an_empty_run_is_empty(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        queue = proj.review_queue("no-such-run", low=0.35, high=0.65)
        assert queue.empty


# ── coding_run_configs ───────────────────────────────────────────────────────

def test_save_and_get_coding_run_config(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        proj.save_coding_run_config(CodingRunConfig(
            config_id="", name="Default run",
            spec={"text_column": "response_text", "mode": "multi_label_noul",
                  "low_threshold": 0.35, "high_threshold": 0.65},
        ))
        config = proj.get_coding_run_config("Default run")
        assert config is not None
        assert config.spec["mode"] == "multi_label_noul"


def test_save_coding_run_config_replaces_by_name(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        proj.save_coding_run_config(CodingRunConfig(config_id="", name="Run",
                                                     spec={"low_threshold": 0.3}))
        proj.save_coding_run_config(CodingRunConfig(config_id="", name="Run",
                                                     spec={"low_threshold": 0.4}))
        configs = proj.list_coding_run_configs()
        assert len(configs) == 1
        assert configs[0].spec["low_threshold"] == 0.4


def test_delete_coding_run_config(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        proj.save_coding_run_config(CodingRunConfig(config_id="", name="Run", spec={}))
        assert proj.delete_coding_run_config("Run") is True
        assert proj.list_coding_run_configs() == []
        assert proj.delete_coding_run_config("Run") is False


def test_get_missing_coding_run_config_returns_none(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        assert proj.get_coding_run_config("nope") is None


# ── JSON export / import carries the new tables ──────────────────────────────

def test_export_import_round_trips_structured_coding_data(tmp_path):
    with Project.create(tmp_path / "a.qnw") as proj:
        _, exc, code = _seed(proj)
        proj.set_code_structured_fields(code, inclusion_criteria="criteria text")
        proj.record_coding_decisions([
            CodingDecision(decision_id="", excerpt_id=exc, code_id=code, run_id="run1",
                           model_score=0.8, model_assigned=True),
        ])
        proj.save_coding_run_config(CodingRunConfig(config_id="", name="Run", spec={"a": 1}))
        proj.export_json(tmp_path / "bundle.json")

    imported = Project.import_json(tmp_path / "bundle.json", tmp_path / "b.qnw")
    try:
        assert imported.get_codebook()[0].inclusion_criteria == "criteria text"
        assert len(imported.list_coding_decisions()) == 1
        assert imported.list_coding_run_configs()[0].spec == {"a": 1}
    finally:
        imported.close()


def test_the_question_asked_of_the_engine_is_a_question_with_the_count_it_rule():
    code = Code(code_id="c1", name="Advising access", definition="Trouble reaching an advisor.",
                inclusion_criteria="mentions waiting or being unable to book",
                exclusion_criteria="mentions a GOOD experience with advising")
    question = code.as_laya_question()
    assert question == "Is this answer about advising access? That means mentions waiting or being unable to book."
    assert "GOOD experience" not in question                      # measured to make it worse


def test_the_leave_out_rule_is_only_sent_when_asked_for():
    code = Code(code_id="c1", name="Money", inclusion_criteria="trouble paying",
                exclusion_criteria="praise for aid")
    assert "praise for aid" in code.as_laya_question(include_exclusion=True)
    assert "praise for aid" not in code.as_laya_question()


def test_a_code_with_only_a_definition_uses_it_and_an_empty_code_has_a_fallback():
    assert "money worries" in Code(code_id="c", name="Money", definition="money worries").as_laya_question()
    assert "Bare" in Code(code_id="c", name="Bare").as_laya_question()
