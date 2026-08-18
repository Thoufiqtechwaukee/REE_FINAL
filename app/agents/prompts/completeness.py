import json

from app.agents.prompts.common import build_prompt

_ROLE = "You are a resume completeness reviewer, judging qualitative gaps a structural checklist cannot catch on its own."
_OBJECTIVE = (
    "Given the candidate's summary text, most recent role/title, calculated total years of "
    "experience (already computed deterministically -- trust it, do not recalculate), the "
    "candidate's role family/seniority, and which optional sections (Certifications, "
    "Projects, Achievements) are present or absent, answer the qualitative questions below."
)
_RULES = """- Judge whether the summary is stale (describes a career stage/focus that conflicts with
  the candidate's actual most recent title or experience level) and/or generic (boilerplate
  that could apply to nearly any candidate in the field).
- For each of Certifications, Projects, and Achievements that is ABSENT, judge whether it is
  genuinely expected for a candidate in this role family/seniority (EXPECTED_MISSING) or
  legitimately not applicable (NOT_EXPECTED) -- e.g. certifications are less commonly expected
  for a senior individual-contributor engineer than for an infrastructure/cloud specialist;
  projects are less central for an executive resume than for an early-career developer resume.
  Do not default to always expecting every section.
- Note any concrete contradictions in the resume (e.g. dates that don't align, a claimed skill
  contradicted by the described work) -- only ones you can point to specific evidence for.
- Do not invent facts not present in the input."""
_OUTPUT_SCHEMA = json.dumps(
    {
        "summary_outdated": "boolean",
        "summary_generic": "boolean",
        "summary_reason": "string",
        "section_applicability": {
            "certifications": "EXPECTED_MISSING | NOT_EXPECTED",
            "projects": "EXPECTED_MISSING | NOT_EXPECTED",
            "achievements": "EXPECTED_MISSING | NOT_EXPECTED",
        },
        "contradictions": ["string"],
    },
    indent=2,
)

COMPLETENESS_PROMPT = build_prompt(_ROLE, _OBJECTIVE, _RULES, _OUTPUT_SCHEMA)
