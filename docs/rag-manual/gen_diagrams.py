#!/usr/bin/env python3
"""Generate crisp, consistent SVG diagrams for the RAG Owner's Manual."""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagrams")
os.makedirs(OUT, exist_ok=True)

FONT = "Liberation Sans, Arial, sans-serif"
MONO = "Liberation Mono, monospace"

# palette: (fill, stroke)
C = {
    "api":    ("#efe6fb", "#7b3fe4"),
    "chain":  ("#e6e9fb", "#4a54d6"),
    "pipe":   ("#e2eefc", "#2f74d0"),
    "store":  ("#e3f5e8", "#2fa559"),
    "config": ("#fdf0d5", "#d99000"),
    "llm":    ("#fde4ec", "#d6417a"),
    "eval":   ("#eceef2", "#7a8699"),
    "data":   ("#e0f3f4", "#2a9aa5"),
    "trace":  ("#eef1f6", "#55617a"),
    "plain":  ("#ffffff", "#9aa3b2"),
}
INK = "#1b2130"
EDGE = "#5a6270"


def hdr(w, h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="{FONT}">'
            f'<defs>'
            f'<marker id="arw" markerWidth="12" markerHeight="12" refX="9" refY="4" orient="auto">'
            f'<path d="M0,0 L9,4 L0,8 z" fill="{EDGE}"/></marker>'
            f'<marker id="arwl" markerWidth="12" markerHeight="12" refX="9" refY="4" orient="auto">'
            f'<path d="M0,0 L9,4 L0,8 z" fill="#c23b6b"/></marker>'
            f'</defs>'
            f'<rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>')


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def box(x, y, w, h, kind, title, lines=None, mono_lines=None, ts=15, r=11):
    f, s = C[kind]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{f}" '
           f'stroke="{s}" stroke-width="2"/>']
    cx = x + w / 2
    ty = y + (22 if title else 16)
    if title:
        out.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="{ts}" '
                   f'font-weight="bold" fill="{INK}">{esc(title)}</text>')
        ty += 6
    if lines:
        for ln in lines:
            ty += 17
            out.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="11.5" '
                       f'fill="{INK}">{esc(ln)}</text>')
    if mono_lines:
        for ln in mono_lines:
            ty += 16
            out.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="10.5" '
                       f'font-family="{MONO}" fill="#33405a">{esc(ln)}</text>')
    return "".join(out), (cx, y + h / 2)


def cylinder(x, y, w, h, kind, title, lines=None):
    f, s = C[kind]
    ry = 13
    out = [f'<path d="M{x},{y+ry} A{w/2},{ry} 0 0 1 {x+w},{y+ry} L{x+w},{y+h-ry} '
           f'A{w/2},{ry} 0 0 1 {x},{y+h-ry} Z" fill="{f}" stroke="{s}" stroke-width="2"/>',
           f'<path d="M{x},{y+ry} A{w/2},{ry} 0 0 0 {x+w},{y+ry}" fill="none" '
           f'stroke="{s}" stroke-width="2"/>']
    cx = x + w / 2
    ty = y + ry + 24
    out.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="15" '
               f'font-weight="bold" fill="{INK}">{esc(title)}</text>')
    if lines:
        for ln in lines:
            ty += 17
            out.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="11" '
                       f'fill="{INK}">{esc(ln)}</text>')
    return "".join(out), (cx, y + h / 2)


def arrow(p1, p2, label=None, dash=False, color=None, curve=0, lx=None, ly=None,
          lsize=11, lbg=True):
    color = color or EDGE
    d = ' stroke-dasharray="6 5"' if dash else ''
    x1, y1 = p1
    x2, y2 = p2
    if curve:
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2 + curve
        path = f'<path d="M{x1},{y1} Q{mx},{my} {x2},{y2}" fill="none" stroke="{color}" ' \
               f'stroke-width="2"{d} marker-end="url(#arw)"/>'
    else:
        path = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" ' \
               f'stroke-width="2"{d} marker-end="url(#arw)"/>'
    out = [path]
    if label:
        if lx is None:
            lx = (x1 + x2) / 2
        if ly is None:
            ly = (y1 + y2) / 2 - 6
        w = len(label) * lsize * 0.56 + 10
        if lbg:
            out.append(f'<rect x="{lx-w/2}" y="{ly-lsize}" width="{w}" height="{lsize+7}" '
                       f'rx="4" fill="#ffffff" opacity="0.92"/>')
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="{lsize}" '
                   f'fill="#333c4d">{esc(label)}</text>')
    return "".join(out)


