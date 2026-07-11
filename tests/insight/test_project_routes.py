from pathlib import Path

import pandas as pd
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.insight.routes.project import insight_project_bp


def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)

    monkeypatch.setattr("data_formulator.insight.routes.project.get_identity_id", lambda: "local:test")
    monkeypatch.setattr("data_formulator.insight.routes.project.get_workspace", lambda _: workspace)
    return app


def test_project_route_creates_workspace_project(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    app = _app_with_workspace(monkeypatch, workspace)

    response = app.test_client().post(
        "/api/insight/project",
        json={"name": "经营分析", "description": "检查销售数据"},
        headers={"X-Workspace-Id": "workspace_1"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["data"]["created"] is True
    assert payload["data"]["project"]["workspace_id"] == "workspace_1"
    assert payload["data"]["project"]["name"] == "经营分析"


def test_dataset_route_registers_workspace_table_version_zero(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    meta = workspace.write_parquet(pd.DataFrame({"region": ["east"], "sales": [10]}), "sales_raw")
    meta.original_name = "Sales Raw"
    workspace.add_table_metadata(meta)
    app = _app_with_workspace(monkeypatch, workspace)

    response = app.test_client().post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": "dataset_sales", "projectName": "经营分析"},
        headers={"X-Workspace-Id": "workspace_1"},
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
        headers={"X-Workspace-Id": "workspace_1"},
    )
    assert list_response.get_json()["data"]["datasets"][0]["id"] == "dataset_sales"
