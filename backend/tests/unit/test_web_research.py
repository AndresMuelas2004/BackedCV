from backedcv.domain.models.research import Source, WebNotes
from backedcv.llm.web_research import merge_notes, notes_from_content

CONTENT = [
    {"type": "text", "text": "I will look this up."},
    {"type": "server_tool_use", "id": "t1", "name": "web_search", "input": {"query": "acme team"}},
    {
        "type": "web_search_tool_result",
        "tool_use_id": "t1",
        "content": [
            {"type": "web_search_result", "url": "https://acme.example/team", "title": "Team"},
            {"type": "web_search_result", "url": "https://acme.example/jobs", "title": "Jobs"},
        ],
    },
    {
        "type": "text",
        "text": " Jane Doe leads the data team.",
        "citations": [
            {
                "type": "web_search_result_location",
                "url": "https://acme.example/team",
                "title": "Team",
                "cited_text": "Jane Doe, Head of Data",
            }
        ],
    },
    {
        "type": "web_search_tool_result",
        "tool_use_id": "t2",
        "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"},
    },
]


def test_notes_hold_the_text_the_pages_and_the_cited_passages():
    notes = notes_from_content(CONTENT)

    assert notes.text == "I will look this up. Jane Doe leads the data team."
    assert [source.url for source in notes.sources] == [
        "https://acme.example/team",
        "https://acme.example/jobs",
    ]
    assert [(quote.url, quote.text) for quote in notes.quotes] == [
        ("https://acme.example/team", "Jane Doe, Head of Data")
    ]
    assert notes.searches == 2


def test_a_plain_string_answer_is_notes_without_pages():
    assert notes_from_content("  Nothing found. ") == WebNotes(text="Nothing found.")


def test_merged_notes_keep_every_page_once_and_add_the_searches():
    first = WebNotes(text="a", sources=[Source(url="https://x.example", title="X")], searches=1)
    second = WebNotes(text="b", sources=[Source(url="https://x.example", title="X")], searches=2)

    merged = merge_notes(first, second)

    assert (merged.text, len(merged.sources), merged.searches) == ("a\nb", 1, 3)
