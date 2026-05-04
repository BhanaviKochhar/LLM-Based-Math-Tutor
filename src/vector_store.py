"""Build a FAISS vector index for semantic retrieval.

This module handles the vector store stage of the Phase 1 pipeline:
- load embedding records produced by embedding.py
- convert embeddings into a float32 NumPy matrix
- normalize vectors for cosine similarity with FAISS inner product search
- build and save a CPU FAISS index
- save aligned metadata for retrieval-time lookup
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import json
import logging

import faiss
import numpy as np

try:
    from src.config import PROJECT_ROOT
except ModuleNotFoundError:
    from config import PROJECT_ROOT


LOGGER = logging.getLogger(__name__)
INDEXES_DIR = PROJECT_ROOT / "indexes"
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "processed" / "embeddings.json"
DEFAULT_INDEX_PATH = INDEXES_DIR / "faiss.index"
DEFAULT_METADATA_PATH = INDEXES_DIR / "metadata.json"


def load_embeddings(input_path: Path | str = DEFAULT_INPUT_PATH) -> list[dict[str, Any]]:
    """Load embedding records from disk."""

    source = Path(input_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Embeddings file does not exist: {source}")

    records = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Expected embeddings JSON to contain a list of records.")

    required_keys = {"chunk_id", "text", "embedding", "source", "page"}
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Embedding record at index {index} must be a JSON object.")
        missing_keys = required_keys - record.keys()
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise ValueError(
                f"Embedding record at index {index} is missing required keys: {missing}"
            )

    return records


def prepare_vectors(records: list[dict[str, Any]]) -> np.ndarray:
    """Convert stored embeddings into a normalized float32 matrix."""

    if not records:
        raise ValueError("Cannot build a vector store from an empty embeddings list.")

    raw_embeddings = [record["embedding"] for record in records]
    vectors = np.asarray(raw_embeddings, dtype=np.float32)

    if vectors.ndim != 2:
        raise ValueError(
            f"Expected embeddings to form a 2D matrix, but received shape {vectors.shape}."
        )
    if vectors.shape[1] == 0:
        raise ValueError("Embedding vectors must have a non-zero dimension.")

    embedding_dimension = vectors.shape[1]
    for index, embedding in enumerate(raw_embeddings, start=1):
        if len(embedding) != embedding_dimension:
            raise ValueError(
                "Inconsistent embedding dimension detected at record "
                f"{index}: expected {embedding_dimension}, received {len(embedding)}."
            )

    faiss.normalize_L2(vectors)
    LOGGER.info("Prepared %s vectors with dimension %s", vectors.shape[0], embedding_dimension)
    return vectors


def build_faiss_index(vectors: np.ndarray) -> faiss.IndexFlatIP:
    """Create an inner-product FAISS index over normalized vectors."""

    if vectors.dtype != np.float32:
        raise ValueError(f"FAISS requires float32 vectors, received {vectors.dtype}.")
    if vectors.ndim != 2:
        raise ValueError("FAISS index input must be a 2D matrix.")

    dimension = vectors.shape[1]
    LOGGER.info("Creating FAISS IndexFlatIP with dimension %s", dimension)
    index = faiss.IndexFlatIP(dimension)
    index.add(vectors)
    LOGGER.info("Added %s vectors to the FAISS index", index.ntotal)
    return index


def save_index(index: faiss.Index, index_path: Path | str = DEFAULT_INDEX_PATH) -> Path:
    """Persist the FAISS index to disk."""

    destination = Path(index_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(destination))
    return destination


def save_metadata(
    records: list[dict[str, Any]],
    metadata_path: Path | str = DEFAULT_METADATA_PATH,
) -> Path:
    """Save retrieval metadata in the same order as vectors were indexed."""

    destination = Path(metadata_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    metadata = [
        {
            "chunk_id": record["chunk_id"],
            "text": record["text"],
            "source": record["source"],
            "page": record["page"],
        }
        for record in records
    ]

    destination.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return destination


def build_argument_parser() -> argparse.ArgumentParser:
    """Create a CLI for local vector store builds."""

    parser = argparse.ArgumentParser(description="Build a FAISS vector index from embeddings.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to embeddings JSON generated by embedding.py.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help="Path for saving the FAISS index file.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=DEFAULT_METADATA_PATH,
        help="Path for saving aligned metadata JSON.",
    )
    return parser


def main() -> None:
    """Run the vector store pipeline and save index artifacts."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    parser = build_argument_parser()
    args = parser.parse_args()

    records = load_embeddings(args.input)
    vectors = prepare_vectors(records)
    index = build_faiss_index(vectors)
    index_path = save_index(index, args.index)
    metadata_path = save_metadata(records, args.metadata)

    LOGGER.info("Loaded %s embedding records.", len(records))
    LOGGER.info("Saved FAISS index to %s", index_path)
    LOGGER.info("Saved metadata to %s", metadata_path)


if __name__ == "__main__":
    main()
