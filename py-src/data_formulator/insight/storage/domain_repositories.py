"""Workspace-scoped repositories for Business Insight domain persistence.

The low-level :class:`InsightStore` owns path confinement and atomic file I/O.
These repositories add domain paths, ID validation, workspace ownership checks,
and object-specific invariants so services never assemble persistence paths.
"""

from __future__ import annotations

import re
from typing import Generic, TypeVar

from pydantic import BaseModel

from data_formulator.insight.domain import (
    AgentRun,
    AgentStep,
    AnalysisGoal,
    Approval,
    Artifact,
    Claim,
    EvidenceRef,
    Experiment,
    FinalSummary,
    GoalCandidate,
    IntentRequest,
    ProjectMaterial,
)
from data_formulator.insight.domain.models import InsightModel, utc_now

from .base import InsightStore


TModel = TypeVar("TModel", bound=InsightModel)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class DomainStoreError(ValueError):
    """Raised when domain persistence would violate ownership or layout rules."""


class DomainObjectAlreadyExistsError(DomainStoreError):
    """Raised when create would overwrite an existing domain object."""


class DomainObjectNotFoundError(DomainStoreError):
    """Raised when an update or append target does not exist."""


def _safe_id(value: str, field_name: str = "id") -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise DomainStoreError(
            f"{field_name} must contain only letters, numbers, underscore, or dash"
        )
    return value


def _require_workspace(model: InsightModel, workspace_id: str) -> None:
    if model.workspace_id != workspace_id:
        raise DomainStoreError(
            f"{type(model).__name__} workspace_id does not match active workspace"
        )


class _WorkspaceModelStore(Generic[TModel]):
    """Reusable atomic JSON repository for one workspace-owned model type."""

    def __init__(
        self,
        store: InsightStore,
        *,
        workspace_id: str,
        directory: str,
        model_type: type[TModel],
    ) -> None:
        self.store = store
        self.workspace_id = workspace_id
        self.directory = directory.strip("/")
        self.model_type = model_type
        if not workspace_id.strip():
            raise DomainStoreError("workspace_id is required")

    def _path(self, object_id: str) -> str:
        return f"{self.directory}/{_safe_id(object_id)}.json"

    def create(self, model: TModel) -> TModel:
        _require_workspace(model, self.workspace_id)
        path = self._path(model.id)
        with self.store.workspace_lock():
            if self.store.exists(path):
                raise DomainObjectAlreadyExistsError(
                    f"{type(model).__name__} already exists: {model.id}"
                )
            self.store.write_json(path, model)
        return model

    def read(self, object_id: str) -> TModel | None:
        path = self._path(object_id)
        if not self.store.exists(path):
            return None
        model = self.store.read_model(path, self.model_type)
        _require_workspace(model, self.workspace_id)
        return model

    def require(self, object_id: str) -> TModel:
        model = self.read(object_id)
        if model is None:
            raise DomainObjectNotFoundError(
                f"{self.model_type.__name__} not found: {object_id}"
            )
        return model

    def update(self, model: TModel) -> TModel:
        _require_workspace(model, self.workspace_id)
        path = self._path(model.id)
        with self.store.workspace_lock():
            if not self.store.exists(path):
                raise DomainObjectNotFoundError(
                    f"{type(model).__name__} not found: {model.id}"
                )
            existing = self.store.read_model(path, self.model_type)
            _require_workspace(existing, self.workspace_id)
            if model.created_at != existing.created_at:
                raise DomainStoreError("created_at is immutable")
            self.store.write_json(path, model)
        return model

    def list(self) -> list[TModel]:
        models: list[TModel] = []
        prefix = f"{self.directory}/"
        for relative_path in self.store.list(self.directory):
            if not relative_path.startswith(prefix) or not relative_path.endswith(".json"):
                continue
            # Generic stores are flat. Nested layouts are handled by RunStore and
            # ExperimentStore rather than accepted accidentally here.
            if "/" in relative_path[len(prefix) :]:
                continue
            model = self.store.read_model(relative_path, self.model_type)
            _require_workspace(model, self.workspace_id)
            models.append(model)
        return sorted(models, key=lambda item: (item.created_at, item.id))


class MaterialStore(_WorkspaceModelStore[ProjectMaterial]):
    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        super().__init__(
            store,
            workspace_id=workspace_id,
            directory="materials",
            model_type=ProjectMaterial,
        )


class IntentStore(_WorkspaceModelStore[IntentRequest]):
    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        super().__init__(
            store,
            workspace_id=workspace_id,
            directory="intents",
            model_type=IntentRequest,
        )


