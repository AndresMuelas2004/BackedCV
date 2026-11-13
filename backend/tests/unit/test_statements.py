"""What the candidate says about a requirement becomes a note a new CV line can cite."""

from backedcv.domain.models import CVLine, ParsedCV, Requirement
from backedcv.domain.statements import can_state, note_ref, with_notes


def _requirement(category: str = "hard_skill", knockout_type: str | None = None) -> Requirement:
    return Requirement(
        id="R07",
        label="Kubernetes",
        quote="Kubernetes",
        category=category,
        importance="required",
        knockout_type=knockout_type,
    )


def test_a_statement_is_cited_by_the_number_of_its_requirement():
    assert note_ref("R07") == "U07"


def test_skills_can_be_stated_and_screening_questions_cannot():
    assert can_state(_requirement())
    assert can_state(_requirement("soft_skill"))
    assert not can_state(_requirement("education"))
    assert not can_state(_requirement("hard_skill", "certification_license"))
    assert not can_state(_requirement("work_authorization", "work_authorization"))


def test_notes_become_citable_without_touching_what_the_model_reads():
    cv = ParsedCV(lines=[CVLine(id="L001", text="Jane Doe")])

    noted = with_notes(cv, {"R07": "I ran our API on Kubernetes at Acme."})

    assert noted.texts_by_ref()["U07"] == "I ran our API on Kubernetes at Acme."
    assert noted.numbered() == cv.numbered()
    assert with_notes(cv, {}) is cv