def title(x, y, s, size=20):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="bold" '
            f'fill="{INK}">{esc(s)}</text>')


def caption(x, y, s, size=12.5):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="#5a6270">{esc(s)}</text>')


def legend(x, y, items):
    out = []
    for i, (kind, lbl) in enumerate(items):
        f, s = C[kind]
        yy = y + i * 22
        out.append(f'<rect x="{x}" y="{yy}" width="16" height="16" rx="3" fill="{f}" '
                   f'stroke="{s}" stroke-width="1.5"/>')
        out.append(f'<text x="{x+22}" y="{yy+13}" font-size="11.5" fill="{INK}">{esc(lbl)}</text>')
    return "".join(out)


def write(name, w, h, body):
    with open(f"{OUT}/{name}.svg", "w") as fh:
        fh.write(hdr(w, h) + body + "</svg>")
    print("wrote", name)


# ===========================================================================
# D1 — SYSTEM OVERVIEW / DATA FLOW
# ===========================================================================
def d1():
    W, H = 1040, 640
    b = [title(30, 40, "1 · System overview — one collection, writers on the left, readers on the right")]
    # writers
    b += [caption(30, 70, "WRITERS  (put vectors in)")]
    _, f_ing = box(30, 88, 300, 78, "store",
                   "File ingestion", ["upload → worker → documents.py"],
                   mono_lines=["ingest_file_chunks()  →  source=\"file\""])
    b.append(_)
    _, f_idx = box(30, 200, 300, 96, "store",
                   "Chat indexer  (taskiq cron)",
                   ["every chat_index_interval_minutes"],
                   mono_lines=["index_pending_messages()", "→ source=\"chat\"  (purge→ingest→stamp)"])
    b.append(_)
    _, f_pg = box(30, 330, 300, 74, "data", "Postgres — messages",
                  ["role · content · sent_at · indexed_at"],
                  mono_lines=["indexed_at IS NULL  = not yet indexed"])
    b.append(_)
    # milvus centre
    _, mil = cylinder(430, 150, 190, 150, "store", "Milvus",
                      ["talos_documents", "(one collection,", "dynamic schema)"])
    b.append(_)
    b.append(caption(430, 130, "SINGLE VECTOR STORE"))
    # readers
    b += [caption(720, 70, "READERS  (query vectors)")]
    _, f_api = box(720, 88, 300, 66, "api", "POST /api/channels/{id}/ask",
                   ["perm: channel.message:send · streams"])
    b.append(_)
    _, f_chain = box(720, 176, 300, 92, "chain", "RAGChain  (orchestrator)",
                     ["load tier-1 tail · retrieve · prompt"],
                     mono_lines=["build_rag_pipeline()  ← shared core", "RAG_PROMPT | llm | stream"])
    b.append(_)
    _, f_llm = box(720, 292, 300, 60, "llm", "LLM  (ChatOpenAI-compatible)",
                   ["streams the grounded answer"])
    b.append(_)
    # eval bottom
    _, f_eval = box(430, 470, 400, 96, "eval", "Evaluation harness",
                    ["RagVariant over an in-memory store"],
                    mono_lines=["calls the SAME build_rag_pipeline()", "and the SAME RAG_PROMPT"])
    b.append(_)
    b.append(caption(430, 452, "MEASURES THE SAME CORE"))
    # arrows writers -> milvus
    b.append(arrow((330, f_ing[1]), (430, 195), "write", curve=-10))
    b.append(arrow((330, f_idx[1]), (430, 240), "write"))
    b.append(arrow((330, f_pg[1]), (720, 222), "tier-1 tail (verbatim)", curve=60,
                   color="#2a9aa5", lx=560, ly=395))
    # milvus <-> readers
    b.append(arrow((620, 210), (720, 210), "read"))
    b.append(arrow((f_api[0], 154), (f_chain[0], 176), "invoke"))
    b.append(arrow((f_chain[0], 268), (f_llm[0], 292), "context+question"))
    # eval -> core (dashed, same code)
    b.append(arrow((f_eval[0], 470), (760, 268), "same code", dash=True,
                   color="#7a8699", curve=-40, lx=650, ly=430))
    b.append(legend(30, 470, [("store", "vector store / ingest"), ("data", "Postgres"),
                              ("api", "HTTP endpoint"), ("chain", "orchestrator"),
                              ("llm", "LLM"), ("eval", "evaluation")]))
    write("d1_overview", W, H, "".join(b))


