from pathlib import Path

import pytest

from data_formulator.insight.domain import GoalCandidate, IntentRequest
from data_formulator.insight.storage import DomainStoreError, GoalCandidateStore, IntentStore, LocalInsightStore


WORKSPACE_ID = "workspace_1"


def _store(tmp_path: Path) -> LocalInsightStore:
    return LocalInsightStore(tmp_path)


def test_intent_and_goal_candidate_stores_round_trip(tmp_path: Path):
    store = _store(tmp_path)
    intents = IntentStore(store, workspace_id=WORKSPACE_ID)
    candidates = GoalCandidateStore(store, workspace_id=WORKSPACE_ID)

    intent = intents.create(
        IntentRequest(
            id="intent_1",
            workspace_id=WORKSPACE_ID,
            dataset_id="dataset_sales",
            dataset_version_id="version_000",
            user_input="Why did revenue decline?",
        )
    )
    saved_candidates = candidates.replace_for_intent(
        intent.id,
        [
            GoalCandidate(
                id="goal_candidate_1",
                workspace_id=WORKSPACE_ID,
                intent_id=intent.id,
                dataset_id="dataset_sales",
                dataset_version_id="version_000",
                title="Analyze revenue drivers",
                goal_type="driver_analysis",
                target_metric="revenue",
                dimensions=["region"],
                confidence=0.8,
            )
        ],
    )

    assert intents.read(intent.id) == intent
    assert [candidate.id for candidate in candidates.list_for_intent(intent.id)] == ["goal_candidate_1"]
    assert saved_candidates[0].target_metric == "revenue"


def test_goal_candidate_store_enforces_limit_and_intent_binding(tmp_path: Path):
    store = _store(tmp_path)
    candidates = GoalCandidateStore(store, workspace_id=WORKSPACE_ID)

    with pytest.raises(DomainStoreError, match="at most 4"):
        candidates.replace_for_intent(
            "intent_1",
            [
                GoalCandidate(
                    id=f"goal_candidate_{index}",
                    workspace_id=WORKSPACE_ID,
                    intent_id="intent_1",
                    dataset_id="dataset_sales",
                    dataset_version_id="version_000",
                    title=f"candidate {index}",
                    goal_type="driver_analysis",
                    confidence=0.5,
                )
                for index in range(5)
            ],
        )

    with pytest.raises(DomainStoreError, match="intent_id"):
        candidates.replace_for_intent(
            "intent_1",
            [
                GoalCandidate(
                    id="goal_candidate_bad",
                    workspace_id=WORKSPACE_ID,
                    intent_id="intent_2",
                    dataset_id="dataset_sales",
                    dataset_version_id="version_000",
                    title="bad",
                    goal_type="driver_analysis",
                    confidence=0.5,
                )
            ],
        )


def test_goal_candidate_store_rejects_cross_intent_id_collisions(tmp_path: Path):
    store = _store(tmp_path)
    candidates = GoalCandidateStore(store, workspace_id=WORKSPACE_ID)

    candidates.replace_for_intent(
        "intent_1",
        [
            GoalCandidate(
                id="goal_candidate_shared",
                workspace_id=WORKSPACE_ID,
                intent_id="intent_1",
                dataset_id="dataset_sales",
                dataset_version_id="version_000",
                title="candidate one",
                goal_type="driver_analysis",
                confidence=0.5,
            )
        ],
    )

    with pytest.raises(DomainStoreError, match="already used by another intent"):
        candidates.replace_for_intent(
            "intent_2",
            [
                GoalCandidate(
                    id="goal_candidate_shared",
                    workspace_id=WORKSPACE_ID,
                    intent_id="intent_2",
                    dataset_id="dataset_sales",
                    dataset_version_id="version_000",
                    title="candidate two",
                    goal_type="driver_analysis",
                    confidence=0.5,
                )
            ],
        )
