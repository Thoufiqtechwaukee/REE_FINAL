from datetime import date
from types import SimpleNamespace

from app.db.models.evaluation import EvidenceStrength
from app.evaluation import scoring


def _experience(start, end, responsibilities=None):
    return SimpleNamespace(start_date=start, end_date=end, responsibilities=responsibilities or ["did a thing", "did another thing"], company="Acme", raw_title="Engineer")


def _skill(id_):
    return SimpleNamespace(id=id_, canonical_name=id_)


def test_score_experience_empty_returns_zero():
    result = scoring.score_experience([], [], {}, 0, "", date.today())
    assert result.total == 0.0


def test_score_experience_full_marks_for_well_documented_current_role():
    exp = _experience(date(2020, 1, 1), date.today(), ["a", "b", "c", "d", "e", "f"])
    exp.is_current = True
    skill = _skill("python")
    result = scoring.score_experience([exp], [skill], {}, 60, "", date.today())
    assert 0 <= result.total <= 25
    documented = next(s for s in result.sub_scores if s.name == "documented_magnitude")
    assert documented.points == documented.points_max  # 60 months >> 24 month full-credit threshold


def test_score_experience_total_never_exceeds_25():
    exp = _experience(date(2015, 1, 1), date.today(), ["a"] * 20)
    exp.is_current = True
    result = scoring.score_experience([exp] * 10, [], {}, 999, "", date.today())
    assert result.total <= 25.0


def test_score_evidence_no_skills_returns_zero():
    result = scoring.score_evidence([], {}, {})
    assert result.total == 0.0


def test_score_evidence_all_strong_scores_high():
    skills = [_skill("python"), _skill("react")]
    strength_map = {"python": EvidenceStrength.STRONG, "react": EvidenceStrength.STRONG}
    result = scoring.score_evidence(skills, strength_map, {"python": True, "react": True})
    assert result.total > 20  # near-max: all strong + project bonus


def test_score_evidence_all_none_scores_low():
    skills = [_skill("python"), _skill("react")]
    strength_map = {"python": EvidenceStrength.NONE, "react": EvidenceStrength.NONE}
    result = scoring.score_evidence(skills, strength_map, {})
    assert result.total <= 2.0  # only the minimum project-bonus floor


def test_score_evidence_mixed_strength():
    skills = [_skill("python"), _skill("react"), _skill("aws")]
    strength_map = {"python": EvidenceStrength.STRONG, "react": EvidenceStrength.MODERATE, "aws": EvidenceStrength.NONE}
    result = scoring.score_evidence(skills, strength_map, {"python": True})
    core = next(s for s in result.sub_scores if s.name == "core_skill_evidence")
    assert core.points == round(12 * (1 / 3), 2)  # 1 of 3 skills STRONG