# ===========================================================================
# D2 — /ask REQUEST SEQUENCE
# ===========================================================================
def d2():
    W, H = 1040, 700
    b = [title(30, 40, "2 · Lifecycle of one /ask request")]
    actors = [("Client", 90, "api"), ("Router\n/ask", 250, "api"),
              ("Postgres", 410, "data"), ("RAGChain", 560, "chain"),
              ("Milvus", 730, "store"), ("LLM", 900, "llm")]
    top, bot = 70, 660
    xs = {}
    for name, x, kind in actors:
        f, s = C[kind]
        xs[name.split("\n")[0]] = x
        lines = name.split("\n")
        b.append(f'<rect x="{x-58}" y="{top}" width="116" height="{34 if len(lines)==1 else 46}" '
                 f'rx="8" fill="{f}" stroke="{s}" stroke-width="2"/>')
        yy = top + (22 if len(lines) == 1 else 19)
        for ln in lines:
            b.append(f'<text x="{x}" y="{yy}" text-anchor="middle" font-size="13" '
                     f'font-weight="bold" fill="{INK}">{esc(ln)}</text>')
            yy += 16
        b.append(f'<line x1="{x}" y1="{top+50}" x2="{x}" y2="{bot}" stroke="#c4cbd6" '
                 f'stroke-width="1.5" stroke-dasharray="3 4"/>')

    def msg(a, bx, y, label, back=False, note=None):
        x1, x2 = xs[a], xs[bx]
        color = "#c23b6b" if back else EDGE
        mk = "arwl" if back else "arw"
        d = ' stroke-dasharray="6 4"' if back else ''
        seg = [f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" '
               f'stroke-width="2"{d} marker-end="url(#{mk})"/>']
        mx = (x1 + x2) / 2
        seg.append(f'<text x="{mx}" y="{y-6}" text-anchor="middle" font-size="11.5" '
                   f'fill="#333c4d">{esc(label)}</text>')
        return "".join(seg)

    y = 120
    steps = [
        ("Client", "Router", "POST question (+debug?)"),
        ("Router", "Postgres", "load un-indexed tail (tier-1) + ids"),
        ("Router", "Postgres", "persist user question"),
        ("Router", "RAGChain", "construct(config, ws, channel, tail, exclude_ids)"),
        ("RAGChain", "Milvus", "retrieve FILE chunks  (expr: workspace + source=file)"),
        ("RAGChain", "Milvus", "retrieve CHAT chunks  (expr: channel + source=chat, minus tail)"),
        ("RAGChain", "LLM", "RAG_PROMPT(context, question, tail)"),
    ]
    for a, bx, lbl in steps:
        b.append(msg(a, bx, y, lbl))
        y += 46
    # stream back
    b.append(msg("LLM", "RAGChain", y, "stream tokens", back=True))
    y += 46
    b.append(msg("RAGChain", "Client", y, "stream answer  (+ __ASK_DEBUG__ trace if debug)", back=True))
    y += 40
    b.append(msg("RAGChain", "Postgres", y, "persist assistant answer  ·  fill RagTrace"))
    y += 20
    b.append(caption(90, y + 20, "Tier-1 = recent un-indexed messages injected verbatim.  Tier-2 = older indexed messages recalled from Milvus.  The two never overlap (exclude_ids)."))
    write("d2_sequence", W, H, "".join(b))


