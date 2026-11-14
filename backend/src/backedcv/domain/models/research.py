"""What a deeper look at one job posting found: the company, the people behind the posting, ways
to reach them and a plan with drafts. Every person and address names the page it came from."""

from typing import Literal

from pydantic import BaseModel, Field

PersonGroup = Literal["posting_owner", "hiring_team", "recruiting", "leadership", "peer"]
ChannelKind = Literal["email", "application", "careers_page", "company_profile", "other"]
ActionKind = Literal["apply", "connect", "message", "email", "follow"]


class Source(BaseModel):
    url: str
    title: str = ""


class Quote(BaseModel):
    """A passage of a page, as a search result showed it and the model cited it."""

    url: str
    text: str


class WebNotes(BaseModel):
    """What one web lookup found."""

    text: str = ""  # the model's notes
    sources: list[Source] = Field(default_factory=list)  # every page the searches returned
    quotes: list[Quote] = Field(default_factory=list)  # the passages the notes cite
    searches: int = 0


class CompanyFact(BaseModel):
    label: str
    value: str
    source_url: str


class CompanyBrief(BaseModel):
    name: str | None = None
    summary: str = ""
    facts: list[CompanyFact] = Field(default_factory=list)


class Person(BaseModel):
    id: str  # P01, P02, ...
    name: str
    role: str
    group: PersonGroup
    why: str
    profile_url: str | None = None
    source_url: str


class Channel(BaseModel):
    id: str  # C01, C02, ...
    kind: ChannelKind
    value: str  # the email address or the link
    label: str
    source_url: str | None = None  # None: the posting itself shows it


class Draft(BaseModel):
    subject: str | None = None
    body: str
    evidence: list[str] = Field(default_factory=list)  # CV line and fact IDs the text relies on


class Action(BaseModel):
    id: str  # A01, A02, ...
    kind: ActionKind
    title: str
    why: str
    person_id: str | None = None
    channel_id: str | None = None
    draft: Draft | None = None


class ResearchReport(BaseModel):
    company: CompanyBrief = Field(default_factory=CompanyBrief)
    people: list[Person] = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # what was not found or was left out
    sources: list[Source] = Field(default_factory=list)
    searches: int = 0
    created_at: str = ""
