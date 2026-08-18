"""
Deterministic responsibility-language classifier, ported from the proven C#
ClassifyResponsibility (priority-ordered, highest bucket wins). Used by the
Experience agent to populate leadership/ownership indicators, and by Growth
as a concrete starting signal for "did scope actually change" rather than
asking Qwen to eyeball raw bullets cold (see plan's Growth scoring notes --
this is a deterministic *signal* into Qwen's reasoning, not the score itself).
"""
import re

_RULES: list[tuple[int, str, re.Pattern]] = [
    (4, "MENTORING_LEADERSHIP", re.compile(
        r"\b(mentored|guided|team lead|managed\s+(?:a\s+)?team|directed|scrum master|"
        r"product owner|led\s+a\s+team|supervised|coached)\b", re.IGNORECASE
    )),
    (3, "ARCHITECTURE", re.compile(
        r"\b(architected|designed\s+(?:the|a|an)?\s*(?:system|architecture|solution)|scaled|"
        r"microservices|distributed system|system design|integration architecture)\b", re.IGNORECASE
    )),
    (2, "OWNERSHIP", re.compile(
        r"\b(managed|owned|led|spearheaded|maintained|responsible for|drove|delivered end-to-end)\b",
        re.IGNORECASE
    )),
    (1, "TASK_EXECUTION", re.compile(
        r"\b(developed|implemented|built|coded|created|configured|analyzed|tested|wrote|fixed|"
        r"designed|developed)\b", re.IGNORECASE
    )),
]

DEFAULT_LEVEL = "TASK_EXECUTION"
DEFAULT_RANK = 1


def classify_bullet(text: str) -> tuple[int, str]:
    for rank, label, pattern in _RULES:
        if pattern.search(text):
            return rank, label
    return 0, "OTHER"


def classify_role(responsibility_texts: list[str]) -> tuple[str, list[str], list[str]]:
    """Returns (role_responsibility_level, leadership_indicators,
    ownership_indicators) -- the role's level is the highest-ranked bucket
    reached by any of its bullets; indicator lists are the literal bullet
    texts that reached MENTORING_LEADERSHIP / OWNERSHIP-or-higher."""
    best_rank = 0
    best_label = DEFAULT_LEVEL
    leadership_indicators: list[str] = []
    ownership_indicators: list[str] = []

    for text in responsibility_texts:
        rank, label = classify_bullet(text)
        if rank > best_rank:
            best_rank, best_label = rank, label
        if label == "MENTORING_LEADERSHIP":
            leadership_indicators.append(text)
        if rank >= 2:
            ownership_indicators.append(text)

    if best_rank == 0:
        best_label = DEFAULT_LEVEL
    return best_label, leadership_indicators, ownership_indicators
