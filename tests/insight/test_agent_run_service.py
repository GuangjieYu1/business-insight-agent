from pathlib import Path

import pandas as pd
import pytest
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.profiling import InsightProfileError
from data_formulator.insight.registry import (
    read_dataset,
    register_dataset_version_zero,
)
from data_formulator.insight.routes import insight_project_bp
from data_formulator.insight.run_service import (
    InsightRunConflictError,
    InsightRunError,
    cancel_agent_run,
    get_agent_run,
    start_agent_run,
)
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


def test_agent_run_stops_at_approval_without_mutating_dataset(tmp_path: Path):
    store = _dirty_store(tmp_path)

    result = start_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
    )

    assert result.run.status == "waiting_approval"
    assert result.run.current_stage == "waiting_approval"
    assert result.run.dataset_version_id == "version_000"
    assert result.run.completed_at is None
    assert result.profile.version_id == "version_000"
    assert result.proposals
    assert any(step.type == "approval" and step.status == "pending" for step in result.steps)
    assert [step.title for step in result.steps[:4]] == [
        "Analysis run started",
        "Inspect dataset version",
        "Profile dataset version",
        "Generate cleaning proposals",
    ]

    persisted = get_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=result.run.id,
    )
    assert persisted.run == result.run
    assert persisted.steps == result.steps
    assert persisted.final_summary is None

    dataset = read_dataset(store, DATASET_ID)
    assert dataset is not None
    assert dataset.active_version_id == "version_000"


def test_agent_run_completes_when_no_proposals_are_required(tmp_path: Path, monkeypatch):
    store = _dirty_store(tmp_path)
    monkeypatch.setattr(
        "data_formulator.insight.run_service.generate_cleaning_proposals_for_version",
        lambda *args, **kwargs: [],
    )

    result = start_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
    )

    assert result.run.status == "completed"
    assert result.run.current_stage == "completed"
    assert result.run.completed_at is not None
    assert result.proposals == []
    assert result.steps[-1].title == "Analysis run completed"
    assert result.steps[-1].status == "completed"


def test_agent_run_failure_is_persisted_with_error_step(tmp_path: Path, monkeypatch):
    store = _dirty_store(tmp_path)

    def fail_profile(*args, **kwargs):
        raise InsightProfileError("Profile limit exceeded")

    monkeypatch.setattr(
        "data_formulator.insight.run_service.generate_dataset_version_profile",
        fail_profile,
    )

    with pytest.raises(InsightRunError, match="Profile limit exceeded"):
        start_agent_run(
            store,
            workspace_id=WORKSPACE_ID,
            dataset_id=DATASET_ID,
        )

    runs = RunStore(store, workspace_id=WORKSPACE_ID).list()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].current_stage == "profiling"
    assert runs[0].completed_at is not None

    snapshot = get_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=runs[0].id,
    )
    assert snapshot.steps[-1].type == "error"
    assert snapshot.steps[-1].status == "failed"
    assert snapshot.steps[-1].detail["stage"] == "profiling"


def test_waiting_run_can_be_cancelled_idempotently(tmp_path: Path):
    store = _dirty_store(tmp_path)
    started = start_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
    )

    cancelled = cancel_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=started.run.id,
        reason="User changed the analysis scope",
    )
    repeated = cancel_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=started.run.id,
        reason="Duplicate cancellation",
    )

    assert cancelled.run.status == "cancelled"
    assert cancelled.run.completed_at is not None
    assert cancelled.steps[-1].status == "cancelled"
    assert cancelled.steps[-1].progress_text == "User changed the analysis scope"
    assert repeated.run == cancelled.run
    assert repeated.steps == cancelled.steps


def test_completed_or_failed_run_cannot_be_cancelled(tmp_path: Path, monkeypatch):
    store = _dirty_store(tmp_path)
    monkeypatch.setattr(
        "data_formulator.insight.run_service.generate_cleaning_proposals_for_version",
        lambda *args, **kwargs: [],
    )
    completed = start_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
    )

    with pytest.raises(InsightRunConflictError, match="cannot be cancelled"):
        cancel_agent_run(
            store,
            workspace_id=WORKSPACE_ID,
            run_id=completed.run.id,
        )


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


def test_agent_run_routes_create_read_steps_and_cancel(tmp_path: Path, monkeypatch):
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
    created_payload = created.get_json()
    assert created_payload["status"] == "success"
    run = created_payload["data"]["run"]
    assert run["status"] == "waiting_approval"
    assert created_payload["data"]["profile"]["version_id"] == "version_000"
    assert created_payload["data"]["proposals"]

    loaded = client.get(f"/api/insight/runs/{run['id']}", headers=headers)
    loaded_payload = loaded.get_json()
    assert loaded_payload["status"] == "success"
    assert loaded_payload["data"]["run"] == run
    assert loaded_payload["data"]["finalSummary"] is None

    steps = client.get(f"/api/insight/runs/{run['id']}/steps", headers=headers)
    steps_payload = steps.get_json()
    assert steps_payload["status"] == "success"
    assert steps_payload["data"]["runId"] == run["id"]
    assert steps_payload["data"]["steps"] == loaded_payload["data"]["steps"]

    cancelled = client.post(
        f"/api/insight/runs/{run['id']}/cancel",
        json={"reason": "Stop before approval"},
        headers=headers,
    )
    cancelled_payload = cancelled.get_json()
    assert cancelled_payload["status"] == "success"
    assert cancelled_payload["data"]["run"]["status"] == "cancelled"
    assert cancelled_payload["data"]["steps"][-1]["progress_text"] == "Stop before approval"


def test_agent_run_route_rejects_missing_dataset(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}

    response = client.post(
        "/api/insight/runs",
        json={"datasetId": "dataset_missing"},
        headers=headers,
    )
    payload = response.get_json()

    assert payload["status"] == "error"
    assert payload["error"]["code"] == "TABLE_NOT_FOUND"
