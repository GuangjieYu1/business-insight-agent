from pathlib import Path

import pandas as pd
import pytest

from data_formulator.insight.profiling import (
    InsightProfileError,
    ProfileLimits,
    generate_dataset_profile,
    profile_dataframe,
    read_dataset_profile,
)
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
    assert profile.duplicate_group_member_count == 2
    assert profile.duplicate_excess_row_count == 1
    assert profile.duplicate_row_count == 1
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
    assert columns["empty"].quality_issue_types == ["empty_column"]
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


def test_profile_dataframe_is_content_deterministic():
    df = pd.DataFrame({"status": ["ok", "ok", "hold"]})
    kwargs = {
        "workspace_id": "workspace_1",
        "dataset_id": "dataset_stable",
        "version_id": "version_000",
        "source_content_hash": "sha256:stable",
        "file_ref": "datasets/dataset_stable/versions/version_000.parquet",
        "profile_ref": "datasets/dataset_stable/profiles/version_000.json",
    }

    first = profile_dataframe(df, **kwargs)
    second = profile_dataframe(df, **kwargs)

    assert first.id == second.id
    assert first.created_at == second.created_at
    assert first.updated_at == second.updated_at
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_generate_dataset_profile_returns_existing_current_profile(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame({"status": ["ok", "ok", "hold"]}),
        original_table_ref="stable_raw",
        dataset_id="dataset_stable",
    )

    first = generate_dataset_profile(store, workspace_id="workspace_1", dataset_id="dataset_stable")
    first_payload = store.read_json("datasets/dataset_stable/profiles/version_000.json")
    second = generate_dataset_profile(store, workspace_id="workspace_1", dataset_id="dataset_stable")
    second_payload = store.read_json("datasets/dataset_stable/profiles/version_000.json")

    assert second == first
    assert second_payload == first_payload


def test_generate_dataset_profile_rejects_sources_over_limits(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame({"value": [1, 2, 3]}),
        original_table_ref="too_large_raw",
        dataset_id="dataset_too_large",
    )

    with pytest.raises(InsightProfileError, match="row limit exceeded"):
        generate_dataset_profile(
            store,
            workspace_id="workspace_1",
            dataset_id="dataset_too_large",
            limits=ProfileLimits(max_rows=2),
        )


def test_profile_dataframe_redacts_sensitive_values_and_disables_samples():
    df = pd.DataFrame(
        {
            "email": ["a@example.com", "b@example.com", "a@example.com"],
            "status": ["active", "active", "paused"],
        }
    )

    profile = profile_dataframe(
        df,
        workspace_id="workspace_1",
        dataset_id="dataset_privacy",
        version_id="version_000",
        source_content_hash="sha256:privacy",
        file_ref="datasets/dataset_privacy/versions/version_000.parquet",
        profile_ref="datasets/dataset_privacy/profiles/version_000.json",
    )

    columns = {column.name: column for column in profile.columns}
    assert profile.sample_policy == "disabled"
    assert profile.sensitive_data_detected is True
    assert profile.redaction_applied is True
    assert columns["email"].sensitive_data_detected is True
    assert columns["email"].redaction_applied is True
    assert columns["email"].top_values == []
    assert columns["email"].sample_values == []
    assert columns["status"].top_values == [{"value": "active", "count": 2}, {"value": "paused", "count": 1}]
    assert columns["status"].sample_values == []
