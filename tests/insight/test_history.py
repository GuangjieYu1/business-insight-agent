from pathlib import Path

import pandas as pd
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.history import (
    compare_dataset_version_profiles,
    list_dataset_operations,
)
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.routes import insight_project_bp
from data_formulator.insight.storage import LocalInsightStore
from data_formulator.insight.versioning import create_dataset_version


def _store_with_comparable_versions(tmp_path: Path) -> LocalInsightStore:
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame(
            {"name": ["Alice", "Alice", "Bob"], "sales": [10, 10, 20]}
        ),
        original_table_ref="sales_raw",
        dataset_id="dataset_sales",
    )
    create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"name": ["Alice", "Bob"], "sales": [10, 20]}),
        reason="Drop duplicate rows",
        operation_type="drop_duplicate_rows",
    )
    return store


def test_dataset_operation_history_is_persistent_and_scoped(tmp_path: Path):
    store = _store_with_comparable_versions(tmp_path)

    operations = list_dataset_operations(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
    )

    assert len(operations) == 1
    assert operations[0].operation_type == "drop_duplicate_rows"
    assert operations[0].input_version_id == "version_000"
    assert operations[0].output_version_id == "version_001"
    assert operations[0].parameters["dataset_id"] == "dataset_sales"


def test_profile_comparison_reports_resolved_and_metric_delta(tmp_path: Path):
    store = _store_with_comparable_versions(tmp_path)

    comparison = compare_dataset_version_profiles(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        before_version_id="version_000",
        after_version_id="version_001",
    )

    assert comparison["beforeVersionId"] == "version_000"
    assert comparison["afterVersionId"] == "version_001"
    assert comparison["metricDelta"]["row_count"] == -1
    assert comparison["metricDelta"]["duplicate_excess_row_count"] == -1
    assert any(
        issue.issue_type == "duplicate_rows"
        for issue in comparison["resolvedIssues"]
    )
    assert not any(
        issue.issue_type == "duplicate_rows"
        for issue in comparison["introducedIssues"]
    )


def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)
    register_error_handlers(app)
    monkeypatch.setattr("data_formulator.insight.routes.project.get_identity_id", lambda: "local:test")
    monkeypatch.setattr("data_formulator.insight.routes.project.get_workspace", lambda _: workspace)
    return app


def test_history_and_comparison_routes(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    store = LocalInsightStore(workspace.confined_root.root)
    register_dataset_version_zero(
        store,
        workspace_id=workspace.confined_root.root.name,
        dataframe=pd.DataFrame(
            {"name": ["Alice", "Alice", "Bob"], "sales": [10, 10, 20]}
        ),
        original_table_ref="sales_raw",
        dataset_id="dataset_sales",
    )
    mutation = create_dataset_version(
        store,
        workspace_id=workspace.confined_root.root.name,
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"name": ["Alice", "Bob"], "sales": [10, 20]}),
        reason="Drop duplicate rows",
        operation_type="drop_duplicate_rows",
    )
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = {"X-Workspace-Id": workspace.confined_root.root.name}

    history_response = client.get(
        "/api/insight/datasets/dataset_sales/operations",
        headers=headers,
    )
    history = history_response.get_json()["data"]["operations"]
    assert [item["id"] for item in history] == [mutation.operation.id]

    operation_response = client.get(
        f"/api/insight/datasets/dataset_sales/operations/{mutation.operation.id}",
        headers=headers,
    )
    assert operation_response.get_json()["data"]["operation"]["id"] == mutation.operation.id

    comparison_response = client.get(
        "/api/insight/datasets/dataset_sales/profiles/compare"
        "?beforeVersionId=version_000&afterVersionId=version_001",
        headers=headers,
    )
    comparison = comparison_response.get_json()["data"]
    assert comparison["metricDelta"]["row_count"] == -1
    assert any(
        issue["issue_type"] == "duplicate_rows"
        for issue in comparison["resolvedIssues"]
    )
