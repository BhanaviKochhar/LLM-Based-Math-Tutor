"""frontend/config.py -- small app-wide flags shared across frontend modules."""

# Flip to False to use the real NCERT backend (scripts.llm). The backend itself
# is untouched -- the functions below only call into it.
MOCK_MODE = False