class GoalCandidateStore(_WorkspaceModelStore[GoalCandidate]):
    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        super().__init__(
            store,
            workspace_id=workspace_id,
            directory="goal_candidates",
            model_type=GoalCandidate,
        )

    def list_for_intent(self, intent_id: str) -> list[GoalCandidate]:
        safe_intent_id = _safe_id(intent_id, "intent_id")
        return [
            candidate for candidate in self.list() if candidate.intent_id == safe_intent_id
        ]

    def replace_for_intent(
        self,
        intent_id: str,
        candidates: list[GoalCandidate],
    ) -> list[GoalCandidate]:
        safe_intent_id = _safe_id(intent_id, "intent_id")
        if len(candidates) > 4:
            raise DomainStoreError("An intent can store at most 4 goal candidates")
        with self.store.workspace_lock():
            for relative_path in list(self.store.list(self.directory)):
                if not relative_path.endswith(".json"):
                    continue
                existing = self.store.read_model(relative_path, self.model_type)
                _require_workspace(existing, self.workspace_id)
                if existing.intent_id == safe_intent_id:
                    self.store.remove_tree(relative_path)
            for candidate in candidates:
                _require_workspace(candidate, self.workspace_id)
                if candidate.intent_id != safe_intent_id:
                    raise DomainStoreError("GoalCandidate intent_id does not match target intent")
                self.store.write_json(self._path(candidate.id), candidate)
        return self.list_for_intent(safe_intent_id)


class GoalStore(_WorkspaceModelStore[AnalysisGoal]):
    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        super().__init__(
            store,
            workspace_id=workspace_id,
            directory="goals",
            model_type=AnalysisGoal,
        )


class ArtifactStore(_WorkspaceModelStore[Artifact]):
    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        super().__init__(
            store,
            workspace_id=workspace_id,
            directory="artifacts",
            model_type=Artifact,
        )


class ApprovalStore(_WorkspaceModelStore[Approval]):
    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        super().__init__(
            store,
            workspace_id=workspace_id,
            directory="approvals",
            model_type=Approval,
        )


class ExperimentStore:
    """Persist Experiment specs under ``experiments/<id>/spec.json``."""

    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        self.store = store
        self.workspace_id = workspace_id
        if not workspace_id.strip():
            raise DomainStoreError("workspace_id is required")

    @staticmethod
    def _path(experiment_id: str) -> str:
        return f"experiments/{_safe_id(experiment_id, 'experiment_id')}/spec.json"

    def create(self, experiment: Experiment) -> Experiment:
        _require_workspace(experiment, self.workspace_id)
        path = self._path(experiment.id)
        with self.store.workspace_lock():
            if self.store.exists(path):
                raise DomainObjectAlreadyExistsError(
                    f"Experiment already exists: {experiment.id}"
                )
            self.store.write_json(path, experiment)
        return experiment

    def read(self, experiment_id: str) -> Experiment | None:
        path = self._path(experiment_id)
        if not self.store.exists(path):
            return None
        experiment = self.store.read_model(path, Experiment)
        _require_workspace(experiment, self.workspace_id)
        return experiment

    def require(self, experiment_id: str) -> Experiment:
        experiment = self.read(experiment_id)
        if experiment is None:
            raise DomainObjectNotFoundError(
                f"Experiment not found: {experiment_id}"
            )
        return experiment

    def update(self, experiment: Experiment) -> Experiment:
        _require_workspace(experiment, self.workspace_id)
        path = self._path(experiment.id)
        with self.store.workspace_lock():
            if not self.store.exists(path):
                raise DomainObjectNotFoundError(
                    f"Experiment not found: {experiment.id}"
                )
            existing = self.store.read_model(path, Experiment)
            _require_workspace(existing, self.workspace_id)
            if experiment.created_at != existing.created_at:
                raise DomainStoreError("created_at is immutable")
            self.store.write_json(path, experiment)
        return experiment

    def list(self) -> list[Experiment]:
        experiments: list[Experiment] = []
        for relative_path in self.store.list("experiments"):
            if not relative_path.endswith("/spec.json"):
                continue
            experiment = self.store.read_model(relative_path, Experiment)
            _require_workspace(experiment, self.workspace_id)
            experiments.append(experiment)
        return sorted(experiments, key=lambda item: (item.created_at, item.id))


class EvidenceStore:
    """Persist Evidence and Claims while enforcing evidence references."""

    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        self._evidence = _WorkspaceModelStore(
            store,
            workspace_id=workspace_id,
            directory="evidence",
            model_type=EvidenceRef,
        )
        self._claims = _WorkspaceModelStore(
            store,
            workspace_id=workspace_id,
            directory="claims",
            model_type=Claim,
        )
        self.workspace_id = workspace_id

    def create_evidence(self, evidence: EvidenceRef) -> EvidenceRef:
        return self._evidence.create(evidence)

    def read_evidence(self, evidence_id: str) -> EvidenceRef | None:
        return self._evidence.read(evidence_id)

    def list_evidence(self) -> list[EvidenceRef]:
        return self._evidence.list()

    def create_claim(self, claim: Claim) -> Claim:
        _require_workspace(claim, self.workspace_id)
        for evidence_id in claim.evidence_refs:
            if self._evidence.read(evidence_id) is None:
                raise DomainStoreError(
                    f"Claim references missing evidence: {evidence_id}"
                )
        return self._claims.create(claim)

    def read_claim(self, claim_id: str) -> Claim | None:
        return self._claims.read(claim_id)

    def list_claims(self) -> list[Claim]:
        return self._claims.list()


