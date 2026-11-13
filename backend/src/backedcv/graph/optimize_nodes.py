"""Optimize-phase nodes: suggest rewrites, verify each one, then pause for the user's review."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypedDict

from langgraph.types import Send, interrupt

from backedcv.domain.corroboration import (
    apply_pass,
    backed_pass,
    barrier_pass,
    not_viable_targets,
    recency_pass,
    refusals_from,
)
from backedcv.domain.guards import NEW_SKILLS, NEW_SUMMARY, apply_guards, keyword_only
from backedcv.domain.keywords import contains_term
from backedcv.domain.models import (
    ClaimCheck,
    JobPosting,
    ParsedCV,
    Requirement,
    RequirementAssessment,
    ReviewDecisions,
    Suggestion,
)
from backedcv.domain.models.screening import clean_prose, short_sentence
from backedcv.domain.models.suggestion import VerificationStatus
from backedcv.domain.recency import entry_last_used, line_last_used
from backedcv.domain.redaction import numbered_rows, redact_contact
from backedcv.domain.statements import can_state, note_ref
from backedcv.graph.nodes import _error, _progress
from backedcv.graph.recompute import (
    assessments_of,
    cv_of,
    recency_of,
    risks_of,
    statements_of,
    today_of,
)
from backedcv.graph.state import AnalysisState
from backedcv.llm.drafts_optimize import (
    AdditionDraft,
    AdditionsDraft,
    ClaimDraft,
    SuggestionDraft,
    SuggestionsDraft,
    VerificationBatchDraft,
    VerificationDraft,
)
from backedcv.llm.prompt_loader import load_prompt
from backedcv.llm.structured import StructuredLLM

log = logging.getLogger(__name__)

CANDIDATE_GROUP = "candidate"  # the lines written from the candidate's words are verified together
NOT_SHOWN = "no CV line or fact shows it"
NOT_SAID = "your own words do not say it"
NOT_WRITTEN = "Your words do not say that you have done this, so nothing was added."


@dataclass
class _Drafted:
    """What one drafting call gives the suggest step."""

    suggestions: list[Suggestion] = field(default_factory=list)
    usage: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # statements no line was written from


class VerifyTask(TypedDict):
    """Payload of one verify_batch call: one CV section's pending suggestions, and the whole CV."""

    cv: dict
    group: list[dict]  # not "suggestions": a TypedDict input schema must not clash with the state


def _cv_block(cv: ParsedCV) -> str:
    """The CV lines and computed facts that suggest and verify read, with contact data redacted."""
    lines = cv.numbered(include_facts=False)
    facts = numbered_rows((fact.id, fact.text) for fact in cv.facts)
    return f"<cv_lines>\n{lines}\n</cv_lines>\n\n<facts>\n{facts}\n</facts>"


def _needs_wording(req: Requirement, a: RequirementAssessment | None, excluded: set[str]) -> bool:
    """Met by evidence, but the posting's exact terms are missing from the CV."""
    return (
        req.id not in excluded
        and a is not None
        and a.status == "met"
        and bool(a.evidence)
        and not a.keyword_present
        and bool(req.terms)
    )


def _requirement_row(req: Requirement, a: RequirementAssessment) -> str:
    terms = ", ".join(f'"{term}"' for term in req.terms)
    evidence = ", ".join(e.ref for e in a.evidence)
    return f"{req.id} | terms: {terms} | evidence: {evidence}"


def _suggestion_row(s: Suggestion) -> str:
    cited = ", ".join(s.cited_refs)
    introduced = ", ".join(s.introduced_terms) or "none"
    after = " ".join(s.after.split())  # one row per suggestion, even when `after` has newlines
    return f"{s.id} | cited: {cited} | introduced: {introduced} | after: {after}"


def _suggested_after(d: SuggestionDraft | AdditionDraft) -> str:
    """Skill names start with a capital, so "vector databases" reads "Vector databases" under
    Skills. A first word that already has a capital ("iOS") keeps its casing. Other kinds keep
    the model's wording."""
    first_word = d.after.partition(" ")[0]
    if d.kind != "add_skill" or first_word != first_word.lower():
        return d.after
    return d.after[:1].upper() + d.after[1:]


def _suggest_target(d: SuggestionDraft, cv: ParsedCV) -> str:
    """Maps the heading or line IDs the model gives onto the section IDs the app uses."""
    if d.kind == "align_wording":
        return d.target
    if d.kind == "tailor_summary":
        summary = next((s for s in cv.sections if s.type == "summary"), None)
        return summary.id if summary else NEW_SUMMARY
    section_of = {line_id: s for s in cv.sections for line_id in s.line_ids}
    for ref in [d.target, *d.cited_refs]:
        section = section_of.get(ref)
        if section is not None and section.type == "skills":
            return section.id
    skills = next((s for s in cv.sections if s.type == "skills"), None)
    return skills.id if skills else NEW_SKILLS


