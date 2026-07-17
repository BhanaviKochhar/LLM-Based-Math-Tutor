"""
Integration test for the retrieve() -> generate() handoff.
Verifies retrieve() output matches the team's interface contract:
retrieve(question, grade) -> list of 3 chunk strings
"""

from scripts.retrieval import retrieve  # adjust import to your actual file/function location


def mock_generate(question, grade, chunks):
    """Stand-in for teammate's generate() function.
    Just checks the inputs are what generate() expects."""
    assert isinstance(question, str) and len(question) > 0
    assert isinstance(grade, int)
    assert isinstance(chunks, list)
    assert len(chunks) == 3, f"Expected 3 chunks, got {len(chunks)}"
    for i, chunk in enumerate(chunks):
        assert isinstance(chunk, str), f"Chunk {i} is not a string: {type(chunk)}"
        assert len(chunk.strip()) > 0, f"Chunk {i} is empty"
    return f"[MOCK ANSWER] Would answer '{question}' for Class {grade} using {len(chunks)} chunks."


def test_handoff():
    test_cases = [
        ("What is addition?", 1),
        ("How do I subtract two-digit numbers?", 2),
        ("What are fractions?", 4),
        ("How do decimals work?", 5),
    ]

    for question, grade in test_cases:
        chunks = retrieve(question, grade)
        answer = mock_generate(question, grade, chunks)
        print(f"PASS | Class {grade} | {question}")
        print(f"     -> {answer}\n")

    print("All integration tests passed. retrieve() matches the contract.")


if __name__ == "__main__":
    test_handoff()