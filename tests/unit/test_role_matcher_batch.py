"""
Guards the claim role_matcher.find_candidates_batch makes in its docstring:
identical per-title matching logic to find_candidates, differing only in how
many round-trips it costs. If someone edits one path's thresholds or ranking
without the other, these fail.

No DB and no network: the catalog lookup maps are passed in pre-built (the
same thing experience.py's hoist does) and the semantic layer is faked, so
this exercises the real _match_local/_combine_fuzzy_and_semantic code.
"""
import asyncio
from dataclasses import dataclass

import pytest

from app.taxonomy import role_matcher


@dataclass
class FakeRole:
    role_id: str
    canonical_title: str


ROLES = [
    FakeRole("software-engineer", "Software Engineer"),
    FakeRole("senior-software-engineer", "Senior Software Engineer"),
    FakeRole("data-scientist", "Data Scientist"),
    FakeRole("engineering-manager", "Engineering Manager"),
]
_BY_ID = {r.role_id: r for r in ROLES}

EXACT_MAP = {role_matcher.loose_key(r.canonical_title): r for r in ROLES}
ALIAS_MAP = {role_matcher.loose_key("SDE"): _BY_ID["software-engineer"]}
FUZZY_UNIVERSE = {r.canonical_title.lower(): r for r in ROLES}
FUZZY_UNIVERSE["sde"] = _BY_ID["software-engineer"]

# Titles chosen to cover every branch of _match_local: exact, alias,
# high-confidence fuzzy, and the semantic-fallback path (both with and
# without a surviving low-confidence fuzzy candidate).
TITLES = [
    "Software Engineer",        # EXACT
    "SDE",                      # ALIAS
    "Senior Software Enginer",  # FUZZY (typo, high confidence)
    "Growth Hacking Wizard",    # semantic fallback, no fuzzy hit
    "Data Scientist",           # EXACT
    "Software Engineer",        # duplicate -- must collapse, not diverge
    "",                         # empty -- must short-circuit to []
]

_SEMANTIC_RESULTS = {
    "Growth Hacking Wizard": [(_BY_ID["data-scientist"], 0.61), (_BY_ID["software-engineer"], 0.58)],
}


class _SemanticSpy:
    """Stands in for the Nomic-backed retrieval layer and counts round-trips."""

    def __init__(self):
        self.single_calls = 0
        self.batch_calls = 0

    async def single(self, db, text, top_k=5, min_similarity=0.5):
        self.single_calls += 1
        return _SEMANTIC_RESULTS.get(text, [])

    async def batch(self, db, texts, top_k=5, min_similarity=0.5):
        self.batch_calls += 1
        return {t: _SEMANTIC_RESULTS.get(t, []) for t in dict.fromkeys(texts)}


@pytest.fixture
def spy(monkeypatch):
    s = _SemanticSpy()
    monkeypatch.setattr(role_matcher, "search_role_candidates", s.single)
    monkeypatch.setattr(role_matcher, "search_role_candidates_batch", s.batch)
    return s


def _shape(candidates):
    return [(c.role.role_id, round(c.confidence, 6), c.method) for c in candidates]


def test_batch_matches_single_result_for_every_title(spy):
    async def run():
        single = {}
        for title in TITLES:
            single[title] = await role_matcher.find_candidates(
                None, title, EXACT_MAP, ALIAS_MAP, FUZZY_UNIVERSE
            )
        batch = await role_matcher.find_candidates_batch(
            None, TITLES, EXACT_MAP, ALIAS_MAP, FUZZY_UNIVERSE
        )
        return single, batch

    single, batch = asyncio.run(run())

    assert set(batch) == set(TITLES)
    for title in TITLES:
        assert _shape(batch[title]) == _shape(single[title]), f"divergence on {title!r}"


def test_batch_collapses_semantic_lookups_into_one_round_trip(spy):
    """The whole point of the change: N titles must not cost N round-trips."""
    asyncio.run(
        role_matcher.find_candidates_batch(None, TITLES, EXACT_MAP, ALIAS_MAP, FUZZY_UNIVERSE)
    )
    assert spy.batch_calls == 1
    assert spy.single_calls == 0


def test_locally_resolvable_titles_skip_the_semantic_layer_entirely(spy):
    """Exact/alias/high-fuzzy titles must not trigger any embedding call."""
    asyncio.run(
        role_matcher.find_candidates_batch(
            None, ["Software Engineer", "SDE", "Data Scientist"], EXACT_MAP, ALIAS_MAP, FUZZY_UNIVERSE
        )
    )
    assert spy.batch_calls == 0
    assert spy.single_calls == 0


def test_empty_title_short_circuits_without_a_lookup(spy):
    result = asyncio.run(
        role_matcher.find_candidates_batch(None, ["", "   "], EXACT_MAP, ALIAS_MAP, FUZZY_UNIVERSE)
    )
    assert result[""] == []
    assert spy.batch_calls == 0
