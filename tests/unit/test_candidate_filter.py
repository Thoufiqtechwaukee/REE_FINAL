from app.taxonomy.candidate_filter import is_plausible_skill_candidate


def test_generic_words_rejected():
    """Spec §17: 'framework' is context, not a skill."""
    for word in ["framework", "platform", "application", "system", "solution", "years", "experience"]:
        assert not is_plausible_skill_candidate(word), f"{word!r} should be rejected"


def test_real_skill_names_accepted():
    for word in ["Python", "React", "PostgreSQL", "AWS", "Docker"]:
        assert is_plausible_skill_candidate(word), f"{word!r} should be accepted"


def test_locations_rejected():
    for word in ["India", "Chennai", "New York"]:
        assert not is_plausible_skill_candidate(word)


def test_languages_and_soft_skills_rejected():
    for word in ["English", "Hindi", "Leadership", "Team Player"]:
        assert not is_plausible_skill_candidate(word)


def test_institution_stems_rejected():
    assert not is_plausible_skill_candidate("Bachelor of Science")
    assert not is_plausible_skill_candidate("University")


def test_unbalanced_parens_rejected():
    assert not is_plausible_skill_candidate("Experience (7+")


def test_fragment_stopwords_rejected():
    assert not is_plausible_skill_candidate("Including prioritizing product")


def test_leaked_section_header_rejected():
    assert not is_plausible_skill_candidate("EDUCATIONAL QUALIFICATION")


def test_sentence_fragment_rejected():
    assert not is_plausible_skill_candidate("responsible for managing the entire delivery pipeline end to end")


def test_empty_and_pure_digits_rejected():
    assert not is_plausible_skill_candidate("")
    assert not is_plausible_skill_candidate("12345")
