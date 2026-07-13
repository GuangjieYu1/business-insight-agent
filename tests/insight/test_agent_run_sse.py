from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd
import pytest
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.domain import AgentRun, AgentStep
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.routes import insight_project_bp
from data_formulator.insight.run_events import (
    format_sse_event,
    parse_event_cursor,
    project_run_events,
    stream_agent_run_events,
)
from data_formulator.insight.run_service import get_agent_run, start_agent_run
from data_formulator.insight.storage import LocalInsightStore, RunStore


WORKSPACE_ID = "workspace_1"
DATASET_ID = "dataset_sales"


def _dirty_store(tmp_path: Path) -> LocalInsightStore:
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id=WORKSPACE_ID,
        dataframe=pd.DataFrame(
            {
                "name": [" Alice ", " Alice ", "Bob"],
                "constant": ["same", "same", "same"],
                "sales": [10, 10, 20],
            }
        ),
        original_table_ref="sales_raw",
        dataset_id=DATASET_ID,
    )
    return store


def _parse_sse(text: str) -> list[dict[str, object]]:
    parsed: list[dict[str, object]] = []
    for block in text.split("\n\n"):
        if not block.strip() or block.startswith("retry:"):
            continue
        item: dict[str, object] = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                item["id"] = line[4:]
            elif line.startswith("event: "):
                item["event"] = line[7:]
            elif line.startswith("data: "):
                item["data"] = json.loads(line[6:])
        if item:
            parsed.append(item)
    return parsed


def test_projected_run_events_are_ordered_and_replayable(tmp_path: Path):
    store = _dirty_store(tmp_path)
    started = start_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
    )
    snapshot = get_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=started.run.id,
    )

    events = project_run_events(snapshot)
    event_ids = [event.id for event in events]

    assert len(event_ids) == len(set(event_ids))
    assert events[0].id == snapshot.steps[0].id
    assert events[0].event_type == "run_started"
    assert [event.event_type for event in events].count("stage_changed") == 4
    assert all(
        event.id.endswith(":stage")
        for event in events
        if event.event_type == "stage_changed"
    )
    assert events[-1].event_type == "approval_required"
    assert events[-1].payload["stage"] == "waiting_approval"
    assert events[-1].payload["runId"] == started.run.id

    serialized = "".join(format_sse_event(event) for event in events)
    assert "Alice" not in serialized
    assert "same" not in serialized
    assert "event: approval_required" in serialized


def test_event_cursor_validation():
    assert parse_event_cursor(None) is None
    assert parse_event_cursor("") is None
    assert parse_event_cursor(" step_001 ") == "step_001"
    assert parse_event_cursor("step_001:stage") == "step_001:stage"

    with pytest.raises(ValueError, match="invalid"):
        parse_event_cursor("bad\ncursor")
    with pytest.raises(ValueError, match="invalid"):
        parse_event_cursor("x" * 257)


def test_active_run_stream_emits_heartbeat_after_persisted_events(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    run = AgentRun(
        id="run_active",
        workspace_id=WORKSPACE_ID,
        dataset_version_id="version_000",
        status="profiling",
        current_stage="profiling",
        started_at=datetime.now(timezone.utc),
    )
    run_store = RunStore(store, workspace_id=WORKSPACE_ID)
    run_store.create(run)
    run_store.append_step(
        AgentStep(
            id="step_profile",
            workspace_id=WORKSPACE_ID,
            run_id=run.id,
            type="tool_call",
            title="Profile dataset version",
            status="running",
            started_at=datetime.now(timezone.utc),
            progress_text="Profiling is still running.",
        )
    )

    chunks = list(
        stream_agent_run_events(
            store,
            workspace_id=WORKSPACE_ID,
            run_id=run.id,
            heartbeat_interval_seconds=0.0,
            poll_interval_seconds=0.0,
            max_idle_seconds=0.0,
        )
    )
    body = "".join(chunks)

    assert "event: step_progress" in body
    assert "event: heartbeat" in body
    heartbeat = _parse_sse(body)[-1]
    heartbeat_data = heartbeat["data"]
    assert isinstance(heartbeat_data, dict)
    assert heartbeat["event"] == "heartbeat"
    assert heartbeat_data["runId"] == run.id
    assert "id" not in heartbeat


def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)
    register_error_handlers(app)
    monkeypatch.setattr(
        "data_formulator.insight.routes.project.get_identity_id",
        lambda: "local:test",
    )
    monkeypatch.setattr(
        "data_formulator.insight.routes.project.get_workspace",
        lambda _: workspace,
    )
    return app


def _create_waiting_run(client, headers: dict[str, str]) -> str:
    registered = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": DATASET_ID},
        headers=headers,
    )
    assert registered.get_json()["status"] == "success"

    created = client.post(
        "/api/insight/runs",
        json={"datasetId": DATASET_ID},
        headers=headers,
    )
    payload = created.get_json()
    assert payload["status"] == "success"
    assert payload["data"]["run"]["status"] == "waiting_approval"
    return payload["data"]["run"]["id"]


def test_sse_route_replays_events_and_supports_last_event_id(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(
        pd.DataFrame(
            {
                "name": [" Alice ", " Alice ", "Bob"],
                "constant": ["same", "same", "same"],
                "sales": [10, 10, 20],
            }
        ),
        "sales_raw",
    )
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}
    run_id = _create_waiting_run(client, headers)

    response = client.get(
        f"/api/insight/runs/{run_id}/events",
        headers=headers,
        buffered=True,
    )
    body = response.get_data(as_text=True)
    events = _parse_sse(body)
    event_ids = [str(event["id"]) for event in events]

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache, no-transform"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert body.startswith("retry: 3000\n\n")
    assert events[0]["event"] == "run_started"
    assert events[-1]["event"] == "approval_required"
    assert len(event_ids) == len(set(event_ids))

    cursor_index = 3
    cursor = event_ids[cursor_index]
    resumed_headers = {**headers, "Last-Event-ID": cursor}
    resumed = client.get(
        f"/api/insight/runs/{run_id}/events",
        headers=resumed_headers,
        buffered=True,
    )
    resumed_events = _parse_sse(resumed.get_data(as_text=True))

    assert [event["id"] for event in resumed_events] == event_ids[cursor_index + 1 :]
    assert resumed_events[-1]["event"] == "approval_required"


def test_sse_route_supports_query_cursor_and_rejects_unknown_cursor(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(
        pd.DataFrame({"constant": ["same", "same"]}),
        "sales_raw",
    )
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}
    run_id = _create_waiting_run(client, headers)

    full = client.get(
        f"/api/insight/runs/{run_id}/events",
        headers=headers,
        buffered=True,
    )
    full_events = _parse_sse(full.get_data(as_text=True))
    cursor = str(full_events[-2]["id"])

    resumed = client.get(
        f"/api/insight/runs/{run_id}/events?afterEventId={cursor}",
        headers=headers,
        buffered=True,
    )
    resumed_events = _parse_sse(resumed.get_data(as_text=True))
    assert [event["id"] for event in resumed_events] == [full_events[-1]["id"]]

    invalid = client.get(
        f"/api/insight/runs/{run_id}/events?afterEventId=unknown_step",
        headers=headers,
        buffered=True,
    )
    payload = invalid.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_REQUEST"


def test_sse_route_validates_run_before_streaming(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}

    response = client.get(
        "/api/insight/runs/run_missing/events",
        headers=headers,
        buffered=True,
    )
    payload = response.get_json()

    assert payload["status"] == "error"
    assert payload["error"]["code"] == "TABLE_NOT_FOUND"
