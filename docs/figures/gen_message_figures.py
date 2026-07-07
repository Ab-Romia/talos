#!/usr/bin/env python3
"""Generate the two Message-System figures for the Talos documentation:

  1. message_orm_layout.svg          — messages ORM column layout: derived
                                       columns and GIN indexes
  2. prosemirror_node_hierarchy.svg  — chat_schema node hierarchy: doc -> block
                                       nodes -> inline group -> custom atoms,
                                       with the mark set

Both are hand-built SVGs so they drop straight into the Typst source via
`#image("figures/<name>.svg")`. Typography (serif body + mono for identifiers)
and the light colour coding follow the document's existing schema diagrams.
"""
import math
import os

OUT = os.path.dirname(os.path.abspath(__file__))

SERIF = "'New Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif"
MONO = "'Latin Modern Mono', 'DejaVu Sans Mono', 'Consolas', monospace"

INK = "#1b2130"
SUB = "#5b6472"
NOTE = "#8a8f99"
STROKE = "#2b2f37"
HAIR = "#cbd0d7"
SLATE = "#3b4250"

# accent (line, tint)
PK = ("#b8860b", "#fbf3dd")
FK = ("#3e6fb0", "#eaf1fb")
SRC = ("#2c8c9a", "#e7f2f4")
DER = ("#c4913a", "#fbf2de")
GIN = ("#2e7d46", "#e6f3ea")
BTREE = ("#5a46a8", "#eeeaf8")
CUSTOM = ("#c4913a", "#fbf2de")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SVG:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.el = []

    def rect(self, x, y, w, h, fill="#ffffff", stroke=None, sw=1.4, rx=0, opacity=None, dash=None):
        a = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"']
        if stroke:
            a.append(f' stroke="{stroke}" stroke-width="{sw}"')
        if dash:
            a.append(f' stroke-dasharray="{dash}"')
        if opacity is not None:
            a.append(f' opacity="{opacity}"')
        a.append("/>")
        self.el.append("".join(a))

    def _tri(self, x, y, dx, dy, color, size=8.5):
        # Explicit arrowhead triangle (portable — Typst/resvg ignores <marker>).
        n = math.hypot(dx, dy) or 1
        ux, uy = dx / n, dy / n
        px, py = -uy, ux
        b1 = (x - size * ux + size * 0.55 * px, y - size * uy + size * 0.55 * py)
        b2 = (x - size * ux - size * 0.55 * px, y - size * uy - size * 0.55 * py)
        self.el.append(f'<path d="M{x:.1f},{y:.1f} L{b1[0]:.1f},{b1[1]:.1f} '
                       f'L{b2[0]:.1f},{b2[1]:.1f} Z" fill="{color}"/>')

    def line(self, x1, y1, x2, y2, stroke=STROKE, sw=1.4, dash=None, arrow=False):
        a = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"']
        if dash:
            a.append(f' stroke-dasharray="{dash}"')
        a.append("/>")
        self.el.append("".join(a))
        if arrow:
            self._tri(x2, y2, x2 - x1, y2 - y1, stroke)

    def path(self, d, stroke=STROKE, sw=1.4, fill="none", dash=None):
        a = [f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"']
        if dash:
            a.append(f' stroke-dasharray="{dash}"')
        a.append("/>")
        self.el.append("".join(a))

    def curve(self, x0, y0, c1x, c1y, c2x, c2y, x1, y1, stroke=STROKE, sw=1.4, dash=None):
        self.path(f"M{x0},{y0} C{c1x},{c1y} {c2x},{c2y} {x1},{y1}", stroke=stroke, sw=sw, dash=dash)
        self._tri(x1, y1, x1 - c2x, y1 - c2y, stroke)

    def text(self, x, y, s, size, fill=INK, family=SERIF, weight=None, anchor="start",
             italic=False, spacing=None):
        a = [f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
             f'font-family="{family}" text-anchor="{anchor}"']
        if weight:
            a.append(f' font-weight="{weight}"')
        if italic:
            a.append(' font-style="italic"')
        if spacing:
            a.append(f' letter-spacing="{spacing}"')
        a.append(f'>{esc(s)}</text>')
        self.el.append("".join(a))

    def pill(self, x, y, label, line, tint, w=None, h=17, size=10):
        tw = w if w else (len(label) * size * 0.62 + 12)
        self.rect(x, y, tw, h, fill=tint, stroke=line, sw=1.1, rx=h / 2)
        self.text(x + tw / 2, y + h - 5, label, size, fill=line, family=MONO,
                  weight="bold", anchor="middle")
        return tw

    def render(self):
        head_no_marker = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
                          f'height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
                          f'font-family="{SERIF}">'
                          f'<rect x="0" y="0" width="{self.w}" height="{self.h}" fill="#ffffff"/>')
        return head_no_marker + "".join(self.el) + "</svg>"

    def save(self, name):
        p = os.path.join(OUT, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.render())
        print("wrote", p)


