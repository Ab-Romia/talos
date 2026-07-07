#!/usr/bin/env python3
"""Generate the remaining Talos-documentation figures (reusing the SVG toolkit
from gen_message_figures.py):

  thread_recursive_cte.svg      — 9.1.3  recursive-CTE thread assembly
  message_delivery_fanout.svg   — 9.1.4  Socket.IO delivery fan-out
  search_jsonb_vs_ilike.svg     — 11.x   JSONB tree vs serialized ILIKE string
  search_two_query_lifecycle.svg— 11.3   two-query (COUNT then SELECT) lifecycle
  future_image_search.svg       — future multimodal search branch
  future_scaled_ai_serving.svg  — future scaled AI-serving architecture

Figures follow the code where it exists (src/chat/*: reply_to_id, store_message,
search.py's ILIKE cast + COUNT/SELECT) and the documented design otherwise.
"""
import gen_message_figures as gm

SVG = gm.SVG
SERIF, MONO = gm.SERIF, gm.MONO
INK, SUB, NOTE, STROKE, HAIR = gm.INK, gm.SUB, gm.NOTE, gm.STROKE, gm.HAIR
esc = gm.esc

# accent palette: (line, tint)
BLUE = ("#3e6fb0", "#eaf1fb")
TEAL = ("#2c8c9a", "#e7f2f4")
AMBER = ("#c4913a", "#fbf2de")
GREEN = ("#2e7d46", "#e6f3ea")
PURPLE = ("#5a46a8", "#eeeaf8")
ROSE = ("#c23b6b", "#fbe7ef")
GREY = ("#6b7480", "#eef0f3")
SLATE = "#3b4250"


def node(s, x, y, w, h, title, sub=None, acc=None, tint="#ffffff", tfam=MONO, tsize=12.5):
    stroke = acc[0] if acc else STROKE
    s.rect(x, y, w, h, fill=tint, stroke=stroke, sw=1.5, rx=9)
    if sub:
        s.text(x + w / 2, y + h / 2 - 3, title, tsize, fill=INK, family=tfam, weight="bold", anchor="middle")
        s.text(x + w / 2, y + h / 2 + 13, sub, 9.5, fill=SUB, family=SERIF, anchor="middle")
    else:
        s.text(x + w / 2, y + h / 2 + 4, title, tsize, fill=INK, family=tfam, weight="bold", anchor="middle")
    return (x + w / 2, y + h / 2)


def hbar(s, x, y, w, h, title, acc, tint="#ffffff"):
    s.rect(x, y, w, h, fill=tint, stroke=acc[0], sw=1.6, rx=10)
    s.rect(x, y, w, 26, fill=acc[1], rx=10)
    s.rect(x, y + 14, w, 12, fill=acc[1])
    s.text(x + 13, y + 18, title, 12, fill=INK, family=MONO, weight="bold")


def arrow(s, x1, y1, x2, y2, color=STROKE, label=None, dash=None, sw=1.5):
    s.line(x1, y1, x2, y2, stroke=color, sw=sw, dash=dash, arrow=True)
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        w = len(label) * 5.6 + 10
        s.rect(mx - w / 2, my - 17, w, 15, fill="#ffffff", opacity=0.92, rx=3)
        s.text(mx, my - 6, label, 9.2, fill="#404757", family=SERIF, anchor="middle")


def stagelabel(s, x, y, text, color=INK):
    s.text(x, y, text, 12, fill=color, family=SERIF, weight="bold")


