from pathlib import Path

import pandas as pd
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.routes.project import insight_project_bp
from data_formulator.insight.storage import LocalInsightStore
from data_formulator.insight.versioning import create_dataset_version, read_operation



def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)
    register_error_handlers(app)

    monkeypatch.setattr("data_formulator.insight.routes.project.get_identity_id", lambda: "local:test")
    monkeypatch.setattr("data_formulator.insight.routes.project.get_workspace", lambda _: workspace)
    return app



def _workspace_headers(workspace: Workspace) -> dict[str, str]:
    return {"X-Workspace-Id": workspace.confined_root.root.name}



def test_project_route_creates_workspace_project(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    app = _app_with_workspace(monkeypatch, workspace)

    response = app.test_client().post(
        "/api/insight/project",
        json={"name": "Business Insight", "description": "Analyze sales performance"},
        headers=_workspace_headers(workspace),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["data"]["created"] is True
    assert payload["data"]["project"]["workspace_id"] == "workspace"
    assert payload["data"]["project"]["name"] == "Business Insight"



def test_project_route_rejects_forged_workspace_header(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    app = _app_with_workspace(monkeypatch, workspace)

    response = app.test_client().post(
        "/api/insight/project",
        json={"name": "Business Insight"},
        headers={"X-Workspace-Id": "forged_workspace"},
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "INVALID_REQUEST"
    assert "does not match" in payload["error"]["message"]
    assert not (workspace.confined_root.root / "insight" / "project.json").exists()



def test_dataset_route_registers_workspace_table_version_zero(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    meta = workspace.write_parquet(pd.DataFrame({"region": ["east"], "sales": [10]}), "sales_raw")
    meta.original_name = "Sales Raw"
    workspace.add_table_metadata(meta)
    app = _app_with_workspace(monkeypatch, workspace)

    response = app.test_client().post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales", "projectName": "Business Insight"},
        headers=_workspace_headers(workspace),
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["dataset"]["id"] == "dataset_sales"
    assert payload["dataset"]["name"] == "Sales Raw"
    assert payload["dataset"]["original_table_ref"] == "sales_raw"
    assert payload["version"]["id"] == "version_000"
    assert payload["version"]["row_count"] == 1
    assert payload["version"]["file_ref"] == "datasets/dataset_sales/versions/version_000.parquet"
    assert payload["project"]["active_dataset_id"] == "dataset_sales"

    list_response = app.test_client().get(
        "/api/insight/datasets",
        headers=_workspace_headers(workspace),
    )
    assert list_response.get_json()["data"]["datasets"][0]["id"] == "dataset_sales"



def test_dataset_route_is_idempotent_for_same_workspace_table(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"region": ["east"], "sales": [10]}), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()

    first = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "projectName": "Business Insight"},
        headers=_workspace_headers(workspace),
    )
    second = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "projectName": "Business Insight"},
        headers=_workspace_headers(workspace),
    )

    first_payload = first.get_json()["data"]
    second_payload = second.get_json()["data"]
    assert first_payload["created"] is True
    assert second_payload["created"] is False
    assert second_payload["dataset"]["id"] == first_payload["dataset"]["id"]

    list_response = client.get("/api/insight/datasets", headers=_workspace_headers(workspace))
    datasets = list_response.get_json()["data"]["datasets"]
    assert [dataset["original_table_ref"] for dataset in datasets] == ["sales_raw"]



def test_dataset_route_never_overwrites_version_zero(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"sales": [10]}), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()

    first = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=_workspace_headers(workspace),
    )
    assert first.get_json()["status"] == "success"

    workspace.write_parquet(pd.DataFrame({"sales": [99]}), "sales_raw")
    second = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=_workspace_headers(workspace),
    )

    payload = second.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "VALIDATION_ERROR"

    store = LocalInsightStore(workspace.confined_root.root)
    loaded = store.read_parquet("datasets/dataset_sales/versions/version_000.parquet")
    assert loaded["sales"].tolist() == [10]



def test_dataset_profile_routes_generate_and_read_version_zero_profile(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(
        pd.DataFrame(
            {
                "region": ["east", "east", "west"],
                "sales": ["10", "10", "bad"],
            }
        ),
        "sales_raw",
    )
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()

    register_response = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=_workspace_headers(workspace),
    )
    assert register_response.get_json()["status"] == "success"

    profile_response = client.post(
        "/api/insight/datasets/dataset_sales/profile",
        headers=_workspace_headers(workspace),
    )

    assert profile_response.status_code == 200
    profile = profile_response.get_json()["data"]["profile"]
    assert profile["dataset_id"] == "dataset_sales"
    assert profile["version_id"] == "version_000"
    assert profile["profile_ref"] == "datasets/dataset_sales/profiles/version_000.json"
    assert {issue["issue_type"] for issue in profile["quality_issues"]} >= {
        "duplicate_rows",
        "numeric_parse_conflict",
    }

    stored_response = client.get(
        "/api/insight/datasets/dataset_sales/profiles/version_000",
        headers=_workspace_headers(workspace),
    )
    assert stored_response.get_json()["data"]["profile"]["id"] == profile["id"]



