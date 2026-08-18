"""
Category-label regressions for skill discovery.

The bug: skills sections are written "Backend: FastAPI, REST API Design". The
extractor split on commas but not colons, then stripped ':' as punctuation --
turning the *label* "Backend:" into the candidate "Backend". Because no
catalog entry matches "Backend", it fell through exact/alias/fuzzy to semantic
search and then to Qwen, which resolved it to ASP.NET Core at 80% confidence
on a resume containing no .NET at all. "Core CS:" likewise became C++, and
"LLM & GenAI:" became Semantic Kernel -- six fabricated skills on one resume.

The rule is structural (a trailing colon marks a label) rather than a denylist
of these particular words, so it generalizes to any category heading.
"""
from app.agents import skill_discovery


def _candidates(text):
    return skill_discovery._extract_skills_section_candidates(text)


def test_category_label_is_not_emitted_as_a_skill():
    got = _candidates("Backend: FastAPI, REST API Design, Object-Oriented Design")
    assert "Backend" not in got
    assert "FastAPI" in got
    assert "REST API Design" in got


def test_core_cs_label_does_not_survive():
    """The exact reported case: 'Core CS' became C++."""
    got = _candidates("Core CS: Data Structures & Algorithms, Problem Solving")
    assert "Core CS" not in got
    assert "Data Structures & Algorithms" in got


def test_label_and_value_are_not_fused_into_one_candidate():
    """Without colon splitting the first value carried its label along, e.g.
    'AI & Machine Learning: Scikit-Learn' -- which only resolved correctly by
    luck, and cost a Qwen round-trip to do it."""
    got = _candidates("AI & Machine Learning: Scikit-Learn, TensorFlow, Keras")
    assert "Scikit-Learn" in got
    assert not any(":" in c for c in got)


def test_label_alone_on_its_line_yields_nothing():
    assert _candidates("Vector Databases:") == []


def test_plain_comma_list_without_labels_is_unchanged():
    got = _candidates("Python, SQL, Machine Learning, Vue.js")
    assert got == ["Python", "SQL", "Machine Learning", "Vue.js"]


def test_long_prose_head_is_not_treated_as_a_label():
    """A colon inside a sentence must not delete the sentence's first half --
    only a short, word-like head is a category prefix."""
    text = "Shipped a retrieval service end to end: Python"
    got = _candidates(text)
    assert any("Shipped a retrieval service" in c for c in got)


def test_multiline_label_block_keeps_only_values():
    text = "Programming: Python\nBackend: FastAPI\nVector Databases: ChromaDB, Pinecone"
    got = _candidates(text)
    for label in ("Programming", "Backend", "Vector Databases"):
        assert label not in got
    for value in ("Python", "FastAPI", "ChromaDB", "Pinecone"):
        assert value in got


# --- Layer 2 scope -------------------------------------------------------

class _FakeSkill:
    def __init__(self, skill_id, name):
        self.skill_id, self.canonical_name, self.display_name = skill_id, name, name
        self.description, self.active = "", True


class _FakeChunk:
    def __init__(self, chunk_id, chunk_type, text):
        self.chunk_id, self.chunk_type, self.original_text = chunk_id, chunk_type, text


def test_chip_style_skills_section_is_scanned_for_catalog_names(monkeypatch):
    """Regression: chip/tag skill layouts separate entries with spaces alone,
    so "Python SQL Machine Learning Vue.js" is one delimiter-free line that
    Layer 1 cannot split. One resume lost its entire skill list to this the
    moment its sections started mapping correctly, because the blob matched
    no catalog entry. Layer 2 therefore scans the Skills section too."""
    import asyncio
    from app.agents import skill_discovery as sd

    catalog = [_FakeSkill("python", "Python"), _FakeSkill("sql", "SQL"),
               _FakeSkill("machine-learning", "Machine Learning"), _FakeSkill("vue-js", "Vue.js")]

    class _Q:
        def filter(self, *a, **k): return self
        def all(self): return catalog

    class _DB:
        def query(self, *a, **k): return _Q()

    monkeypatch.setattr(sd.skill_matcher, "_catalog_lookup_maps", lambda db: ({}, {}, {}))

    async def _no_candidates(db, texts, *a, **k):
        return {t: [] for t in texts}
    monkeypatch.setattr(sd.skill_matcher, "find_candidates_batch", _no_candidates)

    chunks = [_FakeChunk("c1", "SKILL_SECTION", "Python SQL Machine Learning Vue.js")]
    found = asyncio.run(sd.discover_skills(_DB(), chunks))
    assert {d.canonical_name for d in found} == {"Python", "SQL", "Machine Learning", "Vue.js"}
