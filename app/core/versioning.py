"""
Central version constants (spec §49). Bumping any constant here is what
invalidates the relevant cache layer on next read -- see services/caching.py.
Changing only SCORING_VERSION must never force re-embedding (spec §50), so
these are deliberately independent, single-purpose strings rather than one
monolithic "app version."
"""
from dataclasses import dataclass

MODEL_VERSION = "qwen2.5-14b-runpod-v1"
EMBEDDING_VERSION = "nomic-embed-text-v1"
PROMPT_VERSION = "prompts-v1"
SKILL_TAXONOMY_VERSION = "skill-taxonomy-v1"
ROLE_TAXONOMY_VERSION = "role-taxonomy-v1"
NORMALIZATION_VERSION = "normalization-v1"
AGENT_VERSION = "agents-v1"
SCORING_VERSION = "scoring-v1"
CHUNKING_VERSION = "chunking-v1"
VECTOR_INDEX_VERSION = "vector-index-v1"


@dataclass(frozen=True)
class VersionSet:
    model_version: str = MODEL_VERSION
    embedding_version: str = EMBEDDING_VERSION
    prompt_version: str = PROMPT_VERSION
    skill_taxonomy_version: str = SKILL_TAXONOMY_VERSION
    role_taxonomy_version: str = ROLE_TAXONOMY_VERSION
    normalization_version: str = NORMALIZATION_VERSION
    agent_version: str = AGENT_VERSION
    scoring_version: str = SCORING_VERSION
    chunking_version: str = CHUNKING_VERSION
    vector_index_version: str = VECTOR_INDEX_VERSION

    def as_dict(self) -> dict[str, str]:
        return {
            "model_version": self.model_version,
            "embedding_version": self.embedding_version,
            "prompt_version": self.prompt_version,
            "skill_taxonomy_version": self.skill_taxonomy_version,
            "role_taxonomy_version": self.role_taxonomy_version,
            "normalization_version": self.normalization_version,
            "agent_version": self.agent_version,
            "scoring_version": self.scoring_version,
            "chunking_version": self.chunking_version,
            "vector_index_version": self.vector_index_version,
        }

    def semantic_index_key_fields(self) -> dict[str, str]:
        """Fields that gate the semantic-index cache layer (spec §50)."""
        return {
            "chunking_version": self.chunking_version,
            "embedding_version": self.embedding_version,
            "vector_index_version": self.vector_index_version,
        }


CURRENT_VERSIONS = VersionSet()
