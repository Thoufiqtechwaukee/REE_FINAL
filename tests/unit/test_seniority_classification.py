from app.taxonomy.role_matcher import classify_seniority

LEVELS = {
    "Intern": 1, "Trainee": 2, "Junior": 3, "Associate": 4, "Mid-Level": 5,
    "Senior": 6, "Lead": 7, "Principal": 8, "Staff": 9, "Architect": 10,
    "Manager": 11, "Senior Manager": 12, "Director": 13, "Head": 14, "VP": 15, "C-Level": 16,
}


def test_domain_qualifier_does_not_override_seniority_word():
    """Regression: 'Backend Developer Intern' must resolve to Intern despite
    containing no other seniority word that would otherwise dominate."""
    result = classify_seniority("Backend Developer Intern", LEVELS)
    assert result.level_id == LEVELS["Intern"]
    assert not result.is_ambiguous


def test_bare_ambiguous_words_flagged_not_silently_ranked():
    """Regression: the exact reported bug -- 'Project Head' (a single
    student project) must NOT be silently ranked as executive-level."""
    for title in ["Project Head", "Team Head", "Co-Founder", "Founder", "Owner"]:
        result = classify_seniority(title, LEVELS)
        assert result.is_ambiguous, f"{title!r} should be flagged ambiguous"


def test_qualified_head_of_resolves_confidently():
    result = classify_seniority("Head of Engineering", LEVELS)
    assert result.level_id == LEVELS["Head"]
    assert not result.is_ambiguous


def test_ambiguous_title_inherits_previous_role_level_when_no_fallback_given():
    result = classify_seniority("Project Head", LEVELS, previous_level_id=LEVELS["Intern"])
    assert result.is_ambiguous
    assert result.level_id == LEVELS["Intern"]  # inherits previous, never guesses high


def test_full_ladder_resolves_correctly():
    cases = {
        "Software Engineering Intern": "Intern",
        "Junior Software Engineer": "Junior",
        "Software Engineer": "Mid-Level",
        "Senior Software Engineer": "Senior",
        "Lead Software Engineer": "Lead",
        "Principal Engineer": "Principal",
        "Engineering Manager": "Manager",
        "Director of Engineering": "Director",
        "VP of Engineering": "VP",
        "Chief Technology Officer": "C-Level",
    }
    for title, expected_level in cases.items():
        result = classify_seniority(title, LEVELS)
        assert result.level_id == LEVELS[expected_level], f"{title!r} expected {expected_level}, got level_id={result.level_id}"


def test_no_signal_defaults_to_mid_level_not_ambiguous():
    result = classify_seniority("Software Developer", LEVELS)
    assert result.level_id == LEVELS["Mid-Level"]
    assert not result.is_ambiguous
