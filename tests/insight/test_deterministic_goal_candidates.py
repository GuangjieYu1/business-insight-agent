from pathlib import Path

import pandas as pd
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.deterministic_goal_candidates import generate_goal_candidates
from data_formulator.insight.domain import ColumnProfile, DatasetProfile, GoalType
from data_formulator.insight.routes import insight_project_bp


DATASET_ID = "dataset_sales"
WORKSPACE_ID = "workspace"


def _column(name: str, *, inferred_type: str, distinct_count: int, distinct_ratio: float, top_values=None, issue_types=None, numeric_parseable_count: int = 0, numeric_parse_conflict_count: int = 0, datetime_parseable_count: int = 0, datetime_parse_conflict_count: int = 0):
    return ColumnProfile(
        name=name,
        pandas_dtype="object",
        inferred_type=inferred_type,
        row_count=10,
        non_null_count=10,
        null_count=0,
        null_ratio=0.0,
        distinct_count=distinct_count,
        distinct_ratio=distinct_ratio,
        value_storage_policy="stored",
        top_values=top_values or [],
        numeric_parseable_count=numeric_parseable_count,
        numeric_parse_conflict_count=numeric_parse_conflict_count,
        datetime_parseable_count=datetime_parseable_count,
        datetime_parse_conflict_count=datetime_parse_conflict_count,
        quality_issue_types=issue_types or [],
    )


def _profile(columns, issues=None):
    return DatasetProfile(
        id="profile_sales",
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        version_id="version_000",
        source_content_hash="sha256:test",
        file_ref="datasets/dataset_sales/versions/version_000.parquet",
        profile_ref="datasets/dataset_sales/profiles/version_000.json",
        row_count=10,
        column_count=len(columns),
        columns=columns,
        quality_issues=issues or [],
    )


def _base_profile():
    return _profile([
        _column("date", inferred_type="datetime", distinct_count=10, distinct_ratio=1.0, datetime_parseable_count=10),
        _column("revenue", inferred_type="numeric", distinct_count=10, distinct_ratio=1.0, numeric_parseable_count=10),
        _column("sales_amount", inferred_type="numeric", distinct_count=10, distinct_ratio=1.0, numeric_parseable_count=10),
        _column("region", inferred_type="text", distinct_count=3, distinct_ratio=0.3, top_values=[{"value": "\u534e\u4e1c", "count": 4}, {"value": "\u534e\u5357", "count": 3}]),
        _column("product", inferred_type="text", distinct_count=4, distinct_ratio=0.4),
    ])


def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)
    register_error_handlers(app)
    monkeypatch.setattr("data_formulator.insight.routes.project.get_identity_id", lambda: "local:test")
    monkeypatch.setattr("data_formulator.insight.routes.project.get_workspace", lambda _: workspace)
    return app


def _headers(workspace: Workspace) -> dict[str, str]:
    return {"X-Workspace-Id": workspace.confined_root.root.name}


