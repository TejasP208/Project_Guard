"""Split extracted document text into bounded, overlapping embedding inputs."""

CHUNK_CHARACTERS = 3000
OVERLAP_CHARACTERS = 200
MAX_CHUNKS = 32
MAX_DOCUMENT_CHARACTERS = 10_000
MAX_DOCUMENT_LINES = 2_000
MAX_DOCUMENT_SCORING_CHARACTERS = 500


def validate_document_limits(text: str) -> None:
    """Reject extracted document text above the shared processing limits."""
    if len(text) > MAX_DOCUMENT_CHARACTERS:
        raise ValueError(
            f"Document text exceeds the {MAX_DOCUMENT_CHARACTERS:,}-character limit. "
            "Shorten the document and try again."
        )
    line_count = text.count("\n") + 1 if text else 0
    if line_count > MAX_DOCUMENT_LINES:
        raise ValueError(
            f"Document exceeds the {MAX_DOCUMENT_LINES:,}-line limit. "
            "Shorten the document and try again."
        )


def text_for_document_scoring(text: str) -> tuple[str, bool]:
    """Keep accepted documents bounded for scoring and embedding work."""
    normalized = " ".join(text.split())
    was_truncated = len(normalized) > MAX_DOCUMENT_SCORING_CHARACTERS
    return normalized[:MAX_DOCUMENT_SCORING_CHARACTERS], was_truncated


def chunk_document(text: str, *, enforce_document_limits: bool = True) -> list[str]:
    """Cover all text with bounded chunks and sentence/word-aware overlap."""
    if enforce_document_limits:
        validate_document_limits(text)
    text = " ".join(text.split())
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARACTERS, len(text))
        if end < len(text):
            minimum_end = start + CHUNK_CHARACTERS // 2
            # Prefer a sentence boundary, then a word boundary; never split a
            # word just to hit the nominal chunk length when a nearby boundary exists.
            sentence_boundaries = [
                text.rfind(mark, minimum_end, end) + 1
                for mark in (". ", "? ", "! ", "; ", ": ")
            ]
            sentence_end = max(sentence_boundaries)
            if sentence_end > minimum_end:
                end = sentence_end
            else:
                word_end = text.rfind(" ", minimum_end, end)
                if word_end > start:
                    end = word_end
        chunks.append(text[start:end].strip())
        if len(chunks) > MAX_CHUNKS:
            raise ValueError(
                "Text exceeds the limit for comparison "
                f"(maximum {MAX_CHUNKS} chunks of up to {CHUNK_CHARACTERS} characters each "
                f"with {OVERLAP_CHARACTERS}-character overlap). Shorten the document and try again."
            )
        if end == len(text):
            break
        start = max(start + 1, end - OVERLAP_CHARACTERS)

    return chunks
