"""Single seam turning Message.content into plain text.

Today content is a plain str. The rich-msg branch converts it to a
ProseMirror JSONB document; this helper already extracts text from that
shape, so when rich-msg lands only this file needs review, not every
indexer/router call site.
"""

__all__ = ["message_text"]


def _node_text(node: dict) -> str:
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "mention":
        label = (node.get("attrs") or {}).get("label", "")
        return f"@{label}" if label else ""
    children = node.get("content") or []
    sep = "\n" if t == "doc" else ""
    return sep.join(_node_text(c) for c in children)


def message_text(message) -> str:
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _node_text(content)
    return str(content)
