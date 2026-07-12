from pathlib import Path

import pandas as pd
import pytest
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.cleaning import generate_cleaning_proposals
from data_formulator.insight.cleaning_operations import (
    InsightCleaningOperationError,
    apply_cleaning_proposal,
    approve_cleaning_proposal,
    preview_cleaning_proposal,
    read_cleaning_proposal,
    reject_cleaning_proposal,
)
from data_formulator.insight.registry import read_dataset, register_dataset_version_zero
from data_formulator.insight.routes.project import insight_project_bp
from data_formulator.insight.storage import LocalInsightStore
from data_formulator.insight.versioning import create_dataset_version


def _registered_store(tmp_path: Path) -> tuple[LocalInsightStore, str]:
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame(
            {
                "customer_name": [" Alice ", "Bob", "Bob", " Carol\t"],
                "dirty_text": ["ok", "bad\x07", "same", "same"],
                "constant_flag": ["x", "x", "x", "x"],
            }
        ),
        original_table_ref="customers_raw",
        dataset_id="dataset_customers",
    )
    generate_cleaning_proposals(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_customers",
    )
    return store, "dataset_customers"


def _proposal_id(store: LocalInsightStore, problem_type: str) -> str:
    proposals = [
        store.read_json(path)
        for path in store.list("proposals")
        if path.endswith(".json")
    ]
    return next(item["id"] for item in proposals if item["problem_type"] == problem_type)


def test_preview_is_read_only_and_never_returns_raw_values(tmp_path: Path):
    store, dataset_id = _registered_store(tmp_path)
    proposal_id = _proposal_id(store, "whitespace_pollution")
    source_path = f"datasets/{dataset_id}/versions/version_000.parquet"
    source_hash = store.file_sha256(source_path)
    source_before = store.read_parquet(source_path)

    result = preview_cleaning_proposal(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal_id,
    )

    assert result.operation.status == "previewed"
    assert result.operation.operation_type == "trim_string"
    assert result.operation.output_version_id is None
    assert result.operation.animation_payload["affected_rows"] == 2
    assert result.operation.animation_payload["raw_values_included"] is False
    assert all("before" not in item and "after" not in item for item in result.sample_diff)
    assert store.file_sha256(source_path) == source_hash
    pd.testing.assert_frame_equal(store.read_parquet(source_path), source_before)
    assert list(store.list("operations")) == []


def test_apply_requires_approval_and_creates_reversible_version(tmp_path: Path):
    store, dataset_id = _registered_store(tmp_path)
    proposal_id = _proposal_id(store, "whitespace_pollution")

    with pytest.raises(InsightCleaningOperationError, match="approved"):
        apply_cleaning_proposal(
            store,
            workspace_id="workspace_1",
            proposal_id=proposal_id,
        )

    approved = approve_cleaning_proposal(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal_id,
    )
    assert approved.status == "approved"

    result = apply_cleaning_proposal(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal_id,
    )

    original = store.read_parquet(f"datasets/{dataset_id}/versions/version_000.parquet")
    cleaned = store.read_parquet(result.version.file_ref)
    dataset = read_dataset(store, dataset_id)
    persisted_proposal = read_cleaning_proposal(store, proposal_id)

    assert original["customer_name"].tolist() == [" Alice ", "Bob", "Bob", " Carol\t"]
    assert cleaned["customer_name"].tolist() == ["Alice", "Bob", "Bob", "Carol"]
    assert result.version.id == "version_001"
    assert dataset is not None and dataset.active_version_id == "version_001"
    assert result.operation.proposal_id == proposal_id
    assert result.operation.status == "completed"
    assert result.operation.reversible is True
    assert result.operation.before_metrics["row_count"] == 4
    assert result.operation.after_metrics["row_count"] == 4
    assert persisted_proposal is not None and persisted_proposal.status == "applied"


def test_preview_rejects_stale_proposal_after_active_version_changes(tmp_path: Path):
    store, dataset_id = _registered_store(tmp_path)
    proposal_id = _proposal_id(store, "whitespace_pollution")
    create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id=dataset_id,
        dataframe=pd.DataFrame({"customer_name": ["Alice"]}),
        reason="Advance active version",
    )

    with pytest.raises(InsightCleaningOperationError, match="stale"):
        preview_cleaning_proposal(
            store,
            workspace_id="workspace_1",
            proposal_id=proposal_id,
        )


def test_reject_and_parameter_validation(tmp_path: Path):
    store, _ = _registered_store(tmp_path)
    proposal_id = _proposal_id(store, "dirty_character_column")

    rejected = reject_cleaning_proposal(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal_id,
    )
    assert rejected.status == "rejected"

    with pytest.raises(InsightCleaningOperationError, match="cannot be approved"):
        approve_cleaning_proposal(
            store,
            workspace_id="workspace_1",
            proposal_id=proposal_id,
        )

    whitespace_id = _proposal_id(store, "whitespace_pollution")
    with pytest.raises(InsightCleaningOperationError, match="Unsupported operation parameters"):
        preview_cleaning_proposal(
            store,
            workspace_id="workspace_1",
            proposal_id=whitespace_id,
            parameters={"unexpected": True},
        )


def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)
    register_error_handlers(app)
    monkeypatch.setattr("data_formulator.insight.routes.project.get_identity_id", lambda: "local:test")
    monkeypatch.setattr("data_formulator.insight.routes.project.get_workspace", lambda _: workspace)
    return app


def test_reversible_cleaning_routes_complete_preview_approve_apply_flow(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(
        pd.DataFrame({"customer_name": [" Alice ", "Bob", " Carol\t"]}),
        "customers_raw",
    )
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}

    register = client.post(
        "/api/insight/datasets",
        json={"tableName": "customers_raw", "datasetId": "dataset_customers"},
        headers=headers,
    )
    assert register.get_json()["status"] == "success"

    proposals_response = client.post(
        "/api/insight/cleaning/proposals",
        json={"datasetId": "dataset_customers"},
        headers=headers,
    )
    proposals = proposals_response.get_json()["data"]["proposals"]
    proposal = next(item for item in proposals if item["problem_type"] == "whitespace_pollution")

    preview = client.post(
        f"/api/insight/cleaning/proposals/{proposal['id']}/preview",
        json={},
        headers=headers,
    ).get_json()["data"]
    assert preview["operation"]["status"] == "previewed"
    assert preview["operation"]["animation_payload"]["raw_values_included"] is False

    approved = client.post(
        f"/api/insight/cleaning/proposals/{proposal['id']}/approve",
        json={},
        headers=headers,
    ).get_json()["data"]
    assert approved["proposal"]["status"] == "approved"

    applied = client.post(
        f"/api/insight/cleaning/proposals/{proposal['id']}/apply",
        json={},
        headers=headers,
    ).get_json()["data"]
    assert applied["proposal"]["status"] == "applied"
    assert applied["version"]["id"] == "version_001"
    assert applied["dataset"]["active_version_id"] == "version_001"
    assert applied["idempotent"] is False
