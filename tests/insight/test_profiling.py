from pathlib import Path

import pandas as pd

from data_formulator.insight.profiling import generate_dataset_profile, profile_dataframe, read_dataset_profile
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.storage import LocalInsightStore


def _issue_types(profile) -> set[str]:
    return {issue.issue_type for issue in profile.quality_issues}


def test_generate_dataset_profile_detects_initial_quality_rules(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    df = pd.DataFrame(
        {
            "empty": [None] * 20,
            "constant": ["same"] * 20,
            "near_constant": ["A"] * 19 + ["B"],
            "high_missing": [None] * 12 + ["x"] * 8,
            "status": ["ok"] * 20,
            "numericish": ["1", "2", "bad"] + [str(value) for value in range(4, 21)],
            "dateish": ["2026-01-01", "2026-01-02", "bad"] + [f"2026-01-{day:02d}" for day in range(4, 21)],
            "dup_key": list(range(20)),
        }
    )
    df.loc[1] = df.loc[0]
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=df,
        original_table_ref="quality_raw",
        dataset_id="dataset_quality",
    )

    profile = generate_dataset_profile(store, workspace_id="workspace_1", dataset_id="dataset_quality")

    assert profile.dataset_id == "dataset_quality"
    assert profile.version_id == "version_000"
    assert profile.profile_ref == "datasets/dataset_quality/profiles/version_000.json"
    assert profile.row_count == 20
    assert profile.column_count == len(df.columns)
    assert profile.duplicate_row_count == 2
    assert _issue_types(profile) >= {
        "empty_column",
        "constant_column",
        "near_constant_column",
        "high_missing_column",
        "duplicate_rows",
        "numeric_parse_conflict",
        "datetime_parse_conflict",
    }

    columns = {column.name: column for column in profile.columns}
    assert columns["empty"].inferred_type == "empty"
    assert columns["numericish"].numeric_parse_conflict_count == 1
    assert columns["dateish"].datetime_parse_conflict_count == 1
    assert "numeric_parse_conflict" in columns["numericish"].quality_issue_types
    assert store.exists("datasets/dataset_quality/profiles/version_000.json")
    assert read_dataset_profile(store, dataset_id="dataset_quality") == profile


def test_profile_dataframe_detects_mixed_runtime_value_types():
    df = pd.DataFrame({"mixed": pd.Series([1, "two", 3.0, None], dtype=object)})

    profile = profile_dataframe(
        df,
        workspace_id="workspace_1",
        dataset_id="dataset_mixed",
        version_id="version_000",
        source_content_hash="sha256:abc",
        file_ref="datasets/dataset_mixed/versions/version_000.parquet",
        profile_ref="datasets/dataset_mixed/profiles/version_000.json",
    )

    assert "mixed_type_column" in _issue_types(profile)
    assert profile.columns[0].inferred_type == "mixed"
    assert profile.columns[0].python_types == ["number", "str"]
