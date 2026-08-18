"""
Company/role resolution regressions for experience entries.

Two real templates disagree on layout, and the original code handled neither
well:

  A) the date sits alone on its own row, with company and title stacked above
     it. Taking the company from the anchor row left a bare "," (the row read
     "01/2025 - 03/2025,"), and "," is truthy, so it passed validation as an
     employer name.

  B) the title shares a row with a right-aligned date, and the company sits
     on the row below. Here the anchor's residual text is the *title*, not the
     company.

Rather than encode either template, resolution locates the job title by
vocabulary and takes the company from the same side of the date row -- a
resume entry's header is contiguous, so reaching across the date row is how
the next entry's "Achievements/Tasks" label ended up recorded as an employer.
"""
from app.chunking import chunker
from app.models.resume import Block


def _blocks(lines):
    return [Block(block_id=f"b{i}", page_number=1, block_type="line", text=t, sequence=i) for i, t in enumerate(lines)]


def _roles(lines):
    seq = iter(range(1000))
    drafts = chunker._chunk_experience(_blocks(lines), "EXPERIENCE", lambda: next(seq))
    return [d for d in drafts if d.chunk_type == "EXPERIENCE_ROLE"]


def test_template_a_date_alone_on_its_row():
    roles = _roles([
        "VOIS (Vodafone Idea Foundation)",
        "Blockchain Intern",
        "online",
        "01/2025 - 03/2025,",
        "• Developed a decentralized land registry system.",
    ])
    assert len(roles) == 1
    assert roles[0].company == "VOIS (Vodafone Idea Foundation)"
    assert roles[0].role_raw == "Blockchain Intern"


def test_template_b_title_shares_a_row_with_right_aligned_date():
    roles = _roles([
        "Backend Developer Intern May 2024 - Jul 2024",
        "Intel Unnati",
        "• Built backend services in Python using FastAPI.",
    ])
    assert len(roles) == 1
    assert roles[0].role_raw == "Backend Developer Intern"
    assert roles[0].company == "Intel Unnati"


def test_bare_comma_never_becomes_a_company():
    """The precise original failure: stripping the date from '01/2025 -
    03/2025,' left ',' which passed the truthiness check for a company."""
    roles = _roles(["01/2025 - 03/2025,", "• Did some work."])
    assert all(r.company != "," for r in roles)


def test_location_line_is_not_mistaken_for_the_employer():
    roles = _roles([
        "Bangalore",
        "Rius Technology - Intern",
        "08/2023 - 10/2023",
        "• Built a model.",
    ])
    assert roles[0].company != "Bangalore"
    assert roles[0].role_raw == "Rius Technology - Intern"


def test_wrapped_bullet_prose_is_not_mistaken_for_the_employer():
    """Responsibility text wraps onto unbulleted continuation lines that sit
    directly above the next role's date row."""
    roles = _roles([
        "• Designed contracts to automate land registration, ensuring immutability and",
        "fraud prevention.",
        "CodeClause -AI Intern",
        "01/2025 - 02/2025,",
        "• Created an NLP-driven system.",
    ])
    entry = roles[-1]
    assert entry.company != "fraud prevention."
    assert entry.role_raw == "CodeClause -AI Intern"


def test_next_entrys_label_is_not_pulled_across_the_date_row():
    roles = _roles([
        "CodeClause -AI Intern",
        "01/2025 - 02/2025,",
        "Achievements/Tasks",
        "• Created an NLP-driven system.",
    ])
    assert roles[0].company != "Achievements/Tasks"


def test_entry_with_no_usable_header_is_left_for_validation_to_reject():
    """Returning None rather than inventing a company lets
    experience._looks_like_real_role drop the entry."""
    roles = _roles(["01/2025 - 03/2025", "• Something happened."])
    assert roles[0].company is None and roles[0].role_raw is None


def test_multiple_entries_keep_their_own_headers():
    roles = _roles([
        "Alpha Corp",
        "Software Engineer",
        "01/2020 - 12/2020",
        "• Shipped features.",
        "Beta Ltd",
        "Senior Developer",
        "01/2021 - 12/2021",
        "• Led a team.",
    ])
    assert len(roles) == 2
    assert roles[0].role_raw == "Software Engineer" and roles[0].company == "Alpha Corp"
    assert roles[1].role_raw == "Senior Developer" and roles[1].company == "Beta Ltd"
