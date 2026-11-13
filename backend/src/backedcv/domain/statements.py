"""What the candidate says, in their own words, about experience the CV leaves out. A new CV
line can be written from a statement, and the statement is then the evidence the line cites."""

from collections.abc import Mapping

from backedcv.domain.models import ParsedCV, Requirement

# Skills and duties can be told in a sentence. Degrees, licences, languages, years and the
# screening questions are settled elsewhere.
_TELLABLE_CATEGORIES = frozenset({"hard_skill", "soft_skill", "other"})


def note_ref(requirement_id: str) -> str:
    """The ID a suggestion cites for the candidate's words about a requirement: R07 -> U07."""
    return "U" + requirement_id.removeprefix("R")


def can_state(requirement: Requirement) -> bool:
    """True for a requirement the candidate can back with a statement."""
    return requirement.category in _TELLABLE_CATEGORIES and requirement.knockout_type is None


def with_notes(cv: ParsedCV, statements: Mapping[str, str]) -> ParsedCV:
    """The CV with each statement as a citable note (U07 for requirement R07)."""
    if not statements:
        return cv
    notes = {note_ref(rid): text for rid, text in statements.items()}
    return cv.model_copy(update={"candidate_notes": notes})
