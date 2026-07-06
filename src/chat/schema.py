"""
chat_schema  —  the single ProseMirror Schema instance for the whole app.

Import this wherever you need to parse, validate, or build a document:

    from .schema import chat_schema

Block nodes (standard ProseMirror + list extension):
    doc, paragraph, blockquote, heading, code_block,
    hard_break, bullet_list, ordered_list, list_item

Custom inline atoms:
    mention        @user  → attrs: user_id, label
    reference      #channel / file / message / external_url
                          → attrs: ref_type, ref_id, label, url
    slash_command  /cmd   → attrs: command, args

Marks (standard + extras):
    strong, em, underline, strike, code, link
"""

from prosemirror.model import Schema
from prosemirror.schema.basic import schema_basic
from prosemirror.schema.list import add_list_nodes

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

# Start from the basic spec and extend with list nodes
_nodes: dict = add_list_nodes(
    dict(schema_basic.nodes),
    item_content="paragraph block*",
    list_group="block",
)

# @user mention — inline atom, drives notification fanout
_nodes["mention"] = {
    "inline": True,
    "group": "inline",
    "atom": True,          # treated as a single unit by the editor
    "attrs": {
        "user_id": {},     # UUID string — also stored in mentioned_user_ids[]
        "label": {},       # display name at send time, denormalised for render speed
    },
}

# Generic entity pointer — channel, file, message, workspace, external URL
_nodes["reference"] = {
    "inline": True,
    "group": "inline",
    "atom": True,
    "attrs": {
        "ref_type": {},                # RefType enum value
        "ref_id":   {"default": None}, # UUID string; None for external_url
        "label":    {},                # human-readable label
        "url":      {"default": None}, # only for ref_type == "external_url"
    },
}

# Slash command — [OPEN] ephemeral by default; stripped server-side before save
_nodes["slash_command"] = {
    "inline": True,
    "group": "inline",
    "atom": True,
    "attrs": {
        "command": {},              # e.g. "remind", "giphy"
        "args":    {"default": {}}, # optional key-value args
    },
}

# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------

_marks = dict(schema_basic.marks)  # link, em, strong, code — already present

# ProseMirror basic uses "em" / "strong"; TipTap uses "italic" / "bold".
# We add the TipTap-style aliases so the frontend can use either convention.
_marks["italic"]    = {"attrs": {}, "parseDOM": [{"tag": "i"}, {"tag": "em"}]}
_marks["bold"]      = {"attrs": {}, "parseDOM": [{"tag": "b"}, {"tag": "strong"}]}
_marks["underline"] = {"attrs": {}, "parseDOM": [{"tag": "u"}]}
_marks["strike"]    = {"attrs": {}, "parseDOM": [{"tag": "s"}, {"tag": "del"}]}

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

chat_schema = Schema({"nodes": _nodes, "marks": _marks})