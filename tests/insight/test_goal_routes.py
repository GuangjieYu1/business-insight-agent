from pathlib import Path

import pandas as pd
from flask import Flask

from data_formulator.datalake.workspace import Workspace
from data_formulator.error_handler import register_error_handlers
from data_formulator.insight.domain import AnalysisGoal
from data_formulator.insight.routes import insight_project_bp
from data_formulator.insight.storage import GoalStore, LocalInsightStore
from data_formulator.insight.versioning import create_dataset_version


DATASET_ID = "dataset_sales"
WORKSPACE_ID = "workspace"


def _app_with_workspace(monkeypatch, workspace: Workspace) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(insight_project_bp)
    register_error_handlers(app)
    monkeypatch.setattr("data_formulator.insight.routes.project.get_identity_id", lambda: "local:test")
    monkeypatch.setattr("data_formulator.insight.routes.project.get_workspace", lambda _: workspace)
    return app


def _workspace_headers(workspace: Workspace) -> dict[str, str]:
    return {"X-Workspace-Id": workspace.confined_root.root.name}


def _seed_workspace(tmp_path: Path, monkeypatch, *, include_secondary_metric: bool = False):
    workspace = Workspace("local:test", workspace_path=tmp_path / "workspace")
    table = {
        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "revenue": [120, 95, 80],
        "region": ["east", "west", "east"],
        "product": ["A", "B", "A"],
    }
    if include_secondary_metric:
        table["sales_amount"] = [121, 96, 81]
    workspace.write_parquet(pd.DataFrame(table), "sales_raw")
    app = _app_with_workspace(monkeypatch, workspace)
    client = app.test_client()
    headers = _workspace_headers(workspace)
    registered = client.post(
        "/api/insight/datasets",
        json={"tableName": "sales_raw", "datasetId": DATASET_ID},
        headers=headers,
    )
    assert registered.get_json()["status"] == "success"
    return workspace, client, headers


def _manual_intent_payload(*, user_input: str = "why did revenue decline?") -> dict:
    return {
        "datasetId": DATASET_ID,
        "datasetVersionId": "version_000",
        "userInput": user_input,
        "goalCandidates": [
            {
                "title": "Analyze revenue drivers",
                "goalType": "driver_analysis",
                "targetMetric": "revenue",
                "dimensions": ["region", "product"],
                "timeColumn": "date",
                "confidence": 0.82,
                "assumptions": ["Revenue is the main business metric"],
            }
        ],
    }


def _create_manual_intent(client, headers, *, user_input: str = "why did revenue decline?") -> dict:
    response = client.post(
        "/api/insight/intents",
        json=_manual_intent_payload(user_input=user_input),
        headers=headers,
    )
    assert response.status_code == 200
    return response.get_json()["data"]


def test_intent_routes_create_and_read_goal_candidates(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch)

    payload = _create_manual_intent(client, headers)

    assert payload["intent"]["dataset_id"] == DATASET_ID
    assert payload["intent"]["dataset_version_id"] == "version_000"
    assert payload["intent"]["status"] == "candidates_ready"
    assert len(payload["goalCandidates"]) == 1
    candidate = payload["goalCandidates"][0]
    assert candidate["goal_type"] == "driver_analysis"
    assert candidate["target_metric"] == "revenue"
    assert candidate["dimensions"] == ["region", "product"]
    assert candidate["time_column"] == "date"

    stored = client.get(
        f"/api/insight/intents/{payload['intent']['id']}/goal-candidates",
        headers=headers,
    )
    assert stored.get_json()["data"]["goalCandidates"][0]["id"] == candidate["id"]


def test_intent_route_rejects_overlong_input_and_invalid_candidate_fields(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch)

    long_input = client.post(
        "/api/insight/intents",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "userInput": "x" * 2001,
        },
        headers=headers,
    )
    long_payload = long_input.get_json()
    assert long_payload["status"] == "error"
    assert long_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "2000" in long_payload["error"]["message"]

    invalid_candidate = client.post(
        "/api/insight/intents",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "userInput": "show me useful directions",
            "goalCandidates": [
                {
                    "title": "Broken candidate",
                    "goalType": "driver_analysis",
                    "targetMetric": "revenue",
                    "dimensions": ["missing_dimension"],
                }
            ],
        },
        headers=headers,
    )
    invalid_payload = invalid_candidate.get_json()
    assert invalid_payload["status"] == "error"
    assert invalid_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "missing_dimension" in invalid_payload["error"]["message"]