def _drop_padding(suggestions: list[Suggestion], job: JobPosting) -> list[Suggestion]:
    """The model's suggestions without the ones that only pad their line with posting words or
    filler, numbered S01, S02... in their order. Padding is backed by the CV, so it is dropped
    rather than marked unsupported, and it never costs a verifier call."""
    kept: list[Suggestion] = []
    for s in suggestions:
        reason = keyword_only(s, job)
        if reason is None:
            kept.append(s)
        else:
            log.info("suggest dropped a %s edit of %s: %s", s.kind, s.target, reason)
    return [s.model_copy(update={"id": f"S{i:02d}"}) for i, s in enumerate(kept, start=1)]


def _section_of(target: str, cv: ParsedCV) -> str:
    """The CV section a suggestion's target sits in. A target outside every section stands alone."""
    for section in cv.sections:
        if target in (section.id, *section.line_ids):
            return section.id
    return target


def _stored_suggestions(state: AnalysisState) -> list[Suggestion]:
    return [Suggestion.model_validate(row) for row in state.get("suggestions") or []]


def _claim_check(claim: ClaimDraft, refs: dict[str, str], nothing: str = NOT_SHOWN) -> ClaimCheck:
    known = [ref for ref in claim.supported_by if ref in refs]
    unknown = [ref for ref in claim.supported_by if ref not in refs]
    reason = claim.unsupported_reason or None
    if unknown:
        reason = f"cites IDs that are not in the CV: {', '.join(unknown)}"
    elif not known:
        reason = reason or nothing
    return ClaimCheck(text=claim.text, supported_by=known, ok=reason is None, reason=reason)


def _with_verification(
    s: Suggestion, status: VerificationStatus, reason: str | None, claims: list[ClaimCheck]
) -> Suggestion:
    verification = s.verification.model_copy(
        update={"status": status, "reason": reason, "claims": claims}
    )
    return s.model_copy(update={"verification": verification})


def _verdict(s: Suggestion, answer: VerificationDraft | None, cv: ParsedCV) -> Suggestion:
    """Verified only if every hard guard, claim and term passes and the verifier is sure."""
    if answer is None:
        return _with_verification(s, "unsupported", "not verified", [])
    refs = cv.texts_by_ref()
    nothing = NOT_SAID if s.source == "candidate" else NOT_SHOWN
    claims = [_claim_check(c, refs, nothing) for c in answer.claims]
    reasons = [g.detail or g.name for g in s.verification.guards if g.hard and not g.ok]
    reasons += [c.reason for c in claims if c.reason]
    reasons += [
        f"adds a claim: {t.term}" for t in answer.term_judgements if t.verdict == "adds_claim"
    ]
    if answer.uncertain or not claims:
        reasons.append("the verifier was not sure")
    if reasons:
        return _with_verification(s, "unsupported", reasons[0], claims)
    return _with_verification(s, "verified", None, claims)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _entries_block(cv: ParsedCV) -> str:
    """One row per job or project, contact details redacted: where a new line can go."""
    rows = []
    for entry in cv.entries:
        if entry.kind not in ("job", "project"):
            continue
        dates = f"{entry.start} to {entry.end or 'unknown'}" if entry.start else "no dates"
        title = redact_contact(entry.title or "untitled")
        organization = redact_contact(entry.organization or "none")
        rows.append(f"{entry.id} | {entry.kind} | {title} | {organization} | {dates}")
    return "\n".join(rows) or "none"


def _statement_row(req: Requirement, statement: str) -> str:
    terms = ", ".join(f'"{term}"' for term in req.terms) or "none"
    said = redact_contact(_one_line(statement))
    return f"{note_ref(req.id)} | requirement: {req.label} | terms: {terms} | says: {said}"


def _told_requirements(
    job: JobPosting, statements: dict[str, str]
) -> list[tuple[Requirement, str]]:
    """The requirements the candidate spoke for, in posting order, with their words."""
    return [
        (req, statements[req.id])
        for req in job.requirements
        if req.id in statements and can_state(req)
    ]


def _names_skill(req: Requirement, after: str) -> bool:
    """A line for a hard skill must name it with one of the posting's terms: a tool counts as
    shown only when the new line says its name. Other requirements have no such name to check."""
    names = [*req.terms, *req.aliases]
    if req.category != "hard_skill" or not names:
        return True
    return any(contains_term(after, name) for name in names)