class RunStore:
    """Persist run state, append-only steps, and the final summary."""

    def __init__(self, store: InsightStore, *, workspace_id: str) -> None:
        self.store = store
        self.workspace_id = workspace_id
        if not workspace_id.strip():
            raise DomainStoreError("workspace_id is required")

    @staticmethod
    def _run_dir(run_id: str) -> str:
        return f"runs/{_safe_id(run_id, 'run_id')}"

    @classmethod
    def _run_path(cls, run_id: str) -> str:
        return f"{cls._run_dir(run_id)}/run.json"

    @classmethod
    def _steps_path(cls, run_id: str) -> str:
        return f"{cls._run_dir(run_id)}/steps.ndjson"

    @classmethod
    def _summary_path(cls, run_id: str) -> str:
        return f"{cls._run_dir(run_id)}/final_summary.json"

    def create(self, run: AgentRun) -> AgentRun:
        _require_workspace(run, self.workspace_id)
        path = self._run_path(run.id)
        with self.store.workspace_lock():
            if self.store.exists(path):
                raise DomainObjectAlreadyExistsError(
                    f"AgentRun already exists: {run.id}"
                )
            self.store.write_json(path, run)
        return run

    def read(self, run_id: str) -> AgentRun | None:
        path = self._run_path(run_id)
        if not self.store.exists(path):
            return None
        run = self.store.read_model(path, AgentRun)
        _require_workspace(run, self.workspace_id)
        return run

    def require(self, run_id: str) -> AgentRun:
        run = self.read(run_id)
        if run is None:
            raise DomainObjectNotFoundError(f"AgentRun not found: {run_id}")
        return run

    def update(self, run: AgentRun) -> AgentRun:
        _require_workspace(run, self.workspace_id)
        path = self._run_path(run.id)
        with self.store.workspace_lock():
            if not self.store.exists(path):
                raise DomainObjectNotFoundError(f"AgentRun not found: {run.id}")
            existing = self.store.read_model(path, AgentRun)
            _require_workspace(existing, self.workspace_id)
            if run.created_at != existing.created_at:
                raise DomainStoreError("created_at is immutable")
            self.store.write_json(path, run)
        return run

    def list(self) -> list[AgentRun]:
        runs: list[AgentRun] = []
        for relative_path in self.store.list("runs"):
            if not relative_path.endswith("/run.json"):
                continue
            run = self.store.read_model(relative_path, AgentRun)
            _require_workspace(run, self.workspace_id)
            runs.append(run)
        return sorted(runs, key=lambda item: (item.created_at, item.id))

    def append_step(self, step: AgentStep) -> AgentStep:
        _require_workspace(step, self.workspace_id)
        _safe_id(step.id, "step_id")
        run = self.require(step.run_id)
        if run.id != step.run_id:
            raise DomainStoreError("AgentStep run_id does not match AgentRun")

        with self.store.workspace_lock():
            # Re-read under the lock so a run cannot disappear or change owner
            # between validation and append.
            locked_run = self.store.read_model(self._run_path(step.run_id), AgentRun)
            _require_workspace(locked_run, self.workspace_id)
            existing_steps = self._read_steps_unlocked(step.run_id)
            if any(existing.id == step.id for existing in existing_steps):
                raise DomainObjectAlreadyExistsError(
                    f"AgentStep already exists: {step.id}"
                )
            self.store.append_ndjson(self._steps_path(step.run_id), step)
        return step

    def _read_steps_unlocked(self, run_id: str) -> list[AgentStep]:
        records = self.store.read_ndjson(self._steps_path(run_id))
        steps: list[AgentStep] = []
        for record in records:
            step = AgentStep.model_validate(record)
            _require_workspace(step, self.workspace_id)
            if step.run_id != run_id:
                raise DomainStoreError("Persisted AgentStep run_id is inconsistent")
            steps.append(step)
        return steps

    def list_steps(self, run_id: str) -> list[AgentStep]:
        self.require(run_id)
        return self._read_steps_unlocked(run_id)

    def write_final_summary(self, summary: FinalSummary) -> FinalSummary:
        _require_workspace(summary, self.workspace_id)
        run = self.require(summary.run_id)
        summary_path = self._summary_path(run.id)
        with self.store.workspace_lock():
            current_run = self.store.read_model(self._run_path(run.id), AgentRun)
            _require_workspace(current_run, self.workspace_id)
            self.store.write_json(summary_path, summary)
            updated_run = current_run.model_copy(
                update={
                    "final_summary_ref": summary_path,
                    "updated_at": utc_now(),
                }
            )
            self.store.write_json(self._run_path(run.id), updated_run)
        return summary

    def read_final_summary(self, run_id: str) -> FinalSummary | None:
        self.require(run_id)
        path = self._summary_path(run_id)
        if not self.store.exists(path):
            return None
        summary = self.store.read_model(path, FinalSummary)
        _require_workspace(summary, self.workspace_id)
        if summary.run_id != run_id:
            raise DomainStoreError("FinalSummary run_id is inconsistent")
        return summary