def test_goal_routes_confirm_patch_and_activate_goal(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch)
    intent_payload = _create_manual_intent(client, headers)
    candidate = intent_payload["goalCandidates"][0]

    create_goal = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "sourceCandidateId": candidate["id"],
            "dimensions": ["region"],
        },
        headers=headers,
    )
    create_payload = create_goal.get_json()["data"]
    assert create_payload["created"] is True
    assert create_payload["goal"]["status"] == "confirmed"
    assert create_payload["goal"]["source_candidate_id"] == candidate["id"]
    assert create_payload["goal"]["dimensions"] == ["region"]
    assert create_payload["project"]["active_goal_id"] == create_payload["goal"]["id"]

    repeated = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "sourceCandidateId": candidate["id"],
            "dimensions": ["region"],
        },
        headers=headers,
    )
    repeated_payload = repeated.get_json()["data"]
    assert repeated_payload["created"] is False
    assert repeated_payload["goal"]["id"] == create_payload["goal"]["id"]

    patched = client.patch(
        f"/api/insight/goals/{create_payload['goal']['id']}",
        json={"dimensions": ["region", "product"]},
        headers=headers,
    )
    patched_payload = patched.get_json()["data"]
    assert patched_payload["goal"]["dimensions"] == ["region", "product"]
    assert patched_payload["project"]["active_goal_id"] == create_payload["goal"]["id"]

    loaded = client.get(
        f"/api/insight/goals/{create_payload['goal']['id']}",
        headers=headers,
    )
    assert loaded.get_json()["data"]["goal"]["dimensions"] == ["region", "product"]


def test_runs_reject_unconfirmed_or_mismatched_goals(tmp_path: Path, monkeypatch):
    workspace, client, headers = _seed_workspace(tmp_path, monkeypatch)
    store = LocalInsightStore(workspace.confined_root.root)
    GoalStore(store, workspace_id=WORKSPACE_ID).create(
        AnalysisGoal(
            id="goal_pending",
            workspace_id=WORKSPACE_ID,
            dataset_id=DATASET_ID,
            dataset_version_id="version_000",
            goal_type="driver_analysis",
            title="Pending goal",
            target_column="revenue",
            target_metric="revenue",
            dimensions=["region"],
            confidence=0.6,
            status="candidate",
        )
    )

    pending_run = client.post(
        "/api/insight/runs",
        json={"datasetId": DATASET_ID, "versionId": "version_000", "goalId": "goal_pending"},
        headers=headers,
    )
    pending_payload = pending_run.get_json()
    assert pending_payload["status"] == "error"
    assert pending_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "confirmed" in pending_payload["error"]["message"]

    intent_payload = _create_manual_intent(client, headers)
    candidate = intent_payload["goalCandidates"][0]
    goal_response = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "sourceCandidateId": candidate["id"],
        },
        headers=headers,
    )
    goal_id = goal_response.get_json()["data"]["goal"]["id"]

    create_dataset_version(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        dataframe=pd.DataFrame(
            {
                "date": ["2024-01-04"],
                "revenue": [70],
                "region": ["north"],
                "product": ["C"],
            }
        ),
        reason="Create version one",
    )

    mismatched_run = client.post(
        "/api/insight/runs",
        json={"datasetId": DATASET_ID, "versionId": "version_001", "goalId": goal_id},
        headers=headers,
    )
    mismatched_payload = mismatched_run.get_json()
    assert mismatched_payload["status"] == "error"
    assert mismatched_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "dataset version" in mismatched_payload["error"]["message"]