# =============================================================================
# 3 — Recursive CTE thread assembly
# =============================================================================
def fig_thread_cte():
    s = SVG(1180, 616)

    # SQL box
    sx, sy, sw = 60, 44, 1060
    s.rect(sx, sy, sw, 132, fill="#fbfbfa", stroke=PURPLE[0], sw=1.6, rx=10)
    s.rect(sx, sy, sw, 26, fill=PURPLE[1], rx=10)
    s.rect(sx, sy + 14, sw, 12, fill=PURPLE[1])
    s.text(sx + 13, sy + 18, "get_thread()  —  single recursive CTE, one round-trip at any depth", 12,
           fill=INK, family=MONO, weight="bold")
    sql = [
        "WITH RECURSIVE thread AS (",
        "    SELECT * FROM messages WHERE id = :root_id            -- anchor (base case)",
        "  UNION ALL",
        "    SELECT m.* FROM messages m",
        "    JOIN thread t ON m.reply_to_id = t.id                 -- recurse on the self-FK",
        ")  SELECT * FROM thread;",
    ]
    yy = sy + 44
    for ln in sql:
        s.text(sx + 20, yy, ln, 10.5, fill="#33405a", family=MONO)
        yy += 15

    # 4 stages
    top = 236
    s.line(60, top - 16, 1120, top - 16, stroke="#e9ebef", sw=1)
    colw = 250
    xs = [60, 60 + 285, 60 + 285 * 2, 60 + 285 * 2 + 300]

    # ① anchor
    stagelabel(s, xs[0], top + 4, "① Anchor")
    node(s, xs[0] + 70, top + 24, 110, 44, "M1", "root", acc=PURPLE, tint=PURPLE[1])
    s.text(xs[0] + 4, top + 96, "SELECT the root", 9.6, fill=SUB, family=SERIF)
    s.text(xs[0] + 4, top + 110, "message row.", 9.6, fill=SUB, family=SERIF)

    # ② union passes (tree growing)
    stagelabel(s, xs[1], top + 4, "② Union passes")
    tx = xs[1] + 40
    node(s, tx + 60, top + 22, 70, 34, "M1", acc=PURPLE, tint=PURPLE[1], tsize=11)
    node(s, tx, top + 78, 70, 34, "M2", acc=BLUE, tint=BLUE[1], tsize=11)
    node(s, tx + 120, top + 78, 70, 34, "M3", acc=BLUE, tint=BLUE[1], tsize=11)
    node(s, tx, top + 134, 70, 34, "M4", acc=TEAL, tint=TEAL[1], tsize=11)
    s.line(tx + 95, top + 56, tx + 35, top + 78, stroke=STROKE, sw=1.2)
    s.line(tx + 95, top + 56, tx + 155, top + 78, stroke=STROKE, sw=1.2)
    s.line(tx + 35, top + 112, tx + 35, top + 134, stroke=STROKE, sw=1.2)
    s.text(xs[1], top + 184, "each UNION ALL pass adds one depth level;",
           9, fill=NOTE, family=SERIF, italic=True)
    s.text(xs[1], top + 198, "stop when a pass returns 0 rows.",
           9, fill=NOTE, family=SERIF, italic=True)

    # ③ flat result
    stagelabel(s, xs[2], top + 4, "③ Flat result set")
    fr = ["id  reply_to_id", "M1   ∅", "M2   M1", "M3   M1", "M4   M2"]
    s.rect(xs[2], top + 20, 200, 150, fill="#ffffff", stroke=HAIR, sw=1.4, rx=8)
    yy = top + 42
    for i, ln in enumerate(fr):
        s.text(xs[2] + 16, yy, ln, 10.5, fill=(INK if i == 0 else "#33405a"), family=MONO,
               weight=("bold" if i == 0 else None))
        if i == 0:
            s.line(xs[2] + 10, yy + 6, xs[2] + 190, yy + 6, stroke="#e9ebef", sw=1)
        yy += 26 if i == 0 else 22
    s.text(xs[2], top + 190, "n rows, unordered — one query.", 9.6, fill=SUB, family=SERIF)

    # ④ Python tree assembly
    stagelabel(s, xs[3], top + 4, "④ Python tree — O(n)")
    s.rect(xs[3], top + 20, 250, 150, fill=GREEN[1], stroke=GREEN[0], sw=1.5, rx=8)
    tree = ["index rows by id → {id: node}", "wire each non-root into", "parent.children:", "",
            "M1", " ├─ M2", " │   └─ M4", " └─ M3"]
    yy = top + 40
    for ln in tree:
        mono = ln.strip().startswith(("M", "│", "├", "└")) or "M1" in ln
        s.text(xs[3] + 16, yy, ln, 10 if not mono else 11,
               fill=("#2c6b3f" if not mono else INK),
               family=(SERIF if not mono else MONO), italic=(not mono and ln != ""))
        yy += 15 if ln == "" else (16 if mono else 15)

    # arrows between stages
    ay = top + 60
    arrow(s, xs[0] + 190, ay, xs[1] + 30, ay, color=STROKE)
    arrow(s, xs[1] + 235, ay, xs[2] - 6, ay, color=STROKE)
    arrow(s, xs[2] + 202, ay, xs[3] - 6, ay, color=STROKE)

    s.line(60, 592, 1120, 592, stroke="#e9ebef", sw=1)
    s.text(60, 610, "The recursive CTE runs entirely in Postgres (one round-trip regardless of depth); "
                    "the flat rows are then assembled into a nested reply tree in a single O(n) Python pass.",
           9.8, fill=SUB, family=SERIF, italic=True)
    s.save("thread_recursive_cte.svg")


