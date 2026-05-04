"""Load NCERT PDF files and extract raw text page by page.

This module is intentionally narrow in scope for Phase 1:
- discover PDF files from the configured dataset directory
- extract raw text using PyMuPDF
- return structured, inspectable document objects

The output is kept page-aware because later preprocessing steps may need
document boundaries and page metadata for debugging and traceability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
import argparse
import json
import logging

import fitz

try:
    from src.config import EXTRACTED_DATA_DIR, RAW_DOCUMENTS_PATH
except ModuleNotFoundError:
    from config import EXTRACTED_DATA_DIR, RAW_DOCUMENTS_PATH


LOGGER = logging.getLogger(__name__)
DEFAULT_PDF_DIR = EXTRACTED_DATA_DIR
DEFAULT_OUTPUT_PATH = RAW_DOCUMENTS_PATH


@dataclass(slots=True)
class PageText:
    """Raw text extracted from a single PDF page."""

    page_number: int
    text: str


@dataclass(slots=True)
class PDFDocument:
    """Structured representation of one source PDF."""

    file_name: str
    source_path: str
    page_count: int
    pages: list[PageText]
    raw_text: str


def discover_pdf_files(pdf_dir: Path | str = DEFAULT_PDF_DIR) -> list[Path]:
    """Return sorted PDF files from the dataset directory.

    Sorting makes downstream behavior deterministic and easier to debug.
    """

    directory = Path(pdf_dir).expanduser().resolve()
    if not directory.exists():
        raise FileNotFoundError(f"PDF directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Expected a directory containing PDFs: {directory}")

    pdf_files = sorted(path for path in directory.iterdir() if path.suffix.lower() == ".pdf")
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in directory: {directory}")

    return pdf_files


def extract_text_from_pdf(pdf_path: Path | str) -> PDFDocument:
    """Extract page-wise text from a single PDF file."""

    path = Path(pdf_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF file does not exist: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file, received: {path}")

    pages: list[PageText] = []
    LOGGER.info("Extracting text from %s", path.name)

    try:
        with fitz.open(path) as pdf_document:
            page_count = pdf_document.page_count
            for page_index, page in enumerate(pdf_document, start=1):
                page_text = page.get_text("text").strip()
                if not page_text:
                    continue
                pages.append(PageText(page_number=page_index, text=page_text))
    except RuntimeError as exc:
        raise RuntimeError(f"Failed to read PDF file: {path}") from exc

    raw_text = "\n\n".join(page.text for page in pages if page.text)

    if not raw_text:
        LOGGER.warning("No text extracted from PDF: %s", path)
    else:
        LOGGER.info("Finished %s with %s non-empty extracted pages", path.name, len(pages))

    return PDFDocument(
        file_name=path.name,
        source_path=str(path),
        page_count=len(pages),
        pages=pages,
        raw_text=raw_text,
    )


def load_documents(pdf_dir: Path | str = DEFAULT_PDF_DIR) -> list[PDFDocument]:
    """Load all PDFs from the dataset directory and extract raw text."""

    pdf_files = discover_pdf_files(pdf_dir)
    documents = [extract_text_from_pdf(pdf_path) for pdf_path in pdf_files]
    return documents


def save_documents_to_json(
    documents: Iterable[PDFDocument],
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Persist extracted documents for inspection and later pipeline stages."""

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    serializable_documents = []
    for document in documents:
        serializable_document = asdict(document)
        serializable_documents.append(serializable_document)

    destination.write_text(
        json.dumps(serializable_documents, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return destination


def build_argument_parser() -> argparse.ArgumentParser:
    """Create a small CLI so this module can be tested independently."""

    parser = argparse.ArgumentParser(description="Extract raw text from NCERT PDFs.")
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=DEFAULT_PDF_DIR,
        help="Directory containing source PDF files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for saving extracted raw text as JSON.",
    )
    return parser


def main() -> None:
    """Run PDF loading and save extracted text for manual verification."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    parser = build_argument_parser()
    args = parser.parse_args()

    documents = load_documents(args.pdf_dir)
    output_path = save_documents_to_json(documents, args.output)

    LOGGER.info("Loaded %s PDF files.", len(documents))
    LOGGER.info("Saved extracted text to %s", output_path)


if __name__ == "__main__":
    main()
