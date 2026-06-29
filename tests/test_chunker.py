from pipeline.extract.chunker import chunk_text, estimate_tokens


def test_estimate_tokens_rough():
    text = "word " * 100
    tokens = estimate_tokens(text)
    assert 60 < tokens < 140


def test_chunk_short_text_returns_single_chunk():
    text = "short text " * 10
    chunks = chunk_text(text, chunk_size=3000, overlap=200)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_long_text_returns_multiple_chunks():
    text = "word " * 5000
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1


def test_chunks_overlap():
    words = [f"word{i}" for i in range(200)]
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=50, overlap=10)
    assert len(chunks) >= 2
    last_words_chunk0 = chunks[0].split()[-5:]
    first_words_chunk1 = chunks[1].split()[:15]
    overlap = set(last_words_chunk0) & set(first_words_chunk1)
    assert len(overlap) > 0


def test_chunk_preserves_all_content():
    text = "alpha beta gamma delta epsilon " * 100
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    combined = " ".join(chunks)
    for word in ["alpha", "beta", "gamma", "delta", "epsilon"]:
        assert word in combined