# ===========================================================================
# D3 — TWO-TIER MEMORY
# ===========================================================================
def d3():
    W, H = 1040, 470
    b = [title(30, 40, "3 · Two-tier chat memory — every message is in exactly one tier")]
    # timeline
    bx0, bx1, ty = 60, 980, 250
    b.append(f'<line x1="{bx0}" y1="{ty}" x2="{bx1}" y2="{ty}" stroke="#9aa3b2" stroke-width="2"/>')
    b.append(caption(bx0 - 20, ty + 60, "older  ⟵                                                                                                        ⟶  newer (now)"))
    # boundary (between m7 and m8: newest messages are still un-indexed = tier 1)
    bnd = 610
    b.append(f'<line x1="{bnd}" y1="90" x2="{bnd}" y2="410" stroke="#d99000" '
             f'stroke-width="2.5" stroke-dasharray="7 5"/>')
    b.append(f'<text x="{bnd}" y="85" text-anchor="middle" font-size="12.5" font-weight="bold" '
             f'fill="#b06f00">indexer boundary</text>')
    b.append(f'<text x="{bnd}" y="428" text-anchor="middle" font-size="11" '
             f'fill="#b06f00">indexed_at stamped · sent_at &lt; now−grace</text>')
    # messages: left of boundary = indexed (tier 2, green); right = un-indexed (tier 1, purple)
    for i in range(8):
        mx = 110 + i * 78
        indexed = mx < bnd
        f, s = (C["store"] if indexed else C["api"])
        b.append(f'<rect x="{mx-26}" y="{ty-20}" width="52" height="40" rx="7" fill="{f}" '
                 f'stroke="{s}" stroke-width="2"/>')
        b.append(f'<text x="{mx}" y="{ty+5}" text-anchor="middle" font-size="12" '
                 f'fill="{INK}">m{i+1}</text>')
    # tier boxes
    sv, _ = box(60, 110, 500, 66, "store", "TIER 2 · indexed body (semantic recall)",
                ["chat_retriever over Milvus · source=\"chat\" · k=chat_recall_k"])
    b.append(sv)
    sv, _ = box(640, 110, 340, 66, "api", "TIER 1 · un-indexed tail (verbatim)",
                ["indexed_at IS NULL · capped at chat_context_cap", "injected as chat_history"])
    b.append(sv)
    b.append(arrow((344, 176), (344, ty - 22), "recalled by similarity", color="#2fa559"))
    b.append(arrow((734, 176), (734, ty - 22), "injected as-is", color="#7b3fe4"))
    b.append(caption(60, 452, "The indexer moves messages left across the boundary (stamps indexed_at). exclude_message_ids drops any that are momentarily on both sides."))
    write("d3_memory", W, H, "".join(b))


# ===========================================================================
# D4 — build_rag_pipeline internals
# ===========================================================================
def d4():
    W, H = 1120, 340
    b = [title(30, 40, "4 · build_rag_pipeline() — the one shared retrieval composition")]
    y = 120
    _, q = box(30, y, 120, 66, "plain", "query", ["(rewritten?)"])
    b.append(_)
    _, dense = box(200, y, 175, 76, "pipe", "dense search",
                   ["fetch rerank_fetch_k", "(else top_k)"])
    b.append(_)
    _, hyb = box(415, y, 165, 76, "pipe", "+ BM25 hybrid?",
                 ["only if corpus given", "else warn → dense"])
    b.append(_)
    _, rr = box(620, y, 165, 76, "pipe", "rerank?",
                ["cross-encoder", "widen → top_k"])
    b.append(_)
    _, comp = box(825, y, 165, 76, "pipe", "compress?",
                  ["EmbeddingsFilter", "/ LLM extract"])
    b.append(_)
    for a, bb in [(q, dense), (dense, hyb), (hyb, rr), (rr, comp)]:
        b.append(arrow((a[0] + 60 if a is q else a[0] + 87, y + 38),
                       (bb[0] - 82, y + 38)))
    b.append(arrow((comp[0] + 82, y + 38), (comp[0] + 130, y + 38), "top_k docs"))
    b.append(caption(200, y + 120, "Each stage is a RagConfig toggle:  use_hybrid_retrieval · use_reranking (+rerank_fetch_k) · compression_type (+threshold)."))
    b.append(caption(200, y + 142, "PROD passes a Milvus store + tenant filter (search_kwargs).   EVAL passes an in-memory store + corpus (so hybrid actually runs).  Same function."))
    write("d4_pipeline", W, H, "".join(b))


