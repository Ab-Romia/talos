"""message_text() is the single seam for Message.content -> str, so the
rich-msg branch (content: str -> ProseMirror JSONB dict) breaks nothing."""
from types import SimpleNamespace

from rag.message_text import message_text


def test_plain_string_content_passthrough():
    assert message_text(SimpleNamespace(content="hello world")) == "hello world"

def test_none_content_is_empty():
    assert message_text(SimpleNamespace(content=None)) == ""

def test_prosemirror_doc_extracts_text():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "hello "},
            {"type": "mention", "attrs": {"id": "u1", "label": "kiro"}},
        ]},
        {"type": "paragraph", "content": [{"type": "text", "text": "second line"}]},
    ]}
    assert message_text(SimpleNamespace(content=doc)) == "hello @kiro\nsecond line"