# =============================================================================
# FIGURE 1 — messages ORM column layout
# =============================================================================
def figure_orm():
    s = SVG(1180, 664)

    TX, TY, TW = 398, 60, 388
    HEAD = 48
    RH = 38
    rows = [
        # name, type, kind, note, tag
        ("id",                 "uuid",         "pk",     "primary key · uuid7",                    None),
        ("channel_id",         "uuid",         "fk",     "FK → channels · ON DELETE CASCADE",      "btree"),
        ("sender_id",          "uuid",         "fk",     "FK → users · SET NULL · NULL for bot",   None),
        ("content",            "jsonb",        "source", "ProseMirror doc · NOT NULL",             "gin"),
        ("mentioned_user_ids", "uuid[]",       "derived","derived · @> containment fanout",        "gin"),
        ("content_size_bytes", "integer",      "derived","derived · O(1) size audits",             None),
        ("reply_to_id",        "uuid",         "fkself", "FK → messages (self) · SET NULL",        None),
        ("role",               "messagerole",  "plain",  "user · assistant · system",              None),
        ("sent_at",            "timestamptz",  "plain",  "default now()",                          "btree"),
        ("indexed_at",         "timestamptz",  "plain",  "NULL until chat-memory indexer runs",    None),
        ("edited_at",          "timestamptz",  "plain",  "NULL · edit-history stamp",              None),
        ("is_deleted",         "boolean",      "plain",  "soft delete · preserves thread shape",   None),
    ]
    accent = {"pk": PK, "fk": FK, "fkself": FK, "source": SRC, "derived": DER, "plain": (HAIR, "#ffffff")}
    tint = {"source": SRC[1], "derived": DER[1]}
    n = len(rows)
    tbl_h = HEAD + n * RH

    # table shell + header
    s.rect(TX, TY, TW, tbl_h, fill="#ffffff", stroke=STROKE, sw=1.6, rx=10)
    s.path(f"M{TX},{TY+HEAD} h{TW}", stroke=STROKE, sw=1.6)
    s.rect(TX, TY, TW, HEAD, fill=SLATE, stroke=None, rx=10)
    s.rect(TX, TY + HEAD - 12, TW, 12, fill=SLATE)  # square off header bottom
    s.text(TX + 16, TY + 22, "messages", 16, fill="#ffffff", family=MONO, weight="bold")
    s.text(TX + 16, TY + 39, "src/chat/model.py · class Message", 10.5, fill="#c9cfd8",
           family=SERIF, italic=True)
    s.text(TX + TW - 14, TY + 30, "PostgreSQL table", 10.5, fill="#c9cfd8", family=SERIF,
           italic=True, anchor="end")

    ry0 = TY + HEAD
    centers = {}
    for i, (name, typ, kind, note, tag) in enumerate(rows):
        top = ry0 + i * RH
        cy = top + RH / 2
        centers[name] = cy
        ac_line, ac_tint = accent[kind]
        # row tint
        if kind in tint:
            s.rect(TX + 2, top, TW - 4, RH, fill=tint[kind])
        elif i % 2 == 1:
            s.rect(TX + 2, top, TW - 4, RH, fill="#f7f7f5")
        # accent bar
        if kind != "plain":
            s.rect(TX + 2, top + 4, 5, RH - 8, fill=ac_line, rx=2)
        # separator
        if i > 0:
            s.line(TX, top, TX + TW, top, stroke="#e9ebef", sw=1)
        # name + type
        s.text(TX + 18, top + 16, name, 13, fill=INK, family=MONO, weight="bold")
        s.text(TX + TW - 14, top + 16, typ, 11, fill=SUB, family=MONO, anchor="end")
        # note
        s.text(TX + 18, top + 30, note, 9.6, fill=NOTE, family=SERIF)
        # tag pill (right, second line)
        if tag == "gin":
            s.pill(TX + TW - 52, top + 21, "GIN", GIN[0], GIN[1], w=40)
        elif tag == "btree":
            s.pill(TX + TW - 58, top + 21, "btree", BTREE[0], BTREE[1], w=46)

    # ---- left: set_content() write path ----
    bx, by, bw, bh = 60, 214, 288, 150
    s.rect(bx, by, bw, bh, fill="#ffffff", stroke=DER[0], sw=1.6, rx=10)
    s.rect(bx, by, bw, 26, fill=DER[1], rx=10)
    s.rect(bx, by + 14, bw, 12, fill=DER[1])
    s.text(bx + 14, by + 18, "set_content(doc)", 12.5, fill="#8a6420", family=MONO, weight="bold")
    lines = [
        "The only sanctioned write path.",
        "Writes three columns atomically:",
        "· content            ← doc.to_json()",
        "· content_size_bytes ← len(json)",
        "· mentioned_user_ids ← walk AST",
    ]
    yy = by + 44
    for ln in lines:
        mono = ln.startswith("·")
        s.text(bx + 14, yy, ln, 10 if not mono else 9.6,
               fill=INK if not mono else "#4a5162",
               family=SERIF if not mono else MONO)
        yy += 16
    s.text(bx + 14, yy + 2, "parse_doc() validates schema + size first",
           9.2, fill=NOTE, family=SERIF, italic=True)

    # arrows from set_content to the three written columns
    for name in ("content", "mentioned_user_ids", "content_size_bytes"):
        s.curve(bx + bw, by + bh / 2, bx + bw + 34, by + bh / 2,
                TX - 34, centers[name], TX - 2, centers[name], stroke=DER[0], sw=1.5)

    # ---- right: index panel ----
    IX = 828
    IW = 320
    boxes = [
        (150, 66, GIN, "ix_messages_content_gin", "GIN · content (jsonb)",
         "server-side AST / full-text scans", "content"),
        (250, 80, GIN, "ix_messages_mentioned_user_ids_gin", "GIN · mentioned_user_ids (uuid[])",
         "fanout: … @> ARRAY[:uid] — index-only", "mentioned_user_ids"),
        (372, 80, BTREE, "ix_messages_channel_sent_at", "B-tree · (channel_id, sent_at)",
         "channel timeline + keyset pagination", "sent_at"),
    ]
    s.text(IX, 138, "INDEXES", 11, fill=NOTE, family=SERIF, weight="bold", spacing="1.5")
    for (iy, ih, col, title, sub1, sub2, src) in boxes:
        mid = iy + ih / 2
        s.curve(TX + TW, centers[src], TX + TW + 40, centers[src],
                IX - 40, mid, IX - 2, mid, stroke=col[0], sw=1.5)
        s.rect(IX, iy, IW, ih, fill=col[1], stroke=col[0], sw=1.5, rx=9)
        s.rect(IX, iy, 5, ih, fill=col[0], rx=2)
        s.text(IX + 16, iy + 20, title, 11.5, fill=INK, family=MONO, weight="bold")
        s.text(IX + 16, iy + 37, sub1, 10.2, fill="#404757", family=MONO)
        s.text(IX + 16, iy + 53, sub2, 9.8, fill=SUB, family=SERIF)

    # ---- legend ----
    ly = 604
    s.line(60, ly - 18, 1120, ly - 18, stroke="#e9ebef", sw=1)
    legend = [
        (PK, "PK"), (FK, "FK / self-FK"), (SRC, "content (source)"),
        (DER, "derived — set_content()"), (GIN, "GIN index"), (BTREE, "B-tree index"),
    ]
    lx = 60
    for (col, lab) in legend:
        s.rect(lx, ly - 10, 14, 14, fill=col[1], stroke=col[0], sw=1.3, rx=3)
        s.text(lx + 20, ly + 1, lab, 10.5, fill=INK, family=SERIF)
        lx += 30 + len(lab) * 6.4 + 26
    s.text(60, ly + 30,
           "parse_doc() is the validation gate — enforced at the API boundary (MessageCreateSchema) "
           "and again as a Pydantic validator (MessageSchema).",
           10, fill=SUB, family=SERIF, italic=True)

    s.save("message_orm_layout.svg")


