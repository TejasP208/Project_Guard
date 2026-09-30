"""Split extracted document text into bounded, overlapping embedding inputs."""

CHUNK_CHARACTERS = 3000
OVERLAP_CHARACTERS = 200
MAX_CHUNKS = 32


def chunk_document(text: str) -> list[str]:
    """Cover the entire document without cutting it off silently."""
    text = " ".join(text.split())
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARACTERS, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + CHUNK_CHARACTERS // 2, end)
            if boundary > start:
                end = boundary
        chunks.append(text[start:end].strip())
        if len(chunks) > MAX_CHUNKS:
            raise ValueError(
                f"Document is too long for semantic comparison (maximum {MAX_CHUNKS} chunks)."
            )
        if end == len(text):
            break
        start = max(start + 1, end - OVERLAP_CHARACTERS)

    return chunks
