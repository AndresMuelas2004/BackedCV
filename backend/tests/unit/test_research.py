"""The checks on a deeper analysis: people, facts, addresses and links must be shown by a page the
searches returned or by the posting; messages must cite CV lines."""

from backedcv.domain.models.cv import Contact, ContactField, CVLine, ParsedCV
from backedcv.domain.models.research import Channel, Person, Quote, Source, WebNotes
from backedcv.domain.research import assemble, clean_url, plan_actions
from backedcv.llm.drafts_research import (
    ActionDraft,
    ChannelDraft,
    FactDraft,
    OutreachDraft,
    PersonDraft,
    ResearchExtractDraft,
)

SRC = "https://acme.example/team"
JOB = (
    "Backend engineer at Acme. Apply at https://acme.example/jobs/42 "
    "or write to hiring@acme.example."
)


def person(name: str, source_url: str = SRC, profile_url: str | None = None) -> PersonDraft:
    return PersonDraft(
        name=name,
        role="Engineer",
        group="peer",
        why="Works on the team.",
        profile_url=profile_url,
        source_url=source_url,
    )


def extract(
    people: list[PersonDraft] | None = None,
    channels: list[ChannelDraft] | None = None,
    facts: list[FactDraft] | None = None,
) -> ResearchExtractDraft:
    return ResearchExtractDraft(
        company_name="Acme",
        company_summary="Makes things.",
        facts=facts or [],
        people=people or [],
        channels=channels or [],
        gaps=[],
    )


def notes(quotes: list[Quote] | None = None, title: str = "Jane Doe - Acme engineering team"):
    return [WebNotes(sources=[Source(url=SRC, title=title)], quotes=quotes or [])]


def test_clean_url_compares_without_case_www_fragment_or_trailing_slash():
    assert clean_url("HTTPS://WWW.Acme.Example/Team/#people") == clean_url(
        "https://acme.example/Team"
    )


def test_person_named_in_the_title_of_the_source_is_kept():
    found = assemble(extract([person("Jane Doe")]), notes(), JOB)

    assert [p.id for p in found.people] == ["P01"]
    assert found.people[0].name == "Jane Doe"


def test_person_named_only_in_a_quote_of_the_source_is_kept():
    quote = Quote(url=SRC, text="Maria Lopez leads the platform team at Acme.")
    found = assemble(
        extract([person("Maria Lopez")]), notes(quotes=[quote], title="Acme team"), JOB
    )

    assert [p.name for p in found.people] == ["Maria Lopez"]


def test_person_from_an_unreturned_page_is_left_out_and_counted():
    found = assemble(extract([person("Jane Doe", "https://other.example/x")]), notes(), JOB)

    assert found.people == []
    assert found.notes[-1] == "1 person was left out because no page from the searches shows them."


def test_person_whose_name_no_shown_text_has_is_left_out():
    found = assemble(extract([person("Carlos Ruiz")]), notes(), JOB)

    assert found.people == []
    assert found.notes == ["1 person was left out because no page from the searches shows them."]


def test_unreturned_profile_url_becomes_none_and_person_is_kept():
    profile = "https://linkedin.example/in/jane"
    found = assemble(extract([person("Jane Doe", profile_url=profile)]), notes(), JOB)

    assert len(found.people) == 1
    assert found.people[0].profile_url is None


def test_email_in_posting_has_no_source_and_invented_email_is_left_out():
    channels = [
        ChannelDraft(kind="email", value="hiring@acme.example", label="Hiring", source_url=None),
        ChannelDraft(kind="email", value="ghost@acme.example", label="Guess", source_url=None),
    ]
    found = assemble(extract(channels=channels), notes(), JOB)

    assert [(c.value, c.source_url) for c in found.channels] == [("hiring@acme.example", None)]
    assert found.notes == ["1 address or link was left out because no page shows it."]


def test_email_in_a_quote_takes_that_page_as_source():
    quote = Quote(url=SRC, text="Press enquiries: press@acme.example")
    channels = [
        ChannelDraft(kind="email", value="press@acme.example", label="Press", source_url=None)
    ]
    found = assemble(extract(channels=channels), notes(quotes=[quote]), JOB)

    assert [(c.value, c.source_url) for c in found.channels] == [("press@acme.example", SRC)]


def test_link_is_kept_only_when_posting_or_a_search_shows_it():
    channels = [
        ChannelDraft(
            kind="application",
            value="https://acme.example/jobs/42",
            label="Apply",
            source_url=None,
        ),
        ChannelDraft(kind="other", value="https://evil.example/x", label="Other", source_url=None),
        ChannelDraft(
            kind="company_profile",
            value="https://acme.example/team/",
            label="Team page",
            source_url=SRC,
        ),
    ]
    found = assemble(extract(channels=channels), notes(), JOB)

    assert [c.value for c in found.channels] == [
        "https://acme.example/jobs/42",
        "https://acme.example/team/",
    ]


def test_fact_with_unknown_source_is_left_out():
    facts = [
        FactDraft(label="Size", value="About 200 staff.", source_url=SRC),
        FactDraft(label="Funding", value="Series B.", source_url="https://unknown.example/"),
    ]
    found = assemble(extract(facts=facts), notes(), JOB)

    assert [f.label for f in found.company.facts] == ["Size"]


def test_same_person_twice_is_kept_once():
    found = assemble(extract([person("Jane Doe"), person("JANE DOE")]), notes(), JOB)

    assert [p.id for p in found.people] == ["P01"]


def _cv() -> ParsedCV:
    return ParsedCV(
        lines=[
            CVLine(id="L001", text="Jane Doe"),
            CVLine(id="L002", text="Built ETL pipelines in Python"),
        ],
        contact=Contact(name=ContactField(value="Jane Doe", line_id="L001")),
    )


def _action(**fields) -> ActionDraft:
    base = {
        "kind": "message",
        "title": "Write to the lead",
        "why": "The lead owns the team.",
        "person_id": None,
        "channel_id": None,
        "subject": None,
        "body": None,
        "evidence": [],
    }
    return ActionDraft(**(base | fields))


def _people() -> list[Person]:
    return [
        Person(
            id="P01",
            name="Maria Lopez",
            role="Lead",
            group="hiring_team",
            why="Leads the team.",
            source_url=SRC,
        )
    ]


def test_plan_keeps_apply_without_draft_and_numbers_kept_steps_in_order():
    draft = OutreachDraft(
        actions=[
            _action(kind="apply", title="Apply on the posting"),
            _action(
                kind="message",
                person_id="P99",
                body="Hi, I am [Your name].",
                evidence=["L002"],
            ),
            _action(
                kind="message",
                person_id="P01",
                body="Hi, I am [Your name].",
                evidence=["L999"],
            ),
            _action(
                kind="message",
                person_id="P01",
                body="Hi Maria, I am [Your name]. I built ETL pipelines in Python.",
                evidence=["L002"],
            ),
            _action(
                kind="email",
                channel_id="C01",
                title="Ask about the role",
                body="Hello, I am [Your name].",
                evidence=["L002"],
            ),
        ]
    )
    channels = [Channel(id="C01", kind="email", value="hiring@acme.example", label="Hiring")]
    actions = plan_actions(draft, _people(), channels, _cv())

    assert [a.id for a in actions] == ["A01", "A02", "A03"]
    assert actions[0].draft is None
    assert actions[1].draft is not None
    assert actions[1].draft.body == "Hi Maria, I am Jane Doe. I built ETL pipelines in Python."
    assert actions[1].draft.evidence == ["L002"]
    assert actions[2].draft is not None
    assert actions[2].draft.subject == "Ask about the role"
