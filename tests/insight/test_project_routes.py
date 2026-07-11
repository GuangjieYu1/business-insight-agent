from pathlib import Path

import pandas as pd
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.routes.project import insight_project_bp
from data_formulator.insight.storage import LocalInsightStore


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
        json={"name": "经营分析", "description": "检查销售数据"},
        headers=_workspace_headers(workspace),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["data"]["created"] is True
    assert payload["data"]["project"]["workspace_id"] == "workspace"
    assert payload["data"]["project"]["name"] == "经营分析"


def test_project_route_rejects_forged_workspace_header(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    app = _app_with_workspace(monkeypatch, workspace)

    response = app.test_client().post(
        "/api/insight/project",
        json={"name": "经营分析"},
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
        json={"tableName": "sales_raw", "datasetId": "dataset_sales", "projectName": "经营分析"},
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
        json={"tableName": "sales_raw", "projectName": "经营分析"},
        headers=_workspace_headers(workspace),
    )
    second = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "projectName": "经营分析"},
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
