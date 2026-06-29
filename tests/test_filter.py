from pipeline.ingest.filter import matches_topics

KEYWORDS = ["sleep", "REM", "circadian", "VO2 max", "cold exposure"]


def test_matches_exact_keyword_in_title():
    assert matches_topics("The Science of Sleep", "", KEYWORDS)


def test_matches_keyword_in_description():
    assert matches_topics("Ep 42", "Today we talk about circadian rhythms", KEYWORDS)


def test_case_insensitive():
    assert matches_topics("SLEEP SCIENCE", "", KEYWORDS)
    assert matches_topics("rem sleep cycles", "", KEYWORDS)


def test_no_match_returns_false():
    assert not matches_topics("Cooking with Butter", "A great recipe episode", KEYWORDS)


def test_multiword_keyword():
    assert matches_topics("Cold Exposure Benefits", "", KEYWORDS)
    assert matches_topics("vo2 max training", "", KEYWORDS)


def test_empty_keywords_never_matches():
    assert not matches_topics("Sleep Episode", "sleep description", [])
