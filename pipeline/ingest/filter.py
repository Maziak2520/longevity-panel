def matches_topics(title: str, description: str, keywords: list[str]) -> bool:
    if not keywords:
        return False
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in keywords)