# =============================================================================
# 4 — Message delivery fan-out
# =============================================================================
def fig_fanout():
    s = SVG(1180, 600)

    # sender + two entry paths
    node(s, 60, 250, 150, 66, "Sender", "web · mobile · script", acc=BLUE, tint=BLUE[1], tfam=SERIF, tsize=13)
    node(s, 250, 190, 210, 46, "message  event", "Socket.IO", acc=GREY, tint=GREY[1], tsize=11.5)
    node(s, 250, 300, 210, 46, "POST /messages", "REST", acc=GREY, tint=GREY[1], tsize=11.5)
    arrow(s, 210, 274, 250, 213, color=STROKE)
    arrow(s, 210, 292, 250, 323, color=STROKE)

    # store_message (shared)
    hbar(s, 500, 214, 210, 118, "store_message()", GREEN)
    for i, ln in enumerate(["validate (MessageCreateSchema)", "persist → set_content()",
                            "extract mentioned_user_ids"]):
        s.text(510, 250 + i * 20, "· " + ln, 9.6, fill="#2c6b3f", family=SERIF)
    s.text(605, 320, "one shared service", 9, fill=NOTE, family=SERIF, italic=True, anchor="middle")
    arrow(s, 460, 213, 500, 250, color=STROKE)
    arrow(s, 460, 323, 500, 290, color=STROKE)

    # fan-out targets
    # channel room
    hbar(s, 800, 90, 320, 150, "room  channel:{id}", BLUE)
    s.text(812, 122, "sio.send(payload, skip_sid=sender)", 10, fill="#33405a", family=MONO)
    s.text(812, 138, "broadcast to every subscriber — except", 9.6, fill=SUB, family=SERIF)
    s.text(812, 151, "the sender (they already have it).", 9.6, fill=SUB, family=SERIF)
    node(s, 812, 168, 90, 56, "member", "online", acc=GREY, tint="#ffffff", tfam=SERIF, tsize=10.5)
    node(s, 912, 168, 90, 56, "member", "online", acc=GREY, tint="#ffffff", tfam=SERIF, tsize=10.5)
    node(s, 1012, 168, 96, 56, "sender", "skipped", acc=ROSE, tint=ROSE[1], tfam=SERIF, tsize=10.5)

    # personal rooms (mentions)
    hbar(s, 800, 268, 320, 132, "room  user:{uid}   (per mention)", AMBER)
    s.text(812, 300, "flag-modified payload → personal room", 10, fill="#33405a", family=MONO)
    s.text(812, 316, "of each mentioned user (notification).", 9.6, fill=SUB, family=SERIF)
    node(s, 812, 332, 140, 52, "@Kyria", "user:019f…", acc=AMBER, tint=AMBER[1], tfam=SERIF, tsize=11)
    node(s, 962, 332, 146, 52, "@Mohab", "user:019f…", acc=AMBER, tint=AMBER[1], tfam=SERIF, tsize=11)

    # ack back to sender
    arrow(s, 710, 250, 800, 165, color=BLUE[0], label="broadcast")
    arrow(s, 710, 300, 800, 320, color=AMBER[0], label="notify mentions")
    s.line(605, 332, 605, 470, stroke=GREEN[0], sw=1.4, dash="4 4")
    s.line(135, 470, 605, 470, stroke=GREEN[0], sw=1.4, dash="4 4")
    s.line(135, 470, 135, 316, stroke=GREEN[0], sw=1.4, dash="4 4")
    s._tri(135, 316, 0, -1, GREEN[0])
    s.rect(300, 462, 150, 16, fill="#ffffff", opacity=0.92, rx=3)
    s.text(375, 474, "ack { delivered_to }", 9.4, fill="#2c6b3f", family=MONO, anchor="middle")

    s.line(60, 520, 1120, 520, stroke="#e9ebef", sw=1)
    s.text(60, 540, "Both transports converge on the single store_message service, then one message event is multiplexed: "
                    "the standard payload broadcasts to the channel room (sender skipped),", 9.8, fill=SUB, family=SERIF, italic=True)
    s.text(60, 555, "while flag-modified copies are emitted to the personal room of each mentioned user — unifying the "
                    "client's event handlers. (@Talos mentions additionally trigger maybe_ai_reply.)", 9.8, fill=SUB, family=SERIF, italic=True)
    s.save("message_delivery_fanout.svg")