# ===========================================================================
# D5 — the three chokepoints (config seam + trace)
# ===========================================================================
def d5():
    W, H = 1040, 560
    b = [title(30, 40, "5 · The three chokepoints you must hold in your head")]
    # RagConfig -> one consumers box (no crossing arrows)
    b.append(caption(30, 78, "A · RagConfig  →  reaches every component through a real  config=  seam"))
    _, cfg = box(30, 100, 200, 96, "config", "RagConfig",
                 ["one env-driven object", "global_rag_config", "(the only place knobs live)"])
    b.append(_)
    _, cons = box(360, 92, 380, 150, "pipe", "Every factory takes  config= :", [])
    b.append(_)
    cons_lines = ["get_llm(config=…)", "get_embeddings(config=…)",
                  "get_hyde_embeddings(config=…)", "get_query_rewriter(config=…)",
                  "compression_retriever(config=…)", "build_rag_pipeline(config=…)"]
    yy = 138
    for ln in cons_lines:
        b.append(f'<text x="376" y="{yy}" font-size="12" font-family="{MONO}" '
                 f'fill="{INK}">{esc(ln)}</text>')
        yy += 18
    b.append(arrow((230, 148), (358, 150), None, color="#d99000"))
    b.append(f'<text x="775" y="150" font-size="12" fill="#5a6270">change one field →</text>')
    b.append(f'<text x="775" y="170" font-size="12" fill="#5a6270">every consumer moves,</text>')
    b.append(f'<text x="775" y="190" font-size="12" fill="#5a6270">in prod AND eval.</text>')
    # divider
    b.append(f'<line x1="30" y1="270" x2="1010" y2="270" stroke="#e2e6ee" stroke-width="1.5"/>')
    # RagTrace
    b.append(caption(30, 306, "B · RagTrace  ←  filled once per run  →  read by every debug surface (one schema)"))
    _, ch = box(30, 322, 200, 80, "chain", "RAGChain",
                ["fills self.trace"],
                mono_lines=["every stream_query"])
    b.append(_)
    _, tr = box(300, 322, 220, 96, "trace", "RagTrace",
                ["model · effective_config", "rewritten_query · candidates", "final_context · exact prompt"])
    b.append(_)
    b.append(arrow((230, 362), (300, 366), "produce"))
    outs = [("/ask  {debug:true}", 620, 316), ("scripts/debug_ask.py", 620, 360),
            ("chat-ui  🔍 toggle", 620, 404)]
    for name, x, y in outs:
        _, o = box(x, y, 240, 34, "api", None)
        b.append(_)
        b.append(f'<text x="{x+120}" y="{y+22}" text-anchor="middle" font-size="12.5" '
                 f'fill="{INK}">{esc(name)}</text>')
        b.append(arrow((520, 370), (x - 2, y + 17), None, color="#55617a"))
    # chokepoint C note
    b.append(f'<line x1="30" y1="450" x2="1010" y2="450" stroke="#e2e6ee" stroke-width="1.5"/>')
    b.append(caption(30, 486, "C · build_rag_pipeline  →  the only place retrieval logic lives (see diagram 4). Edit it once; production and evaluation both change."))
    b.append(caption(30, 516, "Master these three — all knobs, all retrieval, all observability — and you can scale, debug, and fix any part of the system."))
    write("d5_chokepoints", W, H, "".join(b))


# ===========================================================================
# D6 — eval == ship
# ===========================================================================
def d6():
    W, H = 1040, 500
    b = [title(30, 40, "6 · Eval == ship — evaluation drives the production code")]
    # prod lane
    _, pstore = box(60, 100, 220, 70, "store", "Milvus (talos_documents)",
                    ["approximate ANN search"])
    b.append(_)
    b.append(caption(60, 92, "PRODUCTION"))
    # eval lane
    _, estore = box(60, 330, 220, 70, "eval", "InMemoryVectorStore",
                    ["exact cosine · synthetic corpus"])
    b.append(_)
    b.append(caption(60, 322, "EVALUATION"))
    # shared core
    _, core = box(430, 190, 320, 130, "pipe", "SHARED CORE",
                  [],
                  mono_lines=["build_rag_pipeline(config, store)",
                              "RAG_PROMPT | llm | parse",
                              "RagConfig  (VariantConfig→RagConfig)"])
    b.append(_)
    b.append(f'<text x="590" y="182" text-anchor="middle" font-size="12" font-weight="bold" '
             f'fill="#2f74d0">same functions · same prompt · same config path</text>')
    b.append(arrow((280, 135), (430, 225), "store injected"))
    b.append(arrow((280, 365), (430, 285), "store injected"))
    # outputs
    _, prod = box(820, 120, 190, 66, "api", "/ask answer",
                  ["what users get"])
    b.append(_)
    _, rep = box(820, 320, 190, 76, "trace", "ablation report",
                 ["9 variants · IR + judge", "picks the shipped default"])
    b.append(_)
    b.append(arrow((750, 235), (820, 153), None))
    b.append(arrow((750, 275), (820, 350), None))
    b.append(caption(60, 445, "production_default is DERIVED from global_rag_config, so the measured row is always the deployed config."))
    b.append(caption(60, 467, "The one deliberate difference is the store: approximate ANN (prod) vs exact cosine (eval)."))
    write("d6_eval", W, H, "".join(b))


d1(); d2(); d3(); d4(); d5(); d6()
print("done")
