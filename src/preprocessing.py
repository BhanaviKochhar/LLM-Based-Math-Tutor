"""Clean extracted document text and convert it into embedding-ready chunks.

This module handles the second Phase 1 pipeline step:
- load raw PDF extraction output from JSON
- clean page text without aggressively altering meaning
- split text into overlapping chunks
- filter low-quality chunks
- save chunk records for downstream embedding
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import json
import logging
import re

try:
    from src.config import DATA_DIR, RAW_DOCUMENTS_PATH
except ModuleNotFoundError:
    from config import DATA_DIR, RAW_DOCUMENTS_PATH


LOGGER = logging.getLogger(__name__)
PROCESSED_DATA_DIR = DATA_DIR / "processed"
DEFAULT_INPUT_PATH = RAW_DOCUMENTS_PATH
DEFAULT_OUTPUT_PATH = PROCESSED_DATA_DIR / "chunks.json"
DEFAULT_CHUNK_SIZE = 100
DEFAULT_CHUNK_OVERLAP = 20
MIN_CHUNK_CHARACTERS = 20
HEADER_PATTERNS = (
    r"^Reprint\s+\d{4}(?:-\d{2})?$",
    r"^Maths Mela.*$",
)


def load_raw_documents(input_path: Path | str = DEFAULT_INPUT_PATH) -> list[dict[str, Any]]:
    """Load extracted raw documents from disk."""

    source = Path(input_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Raw documents file does not exist: {source}")

    documents = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(documents, list):
        raise ValueError("Expected raw documents JSON to contain a list of documents.")

    return documents


def clean_text(text: str) -> str:
    """Normalize whitespace and remove obvious page noise while keeping text readable."""

    cleaned_lines: list[str] = []

    for line in text.splitlines():
        normalized_line = re.sub(r"\s+", " ", line).strip()
        if not normalized_line:
            continue
        if any(re.fullmatch(pattern, normalized_line) for pattern in HEADER_PATTERNS):
            continue
        cleaned_lines.append(normalized_line)

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
    cleaned_text = re.sub(r" ?\n ?", "\n", cleaned_text)

    return cleaned_text.strip()


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into ordered, overlapping word chunks."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")
    if overlap < 0:
        raise ValueError("overlap cannot be negative.")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size.")

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    step = chunk_size - overlap

    for start_index in range(0, len(words), step):
        chunk_words = words[start_index : start_index + chunk_size]
        if not chunk_words:
            continue
        chunk = " ".join(chunk_words).strip()
        if len(chunk) >= MIN_CHUNK_CHARACTERS:
            chunks.append(chunk)
        if start_index + chunk_size >= len(words):
            break

    return chunks


def process_documents(
    documents: list[dict[str, Any]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """Convert raw page-wise documents into cleaned chunk records."""

    chunks: list[dict[str, Any]] = []

    for document in documents:
        file_name = document.get("file_name", "unknown.pdf")
        pages = document.get("pages", [])
        file_prefix = Path(file_name).stem
        file_chunk_count = 0

        for page in pages:
            page_number = page.get("page_number")
            page_text = page.get("text", "")
            cleaned_text = clean_text(page_text)
            page_chunks = chunk_text(cleaned_text, chunk_size=chunk_size, overlap=overlap)

            for page_chunk in page_chunks:
                file_chunk_count += 1
                chunks.append(
                    {
                        "chunk_id": f"{file_prefix}_{file_chunk_count}",
                        "text": page_chunk,
                        "source": file_name,
                        "page": page_number,
                    }
                )

        LOGGER.info("Processed %s into %s chunks", file_name, file_chunk_count)

    return chunks


def save_chunks(
    chunks: list[dict[str, Any]],
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Persist processed chunk data for downstream embedding."""

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return destination


def build_argument_parser() -> argparse.ArgumentParser:
    """Create a CLI for local preprocessing runs."""

    parser = argparse.ArgumentParser(description="Preprocess raw documents into chunks.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to raw document JSON generated by data_loader.py.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for saving processed chunks JSON.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Maximum number of words per chunk.",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=DEFAULT_CHUNK_OVERLAP,
        help="Number of overlapping words between consecutive chunks.",
    )
    return parser


def main() -> None:
    """Run the preprocessing pipeline and save chunk output."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    parser = build_argument_parser()
    args = parser.parse_args()

    documents = load_raw_documents(args.input)
    chunks = process_documents(documents, chunk_size=args.chunk_size, overlap=args.overlap)
    output_path = save_chunks(chunks, args.output)

    LOGGER.info("Loaded %s raw documents.", len(documents))
    LOGGER.info("Saved %s chunks to %s", len(chunks), output_path)


if __name__ == "__main__":
    main()
