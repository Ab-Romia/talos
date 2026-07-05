"""Single seam turning Message.content into plain text.

Content is a validated ProseMirror JSONB document (rich-msg); plain strings
are still accepted for bot/legacy callers. Every indexer/router/notification
call site goes through this module instead of touching the AST shape itself.
"""

__all__ = ["doc_text", "message_text"]


def _node_text(node: dict) -> str:
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "mention":
        label = (node.get("attrs") or {}).get("label", "")
        return f"@{label}" if label else ""
    if t == "reference":
        # channel/file/message links — keep the human-readable label so the
        # reference survives into indexed/notified text.
        label = (node.get("attrs") or {}).get("label", "")
        return label
    if t == "slash_command":
        command = (node.get("attrs") or {}).get("command", "")
        return f"/{command}" if command else ""
    children = node.get("content") or []
    sep = "\n" if t == "doc" else ""
    return sep.join(_node_text(c) for c in children)


def doc_text(content) -> str:
    """Plain text of a message content value (ProseMirror dict or plain str)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _node_text(content)
    return str(content)


def message_text(message) -> str:
    return doc_text(getattr(message, "content", None))
