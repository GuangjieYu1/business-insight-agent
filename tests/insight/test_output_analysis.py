from pathlib import Path

import pandas as pd
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.cleaning import generate_cleaning_proposals
from data_formulator.insight.cleaning_operations import approve_cleaning_proposal
from data_formulator.insight.output_analysis import (
    apply_cleaning_proposal_with_output_analysis,
)
from data_formulator.insight.profiling import InsightProfileError
from data_formulator.insight.registry import read_dataset, register_dataset_version_zero
from data_formulator.insight.routes import insight_project_bp
from data_formulator.insight.storage import LocalInsightStore


def _approved_whitespace_proposal(store: LocalInsightStore):
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame({"name": [" Alice ", "Alice"], "sales": [1, 1]}),
        original_table_ref="sales_raw",
        dataset_id="dataset_sales",
    )
    proposals = generate_cleaning_proposals(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
    )
    proposal = next(
        item for item in proposals if item.problem_type == "whitespace_pollution"
    )
    return approve_cleaning_proposal(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal.id,
    )


def test_apply_profiles_output_and_generates_next_proposals(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    proposal = _approved_whitespace_proposal(store)

    result = apply_cleaning_proposal_with_output_analysis(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal.id,
        operation_type="trim_string",
    )

    assert result.apply_result.version.id == "version_001"
    assert result.profile is not None
    assert result.profile.version_id == "version_001"
    assert result.profile_status == "completed"
    assert result.proposal_status == "completed"
    assert any(
        item.problem_type == "duplicate_rows"
        and item.dataset_version_id == "version_001"
        for item in result.next_proposals
    )
    assert store.exists("datasets/dataset_sales/profiles/version_001.json")

    repeated = apply_cleaning_proposal_with_output_analysis(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal.id,
        operation_type="trim_string",
    )
    assert repeated.apply_result.idempotent is True
    assert repeated.apply_result.version.id == "version_001"
    assert repeated.profile_status == "completed"


def test_output_profile_failure_does_not_rollback_cleaning_version(
    tmp_path: Path,
    monkeypatch,
):
    store = LocalInsightStore(tmp_path)
    proposal = _approved_whitespace_proposal(store)

    def fail_profile(*args, **kwargs):
        raise InsightProfileError("synthetic profile failure")

    monkeypatch.setattr(
        "data_formulator.insight.output_analysis.generate_dataset_version_profile",
        fail_profile,
    )

    result = apply_cleaning_proposal_with_output_analysis(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal.id,
        operation_type="trim_string",
    )

    dataset = read_dataset(store, "dataset_sales")
    assert result.apply_result.version.id == "version_001"
    assert dataset is not None and dataset.active_version_id == "version_001"
    assert result.profile is None
    assert result.profile_status == "failed"
    assert result.proposal_status == "skipped"
    assert "synthetic profile failure" in result.warnings[0]


def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)
    register_error_handlers(app)
    monkeypatch.setattr("data_formulator.insight.routes.project.get_identity_id", lambda: "local:test")
    monkeypatch.setattr("data_formulator.insight.routes.project.get_workspace", lambda _: workspace)
    return app


def test_apply_with_analysis_route_returns_output_profile_and_proposals(
    tmp_path: Path,
    monkeypatch,
):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(
        pd.DataFrame({"name": [" Alice ", "Alice"], "sales": [1, 1]}),
        "sales_raw",
    )
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}

    registered = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=headers,
    )
    assert registered.get_json()["status"] == "success"

    store = LocalInsightStore(workspace.confined_root.root)
    proposals = generate_cleaning_proposals(
        store,
        workspace_id=workspace.confined_root.root.name,
        dataset_id="dataset_sales",
    )
    proposal = next(
        item for item in proposals if item.problem_type == "whitespace_pollution"
    )
    approve_cleaning_proposal(
        store,
        workspace_id=workspace.confined_root.root.name,
        proposal_id=proposal.id,
    )

    response = client.post(
        f"/api/insight/cleaning/proposals/{proposal.id}/apply-with-analysis",
        json={"operationType": "trim_string", "parameters": {}},
        headers=headers,
    )
    payload = response.get_json()["data"]

    assert payload["version"]["id"] == "version_001"
    assert payload["profile"]["version_id"] == "version_001"
    assert payload["postProcessing"] == {
        "profileStatus": "completed",
        "proposalStatus": "completed",
        "warnings": [],
    }
    assert any(
        item["problem_type"] == "duplicate_rows"
        and item["dataset_version_id"] == "version_001"
        for item in payload["nextProposals"]
    )
