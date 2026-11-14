"""The checks on a deeper analysis. A person, a fact, an address or a link is kept only when a
page the searches returned (or the posting itself) shows it, and a message is kept only when it
cites CV lines. Whatever fails a check is left out and counted, never repaired."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from backedcv.domain.models.cv import ParsedCV
from backedcv.domain.models.research import (
    Action,
    Channel,
    CompanyBrief,
    CompanyFact,
    Draft,
    Person,
    Source,
    WebNotes,
)
from backedcv.domain.text import fold_lower
from backedcv.llm.drafts_research import OutreachDraft, ResearchExtractDraft

MAX_PEOPLE = 12
MAX_CHANNELS = 8
MAX_FACTS = 8
MAX_GAPS = 5
MAX_ACTIONS = 6
NAME_PLACEHOLDER = "[Your name]"

_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def clean_url(url: str) -> str:
    """The form two addresses are compared in: no fragment, no trailing slash, no leading www."""
    text = url.strip()
    try:
        parts = urlsplit(text.split("#", 1)[0])
    except ValueError:
        # Not parseable: compare the raw text, so it only ever matches itself.
        return text.lower()
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.removesuffix("/")
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


@dataclass(frozen=True)
class Findings:
    company: CompanyBrief
    people: list[Person]
    channels: list[Channel]
    notes: list[str]
    sources: list[Source]


def assemble(draft: ResearchExtractDraft, notes: Sequence[WebNotes], job_text: str) -> Findings:
    # Every page the searches returned, once per address: the first one wins.
    sources: list[Source] = []
    seen_urls: set[str] = set()
    for item in notes:
        for source in item.sources:
            key = clean_url(source.url)
            if key not in seen_urls:
                seen_urls.add(key)
                sources.append(source)

    # What each returned page shows: its title and the passages the notes cite from it.
    texts: dict[str, list[str]] = {clean_url(s.url): [fold_lower(s.title)] for s in sources}
    for item in notes:
        for quote in item.quotes:
            parts = texts.get(clean_url(quote.url))
            if parts is not None:
                parts.append(fold_lower(quote.text))
    shown = {key: " ".join(parts) for key, parts in texts.items()}
    posting = fold_lower(job_text)

    people: list[Person] = []
    people_failed = 0
    seen_names: set[str] = set()
    for item in draft.people:
        if len(people) >= MAX_PEOPLE:
            break
        source_key = clean_url(item.source_url)
        if source_key not in shown:
            people_failed += 1
            continue
        # Dots go first so that "J. Smith" does not leave a lone initial to match.
        words = [w for w in fold_lower(item.name).replace(".", "").split() if len(w) >= 2]
        if len(words) < 2:
            people_failed += 1
            continue
        profile_key = clean_url(item.profile_url) if item.profile_url else None
        profile_shown = profile_key is not None and profile_key in shown
        candidates = [shown[source_key], posting]
        if profile_key is not None and profile_shown:
            candidates.append(shown[profile_key])
        if not any(all(word in text for word in words) for text in candidates):
            people_failed += 1
            continue
        name_key = fold_lower(item.name)
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        people.append(
            Person(
                id=f"P{len(people) + 1:02d}",
                name=item.name.strip(),
                role=item.role.strip(),
                group=item.group,
                why=item.why.strip(),
                profile_url=item.profile_url if profile_shown else None,
                source_url=item.source_url,
            )
        )

    channels: list[Channel] = []
    channels_failed = 0
    seen_values: set[str] = set()
    job_lower = job_text.casefold()
    for item in draft.channels:
        if len(channels) >= MAX_CHANNELS:
            break
        value = item.value.strip()
        draft_source_shown = item.source_url is not None and clean_url(item.source_url) in shown
        if item.kind == "email":
            address = value.casefold()
            if not _EMAIL.match(value) or not (
                address in posting or any(address in text for text in shown.values())
            ):
                channels_failed += 1
                continue
            if draft_source_shown:
                source_url = item.source_url
            else:
                # The posting shows it when no returned page does.
                source_url = next(
                    (s.url for s in sources if address in shown[clean_url(s.url)]), None
                )
        else:
            is_link = value.lower().startswith(("http://", "https://"))
            if not is_link or not (clean_url(value) in shown or value.casefold() in job_lower):
                channels_failed += 1
                continue
            source_url = item.source_url if draft_source_shown else None
        key = value.casefold()
        if key in seen_values:
            continue
        seen_values.add(key)
        channels.append(
            Channel(
                id=f"C{len(channels) + 1:02d}",
                kind=item.kind,
                value=value,
                label=item.label.strip(),
                source_url=source_url,
            )
        )

    facts: list[CompanyFact] = []
    for fact in draft.facts:
        if len(facts) >= MAX_FACTS:
            break
        if clean_url(fact.source_url) not in shown or not fact.label.strip():
            continue
        if not fact.value.strip():
            continue
        facts.append(
            CompanyFact(
                label=fact.label.strip(), value=fact.value.strip(), source_url=fact.source_url
            )
        )

    company = CompanyBrief(
        name=(draft.company_name or "").strip() or None,
        summary=draft.company_summary.strip(),
        facts=facts,
    )

    out_notes = [gap.strip() for gap in draft.gaps if gap.strip()][:MAX_GAPS]
    if people_failed == 1:
        out_notes.append("1 person was left out because no page from the searches shows them.")
    elif people_failed > 1:
        out_notes.append(
            f"{people_failed} people were left out because no page from the searches shows them."
        )
    if channels_failed == 1:
        out_notes.append("1 address or link was left out because no page shows it.")
    elif channels_failed > 1:
        out_notes.append(
            f"{channels_failed} addresses or links were left out because no page shows them."
        )

    return Findings(
        company=company,
        people=people,
        channels=channels,
        notes=out_notes,
        sources=sources,
    )


def plan_actions(
    draft: OutreachDraft,
    people: Sequence[Person],
    channels: Sequence[Channel],
    cv: ParsedCV,
) -> list[Action]:
    person_ids = {person.id for person in people}
    channel_ids = {channel.id for channel in channels}
    cv_refs = cv.texts_by_ref()
    candidate_name = cv.contact.name.value if cv.contact.name is not None else None

    actions: list[Action] = []
    for item in draft.actions:
        if len(actions) >= MAX_ACTIONS:
            break
        person_id = item.person_id if item.person_id in person_ids else None
        channel_id = item.channel_id if item.channel_id in channel_ids else None
        title = item.title.strip()
        why = item.why.strip()
        action_id = f"A{len(actions) + 1:02d}"
        if item.kind in ("apply", "follow"):
            actions.append(
                Action(
                    id=action_id,
                    kind=item.kind,
                    title=title,
                    why=why,
                    person_id=person_id,
                    channel_id=channel_id,
                    draft=None,
                )
            )
            continue

        body = (item.body or "").strip()
        # Only IDs the CV really has count as evidence, each one once.
        evidence = list(dict.fromkeys(ref for ref in item.evidence if ref in cv_refs))
        if not body or (person_id is None and channel_id is None) or not evidence:
            continue
        subject: str | None = None
        if item.kind == "email":
            subject = (item.subject or "").strip() or title
        if candidate_name is not None:
            body = body.replace(NAME_PLACEHOLDER, candidate_name)
            if subject is not None:
                subject = subject.replace(NAME_PLACEHOLDER, candidate_name)
        actions.append(
            Action(
                id=action_id,
                kind=item.kind,
                title=title,
                why=why,
                person_id=person_id,
                channel_id=channel_id,
                draft=Draft(subject=subject, body=body, evidence=evidence),
            )
        )

    return actions
