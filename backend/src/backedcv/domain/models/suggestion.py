"""Suggested CV rewrites and their verification: nothing reaches the new CV unless verified."""

from typing import Literal

from pydantic import BaseModel, Field

from backedcv.domain.models.screening import GatePass

SuggestionKind = Literal["align_wording", "add_skill", "tailor_summary", "add_line"]
# "refused": backed by the CV, but not viable (old evidence or a hidden barrier); never accepted.
VerificationStatus = Literal["pending", "verified", "unsupported", "refused"]


class ClaimCheck(BaseModel):
    """One atomic claim of a suggestion and the CV references that back it."""

    text: str
    supported_by: list[str] = Field(default_factory=list)  # L and F IDs
    ok: bool
    reason: str | None = None


class GuardResult(BaseModel):
    """A deterministic check run in code. Hard failures make the suggestion unsupported."""

    name: str
    ok: bool
    hard: bool = True
    detail: str | None = None


class Verification(BaseModel):
    status: VerificationStatus = "pending"
    claims: list[ClaimCheck] = Field(default_factory=list)
    guards: list[GuardResult] = Field(default_factory=list)
    passes: list[GatePass] = Field(default_factory=list)  # the corroboration gate, in order
    reason: str | None = None  # first failing reason, shown to the user


class Suggestion(BaseModel):
    """A proposed change that may only cite the CV.

    `target` is a line ID (L012) for align_wording, a section ID for add_skill (the line is
    appended to that section) and tailor_summary (the section's lines are replaced), or an entry
    ID (E02) for add_line (a new bullet at the end of that job or project). `before` is the
    original text of the target line, or None when a line is added.
    """

    id: str  # S01, S02, ...
    kind: SuggestionKind
    target: str
    before: str | None = None
    after: str
    requirement_ids: list[str] = Field(default_factory=list)
    cited_refs: list[str] = Field(default_factory=list)
    introduced_terms: list[str] = Field(default_factory=list)
    covers_requirement_ids: list[str] = Field(default_factory=list)  # computed in code
    edited_by_user: bool = False
    # "candidate": written from what the candidate said about a requirement, not from a CV line.
    source: Literal["cv", "candidate"] = "cv"
    verification: Verification = Field(default_factory=Verification)


class ReviewDecisions(BaseModel):
    accepted: list[str] = Field(default_factory=list, max_length=200)
    rejected: list[str] = Field(default_factory=list, max_length=200)
    # True: the user asked for sections and entries to be reordered for the posting. By default
    # the built CV keeps the order of the CV it came from.
    reorder: bool = False
