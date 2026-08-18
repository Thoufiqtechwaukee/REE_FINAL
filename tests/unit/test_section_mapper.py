from app.db.models.common import CanonicalSection
from app.extraction import section_mapper
from app.models.resume import Block


def _blocks(lines):
    return [Block(block_id=f"b{i}", page_number=1, block_type="line", text=t, sequence=i) for i, t in enumerate(lines)]


def test_education_adjective_form_matches():
    """Regression: the adjective heading 'Educational Qualification' must
    resolve to EDUCATION -- the confirmed root cause of a real bug where
    unrecognized headings leaked institution/date content into the wrong
    section."""
    assert section_mapper.match_canonical_section("Educational Qualification") == CanonicalSection.EDUCATION


def test_tools_technologies_require_plural_form():
    """Regression: singular 'Tool'/'Technology' are common inside content
    lines (project titles) and must not hijack section state."""
    assert section_mapper.match_canonical_section("Internal Platform Tool") is None
    assert section_mapper.match_canonical_section("Technologies") == CanonicalSection.SKILLS


def test_projects_requires_plural_form():
    assert section_mapper.match_canonical_section("Major Project") is None
    assert section_mapper.match_canonical_section("Projects") == CanonicalSection.PROJECTS


def test_long_bullet_sentence_never_misfires_as_header():
    long_line = "• " + "Developed and maintained enterprise applications using SKILLS and TOOLS extensively " * 2
    assert not section_mapper.is_possible_heading_line(long_line)


def test_experience_synonyms():
    for heading in ["Experience", "Professional Experience", "Work History", "Employment History", "Career History"]:
        assert section_mapper.match_canonical_section(heading) == CanonicalSection.EXPERIENCE


def test_recurring_template_label_does_not_switch_sections():
    """Regression: 'Achievements/Tasks' is emitted once per role by several
    resume builders. It matched the ACHIEVEMENTS pattern and reset the active
    section mid-Experience, shredding one resume's employment history into
    three bogus ACHIEVEMENTS sections and scoring it 0/25 on Experience.
    Recurrence is the signal -- a heading names a section, so it appears once."""
    blocks = _blocks([
        "Work Experience",
        "Acme Corp",
        "01/2020 - 12/2020",
        "Achievements/Tasks",
        "Built the thing",
        "Beta Ltd",
        "01/2021 - 12/2021",
        "Achievements/Tasks",
        "Built another thing",
    ])
    result = section_mapper.map_blocks_to_sections(blocks)
    assert [s.canonical_section for s in result.sections].count(CanonicalSection.ACHIEVEMENTS.value) == 0
    experience = next(s for s in result.sections if s.canonical_section == CanonicalSection.EXPERIENCE.value)
    assert "Beta Ltd" in experience.text  # the whole section stayed intact


def test_wrapped_bullet_continuation_is_not_a_heading():
    """Regression: responsibility bullets wrap onto unbulleted continuation
    lines short enough to pass the length test. '3+ active projects in an
    agile environment.' matched PROJECTS mid-Experience and dumped every
    remaining role into the Projects section, losing them entirely."""
    assert not section_mapper.is_possible_heading_line("3+ active projects in an agile environment.")
    assert not section_mapper.is_possible_heading_line("coordinated execution across active projects")
    assert not section_mapper.is_possible_heading_line("improving security and transparency,")


def test_real_headings_still_pass_the_tightened_test():
    for heading in [
        "EDUCATION", "WORK EXPERIENCE", "DYNAMIC PROJECTS", "Technical Skills",
        "Certifications", "SELECTED PROJECTS", "Educational Qualifications",
    ]:
        assert section_mapper.is_possible_heading_line(heading), heading
        assert section_mapper.match_canonical_section(heading) is not None, heading


def test_map_blocks_to_sections_switches_on_recognized_heading_only():
    blocks = _blocks([
        "John Doe",
        "555-1234",
        "Professional Summary",
        "Experienced engineer with 10 years in backend systems.",
        "Skills",
        "Python, Django, PostgreSQL",
    ])
    result = section_mapper.map_blocks_to_sections(blocks)
    sections = {s.canonical_section for s in result.sections}
    assert CanonicalSection.SUMMARY.value in sections
    assert CanonicalSection.SKILLS.value in sections
    skills_section = next(s for s in result.sections if s.canonical_section == CanonicalSection.SKILLS.value)
    assert "Python" in skills_section.text
