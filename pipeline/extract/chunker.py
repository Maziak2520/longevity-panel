from __future__ import annotations


def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 0.75)


def words_for_tokens(tokens: int) -> int:
    return int(tokens / 0.75)


def chunk_text(text: str, chunk_size: int = 3000, overlap: int = 200) -> list[str]:
    words = text.split()
    if estimate_tokens(text) <= chunk_size:
        return [text]

    words_per_chunk = words_for_tokens(chunk_size)
    overlap_words = words_for_tokens(overlap)
    chunks = []
    start = 0

    while start < len(words):
        end = min(start + words_per_chunk, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap_words

    return chunks
