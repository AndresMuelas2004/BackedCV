"""Canned web lookups and research answers for tests: no network, no cost."""

from backedcv.domain.models.research import Quote, Source, WebNotes
from backedcv.llm.drafts_research import (
    ActionDraft,
    ChannelDraft,
    FactDraft,
    OutreachDraft,
    PersonDraft,
    ResearchExtractDraft,
)
from tests.fakes_optimize import FakeOptimizeLLM

TEAM_PAGE = "https://example-analytics.example/team"
PROFILE = "https://network.example/in/jane-roe"
CAREERS = "https://example-analytics.example/careers"


class FakeSearcher:
    """Answers each topic with canned notes; the topics in `failing` raise instead."""

    def __init__(self, failing: tuple[str, ...] = ()):
        self.failing = failing
        self.calls: list[tuple[str, str]] = []  # (node, data) of every search

    async def search(self, prompt, data, *, node, max_searches):
        self.calls.append((node, data))
        topic = node.removeprefix("research_")
        if topic in self.failing:
            raise RuntimeError("search failed")
        usage = {
            "node": node,
            "model": "fake",
            "input_tokens": 10,
            "output_tokens": 5,
            "cost_usd": 0.0,
            "cached": False,
            "searches": 1,
        }
        return _canned(topic), usage


def _canned(topic: str) -> WebNotes:
    if topic == "company":
        return WebNotes(
            text="Example Analytics builds dashboards.",
            sources=[Source(url="https://example-analytics.example", title="Example Analytics")],
            searches=1,
        )
    if topic == "team":
        return WebNotes(
            text="Jane Roe leads the data team.",
            sources=[
                Source(url=TEAM_PAGE, title="Team"),
                Source(url=PROFILE, title="Jane Roe - Head of Data - Example Analytics"),
            ],
            quotes=[Quote(url=TEAM_PAGE, text="Jane Roe, Head of Data")],
            searches=1,
        )
    return WebNotes(
        text="Jobs are listed on the careers page.",
        sources=[Source(url=CAREERS, title="Careers")],
        searches=1,
    )


EXTRACT = ResearchExtractDraft(
    company_name="Example Analytics",
    company_summary="Example Analytics builds dashboards.",
    facts=[
        FactDraft(
            label="Product",
            value="Dashboards for analysts.",
            source_url="https://example-analytics.example",
        )
    ],
    people=[
        PersonDraft(
            name="Jane Roe",
            role="Head of Data",
            group="hiring_team",
            why="She leads the team this role joins.",
            profile_url=PROFILE,
            source_url=TEAM_PAGE,
        ),
        # Invented: no page the searches returned shows him, so the checks drop him.
        PersonDraft(
            name="John Ghost",
            role="Recruiter",
            group="recruiting",
            why="He recruits for the company.",
            profile_url=None,
            source_url="https://nowhere.example/john",
        ),
    ],
    channels=[
        ChannelDraft(
            kind="careers_page",
            value=CAREERS,
            label="Careers page",
            source_url=CAREERS,
        )
    ],
    gaps=["No recruiter was found for this company."],
)

OUTREACH = OutreachDraft(
    actions=[
        ActionDraft(
            kind="apply",
            title="Apply on the careers page",
            why="It is the posting's own channel.",
            person_id=None,
            channel_id="C01",
            subject=None,
            body=None,
            evidence=[],
        ),
        ActionDraft(
            kind="connect",
            title="Connect with Jane Roe",
            why="She leads the team this role joins.",
            person_id="P01",
            channel_id=None,
            subject=None,
            body=(
                "Hello Jane, I build ETL pipelines in Python and SQL. I applied for the data "
                "engineer role. [Your name]"
            ),
            evidence=["L006"],
        ),
    ]
)


class FakeResearchLLM(FakeOptimizeLLM):
    """Answers the extract and the outreach; every other schema goes to the parent fakes."""

    async def run(self, prompt, data, schema, *, node):
        usage = {"node": node, "model": "fake", "input_tokens": 10, "output_tokens": 5}
        if schema is ResearchExtractDraft:
            self.calls.append(node)
            self.received.append((node, data))
            return EXTRACT, {**usage, "cost_usd": 0.0}
        if schema is OutreachDraft:
            self.calls.append(node)
            self.received.append((node, data))
            return OUTREACH, {**usage, "cost_usd": 0.0}
        return await super().run(prompt, data, schema, node=node)
