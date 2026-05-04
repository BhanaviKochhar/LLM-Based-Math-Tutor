"""Retrieve semantically relevant textbook chunks from a FAISS vector store.

This module handles the retrieval stage of the Phase 1 pipeline:
- load a saved CPU FAISS index from vector_store.py
- load aligned retrieval metadata from disk
- initialize the same sentence-transformers model used for indexing
- encode and normalize a user query for cosine-similarity search
- return top-k retrieval results and build a readable context string
"""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import logging

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

try:
    from src.config import PROJECT_ROOT
except ModuleNotFoundError:
    from config import PROJECT_ROOT


LOGGER = logging.getLogger(__name__)
INDEXES_DIR = PROJECT_ROOT / "indexes"
DEFAULT_INDEX_PATH = INDEXES_DIR / "faiss.index"
DEFAULT_METADATA_PATH = INDEXES_DIR / "metadata.json"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


def load_faiss_index(index_path: Path) -> faiss.Index:
    """Load a FAISS index from disk and validate that it exists."""

    source = Path(index_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"FAISS index file does not exist: {source}")
    if not source.is_file():
        raise FileNotFoundError(f"FAISS index path is not a file: {source}")

    try:
        index = faiss.read_index(str(source))
    except RuntimeError as error:
        raise RuntimeError(f"Failed to load FAISS index from {source}: {error}") from error

    if index.ntotal == 0:
        raise ValueError(f"Loaded FAISS index is empty: {source}")

    return index


def load_metadata(metadata_path: Path) -> list[dict]:
    """Load aligned retrieval metadata from disk and validate its schema."""

    source = Path(metadata_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Metadata file does not exist: {source}")
    if not source.is_file():
        raise FileNotFoundError(f"Metadata path is not a file: {source}")

    try:
        metadata = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Metadata file is not valid JSON: {source}") from error

    if not isinstance(metadata, list):
        raise ValueError("Expected metadata JSON to contain a list of records.")

    required_keys = {"chunk_id", "text", "source", "page"}
    for index, record in enumerate(metadata, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Metadata record at index {index} must be a JSON object.")
        missing_keys = required_keys - record.keys()
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise ValueError(
                f"Metadata record at index {index} is missing required keys: {missing}"
            )

    return metadata


def load_model(model_name: str = EMBEDDING_MODEL_NAME) -> SentenceTransformer:
    """Load the same embedding model used during indexing on CPU."""

    LOGGER.info("Loading embedding model: %s", model_name)
    try:
        return SentenceTransformer(model_name, device="cpu")
    except Exception as error:
        raise RuntimeError(
            "Failed to load the sentence-transformers model "
            f"'{model_name}'. Ensure the model is available locally or that "
            "network access is available to download it."
        ) from error


def encode_query(model: SentenceTransformer, query: str) -> np.ndarray:
    """Encode a query into a normalized float32 vector with shape (1, dim)."""

    if not isinstance(query, str):
        raise TypeError("Query must be a string.")

    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Query must not be empty.")

    embedding = model.encode(
        normalized_query,
        convert_to_numpy=True,
        show_progress_bar=False,
        normalize_embeddings=False,
    )
    query_vector = np.asarray(embedding, dtype=np.float32).reshape(1, -1)

    if query_vector.shape[1] == 0:
        raise ValueError("Encoded query has zero dimensions.")

    faiss.normalize_L2(query_vector)
    return query_vector


def retrieve(
    query: str,
    index: faiss.Index,
    metadata: list[dict],
    model: SentenceTransformer,
    top_k: int = 3,
) -> list[dict]:
    """Retrieve the top-k most relevant chunks for a user query."""

    if top_k <= 0:
        raise ValueError(f"top_k must be greater than 0, received {top_k}.")

    if index.ntotal != len(metadata):
        raise ValueError(
            "FAISS index and metadata are misaligned: "
            f"{index.ntotal} vectors vs {len(metadata)} metadata records."
        )

    search_k = min(top_k, len(metadata))
    query_vector = encode_query(model, query)
    distances, indices = index.search(query_vector, search_k)

    results: list[dict] = []
    for distance, metadata_index in zip(distances[0], indices[0], strict=True):
        if metadata_index < 0:
            continue
        if metadata_index >= len(metadata):
            raise IndexError(
                "FAISS returned an out-of-range metadata index: "
                f"{metadata_index} for metadata length {len(metadata)}."
            )

        record = metadata[metadata_index]
        results.append(
            {
                "text": record["text"],
                "score": float(distance), # similarity score (higher is better)
                "source": record["source"],
                "page": record["page"],
            }
        )

    LOGGER.info("Query: %s", query)
    LOGGER.info("Retrieved %s results.", len(results))
    return results


def build_context(results: list[dict]) -> str:
    """Combine retrieved chunks into a readable context string."""

    if not results:
        return ""

    sections: list[str] = []
    for index, result in enumerate(results, start=1):
        sections.append(
            "\n".join(
                [
                    f"Result {index}:",
                    f"Source: {result['source']}",
                    f"Page: {result['page']}",
                    f"Score: {result['score']:.4f}",
                    f"Text: {result['text']}",
                ]
            )
        )

    return "\n---\n".join(sections)


def build_argument_parser() -> argparse.ArgumentParser:
    """Create a CLI for local retrieval testing."""

    parser = argparse.ArgumentParser(description="Run semantic retrieval against a FAISS index.")
    parser.add_argument(
        "--query",
        required=True,
        help="The user query to retrieve relevant textbook chunks for.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help="Path to the saved FAISS index file.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=DEFAULT_METADATA_PATH,
        help="Path to the aligned metadata JSON file.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of top results to return.",
    )
    parser.add_argument(
        "--model-name",
        default=EMBEDDING_MODEL_NAME,
        help="Sentence-transformers model name used for query encoding.",
    )
    return parser


def format_results_for_cli(query: str, results: list[dict]) -> str:
    """Format retrieval results for terminal output."""

    lines = [f"Query: {query}", ""]
    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                f"Result {index}:",
                f"Score: {result['score']:.2f}",
                f"Text: {result['text']}",
                f"Source: {result['source']}",
                f"Page: {result['page']}",
                "",
                "---",
                "",
            ]
        )

    if results:
        return "\n".join(lines[:-3])
    return "\n".join(lines)


def main() -> None:
    """Run retrieval from the command line."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    parser = build_argument_parser()
    args = parser.parse_args()

    index = load_faiss_index(args.index)
    metadata = load_metadata(args.metadata)
    model = load_model(args.model_name)
    results = retrieve(
        query=args.query,
        index=index,
        metadata=metadata,
        model=model,
        top_k=args.top_k,
    )

    print(format_results_for_cli(args.query, results))


if __name__ == "__main__":
    main()
