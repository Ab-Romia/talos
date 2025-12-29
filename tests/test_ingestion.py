from unittest import TestCase

documents = ["docs/Requirements & Design/Requirements.md", "docs/TODO™.md"]


class Test(TestCase):
    def test_load_documents(self):
        import asyncio
        from langchain_core.documents import Document
        from src.rag.ingestion import load_documents

        async def _collect():
            out: list[Document] = []
            async for d in load_documents(documents):
                out.append(d)
            return out

        print("Starting document loading test...")
        docs = asyncio.run(_collect())
        print(f"Collected documents: {docs}")
