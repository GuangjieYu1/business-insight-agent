"""Persistence-focused domain contracts used by later analysis stages."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from .models import InsightModel


class Artifact(InsightModel):
    """A workspace-owned output produced by cleaning, analysis, or experiments."""

    artifact_type: Literal[
        "table",
        "chart",
        "metric",
        "model",
        "report",
        "file",
        "other",
    ]
    title: str
    run_id: str | None = None
    experiment_id: str | None = None
    dataset_version_id: str | None = None
    file_ref: str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("file_ref")
    @classmethod
    def _relative_file_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("artifact file_ref must be workspace-relative")
        return normalized


class FinalSummary(InsightModel):
    """Persisted final presentation for one AgentRun."""

    run_id: str
    title: str
    executive_summary: str
    claim_refs: list[str] = Field(default_factory=list)
    operation_refs: list[str] = Field(default_factory=list)
    metric_changes: list[dict[str, Any]] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
