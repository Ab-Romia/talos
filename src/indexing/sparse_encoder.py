"""
Sparse Vector Encoder for Hybrid Search.

Provides BM25-style sparse vector encoding for use with Milvus hybrid search.
Supports multiple sparse encoding strategies:
1. BM25 - Classic TF-IDF with length normalization
2. SPLADE - Neural sparse encoding (if available)
3. TF-IDF - Standard term frequency-inverse document frequency
"""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
import hashlib

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SparseVector:
    """Represents a sparse vector with dimension-value pairs."""

    indices: List[int]
    values: List[float]

    def to_dict(self) -> Dict[int, float]:
        """Convert to dictionary format for Milvus."""
        return dict(zip(self.indices, self.values))

    @classmethod
    def from_dict(cls, data: Dict[int, float]) -> "SparseVector":
        """Create from dictionary."""
        indices = list(data.keys())
        values = list(data.values())
        return cls(indices=indices, values=values)

    def __len__(self) -> int:
        return len(self.indices)


@dataclass
class BM25Stats:
    """Statistics for BM25 scoring."""

    doc_count: int = 0
    avg_doc_length: float = 0.0
    doc_frequencies: Dict[int, int] = field(default_factory=dict)
    total_tokens: int = 0


class SparseEncoder:
    """
    Base class for sparse vector encoders.

    Converts text into sparse vectors for hybrid search.
    """

    def __init__(
        self,
        vocab_size: int = 30000,
        lowercase: bool = True,
        remove_stopwords: bool = True,
        min_token_length: int = 2,
    ):
        """
        Initialize the sparse encoder.

        Args:
            vocab_size: Maximum vocabulary size (hash space)
            lowercase: Convert text to lowercase
            remove_stopwords: Remove common stopwords
            min_token_length: Minimum token length to include
        """
        self.vocab_size = vocab_size
        self.lowercase = lowercase
        self.remove_stopwords = remove_stopwords
        self.min_token_length = min_token_length

        # English stopwords (can be extended)
        self.stopwords: Set[str] = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
            "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
            "to", "was", "were", "will", "with", "the", "this", "but", "they",
            "have", "had", "what", "when", "where", "who", "which", "why", "how",
            "all", "each", "every", "both", "few", "more", "most", "other",
            "some", "such", "no", "nor", "not", "only", "own", "same", "so",
            "than", "too", "very", "can", "just", "should", "now", "or", "if",
            "about", "into", "through", "during", "before", "after", "above",
            "below", "between", "under", "again", "further", "then", "once",
        }

    def tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into words.

        Args:
            text: Input text

        Returns:
            List of tokens
        """
        if self.lowercase:
            text = text.lower()

        # Simple word tokenization (alphanumeric sequences)
        tokens = re.findall(r'\b[a-zA-Z0-9]+\b', text)

        # Filter tokens
        filtered = []
        for token in tokens:
            if len(token) < self.min_token_length:
                continue
            if self.remove_stopwords and token in self.stopwords:
                continue
            filtered.append(token)

        return filtered

    def token_to_index(self, token: str) -> int:
        """
        Convert token to vocabulary index using hashing.

        Args:
            token: Input token

        Returns:
            Vocabulary index
        """
        # Use SHA256 hash and take modulo vocab_size
        hash_value = int(hashlib.sha256(token.encode()).hexdigest(), 16)
        return hash_value % self.vocab_size

    def encode(self, text: str) -> SparseVector:
        """
        Encode text into a sparse vector.

        Args:
            text: Input text

        Returns:
            Sparse vector
        """
        raise NotImplementedError("Subclasses must implement encode()")

    def encode_batch(self, texts: List[str]) -> List[SparseVector]:
        """
        Encode multiple texts into sparse vectors.

        Args:
            texts: List of input texts

        Returns:
            List of sparse vectors
        """
        return [self.encode(text) for text in texts]


class BM25Encoder(SparseEncoder):
    """
    BM25 sparse encoder for text.

    Implements the BM25 ranking function as sparse vectors.
    Suitable for hybrid search with dense embeddings.

    BM25 Formula:
    score(D,Q) = Σ IDF(qi) * (f(qi,D) * (k1 + 1)) / (f(qi,D) + k1 * (1 - b + b * |D|/avgdl))

    Where:
    - f(qi,D) = frequency of term qi in document D
    - |D| = length of document D
    - avgdl = average document length
    - k1, b = tuning parameters
    """

    def __init__(
        self,
        vocab_size: int = 30000,
        k1: float = 1.5,
        b: float = 0.75,
        lowercase: bool = True,
        remove_stopwords: bool = True,
        min_token_length: int = 2,
    ):
        """
        Initialize BM25 encoder.

        Args:
            vocab_size: Maximum vocabulary size
            k1: Term frequency saturation parameter (1.2-2.0)
            b: Length normalization parameter (0.0-1.0, typically 0.75)
            lowercase: Convert text to lowercase
            remove_stopwords: Remove common stopwords
            min_token_length: Minimum token length
        """
        super().__init__(vocab_size, lowercase, remove_stopwords, min_token_length)
        self.k1 = k1
        self.b = b
        self.stats = BM25Stats()
        self._fitted = False

    def fit(self, documents: List[str]) -> "BM25Encoder":
        """
        Fit the encoder on a corpus of documents.

        Computes document frequencies and average document length.

        Args:
            documents: List of documents to fit on

        Returns:
            Self for chaining
        """
        logger.info(f"Fitting BM25 encoder on {len(documents)} documents")

        self.stats = BM25Stats()
        total_length = 0

        for doc in documents:
            tokens = self.tokenize(doc)
            total_length += len(tokens)
            self.stats.doc_count += 1

            # Count unique terms per document
            unique_terms = set()
            for token in tokens:
                idx = self.token_to_index(token)
                unique_terms.add(idx)

            # Update document frequencies
            for idx in unique_terms:
                self.stats.doc_frequencies[idx] = self.stats.doc_frequencies.get(idx, 0) + 1

        self.stats.avg_doc_length = total_length / max(1, self.stats.doc_count)
        self.stats.total_tokens = total_length
        self._fitted = True

        logger.info(
            f"BM25 encoder fitted: {self.stats.doc_count} docs, "
            f"avg length {self.stats.avg_doc_length:.1f}, "
            f"vocab size {len(self.stats.doc_frequencies)}"
        )

        return self

    def _compute_idf(self, term_idx: int) -> float:
        """
        Compute IDF for a term.

        Uses Robertson-Sparck Jones formula:
        IDF = log((N - n + 0.5) / (n + 0.5) + 1)
        """
        n = self.stats.doc_frequencies.get(term_idx, 0)
        N = self.stats.doc_count

        # Smoothed IDF to avoid negative values
        idf = math.log((N - n + 0.5) / (n + 0.5) + 1)
        return max(0.0, idf)  # Ensure non-negative

    def encode(self, text: str) -> SparseVector:
        """
        Encode text using BM25 weights.

        Args:
            text: Input text

        Returns:
            BM25-weighted sparse vector
        """
        tokens = self.tokenize(text)

        if not tokens:
            return SparseVector(indices=[], values=[])

        # Count term frequencies
        term_freqs: Dict[int, int] = Counter()
        for token in tokens:
            idx = self.token_to_index(token)
            term_freqs[idx] += 1

        doc_length = len(tokens)
        avg_dl = self.stats.avg_doc_length if self._fitted else doc_length

        # Compute BM25 weights
        indices = []
        values = []

        for idx, tf in term_freqs.items():
            # IDF component
            if self._fitted:
                idf = self._compute_idf(idx)
            else:
                # Without fitting, use uniform IDF
                idf = 1.0

            # TF component with saturation and length normalization
            length_norm = 1 - self.b + self.b * (doc_length / avg_dl)
            tf_component = (tf * (self.k1 + 1)) / (tf + self.k1 * length_norm)

            # Final BM25 weight
            weight = idf * tf_component

            if weight > 0:
                indices.append(idx)
                values.append(weight)

        return SparseVector(indices=indices, values=values)

    def encode_query(self, query: str) -> SparseVector:
        """
        Encode a query using BM25 weights.

        For queries, we use a simplified version without length normalization.

        Args:
            query: Query text

        Returns:
            BM25-weighted sparse vector
        """
        tokens = self.tokenize(query)

        if not tokens:
            return SparseVector(indices=[], values=[])

        term_freqs: Dict[int, int] = Counter()
        for token in tokens:
            idx = self.token_to_index(token)
            term_freqs[idx] += 1

        indices = []
        values = []

        for idx, tf in term_freqs.items():
            if self._fitted:
                idf = self._compute_idf(idx)
            else:
                idf = 1.0

            # Query TF is typically just binary or log-scaled
            tf_weight = math.log(1 + tf)
            weight = idf * tf_weight

            if weight > 0:
                indices.append(idx)
                values.append(weight)

        return SparseVector(indices=indices, values=values)

    def save(self, path: str) -> None:
        """Save encoder state to file."""
        import json

        state = {
            "vocab_size": self.vocab_size,
            "k1": self.k1,
            "b": self.b,
            "lowercase": self.lowercase,
            "remove_stopwords": self.remove_stopwords,
            "min_token_length": self.min_token_length,
            "stats": {
                "doc_count": self.stats.doc_count,
                "avg_doc_length": self.stats.avg_doc_length,
                "doc_frequencies": {str(k): v for k, v in self.stats.doc_frequencies.items()},
                "total_tokens": self.stats.total_tokens,
            },
            "fitted": self._fitted,
        }

        with open(path, 'w') as f:
            json.dump(state, f)

        logger.info(f"BM25 encoder saved to {path}")

    @classmethod
    def load(cls, path: str) -> "BM25Encoder":
        """Load encoder state from file."""
        import json

        with open(path, 'r') as f:
            state = json.load(f)

        encoder = cls(
            vocab_size=state["vocab_size"],
            k1=state["k1"],
            b=state["b"],
            lowercase=state["lowercase"],
            remove_stopwords=state["remove_stopwords"],
            min_token_length=state["min_token_length"],
        )

        encoder.stats = BM25Stats(
            doc_count=state["stats"]["doc_count"],
            avg_doc_length=state["stats"]["avg_doc_length"],
            doc_frequencies={int(k): v for k, v in state["stats"]["doc_frequencies"].items()},
            total_tokens=state["stats"]["total_tokens"],
        )
        encoder._fitted = state["fitted"]

        logger.info(f"BM25 encoder loaded from {path}")
        return encoder


class TFIDFEncoder(SparseEncoder):
    """
    TF-IDF sparse encoder.

    Simpler alternative to BM25 for sparse vector encoding.
    """

    def __init__(
        self,
        vocab_size: int = 30000,
        sublinear_tf: bool = True,
        lowercase: bool = True,
        remove_stopwords: bool = True,
        min_token_length: int = 2,
    ):
        """
        Initialize TF-IDF encoder.

        Args:
            vocab_size: Maximum vocabulary size
            sublinear_tf: Use log(1 + tf) instead of raw tf
            lowercase: Convert text to lowercase
            remove_stopwords: Remove common stopwords
            min_token_length: Minimum token length
        """
        super().__init__(vocab_size, lowercase, remove_stopwords, min_token_length)
        self.sublinear_tf = sublinear_tf
        self.doc_count = 0
        self.doc_frequencies: Dict[int, int] = {}
        self._fitted = False

    def fit(self, documents: List[str]) -> "TFIDFEncoder":
        """Fit encoder on document corpus."""
        self.doc_count = 0
        self.doc_frequencies = {}

        for doc in documents:
            tokens = self.tokenize(doc)
            self.doc_count += 1

            unique_terms = set()
            for token in tokens:
                idx = self.token_to_index(token)
                unique_terms.add(idx)

            for idx in unique_terms:
                self.doc_frequencies[idx] = self.doc_frequencies.get(idx, 0) + 1

        self._fitted = True
        return self

    def encode(self, text: str) -> SparseVector:
        """Encode text using TF-IDF weights."""
        tokens = self.tokenize(text)

        if not tokens:
            return SparseVector(indices=[], values=[])

        term_freqs: Dict[int, int] = Counter()
        for token in tokens:
            idx = self.token_to_index(token)
            term_freqs[idx] += 1

        indices = []
        values = []

        for idx, tf in term_freqs.items():
            # TF component
            if self.sublinear_tf:
                tf_weight = math.log(1 + tf)
            else:
                tf_weight = tf

            # IDF component
            if self._fitted:
                df = self.doc_frequencies.get(idx, 1)
                idf = math.log(self.doc_count / df) + 1
            else:
                idf = 1.0

            weight = tf_weight * idf

            if weight > 0:
                indices.append(idx)
                values.append(weight)

        # L2 normalize
        norm = math.sqrt(sum(v * v for v in values))
        if norm > 0:
            values = [v / norm for v in values]

        return SparseVector(indices=indices, values=values)


class SPLADEEncoder(SparseEncoder):
    """
    SPLADE neural sparse encoder wrapper.

    Uses a neural model to generate sparse representations.
    Requires the `splade` package to be installed.
    """

    def __init__(
        self,
        model_name: str = "naver/splade-cocondenser-ensembledistil",
        max_length: int = 256,
        device: str = "cpu",
    ):
        """
        Initialize SPLADE encoder.

        Args:
            model_name: HuggingFace model name
            max_length: Maximum sequence length
            device: Device to use (cpu/cuda)
        """
        super().__init__()
        self.model_name = model_name
        self.max_length = max_length
        self.device = device
        self._model = None
        self._tokenizer = None

    def _load_model(self) -> None:
        """Lazy load the SPLADE model."""
        if self._model is not None:
            return

        try:
            from transformers import AutoModelForMaskedLM, AutoTokenizer
            import torch

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForMaskedLM.from_pretrained(self.model_name)
            self._model.to(self.device)
            self._model.eval()

            logger.info(f"Loaded SPLADE model: {self.model_name}")

        except ImportError:
            raise ImportError(
                "SPLADE encoder requires transformers and torch. "
                "Install with: pip install transformers torch"
            )

    def encode(self, text: str) -> SparseVector:
        """Encode text using SPLADE."""
        self._load_model()

        import torch

        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            max_length=self.max_length,
            truncation=True,
            padding=True,
        ).to(self.device)

        with torch.no_grad():
            outputs = self._model(**inputs)
            logits = outputs.logits

        # SPLADE activation: log(1 + ReLU(logits)) * attention_mask
        activations = torch.log(1 + torch.relu(logits))
        activations = activations * inputs["attention_mask"].unsqueeze(-1)

        # Max pooling over sequence length
        sparse_rep = torch.max(activations, dim=1)[0].squeeze()

        # Convert to sparse format
        non_zero_indices = sparse_rep.nonzero().squeeze().cpu().numpy()
        non_zero_values = sparse_rep[non_zero_indices].cpu().numpy()

        if non_zero_indices.ndim == 0:
            non_zero_indices = [int(non_zero_indices)]
            non_zero_values = [float(non_zero_values)]
        else:
            non_zero_indices = non_zero_indices.tolist()
            non_zero_values = non_zero_values.tolist()

        return SparseVector(indices=non_zero_indices, values=non_zero_values)


def create_sparse_encoder(
    encoder_type: str = "bm25",
    **kwargs,
) -> SparseEncoder:
    """
    Factory function to create a sparse encoder.

    Args:
        encoder_type: Type of encoder ("bm25", "tfidf", "splade")
        **kwargs: Encoder-specific arguments

    Returns:
        Sparse encoder instance
    """
    encoder_type = encoder_type.lower()

    if encoder_type == "bm25":
        return BM25Encoder(**kwargs)
    elif encoder_type == "tfidf":
        return TFIDFEncoder(**kwargs)
    elif encoder_type == "splade":
        return SPLADEEncoder(**kwargs)
    else:
        raise ValueError(f"Unknown encoder type: {encoder_type}")
