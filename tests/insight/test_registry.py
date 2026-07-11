from pathlib import Path

import pandas as pd
import pytest

from data_formulator.insight.registry import (
    VERSION_ZERO_ID,
    InsightAlreadyRegisteredError,
    ensure_project,
    list_datasets,
    read_dataset_version_zero,
    register_dataset_version_zero,
)
from data_formulator.insight.storage import LocalInsightStore


def test_ensure_project_is_idempotent(tmp_path: Path):
    store = LocalInsightStore(tmp_path)

    first = ensure_project(store, workspace_id="workspace_1", name="销售分析")
    second = ensure_project(store, workspace_id="workspace_1", name="Ignored")

    assert first.created is True
    assert second.created is False
    assert second.project.id == first.project.id
    assert second.project.name == "销售分析"


def test_register_dataset_creates_immutable_version_zero(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    df = pd.DataFrame({"region": ["east", "west"], "sales": [10, 20]})

    registration = register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=df,
        original_table_ref="sales_raw",
        dataset_name="Sales Raw",
        dataset_id="dataset_sales",
        project_name="经营分析",
    )

    assert registration.dataset.original_version_id == VERSION_ZERO_ID
    assert registration.dataset.active_version_id == VERSION_ZERO_ID
    assert registration.version.id == VERSION_ZERO_ID
    assert registration.version.row_count == 2
    assert registration.version.column_count == 2
    assert registration.version.content_hash.startswith("sha256:")
    assert registration.version.file_ref == "datasets/dataset_sales/versions/version_000.parquet"
    assert registration.project.active_dataset_id == "dataset_sales"
    assert list_datasets(store)[0].id == "dataset_sales"
    assert read_dataset_version_zero(store, "dataset_sales") == registration.version

    loaded = store.read_parquet(registration.version.file_ref)
    pd.testing.assert_frame_equal(loaded, df)


def test_register_dataset_refuses_to_overwrite_version_zero(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    df = pd.DataFrame({"sales": [10]})

    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=df,
        original_table_ref="sales_raw",
        dataset_id="dataset_sales",
    )

    with pytest.raises(InsightAlreadyRegisteredError):
        register_dataset_version_zero(
            store,
            workspace_id="workspace_1",
            dataframe=pd.DataFrame({"sales": [99]}),
            original_table_ref="sales_raw",
            dataset_id="dataset_sales",
        )

    loaded = store.read_parquet("datasets/dataset_sales/versions/version_000.parquet")
    assert loaded["sales"].tolist() == [10]
