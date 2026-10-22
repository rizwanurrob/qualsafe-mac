"""
Undoable coding actions.

The Streamlit build has no undo: a mis-click that codes the wrong passage is
fixed by finding the coding in a list and removing it. Coding is repetitive
close work, and Ctrl+Z is the expected way out of a slip -- this is one of the
concrete wins of the fork, and it costs almost nothing because
`core.span_coding` already has an exact inverse for every action.

Two rules these commands follow, both inherited from the engine:

* **Scoped to this analyst.** `remove_coding` is filtered by `rater_id`, so
  undoing your own work can never delete a colleague's coding or the model's.
* **Idempotent apply.** `apply_codes_to_span` skips a code this rater already
  put on this span, so redo after undo lands exactly one coding, not two.

`redo()` is what `QUndoStack` calls when a command is first pushed, so the
"do" path and the "redo" path are the same code by construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Sequence

from PySide6.QtGui import QUndoCommand

if TYPE_CHECKING:  # pragma: no cover - typing only
    from qualsafe_qt.services.project_service import ProjectService


class ApplyCodesCommand(QUndoCommand):
    """Apply codes to one span; undo removes exactly what this command added.

    Undo is deliberately narrow: it removes only the codes this command
    *actually applied* (`result["applied"]`), never the ones that were already
    on the passage and got skipped. Undoing a no-op must be a no-op.
    """

    def __init__(
        self,
        service: "ProjectService",
        source_id: str,
        char_start: int,
        char_end: int,
        code_names: Sequence[str],
        label: str = "",
    ) -> None:
        names = [str(n).strip() for n in code_names if str(n).strip()]
        super().__init__(label or _describe(names, char_start, char_end))
        self._service = service
        self._source_id = source_id
        self._start = int(char_start)
        self._end = int(char_end)
        self._codes = names
        self._applied: List[str] = []
        self._excerpt_id: Optional[str] = None
        #: Codes this command created in the codebook. Undo removes the coding
        #: but leaves the code defined -- deleting it would take a colleague's
        #: applications of the same new code with it, and an unused code is
        #: already surfaced by the codebook-health panel.
        self.created_codes: List[str] = []

    def redo(self) -> None:  # noqa: D102 - Qt override
        before = self._codes_on_span()
        result = self._service.apply_codes_to_span(
            self._source_id, self._start, self._end, self._codes)
        self._excerpt_id = result["excerpt_id"]
        self.created_codes = list(result.get("new_codes") or [])
        after = self._codes_on_span()
        self._applied = [name for name in after if name not in before]

    def undo(self) -> None:  # noqa: D102 - Qt override
        if not self._excerpt_id:
            return
        for name in self._applied:
            self._service.remove_coding(self._excerpt_id, code_name=name)

    @property
    def excerpt_id(self) -> Optional[str]:
        return self._excerpt_id

    def _codes_on_span(self) -> List[str]:
        _excerpt_id, codes = self._service.codings_on_span(
            self._source_id, self._start, self._end)
        return codes


class RemoveCodingCommand(QUndoCommand):
    """Uncode a passage; undo puts back exactly the codes that were removed."""

    def __init__(
        self,
        service: "ProjectService",
        source_id: str,
        excerpt_id: str,
        char_start: int,
        char_end: int,
        code_name: Optional[str] = None,
        label: str = "",
    ) -> None:
        super().__init__(
            label or (f"Remove '{code_name}'" if code_name else "Remove all codes"))
        self._service = service
        self._source_id = source_id
        self._excerpt_id = excerpt_id
        self._start = int(char_start)
        self._end = int(char_end)
        self._code_name = code_name
        self._removed: List[str] = []

    def redo(self) -> None:  # noqa: D102 - Qt override
        _excerpt_id, before = self._service.codings_on_span(
            self._source_id, self._start, self._end)
        self._removed = [self._code_name] if self._code_name else list(before)
        self._service.remove_coding(self._excerpt_id, code_name=self._code_name)

    def undo(self) -> None:  # noqa: D102 - Qt override
        if not self._removed:
            return
        self._service.apply_codes_to_span(
            self._source_id, self._start, self._end, self._removed)


def _describe(code_names: Sequence[str], start: int, end: int) -> str:
    """Undo-menu text: the codes, then the span, so the history reads sensibly."""
    if not code_names:
        return "Code passage"
    shown = ", ".join(code_names[:2])
    if len(code_names) > 2:
        shown += f" +{len(code_names) - 2}"
    return f"Code '{shown}' ({start}-{end})"


# ── codebook edits ──────────────────────────────────────────────────────────
class ReparentCodeCommand(QUndoCommand):
    """Move a code under a new parent (or to the root). Undo puts it back.

    The store snapshots the codebook inside `set_code_parent`, so a reparent is
    already recoverable through version history. This puts it on the undo stack
    too, because after a drag-and-drop the expected correction is Ctrl+Z, not a
    trip to a version list.
    """

    def __init__(self, service: "ProjectService", code_id: str,
                 new_parent_id: Optional[str], label: str = "") -> None:
        code = service.get_code(code_id)
        name = code.name if code is not None else code_id
        super().__init__(label or f"Move '{name}'")
        self._service = service
        self._code_id = code_id
        self._new_parent = new_parent_id or None
        self._old_parent = code.parent_id if code is not None else None

    def redo(self) -> None:  # noqa: D102 - Qt override
        self._service.set_code_parent(self._code_id, self._new_parent)

    def undo(self) -> None:  # noqa: D102 - Qt override
        self._service.set_code_parent(self._code_id, self._old_parent)


class EditCodeCommand(QUndoCommand):
    """Rename a code and/or change its definition."""

    def __init__(self, service: "ProjectService", code_id: str,
                 name: str, definition: str, label: str = "") -> None:
        code = service.get_code(code_id)
        super().__init__(label or f"Edit '{code.name if code else code_id}'")
        self._service = service
        self._code_id = code_id
        self._new = (name, definition)
        self._old = ((code.name, code.definition) if code is not None
                     else (name, definition))

    def redo(self) -> None:  # noqa: D102 - Qt override
        self._service.update_code(self._code_id, name=self._new[0],
                                  definition=self._new[1])

    def undo(self) -> None:  # noqa: D102 - Qt override
        self._service.update_code(self._code_id, name=self._old[0],
                                  definition=self._old[1])


class AddCodeCommand(QUndoCommand):
    """Create a code. Undo deletes it -- safe only because it is brand new.

    Deleting a code cascades its applications away, which is why no other
    command in this module deletes one. Here the code was created by this very
    command, so it cannot yet carry anyone's coding.
    """

    def __init__(self, service: "ProjectService", name: str,
                 definition: str = "", parent_id: Optional[str] = None) -> None:
        super().__init__(f"Add code '{name}'")
        self._service = service
        self._name = name
        self._definition = definition
        self._parent_id = parent_id
        self.code_id: Optional[str] = None

    def redo(self) -> None:  # noqa: D102 - Qt override
        self.code_id = self._service.add_code(
            self._name, self._definition, self._parent_id)

    def undo(self) -> None:  # noqa: D102 - Qt override
        if self.code_id:
            self._service.delete_code(self.code_id)
            self.code_id = None
