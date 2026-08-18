"""
DistinctTechnologyGuard (ported from the proven C# system): blocks Qwen from
inferring one technology's evidence from a sibling's -- a real observed
failure mode where the model reasoned "Docker usage implies Kubernetes-like
orchestration." Sibling groups are RELATED, never substitutable.
"""
_SIBLING_GROUPS: list[frozenset[str]] = [
    frozenset({"docker", "kubernetes"}),
    frozenset({"aws", "azure", "google-cloud"}),
    frozenset({"react", "angular", "vue-js"}),
    frozenset({"mysql", "postgresql", "sql-server", "oracle-database"}),
    frozenset({"tensorflow", "pytorch", "keras"}),
]

_GROUP_BY_SKILL: dict[str, frozenset[str]] = {}
for _group in _SIBLING_GROUPS:
    for _skill_id in _group:
        _GROUP_BY_SKILL[_skill_id] = _group


def is_cross_technology_leak(skill_id: str, explanation_text: str, all_skill_names_by_id: dict[str, str]) -> bool:
    """True if `explanation_text` (Qwen's justification for skill_id's
    evidence) actually names a different sibling technology instead of
    skill_id itself -- such a verdict must be rejected, not upgraded."""
    group = _GROUP_BY_SKILL.get(skill_id)
    if not group:
        return False
    lowered = explanation_text.lower()
    own_name = all_skill_names_by_id.get(skill_id, "").lower()
    for sibling_id in group:
        if sibling_id == skill_id:
            continue
        sibling_name = all_skill_names_by_id.get(sibling_id, "").lower()
        if sibling_name and sibling_name in lowered and (not own_name or own_name not in lowered):
            return True
    return False