def test_goal_creation_rejects_missing_or_spoofed_intent_without_persisting_goal(tmp_path: Path, monkeypatch):
    workspace, client, headers = _seed_workspace(tmp_path, monkeypatch)
    store = LocalInsightStore(workspace.confined_root.root)

    missing_intent = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "intentId": "intent_missing",
            "goalType": "driver_analysis",
            "title": "Analyze revenue drivers",
            "targetMetric": "revenue",
            "dimensions": ["region"],
        },
        headers=headers,
    )
    missing_payload = missing_intent.get_json()
    assert missing_payload["status"] == "error"
    assert missing_payload["error"]["code"] == "TABLE_NOT_FOUND"
    assert GoalStore(store, workspace_id=WORKSPACE_ID).list() == []

    intent_payload = _create_manual_intent(client, headers)
    candidate = intent_payload["goalCandidates"][0]

    spoofed_intent = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "sourceCandidateId": candidate["id"],
            "intentId": "intent_other",
        },
        headers=headers,
    )
    spoofed_payload = spoofed_intent.get_json()
    assert spoofed_payload["status"] == "error"
    assert spoofed_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "does not match intentId" in spoofed_payload["error"]["message"]
    assert GoalStore(store, workspace_id=WORKSPACE_ID).list() == []


def test_confirmed_goal_keeps_intent_confirmed_and_rejects_status_regression(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch)
    intent_payload = _create_manual_intent(client, headers)
    candidate = intent_payload["goalCandidates"][0]
    intent_id = intent_payload["intent"]["id"]

    create_goal = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "sourceCandidateId": candidate["id"],
        },
        headers=headers,
    )
    goal_id = create_goal.get_json()["data"]["goal"]["id"]

    confirmed_intent = client.get(
        f"/api/insight/intents/{intent_id}",
        headers=headers,
    )
    assert confirmed_intent.get_json()["data"]["intent"]["status"] == "confirmed"

    regressed = client.patch(
        f"/api/insight/goals/{goal_id}",
        json={"status": "candidate"},
        headers=headers,
    )
    regressed_payload = regressed.get_json()
    assert regressed_payload["status"] == "error"
    assert regressed_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "non-confirmed" in regressed_payload["error"]["message"]

    loaded = client.get(
        f"/api/insight/goals/{goal_id}",
        headers=headers,
    )
    assert loaded.get_json()["data"]["goal"]["status"] == "confirmed"


def test_intent_routes_assign_unique_candidate_ids_per_intent(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch)

    response_one = client.post(
        "/api/insight/intents",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "userInput": "why did revenue decline?",
            "goalCandidates": [
                {
                    "id": "goal_candidate_shared",
                    "title": "Analyze revenue drivers",
                    "goalType": "driver_analysis",
                    "targetMetric": "revenue",
                    "dimensions": ["region"],
                    "timeColumn": "date",
                }
            ],
        },
        headers=headers,
    )
    response_two = client.post(
        "/api/insight/intents",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "userInput": "compare revenue by region",
            "goalCandidates": [
                {
                    "id": "goal_candidate_shared",
                    "title": "Analyze revenue drivers",
                    "goalType": "driver_analysis",
                    "targetMetric": "revenue",
                    "dimensions": ["region"],
                    "timeColumn": "date",
                }
            ],
        },
        headers=headers,
    )

    payload_one = response_one.get_json()["data"]
    payload_two = response_two.get_json()["data"]
    assert payload_one["goalCandidates"][0]["id"] != payload_two["goalCandidates"][0]["id"]


def test_goal_creation_blocks_awaiting_clarification_candidates_but_allows_custom_goal(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch, include_secondary_metric=True)

    intent_response = client.post(
        "/api/insight/intents",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "userInput": "why did sales decline recently",
        },
        headers=headers,
    )
    intent_payload = intent_response.get_json()["data"]
    assert intent_payload["intent"]["status"] == "awaiting_clarification"
    candidate = intent_payload["goalCandidates"][0]
    intent_id = intent_payload["intent"]["id"]

    blocked = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "sourceCandidateId": candidate["id"],
        },
        headers=headers,
    )
    blocked_payload = blocked.get_json()
    assert blocked_payload["status"] == "error"
    assert blocked_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "requires clarification" in blocked_payload["error"]["message"]

    custom = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "intentId": intent_id,
            "title": "Analyze revenue drivers",
            "goalType": "driver_analysis",
            "targetMetric": "revenue",
            "dimensions": ["region"],
            "timeColumn": "date",
        },
        headers=headers,
    )
    custom_payload = custom.get_json()["data"]
    assert custom_payload["goal"]["status"] == "confirmed"
    assert custom_payload["project"]["active_goal_id"] == custom_payload["goal"]["id"]

    loaded_intent = client.get(f"/api/insight/intents/{intent_id}", headers=headers)
    assert loaded_intent.get_json()["data"]["intent"]["status"] == "confirmed"


