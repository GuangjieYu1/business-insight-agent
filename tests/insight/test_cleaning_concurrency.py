from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pandas as pd
import pytest

from data_formulator.insight.cleaning import generate_cleaning_proposals
from data_formulator.insight.cleaning_operations import (
    InsightCleaningOperationError,
    apply_cleaning_proposal,
    approve_cleaning_proposal,
    preview_cleaning_proposal,
)
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.storage import LocalInsightStore
from data_formulator.insight.versioning import list_dataset_versions


def _setup(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame(
            {
                "name": [" Alice ", "Bob"],
                "dirty_text": ["ok", "bad\x07"],
            }
        ),
        original_table_ref="customers_raw",
        dataset_id="dataset_customers",
    )
    proposals = generate_cleaning_proposals(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_customers",
    )
    by_type = {proposal.problem_type: proposal for proposal in proposals}
    return store, by_type


def test_invalid_operation_type_is_rejected_cleanly(tmp_path: Path):
    store, proposals = _setup(tmp_path)
    proposal = proposals["whitespace_pollution"]

    with pytest.raises(InsightCleaningOperationError, match="operationType"):
        preview_cleaning_proposal(
            store,
            workspace_id="workspace_1",
            proposal_id=proposal.id,
            operation_type=123,  # type: ignore[arg-type]
        )


def test_concurrent_proposals_for_same_input_version_cannot_both_apply(tmp_path: Path):
    store, proposals = _setup(tmp_path)
    first = proposals["whitespace_pollution"]
    second = proposals["dirty_character_column"]
    for proposal in (first, second):
        approve_cleaning_proposal(
            store,
            workspace_id="workspace_1",
            proposal_id=proposal.id,
        )

    barrier = Barrier(2)

    def run(proposal_id: str):
        barrier.wait()
        try:
            return apply_cleaning_proposal(
                store,
                workspace_id="workspace_1",
                proposal_id=proposal_id,
            )
        except InsightCleaningOperationError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(run, [first.id, second.id]))

    successes = [item for item in outcomes if not isinstance(item, Exception)]
    failures = [item for item in outcomes if isinstance(item, InsightCleaningOperationError)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert "stale" in str(failures[0])
    assert [version.id for version in list_dataset_versions(store, "dataset_customers")] == [
        "version_000",
        "version_001",
    ]
