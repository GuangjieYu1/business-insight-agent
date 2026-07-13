"""Server-Sent Event projection for persisted Business Insight AgentRun state.

Business events are derived from append-only ``AgentStep`` records so reconnects
can replay the same sequence deterministically. Heartbeats are transport-only
and are intentionally not persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
from typing import Any, Iterator

from data_formulator.insight.domain import AgentStep
from data_formulator.insight.run_service import RunSnapshot, get_agent_run
from data_formulator.insight.storage import InsightStore


CLOSED_STREAM_STATUSES = frozenset(
    {
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
    }
)

_STEP_STAGE_BY_TITLE = {
    "Analysis run started": "created",
    "Inspect dataset version": "context_building",
    "Profile dataset version": "profiling",
    "Generate cleaning proposals": "planning",
    "Cleaning approval required": "waiting_approval",
    "Analysis run completed": "completed",
    "Analysis run cancelled": "cancelled",
}

_STEP_EVENT_BY_TITLE = {
    "Analysis run started": "run_started",
    "Cleaning approval required": "approval_required",
    "Analysis run completed": "run_completed",
    "Analysis run failed": "run_failed",
    "Analysis run cancelled": "run_cancelled",
}


@dataclass(frozen=True)
class RunEvent:
    id: int
    event_type: str
    payload: dict[str, Any]


def _timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    return timestamp.isoformat()


def _step_stage(step: AgentStep) -> str:
    detail_stage = step.detail.get("stage")
    if isinstance(detail_stage, str) and detail_stage.strip():
        return detail_stage
    return _STEP_STAGE_BY_TITLE.get(step.title, "unknown")


def _step_event_type(step: AgentStep) -> str:
    explicit = step.detail.get("event_type")
    if isinstance(explicit, str) and explicit.strip():
        return explicit
    mapped = _STEP_EVENT_BY_TITLE.get(step.title)
    if mapped is not None:
        return mapped
    if step.type == "approval":
        return "approval_required"
    if step.type == "artifact":
        return "artifact_created"
    if step.type == "claim":
        return "claim_created"
    if step.status == "running":
        return "step_progress"
    if step.status == "failed":
        return "run_failed" if step.type == "error" else "step_completed"
    if step.status == "cancelled":
        return "run_cancelled"
    return "step_completed"


def _stage_payload(snapshot: RunSnapshot, step: AgentStep, stage: str) -> dict[str, Any]:
    return {
        "eventType": "stage_changed",
        "runId": snapshot.run.id,
        "stepId": step.id,
        "stage": stage,
        "status": snapshot.run.status,
        "title": f"Stage changed to {stage}",
        "progressText": step.progress_text,
        "detail": {"sourceStepId": step.id},
        "collapsedByDefault": True,
        "timestamp": _timestamp(step.started_at or step.created_at),
    }


def _step_payload(snapshot: RunSnapshot, step: AgentStep, stage: str, event_type: str) -> dict[str, Any]:
    return {
        "eventType": event_type,
        "runId": snapshot.run.id,
        "stepId": step.id,
        "stage": stage,
        "status": step.status,
        "title": step.title,
        "progressText": step.progress_text,
        "detail": step.detail,
        "inputRefs": step.input_refs,
        "outputRefs": step.output_refs,
        "collapsedByDefault": step.collapsed_by_default,
        "timestamp": _timestamp(step.completed_at or step.started_at or step.created_at),
    }


def project_run_events(snapshot: RunSnapshot) -> list[RunEvent]:
    """Project persisted Run steps into a stable, replayable event sequence."""

    events: list[RunEvent] = []
    previous_stage: str | None = None
    next_id = 0

    for step in snapshot.steps:
        stage = _step_stage(step)
        if previous_stage is not None and stage != previous_stage and stage != "unknown":
            events.append(
                RunEvent(
                    id=next_id,
                    event_type="stage_changed",
                    payload=_stage_payload(snapshot, step, stage),
                )
            )
            next_id += 1
        if stage != "unknown":
            previous_stage = stage

        event_type = _step_event_type(step)
        events.append(
            RunEvent(
                id=next_id,
                event_type=event_type,
                payload=_step_payload(snapshot, step, stage, event_type),
            )
        )
        next_id += 1

    return events


def format_sse_event(event: RunEvent) -> str:
    data = json.dumps(
        event.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"id: {event.id}\nevent: {event.event_type}\ndata: {data}\n\n"


def format_heartbeat(run_id: str) -> str:
    payload = {
        "eventType": "heartbeat",
        "runId": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"event: heartbeat\ndata: {data}\n\n"


def parse_event_cursor(value: str | None) -> int:
    if value is None or not value.strip():
        return -1
    try:
        cursor = int(value)
    except ValueError as exc:
        raise ValueError("Last-Event-ID must be a non-negative integer") from exc
    if cursor < 0:
        raise ValueError("Last-Event-ID must be a non-negative integer")
    return cursor


def stream_agent_run_events(
    store: InsightStore,
    *,
    workspace_id: str,
    run_id: str,
    after_event_id: int = -1,
    poll_interval_seconds: float = 0.5,
    heartbeat_interval_seconds: float = 15.0,
    max_idle_seconds: float | None = None,
) -> Iterator[str]:
    """Replay persisted events, then follow newly appended Run steps.

    Streams for terminal and approval-waiting Runs close after all persisted
    events are delivered. Active Runs remain open, poll for new steps, and emit
    transport heartbeats. ``max_idle_seconds`` exists for bounded tests and
    operational probes; normal HTTP usage leaves it unset.
    """

    last_sent = after_event_id
    idle_started = time.monotonic()
    last_heartbeat = idle_started

    while True:
        snapshot = get_agent_run(
            store,
            workspace_id=workspace_id,
            run_id=run_id,
        )
        events = project_run_events(snapshot)
        pending = [event for event in events if event.id > last_sent]

        if pending:
            for event in pending:
                yield format_sse_event(event)
                last_sent = event.id
            idle_started = time.monotonic()

        if (
            snapshot.run.status in CLOSED_STREAM_STATUSES
            and last_sent >= len(events) - 1
        ):
            return

        now = time.monotonic()
        if heartbeat_interval_seconds >= 0 and (
            now - last_heartbeat >= heartbeat_interval_seconds
        ):
            yield format_heartbeat(snapshot.run.id)
            last_heartbeat = now

        if max_idle_seconds is not None and now - idle_started >= max_idle_seconds:
            return

        time.sleep(max(0.0, poll_interval_seconds))
