"""
The one object that owns the open project.

**Why a service and not `Project.open()` in each view.** `core.project.Project`
wraps a `sqlite3.Connection` created with the default ``check_same_thread=True``,
so the connection belongs to the thread that opened it. Streamlit sidestepped
this by opening and closing the store on every rerun; a long-lived desktop app
cannot. Funnelling every read and write through a single service, held on the GUI
thread, is what makes that safe — and it gives one place to emit "the project
changed" so every open view refreshes together.

The rule for the rest of the app: **no widget calls `Project` directly.** Views
call `ProjectService`; background work that needs the store opens its **own**
`Project` on its own thread (see `services/tasks.py`) and the service reloads
afterwards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal

from core.project import Project

# The rater id every hand-coding in this app is attributed to. Matches
# `core.span_coding.HUMAN_RATER` so coding done here and coding done in the
# Streamlit build are the same rater in the same store — which is what lets a
# project move between the two front ends without splitting one analyst in two.
from core.span_coding import HUMAN_RATER


class ProjectService(QObject):
    """Owns the open `.qnw` and is the only thing that touches it.

    Signals let views stay dumb: they render what the service hands them and
    re-render when it says something changed, rather than polling the store.
    """

    #: A project was opened or closed. Argument is the path, or "" when closed.
    project_changed = Signal(str)
    #: Coding, codebook, or document content changed — reload your view.
    store_changed = Signal()
    #: Something worth telling the user about happened (status bar text).
    message = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._project: Optional[Project] = None
        self._path: Optional[Path] = None
        self._analyst_name: str = ""

    # ── lifecycle ───────────────────────────────────────────────────────────
    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._project is not None

    @property
    def analyst_name(self) -> str:
        """Display name recorded on this analyst's `Rater` row."""
        return self._analyst_name

    def set_analyst_name(self, name: str) -> None:
        self._analyst_name = str(name or "").strip()
        if self._project is not None:
            self._project.actor = self._analyst_name   # who the event log names

    def open(self, path: Path) -> None:
        """Open an existing store, closing any current one first."""
        path = Path(path)
        self.close()
        self._project = Project.open(path)
        self._project.actor = self._analyst_name
        self._path = path
        self.project_changed.emit(str(path))
        self.store_changed.emit()

    def create(self, path: Path) -> None:
        """Create (or open) a store at `path` and make it active."""
        path = Path(path)
        self.close()
        self._project = Project.create(path)
        self._project.actor = self._analyst_name
        self._path = path
        self.project_changed.emit(str(path))
        self.store_changed.emit()

    def close(self) -> None:
        if self._project is not None:
            self._project.close()
        self._project = None
        self._path = None
        self.project_changed.emit("")

    def reopen(self) -> None:
        """Reconnect to the same file — after a background task wrote to it.

        A worker thread cannot use this connection, so it opens its own. Once it
        finishes, this drops and remakes the GUI-thread connection so the views
        see the worker's writes rather than a stale snapshot.
        """
        if self._path is None:
            return
        path = self._path
        if self._project is not None:
            self._project.close()
        self._project = Project.open(path)
        self.store_changed.emit()

    # ── access ──────────────────────────────────────────────────────────────
    @property
    def project(self) -> Project:
        """The live store. Raises if nothing is open — views must check `is_open`."""
        if self._project is None:
            raise RuntimeError("No project is open.")
        return self._project

    def notify_changed(self) -> None:
        """Announce a store write made through this service's `project`."""
        self.store_changed.emit()

    # ── documents ───────────────────────────────────────────────────────────
    def document_table(self):
        from core.documents import document_table

        return document_table(self.project)

    def document_metadata(self, source_id: str) -> dict:
        source = self.project.get_source(source_id)
        return dict(source.metadata or {}) if source is not None else {}

    # -- interview guide (core/guide_mapping.py) --------------------------------
    def interview_guide(self):
        from core import guide_mapping

        return guide_mapping.saved_guide(self.project)

    def set_interview_guide(self, text: str):
        """Keep the guide with the project and add its themes to the codebook. Returns it."""
        from core import guide_mapping

        template = guide_mapping.parse_guide(text)         # raises GuideError in plain words
        guide_mapping.save_guide(self.project, text)
        guide_mapping.ensure_codes(self.project, template)
        self.store_changed.emit()
        return template

    def guide_plan(self, source_id: str, template, **options):
        from core import guide_mapping

        return guide_mapping.plan(self.project, source_id, template, **options)

    def guide_apply(self, plan, matched, coverage):
        from core import guide_mapping

        report = guide_mapping.apply(self.project, plan, matched, coverage)
        self.store_changed.emit()
        return report

    def guide_suggestion_count(self, source_id=None) -> int:
        from core import guide_mapping

        return guide_mapping.suggestion_count(self.project, source_id)

    def remove_guide_suggestions(self, source_id=None) -> int:
        from core import guide_mapping

        removed = guide_mapping.remove_suggestions(self.project, source_id)
        if removed:
            self.store_changed.emit()
        return removed

    def set_speakers(self, source_id: str, record: dict) -> None:
        """Keep the confirmed speaker roles with the transcript (`core/speakers.py`)."""
        self.project.update_source_metadata(source_id, {"speakers": record})
        self.store_changed.emit()

    def document_text(self, source_id: str) -> str:
        source = self.project.get_source(source_id)
        return (source.raw_text or "") if source is not None else ""

    def coding_spans(
        self,
        source_id: str,
        *,
        rater_id: Optional[str] = None,
        code_names: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        from core.documents import coding_spans

        return coding_spans(self.project, source_id, rater_id=rater_id,
                            code_names=code_names)

    def import_documents(self, items: Sequence[Any], *, case_id: Optional[str] = None
                         ) -> Dict[str, Any]:
        from core.documents import import_documents

        result = import_documents(self.project, items, case_id=case_id)
        if result["imported"]:
            self.store_changed.emit()
        return result

    # ── codebook ────────────────────────────────────────────────────────────
    def codebook(self):
        return self.project.get_codebook()

    def code_names(self) -> List[str]:
        return [c.name for c in self.project.get_codebook()]

    def code_frequency(self) -> Dict[str, int]:
        return self.project.code_frequency()

    def get_code(self, code_id: str):
        return next((c for c in self.project.get_codebook()
                     if c.code_id == code_id), None)

    def add_code(self, name: str, definition: str = "",
                 parent_id: Optional[str] = None) -> str:
        """Create a code. Returns its code_id."""
        from core.model import Code

        code_id = self.project.add_code(Code(
            code_id="", name=name, definition=definition, parent_id=parent_id,
            origin="a_priori", created_by="human"))
        self.store_changed.emit()
        return code_id

    def update_code(self, code_id: str, *, name: Optional[str] = None,
                    definition: Optional[str] = None) -> None:
        if name is not None:
            self.project.rename_code(code_id, name)
        if definition is not None:
            self.project.set_code_definition(code_id, definition)
        self.store_changed.emit()

    def set_code_rules(self, code_id: str, *, use_when: Optional[str] = None,
                       leave_out_when: Optional[str] = None,
                       examples: Optional[List[str]] = None) -> None:
        """Save a code's coding rules: when to use it, when not to, examples.

        These are the codebook entries Saldaña (2013, p. 25) lists after Bernard
        and Ryan. The engine already stored them; this is the desktop's way in.
        The change is written to the event log, which keeps the audit trail.
        """
        self.project.set_code_structured_fields(
            code_id, inclusion_criteria=use_when,
            exclusion_criteria=leave_out_when, examples=examples)
        self.store_changed.emit()

    def set_code_parent(self, code_id: str, parent_id: Optional[str]) -> None:
        """Reparent. Raises ValueError on a move that would create a cycle."""
        self.project.set_code_parent(code_id, parent_id or None)
        self.store_changed.emit()

    def merge_codes(self, from_id: str, into_id: str) -> None:
        self.project.merge_codes(from_id, into_id)
        self.store_changed.emit()

    def delete_code(self, code_id: str) -> None:
        self.project.delete_code(code_id)
        self.store_changed.emit()

    def codebook_health(self) -> Dict[str, Any]:
        from analysis.codebook_health import codebook_health

        return codebook_health(self.project.get_codebook(), self.project.code_frequency())

    # ── codebook versions ───────────────────────────────────────────────────
    def list_codebook_versions(self) -> List[Dict[str, Any]]:
        return self.project.list_codebook_versions()

    def tag_codebook_version(self, note: str) -> str:
        result = self.project.tag_codebook_version(note or "manual tag")
        self.store_changed.emit()
        return result

    def restore_codebook_version(self, version_id: str) -> None:
        """Restore a codebook snapshot, backing the store up first.

        Invariant #8: destructive operations back up the `.qnw` before running.
        A restore deletes every code added since the snapshot (and their
        codings), so it qualifies — `Project.restore_codebook_version` snapshots
        the *codebook*, which is not the same as a copy of the file.
        """
        from core.backups import backup_store

        if self._path is not None:
            backup_store(self._path, reason="pre_codebook_restore")
        self.project.restore_codebook_version(version_id)
        self.store_changed.emit()

    # ── codebook exchange ───────────────────────────────────────────────────
    def export_codebook_yaml(self) -> str:
        from core.codebook_io import export_codebook_yaml

        return export_codebook_yaml(self.project)

    def import_codebook_yaml(self, text: str) -> Dict[str, Any]:
        from core.codebook_io import import_codebook_yaml

        result = import_codebook_yaml(self.project, text)
        self.store_changed.emit()
        return result

    # ── analysis ────────────────────────────────────────────────────────────
    def coding_table(self):
        """One row per code application — what every `analysis/*` function reads."""
        return self.project.coding_table()

    def descriptor_table(self):
        return self.project.descriptor_table()

    def excerpt_lookup(self) -> Dict[str, Any]:
        return {e.excerpt_id: e for e in self.project.list_excerpts()}

    def source_lookup(self) -> Dict[str, Any]:
        return {s.source_id: s for s in self.project.list_sources()}

    def human_rater_ids(self) -> List[str]:
        """Raters eligible for human-vs-human agreement.

        Invariant #6: the coder-vs-coder comparison lists **only** raters whose
        id starts with `human`. A model's codings are never selectable as if they
        were a second person -- "two analysts agreed" and "the analyst agreed
        with the machine" are different claims. The machine is compared in its
        own, labelled mode (`engine_rater_ids`, `compare_with_engine`).
        """
        from core.agreement_pairs import selectable_raters

        # The adjudicated set comes last and is offered on purpose (checking a
        # coder against the reconciled set); the comparison's caveats say it is
        # not an inter-rater figure. Exports never pick it (core.agreement_pairs).
        return selectable_raters(self.project)

    def engine_rater_ids(self) -> List[str]:
        """The pipeline's engine runs, most recent first. Never the text-search
        auto-coder, an imported coder, a Laya run or a simulation."""
        from core.agreement_pairs import engine_raters

        return engine_raters(self.project)

    def primary_human_id(self) -> Optional[str]:
        from core.agreement_pairs import primary_human

        return primary_human(self.project)

    def compare_with_engine(self, human: str, engine: str):
        """A coder against an engine run, with the same caveats the reports carry."""
        from core.agreement_pairs import compare_with_engine

        return compare_with_engine(self.project, human, engine)

    def span_rater_ids(self) -> List[str]:
        """Coders whose span coding can be compared, imported ones included."""
        from core.agreement_pairs import span_raters

        return span_raters(self.project)

    def rater_labels(self, rater_id: str) -> Dict[str, set]:
        return self.project.rater_labels(rater_id)

    def compare_raters(self, rater_a: str, rater_b: str):
        """Two coders on survey responses, with the item-set caveats."""
        from core.agreement_pairs import compare_raters

        return compare_raters(self.project, rater_a, rater_b)

    def span_comparison(self, rater_a: str, rater_b: str, unit: str, rule: str = "any_overlap"):
        from core.agreement_pairs import span_comparison

        return span_comparison(self.project, rater_a, rater_b, unit=unit, rule=rule)

    def documents_in_common(self, rater_a: str, rater_b: str) -> List[tuple]:
        """[(source_id, title, finished_by_both)] for documents both coders coded."""
        spans = self.project.coding_spans_table()
        coded = {r: set(spans.loc[spans["rater_id"] == r, "source_id"]) for r in (rater_a, rater_b)}
        done_a = self.project.documents_coded_by(rater_a)
        done_b = self.project.documents_coded_by(rater_b)
        out = []
        for source in self.project.list_sources():
            if source.type == "document" and source.source_id in coded[rater_a] & coded[rater_b]:
                title = source.metadata.get("title") or source.label or source.source_id
                out.append((source.source_id, title,
                            source.source_id in done_a and source.source_id in done_b))
        return out

    def set_document_finished(self, source_id: str, finished: bool,
                              raters: Optional[List[str]] = None) -> None:
        """Mark a document finished for `raters` (default: this analyst)."""
        for rater in raters or [HUMAN_RATER]:
            self.project.mark_document_coded(rater, source_id, coded=finished)

    def document_finished(self, source_id: str) -> bool:
        return source_id in self.project.documents_coded_by(HUMAN_RATER)

    def get_excerpt(self, excerpt_id: str):
        return self.project.get_excerpt(excerpt_id)

    def record_adjudications(self, decisions: Dict[str, List[str]]) -> Any:
        """Save reconciled codings as the separate `human_adjudicated` rater.

        Never touches either coder's original codings — kappa depends on them,
        and a resolution that rewrote history would make the reported agreement
        unreproducible.
        """
        from core.adjudication import record_adjudications

        result = record_adjudications(self._path, decisions)
        # The helper opens the store on this thread by path, so this connection
        # holds a stale view until it reconnects.
        self.reopen()
        return result

    # ── search ──────────────────────────────────────────────────────────────
    def search(self, query: str, **kwargs) -> List[Any]:
        from core.search import search

        return search(self.project, query, **kwargs)

    def fts_available(self) -> bool:
        return self.project.fts_available()

    def source_types(self) -> List[str]:
        return self.project.source_types()

    def list_cases(self) -> List[Any]:
        return self.project.list_cases()

    def count_sources(self) -> int:
        return self.project.count_sources()

    def corpus_texts(self, source_type: Optional[str] = None,
                     cap: int = 2000) -> List[str]:
        """Source text, paged and capped, for word frequency.

        Read here (on the GUI thread, which owns the connection) rather than in
        the worker that counts the words — a `sqlite3` connection belongs to the
        thread that opened it.
        """
        texts: List[str] = []
        offset = 0
        while len(texts) < cap:
            page = self.project.iter_sources(source_type=source_type, limit=200,
                                             offset=offset)
            if not page:
                break
            texts.extend(s.raw_text or "" for s in page)
            offset += 200
        return texts[:cap]

    def autocode_hits(self, hits, code_name: str, *, query: str = "") -> Dict[str, Any]:
        """Code every search hit under the auto-coding rater.

        `core.autocode.AUTOCODE_RATER` is `auto_textsearch` — deliberately not a
        `human*` id, so text-search coding can never be selected as a coder in
        the agreement screen. That is invariant #6 doing its job: a regex is not
        a second analyst.
        """
        from core.autocode import autocode_hits

        result = autocode_hits(self.project, hits, code_name, query=query)
        self.store_changed.emit()
        return result

    def remove_autocoded(self, code_name: Optional[str] = None) -> int:
        from core.autocode import remove_autocoded

        removed = remove_autocoded(self.project, code_name=code_name)
        self.store_changed.emit()
        return removed

    # ── query & synthesis ───────────────────────────────────────────────────
    def coding_spans_table(self):
        """`coding_table()` plus character spans and case membership.

        The input to boolean queries (NEAR/n needs offsets) and to the framework
        matrix (cases are its rows).
        """
        return self.project.coding_spans_table()

    def add_case(self, name: str, kind: str = "person") -> str:
        from core.model import Case

        case_id = self.project.add_case(Case(case_id="", name=name, kind=kind))
        self.store_changed.emit()
        return case_id

    def case_sources(self, case_id: str) -> List[str]:
        return self.project.case_sources(case_id)

    def assign_source_to_case(self, case_id: str, source_id: str) -> None:
        self.project.assign_source_to_case(case_id, source_id)
        self.store_changed.emit()

    def cell_summary(self, case_id: str, code_name: str):
        from analysis.framework import get_cell_summary

        return get_cell_summary(self.project, case_id, code_name)

    def set_cell_summary(self, case_id: str, code_name: str, text: str) -> None:
        from analysis.framework import set_cell_summary

        set_cell_summary(self.project, case_id, code_name, text,
                         author=self._analyst_name or "human")
        self.store_changed.emit()

    def cell_excerpt_texts(self, excerpt_ids) -> List[str]:
        from analysis.framework import cell_excerpt_texts

        return cell_excerpt_texts(self.project, excerpt_ids)

    # ── code colours (stored in the project, so they travel with it) ────────
    def code_color_overrides(self) -> Dict[str, str]:
        from qualsafe_qt.colors import load_overrides

        if not self.is_open:
            return {}
        return load_overrides(self.project)

    def set_code_color(self, code_name: str, hex_color: Optional[str]) -> None:
        from qualsafe_qt.colors import set_override

        set_override(self.project, code_name, hex_color)
        self.store_changed.emit()

    # ── memos ───────────────────────────────────────────────────────────────
    def list_memos(self, target_type: str, target_id: Optional[str] = None):
        return self.project.list_memos(target_type=target_type, target_id=target_id)

    def add_memo(self, target_type: str, target_id: Optional[str], text: str) -> str:
        from core.model import Memo

        memo_id = self.project.add_memo(Memo(
            memo_id="", target_type=target_type, target_id=target_id,
            text=text, author="human"))
        self.store_changed.emit()
        return memo_id

    def delete_memo(self, memo_id: str) -> None:
        self.project.delete_memo(memo_id)
        self.store_changed.emit()

    # ── span coding ─────────────────────────────────────────────────────────
    def apply_codes_to_span(
        self, source_id: str, char_start: int, char_end: int,
        code_names: Sequence[str],
    ) -> Dict[str, Any]:
        """Code one passage by exact offsets — the path the Qt reader uses.

        Offsets come straight from a `QTextCursor` selection, which is the whole
        point of this front end: `core.span_coding` already accepted exact
        offsets (its "tier 3"), and a real text selection now feeds them.
        """
        from core.span_coding import apply_codes_to_span

        result = apply_codes_to_span(
            self.project, source_id, char_start, char_end, code_names,
            rater_id=HUMAN_RATER, rater_name=self._analyst_name,
        )
        self.store_changed.emit()
        return result

    def remove_coding(self, excerpt_id: str, *, code_name: Optional[str] = None) -> int:
        from core.span_coding import remove_coding

        removed = remove_coding(self.project, excerpt_id, code_name=code_name,
                                rater_id=HUMAN_RATER)
        self.store_changed.emit()
        return removed

    def codings_on_span(self, source_id: str, char_start: int, char_end: int
                        ) -> Tuple[Optional[str], List[str]]:
        """``(excerpt_id, code_names)`` for this analyst's coding of an exact span."""
        for excerpt in self.project.list_excerpts(source_id):
            if excerpt.char_start == char_start and excerpt.char_end == char_end:
                spans = self.coding_spans(source_id, rater_id=HUMAN_RATER)
                for span in spans:
                    if span["excerpt_id"] == excerpt.excerpt_id:
                        return excerpt.excerpt_id, list(span["codes"])
                return excerpt.excerpt_id, []
        return None, []
