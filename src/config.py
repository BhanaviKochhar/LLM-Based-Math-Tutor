"""Central configuration values for the Phase 1 math tutor project."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXTRACTED_DATA_DIR = DATA_DIR / "extracted" / "class3NCERT"
INTERIM_DATA_DIR = DATA_DIR / "interim"
RAW_DOCUMENTS_PATH = INTERIM_DATA_DIR / "raw_documents.json"
