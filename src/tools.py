"""Knowledge retrieval for Ramit agent. Self-contained — reads built artifacts directly."""
import json
import os
import logging
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = Path(os.getenv("KNOWLEDGE_OUTPUT_DIR", str(_ROOT / "knowledge" / "output" / "ramit-sethi")))
_MODEL_NAME = "all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None
_records: list[dict] = []
_embeddings: np.ndarray | None = None
_runtime_context: str = ""


def load_knowledge() -> None:
    """Load the embedding index and runtime context. Safe to call multiple times."""
    global _model, _records, _embeddings, _runtime_context
    if _model is not None:
        return

    logger.info(f"Loading knowledge index from {_DATA_DIR} ...")
    _model = SentenceTransformer(_MODEL_NAME)

    records = []
    index_path = _DATA_DIR / "evidence_index.jsonl"
    with index_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                if rec.get("embedding"):
                    records.append(rec)
    _records = records
    _embeddings = np.array([r["embedding"] for r in records], dtype=np.float32)

    ctx_path = _DATA_DIR / "runtime_context.md"
    _runtime_context = ctx_path.read_text() if ctx_path.exists() else ""

    logger.info(f"Loaded {len(records)} chunks.")


def query_knowledge(query: str, top_k: int = 6) -> str:
    """Retrieve Ramit knowledge for a query. Returns runtime context + top-k source chunks."""
    if _model is None:
        load_knowledge()

    q_vec = np.array(_model.encode(query, normalize_embeddings=True), dtype=np.float32)
    scores = _embeddings @ q_vec
    top_indices = np.argsort(scores)[::-1][:top_k].tolist()

    chunks = []
    for i in top_indices:
        rec = _records[i]
        tags = ", ".join(rec.get("tags", []))
        meta = f"[{rec.get('category', 'general')}] {tags} | {rec.get('tier', '')} | {rec.get('confidence', '')}"
        chunks.append(f"### {meta}\n{rec['text']}")

    return (
        f"## Core Persona Context\n{_runtime_context}\n\n"
        f"## Relevant Source Chunks\n\n" + "\n\n".join(chunks)
    )