# =============================================================================
# 5 — JSONB tree vs serialized ILIKE string
# =============================================================================
def fig_search_ilike():
    s = SVG(1180, 640)

    s.text(60, 40, "A message:", 11, fill=NOTE, family=SERIF, weight="bold")
    s.text(150, 40, "“Hey @Kyria, see the report”", 12, fill=INK, family=SERIF, italic=True)

    # left: JSONB tree
    hbar(s, 60, 64, 470, 300, "content  —  JSONB document tree", TEAL)
    tree = [
        ("doc", 0, "struct"),
        ("paragraph", 1, "struct"),
        ('text  "Hey "', 2, "user"),
        ('mention  {user_id:"019f…", label:"Kyria"}', 2, "mix"),
        ('text  ", see the report"', 2, "user"),
    ]
    yy = 108
    for label, depth, kind in tree:
        x = 84 + depth * 26
        col = TEAL if kind == "user" else (GREY if kind == "struct" else AMBER)
        s.rect(x, yy - 15, 8, 8, fill=col[0], rx=2)
        s.text(x + 16, yy - 8, label, 11, fill=INK, family=MONO)
        if depth > 0:
            s.line(x - 13, yy - 26, x - 13, yy - 8, stroke=HAIR, sw=1.2)
            s.line(x - 13, yy - 11, x, yy - 11, stroke=HAIR, sw=1.2)
        yy += 34
    s.text(84, 340, "Structural nodes/attrs vs. user-visible text values.", 9.6, fill=SUB, family=SERIF, italic=True)

    # right: serialized string
    hbar(s, 560, 64, 560, 300, "content::text  —  what ILIKE '%q%' scans", ROSE)
    # token stream with colouring: (text, kind)  kind: struct/user/uuid
    tokens = [
        ('{"type":', "s"), ('"doc"', "s"), (',"content":[{"type":', "s"), ('"paragraph"', "s"),
        (',"content":[', "s"), ('{"type":"text","text":', "s"), ('"Hey "', "u"), ("},", "s"),
        ('{"type":"mention","attrs":', "s"), ('{"user_id":', "s"), ('"019f2e1d-…"', "id"),
        (',"label":', "s"), ('"Kyria"', "u"), ("}},", "s"), ('{"type":"text","text":', "s"),
        ('", see the report"', "u"), ("}]}]}", "s"),
    ]
    colmap = {"s": ("#8a3b57", ROSE[1]), "u": ("#2c6b3f", GREEN[1]), "id": ("#7a5a10", AMBER[1])}
    x, y = 578, 104
    maxx = 1100
    for tok, kind in tokens:
        w = len(tok) * 6.9 + 6
        if x + w > maxx:
            x = 578
            y += 26
        c = colmap[kind]
        s.rect(x, y - 14, w, 20, fill=c[1], rx=3)
        s.text(x + 3, y, tok, 10.5, fill=c[0], family=MONO)
        x += w + 3
    # legend for string colours
    ly = y + 40
    for (lab, c) in [("structural (node types, keys, attrs)", ("#8a3b57", ROSE[1])),
                     ("user-visible text", ("#2c6b3f", GREEN[1])),
                     ("UUID (mention user_id)", ("#7a5a10", AMBER[1]))]:
        s.rect(578, ly - 11, 14, 14, fill=c[1], stroke=c[0], sw=1.2, rx=3)
        s.text(598, ly, lab, 10, fill=INK, family=SERIF)
        ly += 22

    # risk callouts
    ry = 400
    s.rect(60, ry, 530, 150, fill=ROSE[1], stroke=ROSE[0], sw=1.5, rx=10)
    s.text(78, ry + 26, "False positives", 12.5, fill="#8a3b57", family=SERIF, weight="bold")
    for i, ln in enumerate([
        "Query “text”, “paragraph”, or “mention” matches the",
        "structural node-type tokens — it hits every message.",
        "A UUID fragment matches mention user_id / attrs, not",
        "anything the reader ever typed.",
    ]):
        s.text(78, ry + 50 + i * 20, ln, 10.4, fill=INK, family=SERIF)

    s.rect(610, ry, 510, 150, fill=AMBER[1], stroke=AMBER[0], sw=1.5, rx=10)
    s.text(628, ry + 26, "False negatives", 12.5, fill="#8a6420", family=SERIF, weight="bold")
    for i, ln in enumerate([
        "User-visible text is split across sibling nodes, so a phrase",
        "that spans a mention or line break is not contiguous in the",
        "string: searching “Kyria,” fails — “Kyria” is a mention label",
        "and “,” starts the next text node.",
    ]):
        s.text(628, ry + 50 + i * 20, ln, 10.4, fill=INK, family=SERIF)

    s.text(60, 600, "Casting the whole JSONB doc to text and matching with ILIKE is simple and index-light, but it "
                    "conflates structure with content —", 9.8, fill=SUB, family=SERIF, italic=True)
    s.text(60, 615, "the source of both false positives (structural tokens) and false negatives (text fragmented "
                    "across nodes).", 9.8, fill=SUB, family=SERIF, italic=True)
    s.save("search_jsonb_vs_ilike.svg")