def _told_suggestion(d: AdditionDraft, req: Requirement, cv: ParsedCV) -> Suggestion:
    """The suggestion for one statement, not numbered yet. A new line goes under the entry the
    model names; a skill goes to the Skills section, like any other added skill."""
    if d.kind == "add_line":
        target = d.entry_id or ""
    else:
        skills = next((s for s in cv.sections if s.type == "skills"), None)
        target = skills.id if skills else NEW_SKILLS
    return Suggestion(
        id="S00",
        kind=d.kind,
        target=target,
        after=_suggested_after(d).strip(),
        requirement_ids=[req.id],
        cited_refs=[note_ref(req.id)],
        source="candidate",
    )


async def _word(llm: StructuredLLM, cv: ParsedCV, job: JobPosting, rows: list[str]) -> _Drafted:
    """The model's rewording of lines the CV already has, guarded and without padding."""
    if not rows:
        return _Drafted()
    requirements = "\n".join(rows)
    data = f"{_cv_block(cv)}\n\n<requirements>\n{requirements}\n</requirements>"
    try:
        draft, usage = await llm.run(load_prompt("suggest"), data, SuggestionsDraft, node="suggest")
    except Exception as exc:  # suggestions are optional: the report stands without them
        return _Drafted(errors=[_error("suggest", exc)])
    guarded = [
        apply_guards(
            Suggestion(
                id=f"S{i:02d}",
                kind=d.kind,
                target=_suggest_target(d, cv),
                after=_suggested_after(d),
                requirement_ids=d.requirement_ids,
                cited_refs=d.cited_refs,
            ),
            cv,
            job,
        )
        for i, d in enumerate(draft.suggestions, start=1)
    ]
    return _Drafted(suggestions=_drop_padding(guarded, job), usage=[usage])


async def _write(
    llm: StructuredLLM, cv: ParsedCV, job: JobPosting, told: list[tuple[Requirement, str]]
) -> _Drafted:
    """Lines written from what the candidate said, in one model call. Each line cites only its
    statement; the guards and the verifier then check it against those words."""
    if not told:
        return _Drafted()
    rows = "\n".join(_statement_row(req, text) for req, text in told)
    data = (
        f"<cv_entries>\n{_entries_block(cv)}\n</cv_entries>\n\n<statements>\n{rows}\n</statements>"
    )
    try:
        draft, usage = await llm.run(
            load_prompt("write_additions"), data, AdditionsDraft, node="suggest"
        )
    except Exception as exc:  # the report and the other suggestions stand without them
        return _Drafted(errors=[_error("suggest", exc)])
    by_note = {d.statement_id: d for d in draft.additions}
    drafted = _Drafted(usage=[usage])
    for req, _ in told:
        d = by_note.get(note_ref(req.id))
        if d is None or d.kind == "none" or not d.after.strip():
            reason = (d.reason.strip() if d is not None else "") or NOT_WRITTEN
            drafted.skipped.append({"requirement_id": req.id, "reason": short_sentence(reason)})
        elif not _names_skill(req, d.after):
            reason = f"Your words do not name {clean_prose(req.label)}, so nothing was added."
            drafted.skipped.append({"requirement_id": req.id, "reason": reason})
        else:
            drafted.suggestions.append(_told_suggestion(d, req, cv))
    return drafted


