"""Generator protocol for deterministic editorial outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from core.overview_editorial.context import PortfolioContext
from models.overview_editorial import ArtifactDirective, InsightCandidate, MarginAnnotation


@dataclass(slots=True)
class GeneratorOutput:
    """All outputs produced by a single generator run."""

    candidates: list[InsightCandidate] = field(default_factory=list)
    directives: list[ArtifactDirective] = field(default_factory=list)
    annotations: list[MarginAnnotation] = field(default_factory=list)


class InsightGenerator(Protocol):
    name: str

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        """Return deterministic candidates plus directives and margin annotations."""