# =============================================================================
# 6 — Two-query search lifecycle
# =============================================================================
def fig_search_lifecycle():
    s = SVG(1180, 560)

    # client
    node(s, 60, 210, 160, 70, "Client", "GET /messages/search", acc=BLUE, tint=BLUE[1], tfam=SERIF, tsize=13)
    s.text(140, 300, "?q=report&page=2", 9.6, fill=SUB, family=MONO, anchor="middle")
    s.text(140, 314, "&page_size=20", 9.6, fill=SUB, family=MONO, anchor="middle")

    # router (in)
    hbar(s, 270, 200, 210, 96, "router  (in)", GREY)
    s.text(280, 232, "page 2, page_size 20", 10, fill=INK, family=MONO)
    s.text(280, 252, "→ offset = (2-1)·20 = 20", 10, fill="#33405a", family=MONO)
    s.text(280, 268, "→ limit  = 20", 10, fill="#33405a", family=MONO)
    s.text(280, 286, "page arithmetic stays here", 9, fill=NOTE, family=SERIF, italic=True)
    arrow(s, 220, 245, 270, 245, color=STROKE)

    # service + postgres (two queries)
    hbar(s, 540, 150, 250, 210, "search_messages()", GREEN)
    node(s, 556, 190, 218, 62, "① COUNT(*)", "over filtered set → total = 137", acc=GREEN, tint="#ffffff", tsize=11.5)
    s.rect(556, 264, 218, 80, fill="#ffffff", stroke=GREEN[0], sw=1.5, rx=9)
    s.text(665, 286, "② SELECT …", 11.5, fill=INK, family=MONO, weight="bold", anchor="middle")
    s.text(665, 305, "WHERE filters", 9.2, fill="#33405a", family=MONO, anchor="middle")
    s.text(665, 320, "ORDER BY sent_at DESC", 9.2, fill="#33405a", family=MONO, anchor="middle")
    s.text(665, 335, "LIMIT 20 OFFSET 20", 9.2, fill="#33405a", family=MONO, anchor="middle")
    arrow(s, 480, 245, 540, 245, color=STROKE, label="offset / limit")

    # postgres cylinder
    px = 840
    s.path(f"M{px},{175} A55,13 0 0 1 {px+110},{175} L{px+110},{330} A55,13 0 0 1 {px},{330} Z",
           fill=TEAL[1], stroke=TEAL[0], sw=1.6)
    s.path(f"M{px},{175} A55,13 0 0 0 {px+110},{175}", fill="none", stroke=TEAL[0], sw=1.6)
    s.text(px + 55, 210, "Postgres", 12.5, fill=INK, family=MONO, weight="bold", anchor="middle")
    s.text(px + 55, 232, "messages", 10, fill=SUB, family=MONO, anchor="middle")
    arrow(s, 774, 221, px, 221, color=TEAL[0], label="count")
    arrow(s, 774, 303, px, 300, color=TEAL[0], label="fetch")

    # router (out) envelope
    hbar(s, 60, 380, 1060, 120, "router  (out)  —  reproject + assemble response envelope", BLUE)
    s.text(74, 412, "MessageSchema[]  →  ChatMessageResponse[]", 10.5, fill="#33405a", family=MONO)
    s.text(74, 430, "(internal model never leaks; content passed through as raw ProseMirror JSON)", 9.6, fill=SUB, family=SERIF)
    env = "{ results:[…20], page:2, page_size:20, total:137, total_pages:7, has_next:true, has_previous:true }"
    s.rect(74, 444, 1030, 40, fill="#ffffff", stroke=HAIR, sw=1.3, rx=6)
    s.text(90, 468, env, 10.5, fill=INK, family=MONO)
    arrow(s, 665, 360, 665, 380, color=STROKE)

    s.text(60, 528, "Two round-trips (COUNT then SELECT) instead of a COUNT(*) OVER() window — chosen for readability, at "
                    "the cost of one extra query and a small", 9.8, fill=SUB, family=SERIF, italic=True)
    s.text(60, 543, "consistency window: a message inserted between the two queries can shift a page boundary by one row "
                    "(accepted for channel-history search).", 9.8, fill=SUB, family=SERIF, italic=True)
    s.save("search_two_query_lifecycle.svg")


