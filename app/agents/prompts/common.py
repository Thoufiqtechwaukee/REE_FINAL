"""Shared prompt boilerplate (spec §45). Every agent prompt is built as
ROLE / OBJECTIVE / INPUT / ALLOWED EVIDENCE / RULES / OUTPUT JSON SCHEMA /
CONFIDENCE / ABSTENTION RULES, with these global rules injected into RULES."""

GLOBAL_RULES = """Global rules (apply to every judgment you make):
- Never invent facts, dates, skills, employers, or role history.
- Only reason from the evidence explicitly supplied to you in this prompt -- never from
  general knowledge about what a resume "probably" says.
- Distinguish EXPLICIT evidence (the resume states this directly) from INFERRED evidence
  (you are reasoning indirectly from related text) -- always say which one you are using.
- Do not assume one technology proves another, even when commonly used together in
  practice (e.g. Docker usage does not prove Kubernetes; AWS does not prove Azure; React
  does not prove Angular).
- Do not calculate durations, dates, or overlaps yourself -- those are supplied to you
  already computed and must be trusted, not re-derived.
- Do not invent or assume a reason for an unexplained career gap.
- Return UNKNOWN (or the schema's designated "insufficient evidence" value) rather than
  guessing when the evidence provided does not clearly support a confident judgment.
- Provide source identifiers (chunk ids) for any evidence you cite, when the schema asks
  for them.
- Return valid JSON only, exactly matching the schema given -- no prose outside the JSON."""


def build_prompt(role: str, objective: str, rules: str, output_schema: str) -> str:
    return (
        f"ROLE:\n{role}\n\n"
        f"OBJECTIVE:\n{objective}\n\n"
        f"RULES:\n{rules}\n\n{GLOBAL_RULES}\n\n"
        f"OUTPUT JSON SCHEMA:\n{output_schema}"
    )
