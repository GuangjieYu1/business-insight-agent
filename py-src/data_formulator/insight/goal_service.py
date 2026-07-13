"""Intent and AnalysisGoal persistence helpers for Phase 6A."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data_formulator.insight.domain import AnalysisGoal, ClarificationQuestion, GoalCandidate, GoalFilter, GoalType, IntentRequest, Project
from data_formulator.insight.deterministic_goal_candidates import generate_goal_candidates
from data_formulator.insight.domain.models import new_id, utc_now
from data_formulator.insight.registry import (
    PROJECT_PATH,
    InsightRegistryError,
    ensure_project,
    read_dataset,
    read_dataset_version,
    read_project,
)
from data_formulator.insight.storage import (
    DomainObjectNotFoundError,
    DomainStoreError,
    GoalCandidateStore,
    GoalStore,
    InsightStore,
    IntentStore,
)
from data_formulator.insight.version_profiling import (
    generate_dataset_version_profile,
    read_dataset_version_profile,
)

MAX_GOAL_CANDIDATES = 4
_PHASE6_ALLOWED_GOAL_TYPES = frozenset(
    {
        GoalType.TREND_ANALYSIS,
        GoalType.COMPARISON,
        GoalType.DRIVER_ANALYSIS,
        GoalType.SEGMENT_ANALYSIS,
        GoalType.DISTRIBUTION_ANALYSIS,
        GoalType.DATA_QUALITY_REVIEW,
    }
)


class InsightGoalError(ValueError):
    """Base error for intent and goal management."""


class InsightIntentNotFoundError(InsightGoalError):
    """Raised when an IntentRequest cannot be found."""


class InsightGoalNotFoundError(InsightGoalError):
    """Raised when a GoalCandidate or AnalysisGoal cannot be found."""


class InsightGoalConflictError(InsightGoalError):
    """Raised when an intent or goal payload violates workspace invariants."""


@dataclass(frozen=True)
class IntentSnapshot:
    intent: IntentRequest
    goal_candidates: list[GoalCandidate]
    questions: list[ClarificationQuestion]

@dataclass(frozen=True)
class GoalMutationResult:
    goal: AnalysisGoal
    project: Project
    created: bool


@dataclass(frozen=True)
class _ResolvedDatasetVersion:
    dataset_id: str
    version_id: str
    columns: list[str]


def _load_profile_for_intent(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str,
):
    profile = read_dataset_version_profile(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        version_id=version_id,
    )
    if profile is not None:
        return profile
    return generate_dataset_version_profile(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        version_id=version_id,
    )


def _require_text(value: Any, field_name: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InsightGoalConflictError(f"{field_name} is required")
    cleaned = value.strip()
    if max_length is not None and len(cleaned) > max_length:
        raise InsightGoalConflictError(f"{field_name} must be at most {max_length} characters")
    return cleaned

def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InsightGoalConflictError(f"{field_name} must be a string")
    cleaned = value.strip()
    return cleaned or None


def _optional_bool(value: Any, field_name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise InsightGoalConflictError(f"{field_name} must be a boolean")


def _optional_float(value: Any, field_name: str, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        numeric = float(value)
        if 0.0 <= numeric <= 1.0:
            return numeric
    raise InsightGoalConflictError(f"{field_name} must be a number between 0 and 1")


def _normalize_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InsightGoalConflictError(f"{field_name} must be a list of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise InsightGoalConflictError(f"{field_name} must contain non-empty strings")
        cleaned = item.strip()
        if cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)
    return normalized


def _normalize_filters(value: Any) -> list[GoalFilter]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InsightGoalConflictError("filters must be a list")
    filters: list[GoalFilter] = []
    for item in value:
        if isinstance(item, GoalFilter):
            filters.append(item)
            continue
        if not isinstance(item, dict):
            raise InsightGoalConflictError("filters must contain objects")
        try:
            filters.append(GoalFilter.model_validate(item))
        except Exception as exc:  # pragma: no cover - pydantic keeps message specific
            raise InsightGoalConflictError(str(exc)) from exc
    return filters


def _resolve_goal_type(value: Any, field_name: str = "goalType") -> GoalType:
    text = _require_text(value, field_name)
    try:
        goal_type = GoalType(text)
    except ValueError as exc:
        raise InsightGoalConflictError(f"Unsupported goal type: {text}") from exc
    if goal_type not in _PHASE6_ALLOWED_GOAL_TYPES:
        raise InsightGoalConflictError(f"Goal type is not enabled in Phase 6: {goal_type.value}")
    return goal_type


def _resolve_dataset_version(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    dataset_version_id: str | None,
) -> _ResolvedDatasetVersion:
    dataset_id = _require_text(dataset_id, "datasetId")
    try:
        dataset = read_dataset(store, dataset_id)
    except InsightRegistryError as exc:
        raise InsightGoalConflictError(str(exc)) from exc
    if dataset is None:
        raise InsightGoalNotFoundError(f"Dataset not found: {dataset_id}")
    if dataset.workspace_id != workspace_id:
        raise InsightGoalConflictError("Dataset workspace_id does not match active workspace")

    resolved_version_id = dataset_version_id or dataset.active_version_id
    try:
        version = read_dataset_version(store, dataset.id, resolved_version_id)
    except InsightRegistryError as exc:
        raise InsightGoalConflictError(str(exc)) from exc
    if version is None:
        raise InsightGoalNotFoundError(
            f"Dataset version not found: {dataset.id}/{resolved_version_id}"
        )
    if version.workspace_id != workspace_id:
        raise InsightGoalConflictError(
            "Dataset version workspace_id does not match active workspace"
        )
    columns = [str(column) for column in store.read_parquet(version.file_ref).columns.tolist()]
    return _ResolvedDatasetVersion(dataset.id, version.id, columns)


def _validate_field_references(
    *,
    columns: list[str],
    target_metric: str | None,
    dimensions: list[str],
    time_column: str | None,
    filters: list[GoalFilter],
) -> None:
    available = set(columns)
    missing: list[str] = []
    for field in [target_metric, time_column, *dimensions, *[goal_filter.column for goal_filter in filters]]:
        if field is not None and field not in available and field not in missing:
            missing.append(field)
    if missing:
        joined = ", ".join(sorted(missing))
        raise InsightGoalConflictError(f"Referenced fields do not exist in dataset version: {joined}")


def _project_with_active_goal(
    store: InsightStore,
    *,
    workspace_id: str,
    goal_id: str,
) -> Project:
    with store.workspace_lock():
        project = read_project(store)
        if project is None:
            project = Project(
                id=new_id("project"),
                workspace_id=workspace_id,
                name="Business Insight Project",
            )
        if project.workspace_id != workspace_id:
            raise InsightGoalConflictError("Project workspace_id does not match active workspace")
        updated = project.model_copy(
            update={
                "active_goal_id": goal_id,
                "updated_at": utc_now(),
            }
        )
        store.write_json(PROJECT_PATH, updated)
    return updated

def _goal_signature(goal: AnalysisGoal) -> tuple[Any, ...]:
    return (
        goal.dataset_id,
        goal.dataset_version_id,
        goal.intent_id,
        goal.source_candidate_id,
        goal.goal_type,
        goal.title,
        goal.target_metric,
        tuple(goal.dimensions),
        goal.time_column,
        tuple((goal_filter.column, goal_filter.operator, goal_filter.value) for goal_filter in goal.filters),
        goal.task_type,
        goal.description,
        tuple(goal.reasoning),
        round(goal.confidence, 6),
        goal.status,
    )


def _goal_from_candidate(
    *,
    workspace_id: str,
    resolved: _ResolvedDatasetVersion,
    candidate: GoalCandidate | None,
    payload: dict[str, Any],
) -> AnalysisGoal:
    title = _optional_text(payload.get("title"), "title") or (candidate.title if candidate else None)
    if title is None:
        raise InsightGoalConflictError("title is required")
    goal_type = (
        _resolve_goal_type(payload["goalType"], "goalType")
        if payload.get("goalType") is not None
        else (candidate.goal_type if candidate is not None else None)
    )
    if goal_type is None:
        raise InsightGoalConflictError("goalType is required")
    target_metric = _optional_text(payload.get("targetMetric"), "targetMetric")
    if target_metric is None and candidate is not None:
        target_metric = candidate.target_metric
    dimensions = (
        _normalize_string_list(payload.get("dimensions"), "dimensions")
        if payload.get("dimensions") is not None
        else (list(candidate.dimensions) if candidate is not None else [])
    )
    time_column = _optional_text(payload.get("timeColumn"), "timeColumn")
    if time_column is None and candidate is not None:
        time_column = candidate.time_column
    filters = (
        _normalize_filters(payload.get("filters"))
        if payload.get("filters") is not None
        else (list(candidate.filters) if candidate is not None else [])
    )
    description = _optional_text(payload.get("description"), "description") or (
        candidate.description if candidate is not None else ""
    )
    reasoning = (
        _normalize_string_list(payload.get("reasoning"), "reasoning")
        if payload.get("reasoning") is not None
        else (list(candidate.assumptions) if candidate is not None else [])
    )
    confidence = (
        _optional_float(payload.get("confidence"), "confidence", default=0.0)
        if payload.get("confidence") is not None
        else (candidate.confidence if candidate is not None else 0.0)
    )
    task_type = payload.get("taskType") or payload.get("task_type") or "descriptive"
    if task_type not in {"descriptive", "regression", "classification", "forecasting", "anomaly"}:
        raise InsightGoalConflictError("taskType is invalid")

    _validate_field_references(
        columns=resolved.columns,
        target_metric=target_metric,
        dimensions=dimensions,
        time_column=time_column,
        filters=filters,
    )

    return AnalysisGoal(
        id=_optional_text(payload.get("goalId"), "goalId") or new_id("goal"),
        workspace_id=workspace_id,
        dataset_id=resolved.dataset_id,
        dataset_version_id=resolved.version_id,
        intent_id=candidate.intent_id if candidate is not None else _optional_text(payload.get("intentId"), "intentId"),
        source_candidate_id=candidate.id if candidate is not None else _optional_text(payload.get("sourceCandidateId"), "sourceCandidateId"),
        goal_type=goal_type,
        title=title,
        target_column=target_metric,
        target_metric=target_metric,
        dimensions=dimensions,
        time_column=time_column,
        filters=filters,
        task_type=task_type,
        description=description,
        reasoning=reasoning,
        confidence=confidence,
        status="confirmed",
    )


def _candidate_from_payload(
    *,
    workspace_id: str,
    intent_id: str,
    resolved: _ResolvedDatasetVersion,
    payload: dict[str, Any],
) -> GoalCandidate:
    title = _require_text(payload.get("title"), "goalCandidates[].title")
    goal_type = _resolve_goal_type(
        payload.get("goalType") if payload.get("goalType") is not None else payload.get("goal_type"),
        "goalCandidates[].goalType",
    )
    target_metric = _optional_text(
        payload.get("targetMetric") if payload.get("targetMetric") is not None else payload.get("target_metric"),
        "goalCandidates[].targetMetric",
    )
    dimensions = _normalize_string_list(payload.get("dimensions"), "goalCandidates[].dimensions")
    time_column = _optional_text(
        payload.get("timeColumn") if payload.get("timeColumn") is not None else payload.get("time_column"),
        "goalCandidates[].timeColumn",
    )
    filters = _normalize_filters(payload.get("filters"))
    _validate_field_references(
        columns=resolved.columns,
        target_metric=target_metric,
        dimensions=dimensions,
        time_column=time_column,
        filters=filters,
    )
    return GoalCandidate(
        id=_optional_text(payload.get("id"), "goalCandidates[].id") or new_id("goal_candidate"),
        workspace_id=workspace_id,
        intent_id=intent_id,
        dataset_id=resolved.dataset_id,
        dataset_version_id=resolved.version_id,
        title=title,
        description=_optional_text(payload.get("description"), "goalCandidates[].description") or "",
        goal_type=goal_type,
        target_metric=target_metric,
        dimensions=dimensions,
        time_column=time_column,
        filters=filters,
        confidence=_optional_float(payload.get("confidence"), "goalCandidates[].confidence", default=0.0),
        assumptions=_normalize_string_list(payload.get("assumptions"), "goalCandidates[].assumptions"),
        missing_information=_normalize_string_list(
            payload.get("missingInformation")
            if payload.get("missingInformation") is not None
            else payload.get("missing_information"),
            "goalCandidates[].missingInformation",
        ),
        requires_confirmation=_optional_bool(
            payload.get("requiresConfirmation")
            if payload.get("requiresConfirmation") is not None
            else payload.get("requires_confirmation"),
            "goalCandidates[].requiresConfirmation",
            default=True,
        ),
    )


def create_intent_request(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    dataset_version_id: str | None,
    user_input: str,
    goal_candidates: list[dict[str, Any]] | None = None,
) -> IntentSnapshot:
    resolved = _resolve_dataset_version(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
    )
    intent_store = IntentStore(store, workspace_id=workspace_id)
    candidate_store = GoalCandidateStore(store, workspace_id=workspace_id)
    intent = IntentRequest(
        id=new_id("intent"),
        workspace_id=workspace_id,
        dataset_id=resolved.dataset_id,
        dataset_version_id=resolved.version_id,
        user_input=_require_text(user_input, "userInput", max_length=2000),
    )
    intent_store.create(intent)

    candidate_models: list[GoalCandidate] = []
    questions: list[ClarificationQuestion] = []
    if goal_candidates is not None:
        if not isinstance(goal_candidates, list):
            raise InsightGoalConflictError("goalCandidates must be a list")
        if len(goal_candidates) > MAX_GOAL_CANDIDATES:
            raise InsightGoalConflictError("An intent can return at most 4 goal candidates")
        for candidate_payload in goal_candidates:
            if not isinstance(candidate_payload, dict):
                raise InsightGoalConflictError("goalCandidates must contain objects")
            candidate_models.append(
                _candidate_from_payload(
                    workspace_id=workspace_id,
                    intent_id=intent.id,
                    resolved=resolved,
                    payload=candidate_payload,
                )
            )
    else:
        profile = _load_profile_for_intent(
            store,
            workspace_id=workspace_id,
            dataset_id=resolved.dataset_id,
            version_id=resolved.version_id,
        )
        generated = generate_goal_candidates(
            workspace_id=workspace_id,
            intent_id=intent.id,
            dataset_id=resolved.dataset_id,
            dataset_version_id=resolved.version_id,
            user_input=intent.user_input,
            profile=profile,
        )
        candidate_models = generated.candidates
        questions = generated.questions

    candidate_store.replace_for_intent(intent.id, candidate_models)
    status = "candidates_ready" if candidate_models or questions else "created"
    intent = intent_store.update(
        intent.model_copy(
            update={
                "clarification_questions": questions,
                "status": status,
                "updated_at": utc_now(),
            }
        )
    )
    return IntentSnapshot(intent=intent, goal_candidates=candidate_models, questions=list(intent.clarification_questions))


def get_intent_snapshot(
    store: InsightStore,
    *,
    workspace_id: str,
    intent_id: str,
) -> IntentSnapshot:
    try:
        intent = IntentStore(store, workspace_id=workspace_id).read(intent_id)
    except DomainStoreError as exc:
        raise InsightGoalConflictError(str(exc)) from exc
    if intent is None:
        raise InsightIntentNotFoundError(f"IntentRequest not found: {intent_id}")
    candidates = GoalCandidateStore(store, workspace_id=workspace_id).list_for_intent(intent.id)
    return IntentSnapshot(intent=intent, goal_candidates=candidates, questions=list(intent.clarification_questions))


def get_analysis_goal(
    store: InsightStore,
    *,
    workspace_id: str,
    goal_id: str,
) -> AnalysisGoal:
    try:
        goal = GoalStore(store, workspace_id=workspace_id).read(goal_id)
    except DomainStoreError as exc:
        raise InsightGoalConflictError(str(exc)) from exc
    if goal is None:
        raise InsightGoalNotFoundError(f"AnalysisGoal not found: {goal_id}")
    return goal


def _resolve_goal_intent(
    store: InsightStore,
    *,
    workspace_id: str,
    resolved: _ResolvedDatasetVersion,
    candidate: GoalCandidate | None,
    explicit_intent_id: str | None,
) -> IntentRequest | None:
    if candidate is not None and explicit_intent_id is not None and explicit_intent_id != candidate.intent_id:
        raise InsightGoalConflictError("sourceCandidateId does not match intentId")
    intent_id = candidate.intent_id if candidate is not None else explicit_intent_id
    if intent_id is None:
        return None
    intent = IntentStore(store, workspace_id=workspace_id).read(intent_id)
    if intent is None:
        raise InsightIntentNotFoundError(f"IntentRequest not found: {intent_id}")
    if intent.dataset_id != resolved.dataset_id or intent.dataset_version_id != resolved.version_id:
        raise InsightGoalConflictError("IntentRequest does not match the selected dataset version")
    return intent

def create_analysis_goal(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    dataset_version_id: str | None,
    payload: dict[str, Any],
) -> GoalMutationResult:
    resolved = _resolve_dataset_version(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
    )
    explicit_intent_id = _optional_text(
        payload.get("intentId") if payload.get("intentId") is not None else payload.get("intent_id"),
        "intentId",
    )
    candidate = None
    source_candidate_id = _optional_text(
        payload.get("sourceCandidateId") if payload.get("sourceCandidateId") is not None else payload.get("source_candidate_id"),
        "sourceCandidateId",
    )
    if source_candidate_id is not None:
        candidate = GoalCandidateStore(store, workspace_id=workspace_id).read(source_candidate_id)
        if candidate is None:
            raise InsightGoalNotFoundError(f"GoalCandidate not found: {source_candidate_id}")
        if candidate.dataset_id != resolved.dataset_id or candidate.dataset_version_id != resolved.version_id:
            raise InsightGoalConflictError("GoalCandidate does not belong to the selected dataset version")

    intent = _resolve_goal_intent(
        store,
        workspace_id=workspace_id,
        resolved=resolved,
        candidate=candidate,
        explicit_intent_id=explicit_intent_id,
    )

    goal = _goal_from_candidate(
        workspace_id=workspace_id,
        resolved=resolved,
        candidate=candidate,
        payload=payload,
    )
    goal_store = GoalStore(store, workspace_id=workspace_id)
    intent_store = IntentStore(store, workspace_id=workspace_id)
    for existing in goal_store.list():
        if _goal_signature(existing) == _goal_signature(goal):
            project = _project_with_active_goal(
                store,
                workspace_id=workspace_id,
                goal_id=existing.id,
            )
            if intent is not None and intent.status != "confirmed":
                intent_store.update(
                    intent.model_copy(update={"status": "confirmed", "updated_at": utc_now()})
                )
            return GoalMutationResult(goal=existing, project=project, created=False)

    goal = goal_store.create(goal)
    if intent is not None and intent.status != "confirmed":
        intent_store.update(intent.model_copy(update={"status": "confirmed", "updated_at": utc_now()}))
    project = _project_with_active_goal(store, workspace_id=workspace_id, goal_id=goal.id)
    return GoalMutationResult(goal=goal, project=project, created=True)



def update_analysis_goal(
    store: InsightStore,
    *,
    workspace_id: str,
    goal_id: str,
    payload: dict[str, Any],
) -> GoalMutationResult:
    existing = get_analysis_goal(store, workspace_id=workspace_id, goal_id=goal_id)
    if existing.dataset_id is None:
        raise InsightGoalConflictError("Legacy AnalysisGoal cannot be updated until dataset binding is defined")
    resolved = _resolve_dataset_version(
        store,
        workspace_id=workspace_id,
        dataset_id=existing.dataset_id,
        dataset_version_id=existing.dataset_version_id,
    )
    candidate = None
    if existing.source_candidate_id is not None:
        candidate = GoalCandidateStore(store, workspace_id=workspace_id).read(existing.source_candidate_id)
        if candidate is None:
            raise InsightGoalNotFoundError(
                f"GoalCandidate not found: {existing.source_candidate_id}"
            )
    explicit_intent_id = _optional_text(existing.intent_id, "intentId")
    intent = _resolve_goal_intent(
        store,
        workspace_id=workspace_id,
        resolved=resolved,
        candidate=candidate,
        explicit_intent_id=explicit_intent_id,
    )

    requested_status = payload.get("status") if "status" in payload else existing.status
    if requested_status not in {"candidate", "confirmed", "rejected"}:
        raise InsightGoalConflictError("status is invalid")
    if existing.status == "confirmed" and requested_status != "confirmed":
        raise InsightGoalConflictError("Confirmed AnalysisGoal cannot transition to a non-confirmed state")
    if existing.status == "rejected" and requested_status != "rejected":
        raise InsightGoalConflictError("Rejected AnalysisGoal cannot transition to a different state")
    if existing.status == "candidate" and requested_status not in {"candidate", "confirmed"}:
        raise InsightGoalConflictError("Candidate AnalysisGoal can only remain candidate or become confirmed")

    merged_payload = {
        "goalId": existing.id,
        "title": payload.get("title", existing.title),
        "goalType": payload.get("goalType", payload.get("goal_type", existing.goal_type)),
        "targetMetric": payload.get("targetMetric", payload.get("target_metric", existing.target_metric)),
        "dimensions": payload.get("dimensions", list(existing.dimensions)),
        "timeColumn": payload.get("timeColumn", payload.get("time_column", existing.time_column)),
        "filters": payload.get("filters", [goal_filter.model_dump(mode="json") for goal_filter in existing.filters]),
        "description": payload.get("description", existing.description),
        "reasoning": payload.get("reasoning", list(existing.reasoning)),
        "confidence": payload.get("confidence", existing.confidence),
        "taskType": payload.get("taskType", payload.get("task_type", existing.task_type)),
        "sourceCandidateId": existing.source_candidate_id,
        "intentId": existing.intent_id,
    }
    updated = _goal_from_candidate(
        workspace_id=workspace_id,
        resolved=resolved,
        candidate=candidate,
        payload=merged_payload,
    ).model_copy(
        update={
            "created_at": existing.created_at,
            "updated_at": utc_now(),
            "status": requested_status,
        }
    )
    goal_store = GoalStore(store, workspace_id=workspace_id)
    updated = goal_store.update(updated)
    if intent is not None and updated.status == "confirmed" and intent.status != "confirmed":
        IntentStore(store, workspace_id=workspace_id).update(
            intent.model_copy(update={"status": "confirmed", "updated_at": utc_now()})
        )
    project = (
        _project_with_active_goal(store, workspace_id=workspace_id, goal_id=updated.id)
        if updated.status == "confirmed"
        else read_project(store) or ensure_project(store, workspace_id=workspace_id).project
    )
    return GoalMutationResult(goal=updated, project=project, created=False)