def make_optimize_nodes(llm: StructuredLLM) -> dict[str, Callable]:
    async def suggest(state: AnalysisState) -> dict:
        _progress("suggest", "started")
        cv = cv_of(state)
        job = JobPosting.model_validate(state["job"])
        excluded = set(state.get("excluded_ids") or [])
        assessments = assessments_of(state)
        # Requirements that are not viable (too old, or blocked by a hidden barrier) get no wording.
        held = not_viable_targets(job, assessments, recency_of(state), risks_of(state), excluded)
        skipped = excluded | {refusal.requirement_id for refusal in held}
        rows = [
            _requirement_row(req, assessments[req.id])
            for req in job.requirements
            if _needs_wording(req, assessments.get(req.id), skipped)
        ]
        told = _told_requirements(job, statements_of(state))
        if not rows and not told:
            _progress("suggest", "done", suggestions=0)
            return {"suggestions": []}
        # The rewording of what the CV has and the lines from the candidate's words run together.
        worded, written = await asyncio.gather(
            _word(llm, cv, job, rows), _write(llm, cv, job, told)
        )
        first = len(worded.suggestions) + 1
        added = [
            apply_guards(s.model_copy(update={"id": f"S{i:02d}"}), cv, job)
            for i, s in enumerate(written.suggestions, start=first)
        ]
        suggestions = [s.model_dump() for s in [*worded.suggestions, *added]]
        _progress("suggest", "done", suggestions=len(suggestions))
        update: dict = {"suggestions": suggestions}
        if told:
            update["skipped_statements"] = written.skipped
        if usage := [*worded.usage, *written.usage]:
            update["usage"] = usage
        if errors := [*worded.errors, *written.errors]:
            update["errors"] = errors
        return update

    def route_verification(state: AnalysisState) -> list[Send] | str:
        suggestions = [Suggestion.model_validate(s) for s in state.get("suggestions") or []]
        pending = [s for s in suggestions if s.verification.status == "pending"]
        if not pending:
            return "gate_recency"  # an empty Send list would end the graph early
        cv = cv_of(state)
        groups: dict[str, list[dict]] = {}
        for s in pending:
            key = CANDIDATE_GROUP if s.source == "candidate" else _section_of(s.target, cv)
            groups.setdefault(key, []).append(s.model_dump())
        # The verifier needs the candidate's notes only when there are any.
        payload = cv.model_dump() if cv.candidate_notes else state["cv"]
        return [
            Send("verify_batch", VerifyTask(cv=payload, group=rows)) for rows in groups.values()
        ]

    async def verify_batch(task: VerifyTask) -> dict:
        _progress("verify", "started")
        cv = ParsedCV.model_validate(task["cv"])
        suggestions = [Suggestion.model_validate(s) for s in task["group"]]
        rows = "\n".join(_suggestion_row(s) for s in suggestions)
        if all(s.source == "candidate" for s in suggestions):
            # Lines written from the candidate's words are checked against those words alone.
            prompt = load_prompt("verify_additions")
            cited = dict.fromkeys(
                ref for s in suggestions for ref in s.cited_refs if ref in cv.candidate_notes
            )
            notes = numbered_rows((ref, _one_line(cv.candidate_notes[ref])) for ref in cited)
            data = f"<statements>\n{notes}\n</statements>\n\n<suggestions>\n{rows}\n</suggestions>"
        else:
            prompt = load_prompt("verify")
            data = f"{_cv_block(cv)}\n\n<suggestions>\n{rows}\n</suggestions>"
        try:
            batch, usage = await llm.run(prompt, data, VerificationBatchDraft, node="verify_batch")
        except Exception as exc:  # no answer is no proof: the whole group is unsupported
            _progress("verify", "done", suggestions=len(suggestions))
            failed = [
                _with_verification(s, "unsupported", "verification failed", []) for s in suggestions
            ]
            return {
                "suggestions": [s.model_dump() for s in failed],
                "errors": [_error("verify_batch", exc)],
            }
        answers = {v.suggestion_id: v for v in batch.verifications}
        checked = [_verdict(s, answers.get(s.id), cv) for s in suggestions]
        _progress("verify", "done", suggestions=len(checked))
        return {"suggestions": [s.model_dump() for s in checked], "usage": [usage]}

    async def gate_recency(state: AnalysisState) -> dict:
        """Every suggestion must pass the backed check, then the recency check. No model call."""
        today = today_of(state)
        cv = ParsedCV.model_validate(state["cv"])
        # A line added to a job is as recent as the job, so entries are dated too.
        last_used = {**line_last_used(cv, today), **entry_last_used(cv, today)}
        recency = recency_of(state)
        rows = []
        for s in _stored_suggestions(state):
            s = apply_pass(s, backed_pass(s))
            s = apply_pass(s, recency_pass(s, recency, last_used, today))
            rows.append(s.model_dump())
        return {"suggestions": rows}

    async def gate_barriers(state: AnalysisState) -> dict:
        """The barrier check on every suggestion, then the refusals: requirements not viable from
        the start, and every suggestion refused by a gate."""
        job = JobPosting.model_validate(state["job"])
        assessments = assessments_of(state)
        recency = recency_of(state)
        risks = risks_of(state)
        excluded = set(state.get("excluded_ids") or [])
        rows = [apply_pass(s, barrier_pass(s, risks)) for s in _stored_suggestions(state)]
        refusals = [
            *not_viable_targets(job, assessments, recency, risks, excluded),
            *refusals_from(rows),
        ]
        return {
            "suggestions": [s.model_dump() for s in rows],
            "refusals": [r.model_dump() for r in refusals],
        }

    async def await_review(state: AnalysisState) -> dict:
        # Nothing runs before the interrupt: a node restarts from its top on resume.
        decisions = ReviewDecisions.model_validate(interrupt({"stage": "review_ready"}))
        return {"decisions": decisions.model_dump()}

    return {
        "suggest": suggest,
        "route_verification": route_verification,
        "verify_batch": verify_batch,
        "gate_recency": gate_recency,
        "gate_barriers": gate_barriers,
        "await_review": await_review,
    }
