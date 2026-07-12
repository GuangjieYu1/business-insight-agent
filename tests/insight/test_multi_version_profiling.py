from pathlib import Path

import pandas as pd
import pytest
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.cleaning import list_cleaning_proposals
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.routes import insight_project_bp
from data_formulator.insight.storage import LocalInsightStore
from data_formulator.insight.version_cleaning import generate_cleaning_proposals_for_version
from data_formulator.insight.version_profiling import (
    generate_dataset_version_profile,
    read_dataset_version_profile,
)
from data_formulator.insight.versioning import create_dataset_version


def _store_with_two_versions(tmp_path: Path) -> LocalInsightStore:
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame({"name": [" Alice ", "Bob"], "sales": [10, 20]}),
        original_table_ref="sales_raw",
        dataset_id="dataset_sales",
    )
    create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"name": ["Alice", "Alice", "Bob"], "sales": [10, 10, 20]}),
        reason="Normalize customer names",
        operation_type="trim_string",
    )
    return store


def test_profiles_are_persisted_per_dataset_version(tmp_path: Path):
    store = _store_with_two_versions(tmp_path)

    profile_000 = generate_dataset_version_profile(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        version_id="version_000",
    )
    profile_001 = generate_dataset_version_profile(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        version_id="version_001",
    )

    assert profile_000.version_id == "version_000"
    assert profile_001.version_id == "version_001"
    assert profile_000.id != profile_001.id
    assert profile_000.source_content_hash != profile_001.source_content_hash
    assert store.exists("datasets/dataset_sales/profiles/version_000.json")
    assert store.exists("datasets/dataset_sales/profiles/version_001.json")
    assert read_dataset_version_profile(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        version_id="version_001",
    ) == profile_001


def test_version_proposals_use_exact_profile_version(tmp_path: Path):
    store = _store_with_two_versions(tmp_path)

    proposals = generate_cleaning_proposals_for_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        version_id="version_001",
    )

    duplicate = next(proposal for proposal in proposals if proposal.problem_type == "duplicate_rows")
    assert duplicate.dataset_version_id == "version_001"
    assert duplicate.scope["version_id"] == "version_001"
    persisted = list_cleaning_proposals(
        store,
        dataset_id="dataset_sales",
        version_id="version_001",
    )
    assert [proposal.id for proposal in persisted] == [proposal.id for proposal in proposals]


def test_missing_version_profile_is_rejected(tmp_path: Path):
    store = _store_with_two_versions(tmp_path)

    with pytest.raises(ValueError, match="Dataset version not found"):
        generate_dataset_version_profile(
            store,
            workspace_id="workspace_1",
            dataset_id="dataset_sales",
            version_id="version_999",
        )


def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)
    register_error_handlers(app)
    monkeypatch.setattr("data_formulator.insight.routes.project.get_identity_id", lambda: "local:test")
    monkeypatch.setattr("data_formulator.insight.routes.project.get_workspace", lambda _: workspace)
    return app


def test_version_profile_and_proposal_routes(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"name": [" Alice ", "Bob"], "sales": [10, 20]}), "sales_raw")
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
    create_dataset_version(
        store,
        workspace_id=workspace.confined_root.root.name,
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"name": ["Alice", "Alice"], "sales": [10, 10]}),
        reason="Create version one",
    )

    generated = client.post(
        "/api/insight/datasets/dataset_sales/versions/version_001/profile",
        headers=headers,
    )
    assert generated.get_json()["data"]["profile"]["version_id"] == "version_001"

    loaded = client.get(
        "/api/insight/datasets/dataset_sales/versions/version_001/profile",
        headers=headers,
    )
    assert loaded.get_json()["data"]["profile"]["version_id"] == "version_001"

    proposal_response = client.post(
        "/api/insight/datasets/dataset_sales/versions/version_001/cleaning/proposals",
        headers=headers,
    )
    proposals = proposal_response.get_json()["data"]["proposals"]
    assert any(proposal["problem_type"] == "duplicate_rows" for proposal in proposals)
    assert all(proposal["dataset_version_id"] == "version_001" for proposal in proposals)
