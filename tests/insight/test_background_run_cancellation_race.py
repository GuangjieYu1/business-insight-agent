from pathlib import Path

import pandas as pd

from data_formulator.insight import background_runs
from data_formulator.insight.background_runs import (
    create_background_agent_run,
    execute_background_agent_run,
)
from data_formulator.insight.goal_service import create_analysis_goal
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.run_service import cancel_agent_run, get_agent_run
from data_formulator.insight.storage import LocalInsightStore


WORKSPACE_ID = "workspace_1"
DATASET_ID = "dataset_sales"


def _confirmed_goal_id(store: LocalInsightStore) -> str:
    return create_analysis_goal(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        dataset_version_id="version_000",
        payload={
            "title": "Analyze constant column impact",
            "goalType": "driver_analysis",
            "targetMetric": "constant",
            "dimensions": [],
        },
    ).goal.id


def test_cancellation_wins_while_background_profile_is_running(
    tmp_path: Path,
    monkeypatch,
):
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id=WORKSPACE_ID,
        dataframe=pd.DataFrame({"constant": ["same", "same"]}),
        original_table_ref="sales_raw",
        dataset_id=DATASET_ID,
    )
    created = create_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        dataset_id=DATASET_ID,
        goal_id=_confirmed_goal_id(store),
    )
    original_profile = background_runs.generate_dataset_version_profile

    def cancel_during_profile(*args, **kwargs):
        cancel_agent_run(
            store,
            workspace_id=WORKSPACE_ID,
            run_id=created.run.id,
            reason="Cancel during profile",
        )
        return original_profile(*args, **kwargs)

    monkeypatch.setattr(
        background_runs,
        "generate_dataset_version_profile",
        cancel_during_profile,
    )

    result = execute_background_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=created.run.id,
    )
    snapshot = get_agent_run(
        store,
        workspace_id=WORKSPACE_ID,
        run_id=created.run.id,
    )

    assert result.run.status == "cancelled"
    assert snapshot.run.status == "cancelled"
    assert snapshot.steps[-1].title == "Analysis run cancelled"
    assert snapshot.steps[-1].progress_text == "Cancel during profile"
    assert all(step.title != "Profile dataset version" for step in snapshot.steps)
    assert all(step.title != "Generate cleaning proposals" for step in snapshot.steps)
