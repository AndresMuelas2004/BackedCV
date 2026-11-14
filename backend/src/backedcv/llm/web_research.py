"""The web lookups of the deeper analysis: one model call that may search the web, and what it
found (the model's notes, every page it was shown and the passages it cited)."""

from typing import Any, Protocol

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backedcv.config import load
from backedcv.domain.models.research import Quote, Source, WebNotes
from backedcv.llm.prompt_loader import Prompt
from backedcv.llm.structured import MAX_TOKENS, LLMError, usage_record
from backedcv.settings import Settings

MAX_RESUMES = 2  # times a paused search turn is resumed before its notes are taken as they are


class WebSearcher(Protocol):
    async def search(
        self, prompt: Prompt, data: str, *, node: str, max_searches: int
    ) -> tuple[WebNotes, dict]: ...


def notes_from_content(content: Any) -> WebNotes:
    """What one search turn found, read from the content blocks of the model's answer."""
    if isinstance(content, str):
        return WebNotes(text=content.strip())
    texts: list[str] = []
    sources: dict[str, Source] = {}
    quotes: list[Quote] = []
    searches = 0
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
            for citation in block.get("citations") or []:
                url, cited = citation.get("url"), citation.get("cited_text")
                if url and cited:
                    quotes.append(Quote(url=url, text=cited))
                    sources.setdefault(url, Source(url=url, title=citation.get("title") or ""))
        elif block.get("type") == "web_search_tool_result":
            searches += 1
            results = block.get("content")
            # A failed search carries one error object instead of the list of results.
            for result in results if isinstance(results, list) else []:
                url = result.get("url") if isinstance(result, dict) else None
                if url:
                    sources.setdefault(url, Source(url=url, title=result.get("title") or ""))
    return WebNotes(
        text="".join(texts).strip(),
        sources=list(sources.values()),
        quotes=quotes,
        searches=searches,
    )


def merge_notes(first: WebNotes, second: WebNotes) -> WebNotes:
    """Two parts of one lookup as one: the texts in order, every page once."""
    sources = {source.url: source for source in [*first.sources, *second.sources]}
    return WebNotes(
        text="\n".join(text for text in (first.text, second.text) if text),
        sources=list(sources.values()),
        quotes=[*first.quotes, *second.quotes],
        searches=first.searches + second.searches,
    )


class AnthropicWebSearcher:
    """Asks Claude with Anthropic's web search tool, which runs on Anthropic's side."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def search(
        self, prompt: Prompt, data: str, *, node: str, max_searches: int
    ) -> tuple[WebNotes, dict]:
        config = load("models")
        tool = {
            "type": config["web_search"]["tool"],
            "name": "web_search",
            "max_uses": max_searches,
        }
        model = self.settings.model_fast
        chat = ChatAnthropic(
            model=model,
            max_tokens=MAX_TOKENS,
            max_retries=1,
            effort=config.get("effort", {}).get(prompt.id, "low"),
        ).bind_tools([tool])
        messages = [SystemMessage(prompt.text), HumanMessage(data)]
        run_config = {"run_name": node, "metadata": prompt.metadata, "tags": [prompt.id]}
        notes = WebNotes()
        usage = usage_record(node, model, None)
        for _ in range(MAX_RESUMES + 1):
            message = await chat.ainvoke(messages, config=run_config)
            notes = merge_notes(notes, notes_from_content(message.content))
            usage = _add_usage(usage, usage_record(node, model, message))
            reason = message.response_metadata.get("stop_reason")
            if reason == "refusal":
                raise LLMError(f"{node}: the model declined the request")
            if reason != "pause_turn":
                break
            # A paused turn goes on when the answer so far is sent back as it is.
            messages = [*messages, message]
        price = config["web_search"]["price_per_search"]
        usage["searches"] = notes.searches
        usage["cost_usd"] = round(usage["cost_usd"] + notes.searches * price, 6)
        return notes, usage


def _add_usage(total: dict, part: dict) -> dict:
    return {
        **total,
        "input_tokens": total["input_tokens"] + part["input_tokens"],
        "output_tokens": total["output_tokens"] + part["output_tokens"],
        "cost_usd": round(total["cost_usd"] + part["cost_usd"], 6),
    }
