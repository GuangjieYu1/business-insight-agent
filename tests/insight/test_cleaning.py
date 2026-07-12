from pathlib import Path

import pandas as pd

from data_formulator.insight.cleaning import generate_cleaning_proposals, list_cleaning_proposals
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.storage import LocalInsightStore


def test_generate_cleaning_proposals_maps_profile_issues_to_operations(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    dataframe = pd.DataFrame(
        {
            "constant_flag": ["same"] * 24,
            "customer_id": [f"CUST-{index:03d}" for index in range(24)],
            "dirty_text": ["ok"] * 24,
            "whitespace_text": ["north"] * 24,
            "amount": list(range(23)) + [1000],
        }
    )
    dataframe.loc[1, "dirty_text"] = "bad\x07"
    dataframe.loc[2, "whitespace_text"] = " east"
    dataframe.loc[3, "whitespace_text"] = "west "
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=dataframe,
        original_table_ref="sales_raw",
        dataset_id="dataset_sales",
    )

    proposals = generate_cleaning_proposals(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
    )

    proposals_by_problem = {proposal.problem_type: proposal for proposal in proposals}
    assert proposals_by_problem["constant_column"].recommended_operation == "drop_column"
    assert proposals_by_problem["high_cardinality_id_like"].recommended_operation == "mark_column_as_id"
    assert proposals_by_problem["dirty_character_column"].recommended_operation == "replace_invalid_character"
    assert proposals_by_problem["whitespace_pollution"].recommended_operation == "trim_string"
    assert proposals_by_problem["outlier_warning"].recommended_operation == "keep_rows"

    persisted = list_cleaning_proposals(store, dataset_id="dataset_sales", version_id="version_000")
    assert {proposal.id for proposal in persisted} == {proposal.id for proposal in proposals}