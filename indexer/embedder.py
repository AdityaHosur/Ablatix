"""
Embedding logic for Ablatix Indexer.
Supports BGE-M3 (text) embeddings and cross-encoder reranking.
"""

from typing import List, Union, Optional
import torch

try:
    from transformers import AutoTokenizer, AutoModel
except ImportError:
    AutoTokenizer = None
    AutoModel = None

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None


class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", device: Optional[str] = None):
        """
        Initialize the embedder.
        :param model_name: Hugging Face model name for BGE-M3.
        :param device: 'cuda', 'cpu', or None for auto.
        """
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        if AutoTokenizer is None or AutoModel is None:
            raise ImportError("Please install transformers for BGE-M3 support.")

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(self.device)

    def embed_text(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        :param texts: Single string or list of strings.
        :return: List of embedding vectors.
        """
        if isinstance(texts, str):
            texts = [texts]

        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            return_tensors="pt"
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)
            embeddings = outputs.last_hidden_state[:, 0, :].cpu().numpy()

        return embeddings.tolist()


class Reranker:
    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        device: Optional[str] = None
    ):
        """
        Initialize the reranker.
        :param model_name: Hugging Face cross-encoder model name.
        :param device: 'cuda', 'cpu', or None for auto.
        """
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.use_cross_encoder = CrossEncoder is not None

        if self.use_cross_encoder:
            # Use sentence-transformers CrossEncoder (recommended)
            self.model = CrossEncoder(model_name, device=self.device)
        else:
            # Fallback: use transformers directly
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)

    def rerank(self, query: str, docs: List[str]) -> List[float]:
        """
        Rerank documents based on query relevance.
        :param query: Query string.
        :param docs: List of document strings.
        :return: List of relevance scores.
        """
        if not docs:
            return []

        if self.use_cross_encoder:
            # sentence-transformers CrossEncoder predict
            pairs = [[query, doc] for doc in docs]
            scores = self.model.predict(pairs)
            return scores.tolist()
        else:
            # Fallback: use transformers directly
            pairs = [[query, doc] for doc in docs]
            inputs = self.tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512
            ).to(self.device)

            with torch.no_grad():
                outputs = self.model(**inputs)
                scores = outputs.logits.squeeze(-1).cpu().numpy()

            return scores.tolist()