def test_goal_patch_rejects_binding_changes(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch)
    intent_payload = _create_manual_intent(client, headers)
    candidate = intent_payload["goalCandidates"][0]
    goal_response = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "sourceCandidateId": candidate["id"],
        },
        headers=headers,
    )
    goal_id = goal_response.get_json()["data"]["goal"]["id"]

    patched = client.patch(
        f"/api/insight/goals/{goal_id}",
        json={"datasetId": "dataset_other"},
        headers=headers,
    )
    patched_payload = patched.get_json()
    assert patched_payload["status"] == "error"
    assert patched_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "immutable" in patched_payload["error"]["message"]


def test_goal_creation_idempotence_normalizes_filter_order(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch)

    first = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "title": "Compare revenue by region",
            "goalType": "comparison",
            "targetMetric": "revenue",
            "dimensions": ["region"],
            "timeColumn": "date",
            "filters": [
                {"column": "region", "operator": "eq", "value": "east"},
                {"column": "product", "operator": "eq", "value": "A"},
            ],
        },
        headers=headers,
    ).get_json()["data"]

    repeated = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "title": "Compare revenue by region",
            "goalType": "comparison",
            "targetMetric": "revenue",
            "dimensions": ["region"],
            "timeColumn": "date",
            "filters": [
                {"column": "product", "operator": "eq", "value": "A"},
                {"column": "region", "operator": "eq", "value": "east"},
            ],
        },
        headers=headers,
    ).get_json()["data"]

    changed = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "title": "Compare revenue by region",
            "goalType": "comparison",
            "targetMetric": "revenue",
            "dimensions": ["region"],
            "timeColumn": "date",
            "filters": [
                {"column": "region", "operator": "eq", "value": "west"},
                {"column": "product", "operator": "eq", "value": "A"},
            ],
        },
        headers=headers,
    ).get_json()["data"]

    assert first["created"] is True
    assert repeated["created"] is False
    assert repeated["goal"]["id"] == first["goal"]["id"]
    assert changed["created"] is True
    assert changed["goal"]["id"] != first["goal"]["id"]


def test_runs_require_goal_id_and_active_goal_match(tmp_path: Path, monkeypatch):
    _, client, headers = _seed_workspace(tmp_path, monkeypatch)

    missing_goal = client.post(
        "/api/insight/runs",
        json={"datasetId": DATASET_ID, "versionId": "version_000"},
        headers=headers,
    )
    missing_payload = missing_goal.get_json()
    assert missing_payload["status"] == "error"
    assert missing_payload["error"]["code"] == "INVALID_REQUEST"
    assert "goalId is required" in missing_payload["error"]["message"]

    first_goal = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "title": "Analyze revenue drivers",
            "goalType": "driver_analysis",
            "targetMetric": "revenue",
            "dimensions": ["region"],
            "timeColumn": "date",
        },
        headers=headers,
    ).get_json()["data"]["goal"]

    second_goal = client.post(
        "/api/insight/goals",
        json={
            "datasetId": DATASET_ID,
            "datasetVersionId": "version_000",
            "title": "Compare revenue by product",
            "goalType": "comparison",
            "targetMetric": "revenue",
            "dimensions": ["product"],
            "timeColumn": "date",
        },
        headers=headers,
    ).get_json()["data"]["goal"]

    mismatched_goal = client.post(
        "/api/insight/runs",
        json={"datasetId": DATASET_ID, "versionId": "version_000", "goalId": first_goal["id"]},
        headers=headers,
    )
    mismatched_payload = mismatched_goal.get_json()
    assert mismatched_payload["status"] == "error"
    assert mismatched_payload["error"]["code"] == "VALIDATION_ERROR"
    assert "active confirmed goal" in mismatched_payload["error"]["message"]

    active_goal = client.post(
        "/api/insight/runs",
        json={"datasetId": DATASET_ID, "versionId": "version_000", "goalId": second_goal["id"]},
        headers=headers,
    )
    assert active_goal.get_json()["status"] == "success"