def test_dataset_profile_get_requires_existing_profile(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"sales": [10]}), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()

    client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=_workspace_headers(workspace),
    )
    response = client.get(
        "/api/insight/datasets/dataset_sales/profiles/version_000",
        headers=_workspace_headers(workspace),
    )

    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "TABLE_NOT_FOUND"
    assert "Dataset profile not found" in payload["error"]["message"]



def test_dataset_versions_route_lists_history_and_active_version(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"sales": [10]}), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()

    client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=_workspace_headers(workspace),
    )
    store = LocalInsightStore(workspace.confined_root.root)
    create_dataset_version(
        store,
        workspace_id="workspace",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"sales": [11]}),
        reason="Create version one",
    )

    response = client.get(
        "/api/insight/datasets/dataset_sales/versions",
        headers=_workspace_headers(workspace),
    )

    payload = response.get_json()["data"]
    assert payload["activeVersionId"] == "version_001"
    assert [version["id"] for version in payload["versions"]] == ["version_000", "version_001"]
    assert payload["versions"][0]["status"] == "historical"
    assert payload["versions"][1]["status"] == "active"



def test_activate_version_route_switches_active_version(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"sales": [10]}), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()

    client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=_workspace_headers(workspace),
    )
    store = LocalInsightStore(workspace.confined_root.root)
    create_dataset_version(
        store,
        workspace_id="workspace",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"sales": [11]}),
        reason="Create version one",
    )
    create_dataset_version(
        store,
        workspace_id="workspace",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"sales": [12]}),
        reason="Create version two",
    )

    response = client.post(
        "/api/insight/datasets/dataset_sales/activate-version",
        json={"versionId": "version_001", "reason": "Compare prior state"},
        headers=_workspace_headers(workspace),
    )

    payload = response.get_json()["data"]
    assert payload["dataset"]["active_version_id"] == "version_001"
    assert payload["activeVersion"]["id"] == "version_001"
    assert payload["previousVersion"]["id"] == "version_002"
    assert payload["operation"]["operation_type"] == "activate_version"



def test_undo_operation_route_reverts_to_parent_version(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"sales": [10]}), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()

    client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=_workspace_headers(workspace),
    )
    store = LocalInsightStore(workspace.confined_root.root)
    mutation = create_dataset_version(
        store,
        workspace_id="workspace",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"sales": [11]}),
        reason="Create version one",
        operation_type="manual_transform",
    )

    response = client.post(
        f"/api/insight/operations/{mutation.operation.id}/undo",
        json={"reason": "Undo latest change"},
        headers=_workspace_headers(workspace),
    )

    payload = response.get_json()["data"]
    original_operation = read_operation(store, mutation.operation.id)

    assert payload["dataset"]["active_version_id"] == "version_000"
    assert payload["activeVersion"]["id"] == "version_000"
    assert payload["previousVersion"]["id"] == "version_001"
    assert payload["operation"]["operation_type"] == "undo_activation"
    assert payload["undoneOperation"]["status"] == "undone"
    assert original_operation is not None and original_operation.status == "undone"

def test_cleaning_proposals_route_generates_version_zero_proposals(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(
        pd.DataFrame(
            {
                "constant_flag": ["same"] * 8,
                "whitespace_text": [" east", "west ", "north", "south", "east", "west", "north", "south"],
                "amount": [1, 2, 3, 4, 5, 6, 7, 8],
            }
        ),
        "sales_raw",
    )
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()

    client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales"},
        headers=_workspace_headers(workspace),
    )

    response = client.post(
        "/api/insight/cleaning/proposals",
        json={"datasetId": "dataset_sales", "versionId": "version_000"},
        headers=_workspace_headers(workspace),
    )

    payload = response.get_json()["data"]
    proposals = {proposal["problem_type"]: proposal for proposal in payload["proposals"]}
    assert proposals["constant_column"]["recommended_operation"] == "drop_column"
    assert proposals["whitespace_pollution"]["recommended_operation"] == "trim_string"

    list_response = client.get(
        "/api/insight/cleaning/proposals?datasetId=dataset_sales&versionId=version_000",
        headers=_workspace_headers(workspace),
    )
    persisted = list_response.get_json()["data"]["proposals"]
    assert {proposal["id"] for proposal in persisted} == {proposal["id"] for proposal in payload["proposals"]}
