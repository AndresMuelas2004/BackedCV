"""LLM-facing output schemas for the deeper analysis: what the web notes hold, and the plan.

Same strict-mode rules as drafts.py.
"""

from pydantic import BaseModel, Field

from backedcv.domain.models.research import ActionKind, ChannelKind, PersonGroup


class FactDraft(BaseModel):
    label: str = Field(
        description="What the fact is about, in 1-3 words: Size, Product, Funding, Tech stack, "
        "Offices, News."
    )
    value: str = Field(
        description="The fact in one plain sentence of at most 25 words, as the notes state it."
    )
    source_url: str = Field(
        description="The page address the notes give for this fact, copied exactly."
    )


class PersonDraft(BaseModel):
    name: str = Field(description="Full name, exactly as the notes state it.")
    role: str = Field(description="Job title and team at the company, as the notes state them.")
    group: PersonGroup = Field(
        description="posting_owner: the person who published or owns this posting. hiring_team: "
        "the manager, the lead or the members of the team the role joins. recruiting: recruiters, "
        "talent acquisition and HR. leadership: founders and heads of the area. peer: people in "
        "the same or a similar role."
    )
    why: str = Field(
        description="For the user, in English: one plain sentence of at most 20 words on why this "
        "person matters for this application."
    )
    profile_url: str | None = Field(
        description="The address of the person's public professional profile, copied exactly "
        "from the notes; null when the notes give none."
    )
    source_url: str = Field(
        description="The page address the notes give as showing this person at the company, "
        "copied exactly."
    )


class ChannelDraft(BaseModel):
    kind: ChannelKind = Field(
        description="email: an email address. application: the page or form where this job is "
        "applied for. careers_page: the company's jobs page. company_profile: the company's page "
        "on a professional network. other: any other way to reach the company."
    )
    value: str = Field(
        description="The email address or the link, copied exactly from the notes or from the "
        "posting."
    )
    label: str = Field(description="For the user, in English: what it is, in at most 8 words.")
    source_url: str | None = Field(
        description="The page address the notes give for it, copied exactly; null when the "
        "posting itself shows it."
    )


class ResearchExtractDraft(BaseModel):
    company_name: str | None = Field(
        description="The company's name as its own pages write it; null when unknown."
    )
    company_summary: str = Field(
        description="For the user, in English: 2-4 plain sentences on what the company does and "
        "what matters for someone applying to this job. Only what the notes state. Empty when the "
        "notes say nothing about the company."
    )
    facts: list[FactDraft] = Field(
        description="At most 8 facts about the company, the most useful for this application first."
    )
    people: list[PersonDraft] = Field(
        description="At most 12 people, the most useful first. Never the same person twice."
    )
    channels: list[ChannelDraft] = Field(
        description="At most 8 ways to reach the company or to apply. Never the same one twice."
    )
    gaps: list[str] = Field(
        description="For the user, in English: what was looked for and not found, one short plain "
        "sentence each, at most 5."
    )


class ActionDraft(BaseModel):
    kind: ActionKind = Field(
        description="apply: send the application. connect: a connection request on a professional "
        "network. message: a direct message to someone the candidate can already write to. email: "
        "an email. follow: follow the company or a person."
    )
    title: str = Field(
        description="For the user, in English: the step in at most 10 words, starting with a verb."
    )
    why: str = Field(
        description="For the user, in English: one plain sentence of at most 25 words on why this "
        "step helps."
    )
    person_id: str | None = Field(
        description="The ID (P..) of the person the step is about; null when it is about no one."
    )
    channel_id: str | None = Field(
        description="The ID (C..) of the channel the step uses; null when it uses none."
    )
    subject: str | None = Field(
        description="The subject line, for kind email only; null otherwise."
    )
    body: str | None = Field(
        description="The ready-to-send text for connect, message and email, in the language of the "
        "posting; null for apply and follow."
    )
    evidence: list[str] = Field(
        description="IDs of the CV lines (L...) and facts (F...) that show everything the text "
        "says about the candidate. Empty when there is no text."
    )


class OutreachDraft(BaseModel):
    actions: list[ActionDraft] = Field(description="At most 6 steps, in the order to do them.")
