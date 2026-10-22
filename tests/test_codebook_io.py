"""Codebook exchange: rules and examples travel with the codes."""

def test_inclusion_and_exclusion_rules_and_examples_survive_import_and_export(tmp_path):
    """A structured codebook lost its rules on import (found by an independent review of the project)."""
    from core.codebook_io import export_codebook_yaml, import_codebook_yaml
    from core.project import Project

    text = """codebook:
- name: Financial stress
  definition: Worry about paying for college.
  inclusion_criteria: Costs described as a burden.
  exclusion_criteria: Money mentioned only to say it is not a problem.
  examples:
  - Money has been the hardest part.
  - The costs added up fast.
- name: Belonging
  definition: Feeling connected.
"""
    with Project.create(tmp_path / "a.qnw") as proj:
        import_codebook_yaml(proj, text)
        codes = {c.name: c for c in proj.get_codebook()}
        stress = codes["Financial stress"]
        assert stress.inclusion_criteria == "Costs described as a burden."
        assert stress.exclusion_criteria == "Money mentioned only to say it is not a problem."
        assert stress.examples == ["Money has been the hardest part.", "The costs added up fast."]
        assert not codes["Belonging"].inclusion_criteria and codes["Belonging"].examples == []
        exported = export_codebook_yaml(proj)
    assert "inclusion_criteria" in exported and "Money has been the hardest part." in exported
    with Project.create(tmp_path / "b.qnw") as other:
        import_codebook_yaml(other, exported)
        again = {c.name: c for c in other.get_codebook()}["Financial stress"]
        assert again.exclusion_criteria == "Money mentioned only to say it is not a problem."
        assert len(again.examples) == 2