# =============================================================================
# 7 — Future: multimodal (image) search branch
# =============================================================================
def fig_image_search():
    s = SVG(1180, 520)

    # current text lane
    s.rect(48, 70, 1084, 150, fill="#fbfcfb", stroke=GREEN[0], sw=1.4, rx=12)
    s.text(64, 96, "CURRENT  —  text-based pipeline", 11, fill="#2c6b3f", family=SERIF, weight="bold", spacing="0.6")
    node(s, 70, 116, 170, 70, "Documents", "PDF · DOCX · text", acc=GREEN, tint=GREEN[1], tfam=SERIF, tsize=12)
    node(s, 300, 116, 190, 70, "Text embedder", "all-MiniLM-L6-v2", acc=GREEN, tint="#ffffff", tsize=11)
    arrow(s, 240, 151, 300, 151, color=GREEN[0], label="chunks")

    # proposed image lane
    s.rect(48, 250, 1084, 150, fill="#fefbf5", stroke=AMBER[0], sw=1.4, rx=12, dash="7 5")
    s.text(64, 276, "PROPOSED  —  image / multimodal branch", 11, fill="#8a6420", family=SERIF, weight="bold", spacing="0.6")
    node(s, 70, 296, 170, 70, "Images", "photos · figures · scans", acc=AMBER, tint=AMBER[1], tfam=SERIF, tsize=12)
    node(s, 300, 296, 190, 70, "Image embedder", "CLIP-style multimodal", acc=AMBER, tint="#ffffff", tsize=11)
    arrow(s, 240, 331, 300, 331, color=AMBER[0])

    # shared retrieval index
    px = 620
    s.path(f"M{px},{190} A70,16 0 0 1 {px+140},{190} L{px+140},{290} A70,16 0 0 1 {px},{290} Z",
           fill=TEAL[1], stroke=TEAL[0], sw=1.8)
    s.path(f"M{px},{190} A70,16 0 0 0 {px+140},{190}", fill="none", stroke=TEAL[0], sw=1.8)
    s.text(px + 70, 226, "Retrieval index", 12, fill=INK, family=MONO, weight="bold", anchor="middle")
    s.text(px + 70, 245, "Milvus", 10.5, fill=SUB, family=MONO, anchor="middle")
    s.text(px + 70, 261, "one shared store", 9.4, fill=NOTE, family=SERIF, italic=True, anchor="middle")
    arrow(s, 490, 151, px + 4, 214, color=GREEN[0], label="vectors")
    arrow(s, 490, 331, px + 4, 266, color=AMBER[0], label="vectors", dash="6 4")

    # unified query + results
    node(s, 830, 150, 150, 62, "Query", "text or image", acc=BLUE, tint=BLUE[1], tfam=SERIF, tsize=12)
    node(s, 830, 300, 150, 62, "Ranked results", "same contract", acc=PURPLE, tint=PURPLE[1], tfam=SERIF, tsize=11.5)
    arrow(s, 830, 181, px + 140, 220, color=BLUE[0], label="embed → search")
    arrow(s, px + 140, 250, 830, 320, color=PURPLE[0], label="top-k")

    s.text(48, 452, "The proposed image branch reuses the same retrieval index and query contract as the text pipeline: "
                    "only the embedding model changes.", 9.8, fill=SUB, family=SERIF, italic=True)
    s.text(48, 468, "A multimodal embedder maps images into the same vector space, so a single similarity search spans "
                    "text and image content.", 9.8, fill=SUB, family=SERIF, italic=True)
    s.text(48, 496, "Dashed = proposed / future work.", 9.4, fill=NOTE, family=SERIF, italic=True)
    s.save("future_image_search.svg")


