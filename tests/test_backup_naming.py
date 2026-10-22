"""
Backups must not overwrite each other (`core/backups.py`).

Found by replacing a vacuous assertion. `tests/test_qt_data.py` contained
`assert widget.backup_list.count() >= 0`, which a Qt count satisfies
unconditionally. Tightening it to "the count grew by one" failed immediately:
clicking *Back up now* twice produced **one** file.

The cause is a precision assumption that does not hold. `backup_store` names
files with `datetime.now().strftime(..."%f")` and a comment describing it as a
microsecond stamp. On Windows `datetime.now()` advances in ticks of roughly a
millisecond or worse — eight calls in a tight loop return **one identical
value** — so two backups inside a tick produced the same filename and
`shutil.copy2` silently overwrote the first.

Why that matters more than it sounds: the automatic backups taken before
destructive operations arrive in bursts. A five-deep safety net silently became
one deep exactly where depth was the point.

These tests are about names and ordering, not about copying, because the copy
was never what was broken.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.backups import DEFAULT_KEEP, backup_store, list_backups
from core.project import Project


@pytest.fixture()
def store(tmp_path):
    path = tmp_path / "p.qnw"
    Project.create(path).close()
    return path


class TestRapidBackupsDoNotCollide:

    def test_two_backups_in_the_same_instant_are_two_files(self, store):
        first = backup_store(store, reason="manual")
        second = backup_store(store, reason="manual")

        assert first is not None and second is not None
        assert first.name != second.name
        assert first.exists() and second.exists()

    def test_a_burst_produces_one_file_each(self, store):
        """The realistic shape of the bug: several safety backups at once."""
        made = [backup_store(store, reason="before erasure") for _ in range(8)]

        assert len({path.name for path in made}) == 8

    def test_the_burst_is_kept_to_the_retention_limit(self, store):
        """Distinct names must not mean an unbounded directory."""
        for _ in range(DEFAULT_KEEP + 4):
            backup_store(store, reason="manual")

        assert len(list_backups(store)) == DEFAULT_KEEP

    def test_different_reasons_in_one_tick_stay_distinct(self, store):
        first = backup_store(store, reason="before erasure")
        second = backup_store(store, reason="manual")

        assert first.name != second.name


class TestOrderingStaysChronological:
    """`list_backups` sorts by name and `_prune` deletes from the end of that
    sort, so a name that sorts wrongly deletes the wrong backup."""

    def test_newest_first(self, store):
        made = [backup_store(store, reason="manual") for _ in range(4)]

        listed = [path.name for path in list_backups(store)]

        assert listed == sorted(listed, reverse=True)
        assert listed[0] == made[-1].name, "the newest backup is not listed first"

    def test_pruning_removes_the_oldest_not_an_arbitrary_one(self, store):
        made = [backup_store(store, reason="manual")
                for _ in range(DEFAULT_KEEP + 2)]

        surviving = {path.name for path in list_backups(store)}

        assert made[0].name not in surviving, "the oldest survived a prune"
        assert made[-1].name in surviving, "the newest was pruned"

    def test_the_sequence_number_is_zero_padded(self, store):
        """Unpadded, `_10_` would sort before `_2_` and the ordering above
        would be wrong only once ten backups shared a tick."""
        made = backup_store(store, reason="manual")

        parts = made.stem.split("_")
        assert any(part.isdigit() and len(part) == 3 for part in parts)

    def test_the_sequence_is_always_present_not_only_on_collision(self, store):
        """`..._971360_manual` and `..._971360_1_manual` sort with the later
        file first, which would make `list_backups` report the wrong newest.
        Uniform names are what keep the ordering honest."""
        first = backup_store(store, reason="manual")
        second = backup_store(store, reason="manual")

        assert "_000_" in first.name
        assert first.name.count("_") == second.name.count("_")


@pytest.fixture()
def frozen_clock(monkeypatch):
    """Every `datetime.now()` inside `core.backups` returns one instant — the
    worst case of a coarse clock, made deterministic on every OS."""
    import core.backups as backups
    from datetime import datetime

    instant = datetime(2026, 1, 2, 3, 4, 5, 678901)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(backups, "datetime", _Frozen)
    return instant


class TestTheStampIsNotTrustedForUniqueness:

    def test_a_frozen_clock_still_yields_distinct_ordered_names(
            self, store, frozen_clock):
        """The guarantee itself, independent of the host clock. On Linux and
        macOS `now()` is usually fine-grained enough that the burst tests above
        would pass without the sequence number; freezing the clock is what
        proves the sequence number, not the stamp, carries uniqueness."""
        made = [backup_store(store, reason="before erasure") for _ in range(4)]

        stamp = frozen_clock.strftime("%Y%m%d_%H%M%S_%f")
        assert all(stamp in path.name for path in made), "the clock was not frozen"
        assert len({path.name for path in made}) == 4
        listed = [path.name for path in list_backups(store)]
        assert listed == [path.name for path in reversed(made)]

    def test_the_clock_really_is_this_coarse(self):
        """The premise, measured rather than assumed — and a canary. On Windows
        `now()` repeats within a tick; on Linux and macOS it usually does not,
        which is why this skips rather than fails there. The frozen-clock test
        above carries the guarantee either way."""
        from datetime import datetime

        stamps = {datetime.now().strftime("%Y%m%d_%H%M%S_%f") for _ in range(50)}

        if len(stamps) == 50:
            pytest.skip(
                "datetime.now() is fine-grained on this host; the sequence "
                "number in backup names is belt-and-braces here rather than "
                "load bearing (see the comment in core/backups.py)")

    def test_a_missing_store_is_still_refused(self, tmp_path):
        assert backup_store(tmp_path / "absent.qnw") is None

    def test_the_name_records_the_reason(self, store):
        made = backup_store(store, reason="before erasure")

        assert "before_erasure" in made.name
