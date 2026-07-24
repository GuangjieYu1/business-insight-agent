from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.background_runs import (
    create_background_agent_run,
    execute_background_agent_run,
    list_agent_runs,
)
from data_formulator.insight.goal_service import create_analysis_goal
from data_formulator.insight.registry import read_dataset, register_dataset_version_zero
from data_formulator.insight.routes import insight_project_bp
from data_formulator.insight.run_events import project_run_events
from data_formulator.insight.run_service import (
    InsightRunConflictError,
    cancel_agent_run,
    get_agent_run,
)
from data_formulator.insight.storage import LocalInsightStore


WORKSPACE_ID = "workspace_1"
DATASET_ID = "dataset_sales"


def _store(tmp_path: Path, *, dataset_id: str = DATASET_ID) -> LocalInsightStore:
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
        original_table_ref=f"{dataset_id}_raw",
        dataset_id=dataset_id,
    )
    return store


def _confirmed_goal_id(store: LocalInsightStore, dataset_id: str = DATASET_ID) -> str:
    return create_analysis_goal(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=dataset_id,
        dataset_version_id="version_000",
        payload={
            "title": "Analyze sales drivers",
            "goalType": "driver_analysis",
            "targetMetric": "sales",
            "dimensions": ["name"],
        },
    ).goal.id


def test_background_creation_returns_before_execution_and_preserves_dataset(tmp_path: Path):
    store = _store(tmp_path)

    created = create_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        goal_id=_confirmed_goal_id(store),
    )

    assert created.run.status == "created"
    assert created.run.current_stage == "created"
    assert len(created.steps) == 1
    assert created.steps[0].title == "Analysis run started"
    assert created.steps[0].detail["execution_mode"] == "background"

    dataset = read_dataset(store, DATASET_ID)
    assert dataset is not None
    assert dataset.active_version_id == "version_000"


def test_background_execution_reaches_waiting_approval_without_data_mutation(tmp_path: Path):
    store = _store(tmp_path)
    created = create_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        goal_id=_confirmed_goal_id(store),
    )

    executed = execute_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=created.run.id,
    )

    assert executed.run.status == "waiting_approval"
    assert executed.proposals
    assert executed.final_summary is None
    assert executed.steps[-1].title == "Cleaning approval required"
    assert executed.steps[-1].status == "pending"

    dataset = read_dataset(store, DATASET_ID)
    assert dataset is not None
    assert dataset.active_version_id == "version_000"


def test_completed_background_run_persists_summary_before_terminal_event(
    tmp_path: Path,
    monkeypatch,
):
    store = _store(tmp_path)
    created = create_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        goal_id=_confirmed_goal_id(store),
    )
    monkeypatch.setattr(
        "data_formulator.insight.background_runs.generate_cleaning_proposals_for_version",
        lambda *args, **kwargs: [],
    )

    executed = execute_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=created.run.id,
    )
    snapshot = get_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=created.run.id,
    )
    events = project_run_events(snapshot)

    assert executed.run.status == "completed"
    assert executed.run.final_summary_ref == f"runs/{created.run.id}/final_summary.json"
    assert executed.final_summary is not None
    assert snapshot.final_summary is not None
    assert snapshot.final_summary.id == executed.final_summary.id
    assert snapshot.steps[-1].title == "Analysis run completed"
    assert snapshot.steps[-1].detail["final_summary_id"] == snapshot.final_summary.id
    assert events[-1].event_type == "run_completed"


def test_cancelled_background_run_cannot_continue(tmp_path: Path):
    store = _store(tmp_path)
    created = create_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        goal_id=_confirmed_goal_id(store),
    )
    cancelled = cancel_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=created.run.id,
        reason="Stop before execution",
    )

    with pytest.raises(InsightRunConflictError, match="Cancelled AgentRun"):
        execute_background_agent_run(
            store,
            workspace_id=WORKSPACE_ID,
            run_id=created.run.id,
        )

    snapshot = get_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=created.run.id,
    )
    assert snapshot.run.status == "cancelled"
    assert snapshot.steps == cancelled.steps
    assert snapshot.steps[-1].progress_text == "Stop before execution"


def test_run_listing_filters_by_dataset_and_returns_newest_first(tmp_path: Path):
    store = _store(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id=WORKSPACE_ID,
        dataframe=pd.DataFrame({"value": [1, 2, 3]}),
        original_table_ref="inventory_raw",
        dataset_id="dataset_inventory",
    )
    first = create_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        goal_id=_confirmed_goal_id(store),
    )
    second = create_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        goal_id=_confirmed_goal_id(store),
    )
    inventory_goal_id = create_analysis_goal(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id="dataset_inventory",
        dataset_version_id="version_000",
        payload={
            "title": "Review inventory",
            "goalType": "data_quality_review",
        },
    ).goal.id
    create_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id="dataset_inventory",
        goal_id=inventory_goal_id,
    )

    sales_runs = list_agent_runs(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
    )

    assert [run.id for run in sales_runs] == [second.run.id, first.run.id]


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


def _create_goal_via_api(client, headers, *, title: str = "Analyze sales drivers") -> str:
    response = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "title": title,
            "goalType": "driver_analysis",
            "targetMetric": "sales",
            "dimensions": ["constant"],
        },
        headers=headers,
    )
    return response.get_json()["data"]["goal"]["id"]


def test_background_run_routes_return_immediately_and_restore_by_dataset(
    tmp_path: Path,
    monkeypatch,
):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(
        pd.DataFrame({"constant": ["same", "same"], "sales": [10, 10]}),
        "sales_raw",
    )
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}

    registered = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": DATASET_ID},
        headers=headers,
    )
    assert registered.get_json()["status"] == "success"

    goal_id = _create_goal_via_api(client, headers)

    launched: list[str] = []
    monkeypatch.setattr(
        "data_formulator.insight.routes.runs.launch_background_agent_run",
        lambda store, workspace_id, run_id: launched.append(run_id),
    )

    created = client.post(
        "/api/insight/runs",
        json={
            "datasetId": DATASET_ID,
            "versionId": "version_000",
            "goalId": goal_id,
            "executionMode": "background",
        },
        headers=headers,
    )
    payload = created.get_json()

    assert payload["status"] == "success"
    assert payload["data"]["executionMode"] == "background"
    assert payload["data"]["run"]["status"] == "created"
    assert payload["data"]["finalSummary"] is None
    assert payload["data"]["profile"] is None
    assert launched == [payload["data"]["run"]["id"]]

    listed = client.get(
        f"/api/insight/runs?datasetId={DATASET_ID}",
        headers=headers,
    ).get_json()
    assert listed["status"] == "success"
    assert [run["id"] for run in listed["data"]["runs"]] == launched

    restored = client.get(
        f"/api/insight/runs/{launched[0]}",
        headers=headers,
    ).get_json()
    assert restored["data"]["steps"][0]["title"] == "Analysis run started"


def test_run_route_rejects_invalid_execution_mode(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"value": [1]}), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}
    client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": DATASET_ID},
        headers=headers,
    )

    response = client.post(
        "/api/insight/runs",
        json={"datasetId": DATASET_ID, "executionMode": "unknown"},
        headers=headers,
    )
    payload = response.get_json()

    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_REQUEST"
