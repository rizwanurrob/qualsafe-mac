"""'The order they were ingested' must be the order sources were added, not the order of their random ids."""

from __future__ import annotations

from core.model import Source
from core.project import Project


def test_ingestion_order_is_insertion_order_even_though_ids_are_random(tmp_path):
    with Project.create(tmp_path / "p.qnw") as proj:
        added = [proj.add_source(Source(source_id="", type="survey_response", raw_text=f"answer {i}", label=f"S{i}"))
                 for i in range(40)]
        assert proj.source_ids_in_ingestion_order() == added
        # the id-sorted list is a different, arbitrary order: that is why the saturation views must not use it
        assert [s.source_id for s in proj.list_sources()] == sorted(added)
        assert sorted(added) != added
