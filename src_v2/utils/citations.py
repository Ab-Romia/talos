"""Citation handling utilities."""


def format_citations(documents) -> str:
    if not documents:
        return ""

    citations = []
    seen_sources = set()

    for i, doc in enumerate(documents, 1):
        source = doc.metadata.get("source", "Unknown")

        if source in seen_sources:
            continue
        seen_sources.add(source)

        page = doc.metadata.get("page")
        if page is not None:
            citations.append(f"[{i}] {source} (page {page})")
        else:
            citations.append(f"[{i}] {source}")

    if citations:
        return "\n\nSources:\n" + "\n".join(citations)
    return ""


def add_citations_to_response(response: str, documents) -> str:
    citations = format_citations(documents)
    return response + citations if citations else response