def _seed_workspace(tmp_path: Path, monkeypatch):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    workspace.write_parquet(pd.DataFrame({"date": ["2024-01-01", "2024-01-02", "2024-01-03"], "revenue": [120, 95, 80], "sales_amount": [121, 96, 81], "region": ["\u534e\u4e1c", "\u534e\u5357", "\u534e\u4e1c"], "product": ["A", "B", "A"]}), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = _headers(workspace)
    registered = client.post("/api/insight/datasets", json={"tableName": "sales_raw", "datasetId": DATASET_ID}, headers=headers)
    assert registered.get_json()["status"] == "success"
    return client, headers


def test_prefers_trend_before_driver_when_metric_is_ambiguous():
    result = generate_goal_candidates(workspace_id=WORKSPACE_ID, intent_id="intent_1", dataset_id=DATASET_ID, dataset_version_id="version_000", user_input="\u4e3a\u4ec0\u4e48\u6700\u8fd1\u6536\u5165\u4e0b\u964d\u4e86", profile=_base_profile())
    assert result.candidates[0].goal_type == GoalType.TREND_ANALYSIS
    assert result.candidates[1].goal_type == GoalType.DRIVER_ANALYSIS
    assert result.questions[0].text_code == "insight.metricQuestion"
    assert {option.label for option in result.questions[0].options} >= {"revenue", "sales_amount"}


def test_skips_trend_without_trusted_time_column():
    profile = _profile([
        _column("revenue", inferred_type="numeric", distinct_count=10, distinct_ratio=1.0, numeric_parseable_count=10),
        _column("region", inferred_type="text", distinct_count=3, distinct_ratio=0.3),
        _column("product", inferred_type="text", distinct_count=4, distinct_ratio=0.4),
    ])
    result = generate_goal_candidates(workspace_id=WORKSPACE_ID, intent_id="intent_2", dataset_id=DATASET_ID, dataset_version_id="version_000", user_input="\u4e3a\u4ec0\u4e48\u6700\u8fd1\u6536\u5165\u4e0b\u964d\u4e86", profile=profile)
    assert all(candidate.goal_type != GoalType.TREND_ANALYSIS for candidate in result.candidates)


def test_distribution_only_appears_for_distribution_queries():
    base = _base_profile()
    compare_result = generate_goal_candidates(workspace_id=WORKSPACE_ID, intent_id="intent_3", dataset_id=DATASET_ID, dataset_version_id="version_000", user_input="compare revenue by region", profile=base)
    distribution_result = generate_goal_candidates(workspace_id=WORKSPACE_ID, intent_id="intent_4", dataset_id=DATASET_ID, dataset_version_id="version_000", user_input="\u6536\u5165\u5206\u5e03\u600e\u4e48\u6837", profile=base)
    assert all(candidate.goal_type != GoalType.DISTRIBUTION_ANALYSIS for candidate in compare_result.candidates)
    assert any(candidate.goal_type == GoalType.DISTRIBUTION_ANALYSIS for candidate in distribution_result.candidates)


def test_generates_only_safe_explicit_filters():
    result = generate_goal_candidates(workspace_id=WORKSPACE_ID, intent_id="intent_5", dataset_id=DATASET_ID, dataset_version_id="version_000", user_input="\u6700\u8fd1\u4e09\u4e2a\u6708\u534e\u4e1c\u5730\u533a\u9500\u552e\u989d\u4e3a\u4ec0\u4e48\u4e0b\u964d\u4e86", profile=_base_profile())
    trend = next(candidate for candidate in result.candidates if candidate.goal_type == GoalType.TREND_ANALYSIS)
    filters = {(item.column, item.operator, item.value) for item in trend.filters}
    assert ("date", "relative_last_n_months", 3) in filters
    assert ("region", "eq", "\u534e\u4e1c") in filters


def test_create_intent_route_autogenerates_candidates_and_questions(tmp_path: Path, monkeypatch):
    client, headers = _seed_workspace(tmp_path, monkeypatch)
    response = client.post("/api/insight/intents", json={"datasetId": DATASET_ID, "datasetVersionId": "version_000", "userInput": "\u4e3a\u4ec0\u4e48\u6700\u8fd1\u6536\u5165\u4e0b\u964d\u4e86"}, headers=headers)
    payload = response.get_json()["data"]
    assert response.status_code == 200
    assert payload["intent"]["status"] == "candidates_ready"
    assert payload["goalCandidates"][0]["goal_type"] == "trend_analysis"
    assert payload["questions"][0]["text_code"] == "insight.metricQuestion"
    loaded = client.get(f"/api/insight/intents/{payload['intent']['id']}", headers=headers).get_json()["data"]
    assert loaded["questions"][0]["text_code"] == "insight.metricQuestion"
    assert loaded["intent"]["clarification_questions"][0]["text_code"] == "insight.metricQuestion"


def test_manual_empty_goal_candidates_do_not_trigger_auto_generation(tmp_path: Path, monkeypatch):
    client, headers = _seed_workspace(tmp_path, monkeypatch)
    response = client.post("/api/insight/intents", json={"datasetId": DATASET_ID, "datasetVersionId": "version_000", "userInput": "check data", "goalCandidates": []}, headers=headers)
    payload = response.get_json()["data"]
    assert response.status_code == 200
    assert payload["goalCandidates"] == []
    assert payload["questions"] == []