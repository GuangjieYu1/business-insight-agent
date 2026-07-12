from pathlib import Path

import pandas as pd

from data_formulator.insight.cleaning import generate_cleaning_proposals
from data_formulator.insight.cleaning_operations import (
    apply_cleaning_proposal,
    approve_cleaning_proposal,
)
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.storage import LocalInsightStore
from data_formulator.insight.versioning import list_dataset_versions


def test_repeated_apply_returns_existing_version(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame({"name": [" Alice ", "Bob"]}),
        original_table_ref="customers_raw",
        dataset_id="dataset_customers",
    )
    proposals = generate_cleaning_proposals(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_customers",
    )
    proposal = next(item for item in proposals if item.problem_type == "whitespace_pollution")
    approve_cleaning_proposal(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal.id,
    )

    first = apply_cleaning_proposal(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal.id,
    )
    second = apply_cleaning_proposal(
        store,
        workspace_id="workspace_1",
        proposal_id=proposal.id,
    )

    assert first.idempotent is False
    assert second.idempotent is True
    assert second.version.id == first.version.id == "version_001"
    assert second.operation.id == first.operation.id
    assert [version.id for version in list_dataset_versions(store, "dataset_customers")] == [
        "version_000",
        "version_001",
    ]