# =============================================================================
# 8 — Future: scaled AI-serving architecture
# =============================================================================
def fig_scaled_ai():
    s = SVG(1180, 560)

    node(s, 60, 232, 130, 66, "Clients", "at scale", acc=BLUE, tint=BLUE[1], tfam=SERIF, tsize=13)
    node(s, 230, 232, 150, 66, "Load balancer", None, acc=GREY, tint=GREY[1], tsize=11.5)
    arrow(s, 190, 265, 230, 265, color=STROKE)

    # API instances
    node(s, 430, 190, 150, 48, "API instance", None, acc=GREY, tint="#ffffff", tsize=11)
    node(s, 430, 258, 150, 48, "API instance", None, acc=GREY, tint="#ffffff", tsize=11)
    arrow(s, 380, 258, 430, 214, color=STROKE)
    arrow(s, 380, 272, 430, 282, color=STROKE)

    # cache layer (in front of inference)
    hbar(s, 640, 70, 200, 110, "Cache layer", AMBER)
    s.text(650, 104, "response / semantic", 10, fill="#8a6420", family=SERIF)
    s.text(650, 120, "cache — in front of", 10, fill="#8a6420", family=SERIF)
    s.text(650, 136, "the inference service", 10, fill="#8a6420", family=SERIF)
    s.text(650, 160, "hit → skip inference", 9.4, fill=NOTE, family=SERIF, italic=True)

    # inference pool
    hbar(s, 640, 210, 200, 150, "Inference service", ROSE)
    node(s, 655, 250, 170, 40, "LLM replica · GPU", None, acc=ROSE, tint="#ffffff", tsize=10)
    node(s, 655, 296, 170, 40, "LLM replica · GPU", None, acc=ROSE, tint="#ffffff", tsize=10)
    s.text(740, 350, "distributed / autoscaled", 9, fill=NOTE, family=SERIF, italic=True, anchor="middle")

    arrow(s, 580, 250, 640, 128, color=STROKE, label="query")
    arrow(s, 740, 180, 740, 210, color=AMBER[0], label="miss")

    # sharded vector db
    hbar(s, 900, 150, 220, 210, "Vector DB  —  sharded", TEAL)
    for i in range(3):
        yy = 190 + i * 52
        s.path(f"M{918},{yy} A45,10 0 0 1 {1008},{yy} L{1008},{yy+34} A45,10 0 0 1 {918},{yy+34} Z",
               fill=TEAL[1], stroke=TEAL[0], sw=1.4)
        s.path(f"M{918},{yy} A45,10 0 0 0 {1008},{yy}", fill="none", stroke=TEAL[0], sw=1.4)
        s.text(963, yy + 24, f"shard {i+1}", 10, fill=INK, family=MONO, anchor="middle")
    s.text(1088, 200, "…", 14, fill=SUB, family=MONO, anchor="middle")
    arrow(s, 840, 285, 900, 255, color=TEAL[0], label="retrieve")

    s.line(60, 452, 1120, 452, stroke="#e9ebef", sw=1)
    s.text(60, 474, "Proposed scaling path (Ch. IX): a cache layer fronts a distributed, autoscaled inference pool so "
                    "repeat / cacheable requests skip the model entirely,", 9.8, fill=SUB, family=SERIF, italic=True)
    s.text(60, 490, "while the vector store is sharded across nodes — letting the platform serve organizations well beyond "
                    "the validation scale. All boxes are future work.", 9.8, fill=SUB, family=SERIF, italic=True)
    s.save("future_scaled_ai_serving.svg")


if __name__ == "__main__":
    fig_thread_cte()
    fig_fanout()
    fig_search_ilike()
    fig_search_lifecycle()
    fig_image_search()
    fig_scaled_ai()
