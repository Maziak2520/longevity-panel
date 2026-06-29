from __future__ import annotations


def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 0.75)


def chunk_text(text: str, chunk_size: int = 3000, overlap: int = 200) -> list[str]:
    words = text.split()
    if estimate_tokens(text) <= chunk_size:
        return [text]

    words_per_chunk = int(chunk_size / 0.75)
    overlap_words = int(overlap / 0.75)
    chunks = []
    start = 0

    while start < len(words):
        end = min(start + words_per_chunk, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap_words

    return chunks
