"""
db/vector_store.py

FAISS vector store for historical incident retrieval.
"""

import json
import os
import numpy as np
from pathlib import Path
from typing import Any
from langchain_core.tools import tool

# ── Paths ─────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).parent.parent / "data"
_PAST_INCIDENTS_PATH = _DATA_DIR / "past_incidents.json"

# ── Default Incidents Seed ────────────────────────────────────────────────────
DEFAULT_PAST_INCIDENTS = [
    {
        "text": "Inverter output dropped to zero despite normal solar capacity. Applying restart_inverter cleared the fault and restored normal output.",
        "system_id": "SYS_008",
        "action": "restart_inverter",
        "result": "success",
    },
    {
        "text": "Solar output was zero with healthy inverter flag during mid-day peak. restart_inverter was applied and output returned to 8kW.",
        "system_id": "SYS_014",
        "action": "restart_inverter",
        "result": "success",
    },
    {
        "text": "Battery state of charge (SOC) dropped from 80% to 15% in less than 2 hours. reset_battery_management was executed, which stabilized the SOC.",
        "system_id": "SYS_022",
        "action": "reset_battery_management",
        "result": "success",
    },
    {
        "text": "Battery management system reported rapid capacity loss and warning status. BMS reset cleared the warning and charge rate normalized.",
        "system_id": "SYS_032",
        "action": "reset_battery_management",
        "result": "success",
    },
    {
        "text": "System went completely offline with no telemetry for over 60 minutes. force_reconnect was attempted twice but failed. Escalated to technician.",
        "system_id": "SYS_018",
        "action": "escalate_issue",
        "result": "escalated",
    },
    {
        "text": "No communication from system for 45 minutes. force_reconnect was applied and communication was restored within 5 minutes.",
        "system_id": "SYS_044",
        "action": "force_reconnect",
        "result": "success",
    },
    {
        "text": "Solar output was below 30% of expected capacity under clear skies. clear_low_output_flag was applied after confirming no physical damage.",
        "system_id": "SYS_004",
        "action": "clear_low_output_flag",
        "result": "success",
    },
]


# ── Embedding Encoder (with fallback) ──────────────────────────────────────────

class CustomVectorEncoder:
    """
    A simple TF-IDF inspired vectorizer in pure Python to serve as an instant,
    dependency-free local fallback when no API keys are configured.
    """
    def __init__(self, vocabulary: list[str] | None = None):
        self.vocabulary = vocabulary or []
        self.idf = {}

    def fit(self, texts: list[str]) -> None:
        doc_tokens = []
        vocab = set()
        for text in texts:
            tokens = [w.lower() for w in text.split() if w.isalnum()]
            doc_tokens.append(tokens)
            vocab.update(tokens)
        
        self.vocabulary = sorted(list(vocab))
        n_docs = len(texts)
        
        for term in self.vocabulary:
            doc_freq = sum(1 for doc in doc_tokens if term in doc)
            self.idf[term] = np.log((1 + n_docs) / (1 + doc_freq)) + 1

    def encode(self, texts: list[str]) -> np.ndarray:
        if not self.vocabulary:
            self.fit(texts)

        vectors = []
        for text in texts:
            tokens = [w.lower() for w in text.split() if w.isalnum()]
            vector = np.zeros(len(self.vocabulary), dtype=np.float32)
            for token in tokens:
                if token in self.idf:
                    idx = self.vocabulary.index(token)
                    vector[idx] += self.idf[token]
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm
            vectors.append(vector)
        return np.array(vectors, dtype=np.float32)


# ── Vector Store Index ────────────────────────────────────────────────────────

class IncidentVectorStore:
    def __init__(self):
        self.incidents = []
        self.index = None
        self.encoder = CustomVectorEncoder()
        self.load_or_build()

    def get_embeddings(self, texts: list[str]) -> np.ndarray:
        """
        Get embeddings using OpenAI if key is present, otherwise falls back to persistent CustomVectorEncoder.
        """
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)
                response = client.embeddings.create(
                    input=texts,
                    model="text-embedding-3-small"
                )
                embeddings = [data.embedding for data in response.data]
                return np.array(embeddings, dtype=np.float32)
            except Exception:
                pass

        # Fallback using our single, fitted encoder
        return self.encoder.encode(texts)

    def load_or_build(self) -> None:
        if not _PAST_INCIDENTS_PATH.exists():
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(_PAST_INCIDENTS_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_PAST_INCIDENTS, f, indent=2, ensure_ascii=False)
            self.incidents = DEFAULT_PAST_INCIDENTS
        else:
            with open(_PAST_INCIDENTS_PATH, encoding="utf-8") as f:
                self.incidents = json.load(f)

        # Fit encoder on all past incidents texts once
        corpus = [inc["text"] for inc in self.incidents]
        self.encoder.fit(corpus)

        try:
            import faiss
            embeddings = self.get_embeddings(corpus)
            dim = embeddings.shape[1]

            # Build FAISS index
            self.index = faiss.IndexFlatIP(dim)
            self.index.add(embeddings)
        except Exception:
            self.index = None

    def search(self, query: str, k: int = 2) -> list[dict[str, Any]]:
        if not self.incidents:
            return []

        query_emb = self.get_embeddings([query])

        if self.index is not None:
            try:
                scores, indices = self.index.search(query_emb, k)
                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx < len(self.incidents) and idx >= 0:
                        res = dict(self.incidents[idx])
                        res["similarity_score"] = float(score)
                        results.append(res)
                return results
            except Exception:
                pass

        # NumPy manual cosine similarity fallback using same persistent encoder
        corpus = [inc["text"] for inc in self.incidents]
        embeddings = self.get_embeddings(corpus)
        similarities = np.dot(embeddings, query_emb[0])
        top_indices = np.argsort(similarities)[::-1][:k]
        
        results = []
        for idx in top_indices:
            res = dict(self.incidents[idx])
            res["similarity_score"] = float(similarities[idx])
            results.append(res)
        return results


# Global singleton vector store instance
_vector_store = None

def get_vector_store() -> IncidentVectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = IncidentVectorStore()
    return _vector_store


# ── Registered Tool ───────────────────────────────────────────────────────────

@tool
def search_similar_incidents(query_text: str) -> dict:
    """
    Search historical operational records for past incidents and resolution outcomes
    similar to a current anomaly.

    Args:
        query_text: Description of the anomaly or issue to match, e.g. 'inverter output dropped to zero'.

    Returns:
        {
          "query": str,
          "results": list[dict],  # list of similar incident dictionaries
        }
    """
    store = get_vector_store()
    results = store.search(query_text, k=2)
    return {
        "query": query_text,
        "results": results,
    }
