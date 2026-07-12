from pathlib import Path

import pandas as pd
import pytest

from data_formulator.insight.registry import read_dataset, read_dataset_version, register_dataset_version_zero
from data_formulator.insight.storage import LocalInsightStore
from data_formulator.insight.versioning import (
    InsightVersioningError,
    activate_dataset_version,
    create_dataset_version,
    list_dataset_versions,
    read_operation,
    undo_dataset_version_by_operation,
)


def _register_dataset(store: LocalInsightStore) -> None:
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [10, 20]}),
        original_table_ref="sales_raw",
        dataset_id="dataset_sales",
    )


def test_create_dataset_version_creates_active_successor(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    _register_dataset(store)

    mutation = create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [11, 22]}),
        reason="Normalize values",
        operation_type="manual_transform",
    )

    dataset = read_dataset(store, "dataset_sales")
    original = read_dataset_version(store, "dataset_sales", "version_000")

    assert mutation.version.id == "version_001"
    assert mutation.version.parent_version_id == "version_000"
    assert mutation.version.created_by_operation_id == mutation.operation.id
    assert mutation.dataset.active_version_id == "version_001"
    assert dataset is not None and dataset.active_version_id == "version_001"
    assert original is not None and original.status == "historical"
    assert read_operation(store, mutation.operation.id).output_version_id == "version_001"


def test_create_dataset_version_can_branch_from_historical_parent(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    _register_dataset(store)

    first = create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [12, 24]}),
        reason="First derived version",
    )
    branch = create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [13, 26]}),
        parent_version_id="version_000",
        reason="Branch from immutable source",
    )

    versions = {version.id: version for version in list_dataset_versions(store, "dataset_sales")}

    assert first.version.id == "version_001"
    assert branch.version.id == "version_002"
    assert branch.version.parent_version_id == "version_000"
    assert versions["version_000"].status == "historical"
    assert versions["version_001"].status == "historical"
    assert versions["version_002"].status == "active"


def test_activate_dataset_version_switches_active_history(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    _register_dataset(store)
    create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [15, 25]}),
        reason="Derived v1",
    )
    create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [18, 28]}),
        reason="Derived v2",
    )

    activation = activate_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        version_id="version_001",
        reason="Compare prior branch",
    )

    dataset = read_dataset(store, "dataset_sales")
    version_001 = read_dataset_version(store, "dataset_sales", "version_001")
    version_002 = read_dataset_version(store, "dataset_sales", "version_002")

    assert activation.active_version.id == "version_001"
    assert activation.previous_version.id == "version_002"
    assert dataset is not None and dataset.active_version_id == "version_001"
    assert version_001 is not None and version_001.status == "active"
    assert version_002 is not None and version_002.status == "historical"


def test_undo_dataset_version_by_operation_reverts_and_marks_operation_undone(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    _register_dataset(store)
    mutation = create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [17, 27]}),
        reason="Drop a noisy column",
        operation_type="drop_column",
    )

    activation = undo_dataset_version_by_operation(
        store,
        workspace_id="workspace_1",
        operation_id=mutation.operation.id,
        reason="Undo latest dataset change",
    )

    dataset = read_dataset(store, "dataset_sales")
    original_operation = read_operation(store, mutation.operation.id)

    assert activation.active_version.id == "version_000"
    assert activation.previous_version.id == "version_001"
    assert activation.operation.operation_type == "undo_activation"
    assert activation.undone_operation is not None
    assert activation.undone_operation.status == "undone"
    assert dataset is not None and dataset.active_version_id == "version_000"
    assert original_operation is not None and original_operation.status == "undone"


def test_undo_requires_operation_output_to_still_be_active(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    _register_dataset(store)
    first = create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [17, 27]}),
        reason="First change",
    )
    create_dataset_version(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
        dataframe=pd.DataFrame({"region": ["east", "west"], "sales": [18, 28]}),
        reason="Second change",
    )

    with pytest.raises(InsightVersioningError, match="still be the active dataset version"):
        undo_dataset_version_by_operation(
            store,
            workspace_id="workspace_1",
            operation_id=first.operation.id,
        )