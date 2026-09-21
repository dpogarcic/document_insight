"""Typed configuration snapshots used by document processing."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Capability(StrEnum):
    """Capabilities that have independently versioned behavior."""

    NER = "ner"
    CHUNKING = "chunking"
    LEXICAL = "lexical"
    EMBEDDING = "embedding"
    RERANKING = "reranking"
    GENERATION = "generation"


class IndexGenerationStatus(StrEnum):
    """Lifecycle of one immutable derived-data generation."""

    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class NerConfiguration(BaseModel):
    """Non-secret configuration for the local NER capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    english_model: str
    croatian_model: str
    model_revision: str


class ChunkingConfiguration(BaseModel):
    """Non-secret deterministic configuration for page-aware chunking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    implementation: str
    implementation_revision: str
    max_chars: int = Field(ge=200, le=4_000)
    overlap_chars: int = Field(ge=0, le=1_000)

    @model_validator(mode="after")
    def validate_overlap(self) -> "ChunkingConfiguration":
        """Require forward progress for every chunk window."""
        if self.overlap_chars >= self.max_chars:
            raise ValueError("overlap_chars must be smaller than max_chars")
        return self


class EmbeddingConfiguration(BaseModel):
    """Non-secret embedding settings for one immutable configuration revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    configuration_revision: str
    dimensions: Annotated[int, Field(ge=1, le=16_384)]
    normalize: bool
    batch_size: Annotated[int, Field(ge=1, le=512)]


@dataclass(frozen=True, slots=True)
class ResolvedIngestionProfile:
    """Exact immutable configuration a processing job must use."""

    ingestion_profile_id: UUID
    ner_profile_id: UUID
    chunking_profile_id: UUID
    lexical_profile_id: UUID
    embedding_profile_id: UUID
    ner: NerConfiguration
    chunking: ChunkingConfiguration
    embedding: EmbeddingConfiguration
