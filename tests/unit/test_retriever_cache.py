from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestCrossEncoderCache:
    def test_cross_encoder_is_loaded_once(self):
        """The cross-encoder model is expensive to build. Repeated calls
        from get_retriever (one per chat message) must reuse the same
        instance instead of reinstantiating the transformer each time."""
        from rag.retrieval import retrievers

        retrievers._get_cross_encoder.cache_clear()

        with patch.object(
            retrievers,
            "HuggingFaceCrossEncoder",
            return_value=MagicMock(),
        ) as factory:
            first = retrievers._get_cross_encoder()
            second = retrievers._get_cross_encoder()

        assert first is second
        assert factory.call_count == 1