# =============================================================================
# FIGURE 2 — chat_schema node hierarchy
# =============================================================================
def figure_hierarchy():
    s = SVG(1180, 726)

    def node(x, y, w, h, title, sub, line=STROKE, tint="#ffffff", star=False, tsize=12.5):
        s.rect(x, y, w, h, fill=tint, stroke=line, sw=1.5, rx=8)
        label = ("★ " + title) if star else title
        s.text(x + w / 2, y + (h / 2 + 1 if not sub else 17), label, tsize,
               fill=INK, family=MONO, weight="bold", anchor="middle")
        if sub:
            s.text(x + w / 2, y + h - 9, sub, 9.4, fill=SUB, family=SERIF, anchor="middle")

    # ---- doc root ----
    node(506, 40, 168, 50, "doc", "content: block+", line=STROKE, tint="#eef0f3", tsize=15)

    # ---- block group container ----
    bgx, bgy, bgw, bgh = 96, 150, 700, 150
    s.rect(bgx, bgy, bgw, bgh, fill="#fbfbfa", stroke=HAIR, sw=1.4, rx=12, dash="1 0")
    s.text(bgx + 16, bgy + 22, "block  nodes", 12.5, fill=INK, family=MONO, weight="bold")
    s.text(bgx + 16, bgy + 37, 'group: "block"  — direct children of doc', 9.8, fill=SUB,
           family=SERIF, italic=True)
    s.line(506 + 84, 90, bgx + bgw / 2, bgy, stroke=STROKE, sw=1.5, arrow=True)

    blocks = [
        ("paragraph", "inline*"), ("heading", "inline* · level"),
        ("blockquote", "block+"), ("code_block", "text*"),
        ("bullet_list", "list_item+"), ("ordered_list", "list_item+"),
        ("list_item", "paragraph block*"), ("horizontal_rule", "atom"),
    ]
    cw, ch, gx, gy = 158, 40, 12, 12
    bx0 = bgx + 18
    by0 = bgy + 48
    block_pos = {}
    for i, (nm, md) in enumerate(blocks):
        col = i % 4
        rw = i // 4
        x = bx0 + col * (cw + gx)
        y = by0 + rw * (ch + gy)
        node(x, y, cw, ch, nm, md, line="#b9c0ca", tint="#ffffff", tsize=11.5)
        block_pos[nm] = (x + cw / 2, y + ch)

    # ---- inline group container ----
    igx, igy, igw, igh = 96, 372, 700, 118
    s.rect(igx, igy, igw, igh, fill="#fbfbfa", stroke=HAIR, sw=1.4, rx=12, dash="1 0")
    s.text(igx + 16, igy + 22, "inline  group", 12.5, fill=INK, family=MONO, weight="bold")
    s.text(igx + 16, igy + 37, 'group: "inline"  — content of paragraph / heading', 9.8,
           fill=SUB, family=SERIF, italic=True)
    # block container -> inline group (paragraph & heading hold inline content)
    s.line(bgx + bgw / 2, bgy + bgh, igx + igw / 2, igy, stroke=STROKE, sw=1.5, arrow=True)
    lyv = (bgy + bgh + igy) / 2
    s.rect(igx + igw / 2 + 10, lyv - 11, 250, 20, fill="#ffffff", opacity=0.95, rx=4)
    s.text(igx + igw / 2 + 18, lyv + 3, "content: inline*", 10, fill="#404757", family=MONO)
    s.text(igx + igw / 2 + 130, lyv + 3, "of paragraph / heading", 9.4, fill=SUB,
           family=SERIF, italic=True)

    inlines = [
        ("text", "+ marks", False), ("hard_break", "atom", False), ("image", "atom", False),
        ("mention", "atom", True), ("reference", "atom", True), ("slash_command", "atom", True),
    ]
    iw, ih2, igp = 100, 40, 12
    ix0 = igx + 18
    iy0 = igy + 54
    inline_pos = {}
    for i, (nm, md, star) in enumerate(inlines):
        x = ix0 + i * (iw + igp)
        col = CUSTOM if star else ("#b9c0ca", "#ffffff")
        node(x, iy0, iw, ih2, nm, md, line=col[0], tint=col[1] if star else "#ffffff",
             star=star, tsize=10.3 if len(nm) > 9 else 11)
        inline_pos[nm] = (x + iw / 2, iy0 + ih2, x + iw / 2)

    # ---- custom atom attribute cards ----
    cards = [
        ("mention", ["user_id", "label"],
         "drives notification fanout;", "label denormalised for render"),
        ("reference", ["ref_type", "ref_id?", "label", "url?"],
         "channel · file · message ·", "workspace · external_url"),
        ("slash_command", ["command", "args"],
         "ephemeral — stripped", "server-side before persist"),
    ]
    cy0 = 560
    cardw = 232
    cgap = 20
    cx0 = 96
    for i, (nm, attrs, l1, l2) in enumerate(cards):
        x = cx0 + i * (cardw + cgap)
        h = 118
        s.rect(x, cy0, cardw, h, fill=CUSTOM[1], stroke=CUSTOM[0], sw=1.5, rx=9)
        s.rect(x, cy0, cardw, 24, fill=CUSTOM[1], rx=9)
        s.text(x + 12, cy0 + 17, nm, 11.5, fill="#8a6420", family=MONO, weight="bold")
        s.text(x + cardw - 12, cy0 + 17, "atom: true", 9, fill="#a07a30", family=MONO, anchor="end")
        s.text(x + 12, cy0 + 40, "attrs", 9.4, fill=NOTE, family=SERIF, italic=True)
        ax = x + 12
        ay = cy0 + 58
        for a in attrs:
            tw = s.pill(ax, ay - 12, a, "#8a6420", "#ffffff", h=17, size=9.4)
            ax += tw + 8
            if ax > x + cardw - 60:
                ax = x + 12
                ay += 22
        s.text(x + 12, cy0 + h - 26, l1, 9.4, fill=SUB, family=SERIF)
        s.text(x + 12, cy0 + h - 12, l2, 9.4, fill=SUB, family=SERIF)
        # connector from inline atom to its card
        px, py, _ = inline_pos[nm]
        s.curve(px, py, px, py + 40, x + cardw / 2, cy0 - 40, x + cardw / 2, cy0,
                stroke=CUSTOM[0], sw=1.4, dash="4 4")

    # ---- marks panel ----
    mx, my, mw, mh = 828, 372, 300, 232
    s.rect(mx, my, mw, mh, fill="#ffffff", stroke=STROKE, sw=1.5, rx=10)
    s.rect(mx, my, mw, 30, fill="#eef0f3", rx=10)
    s.rect(mx, my + 18, mw, 12, fill="#eef0f3")
    s.text(mx + 14, my + 20, "marks", 12.5, fill=INK, family=MONO, weight="bold")
    s.text(mx + mw - 14, my + 20, "apply to inline text", 9.4, fill=SUB, family=SERIF,
           italic=True, anchor="end")
    marks = [
        ("strong", "bold"), ("em", "italic"), ("underline", None),
        ("strike", None), ("code", None), ("link", None),
    ]
    myy = my + 48
    for canon, alias in marks:
        s.text(mx + 18, myy, canon, 11, fill=INK, family=MONO, weight="bold")
        if alias:
            s.text(mx + 120, myy, f"alias: {alias}", 9.8, fill=DER[0], family=MONO)
        myy += 24
    s.line(mx + 14, myy - 12, mx + mw - 14, myy - 12, stroke="#e9ebef", sw=1)
    s.text(mx + 18, myy + 6, "TipTap aliases bold↔strong,", 9.6, fill=SUB, family=SERIF)
    s.text(mx + 18, myy + 20, "italic↔em both registered —", 9.6, fill=SUB, family=SERIF)
    s.text(mx + 18, myy + 34, "no client normalisation step.", 9.6, fill=SUB, family=SERIF)
    # marks apply to inline text — short connector from inline group to marks panel
    my_mid = igy + igh / 2
    s.line(igx + igw, my_mid, mx, my_mid, stroke=DER[0], sw=1.4, dash="4 4", arrow=True)
    s.rect((igx + igw + mx) / 2 - 26, my_mid - 22, 52, 16, fill="#ffffff", opacity=0.92, rx=4)
    s.text((igx + igw + mx) / 2, my_mid - 10, "marks", 9.4, fill=DER[0], family=MONO, anchor="middle")

    # ---- footnote ----
    s.line(96, 686, 1128, 686, stroke="#e9ebef", sw=1)
    s.text(96, 706,
           "★ = custom inline atom extending the base ProseMirror schema.  All atoms are indivisible "
           "(atom: true).  chat_schema is a module-level singleton — one instance for the whole app.",
           10, fill=SUB, family=SERIF, italic=True)

    s.save("prosemirror_node_hierarchy.svg")


if __name__ == "__main__":
    figure_orm()
    figure_hierarchy()
