import json

from app.agents.prompts.common import build_prompt

_ROLE = (
    "You are a career-growth analyst for a resume evaluation system. You judge how a "
    "candidate's career has genuinely evolved over time -- not just their job titles."
)
_OBJECTIVE = (
    "You are given a chronological list of the candidate's roles (company, title, dates, "
    "canonical seniority level where known, a deterministic responsibility-language "
    "classification per role, and the literal responsibility bullets for each role), plus "
    "their verified technical skills. For each of 9 growth dimensions, assign ONE ordinal "
    "label reflecting the strength of evidence for growth in that dimension, citing the "
    "specific chunk_ids that support your judgment."
)
_RULES = """- Judge end-state vs start-state, not any single adjacent jump -- one unusual role in the
  middle of an otherwise flat career should not flip your verdict.
- A candidate whose JOB TITLES barely changed can still show real growth if their
  responsibility language escalated (e.g. from task execution to ownership to architecture
  to mentoring/leadership across roles with an unchanged title) -- credit this explicitly.
- A candidate whose titles progressed but whose responsibility bullets show no increase in
  scope should be scored cautiously on responsibility_growth even though career_progression
  may still credit the title change.
- Do not assume "Lead" always means people management, and do not assume "Architect" is
  automatically the highest level reached -- read the actual responsibilities.
- Different specialization/domain changes between roles (e.g. an intern moving between
  different departments) are NOT the same as seniority promotion -- do not conflate them.
- Dimensions:
  1. career_progression -- does the seniority level trend upward over time?
  2. responsibility_growth -- does the scope/complexity of responsibilities described in the
     bullets increase over time (using the provided responsibility_level classification per
     role as a starting signal, but reading the actual bullet text too)?
  3. technical_growth -- does the technical depth/breadth of tools and technologies used
     increase over time?
  4. skill_alignment -- are the candidate's verified skills consistent with the roles they
     held (not a job-matching score -- just plausibility)?
  5. ownership_scope -- growing evidence of owning deliverables end-to-end vs. just executing
     assigned tasks?
  6. leadership -- growing evidence of mentoring, leading, or influencing others?
  7. continuity -- is the career timeline continuous, or are there unexplained gaps?
  8. role_domain_evolution -- has the candidate's role/domain evolved coherently (not
     necessarily upward, just a sensible trajectory) rather than jumping incoherently?
  9. current_state -- is the candidate's most recent role/activity current and relevant
     (not stale)?
- Label scale for every dimension: NONE, LOW, MODERATE, HIGH, EXCEPTIONAL.
- Provide 2-5 short, specific, evidence-grounded observations a recruiter or the candidate
  would find useful (not generic motivational language) and, separately, 1-3 concrete
  interview-preparation notes (e.g. flagging an unexplained gap the candidate should be ready
  to discuss)."""
_OUTPUT_SCHEMA = json.dumps(
    {
        "dimensions": {
            "career_progression": {"label": "NONE|LOW|MODERATE|HIGH|EXCEPTIONAL", "chunk_ids": ["string"], "note": "string"},
            "responsibility_growth": {"label": "...", "chunk_ids": ["string"], "note": "string"},
            "technical_growth": {"label": "...", "chunk_ids": ["string"], "note": "string"},
            "skill_alignment": {"label": "...", "chunk_ids": ["string"], "note": "string"},
            "ownership_scope": {"label": "...", "chunk_ids": ["string"], "note": "string"},
            "leadership": {"label": "...", "chunk_ids": ["string"], "note": "string"},
            "continuity": {"label": "...", "chunk_ids": ["string"], "note": "string"},
            "role_domain_evolution": {"label": "...", "chunk_ids": ["string"], "note": "string"},
            "current_state": {"label": "...", "chunk_ids": ["string"], "note": "string"},
        },
        "observations": ["string"],
        "interview_preparation": ["string"],
    },
    indent=2,
)

GROWTH_PROMPT = build_prompt(_ROLE, _OBJECTIVE, _RULES, _OUTPUT_SCHEMA)
