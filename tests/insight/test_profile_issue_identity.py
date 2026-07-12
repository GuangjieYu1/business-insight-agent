from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from data_formulator.insight.cleaning import (
    _proposal_path,
    generate_cleaning_proposals,
)
from data_formulator.insight.domain.models import (
    DatasetProfile,
    ProfileQualityIssue,
    build_profile_issue_id,
)
from data_formulator.insight.history import compare_dataset_version_profiles
from data_formulator.insight.profiling import profile_dataframe
from data_formulator.insight.registry import register_dataset_version_zero
from data_formulator.insight.storage import LocalInsightStore


def _issue(**overrides):
    payload = {
        "issue_type": "constant_column",
        "severity": "low",
        "scope": {"column": "region"},
        "metrics": {"non_null_count": 3},
        "message": "constant",
    }
    payload.update(overrides)
    return ProfileQualityIssue.model_validate(payload)


def _profile(version_id: str, issue: ProfileQualityIssue) -> DatasetProfile:
    return DatasetProfile(
        id=f"profile_{version_id}",
        workspace_id="workspace_1",
        dataset_id="dataset_1",
        version_id=version_id,
        source_content_hash=f"sha256:{version_id}",
        file_ref=f"datasets/dataset_1/versions/{version_id}.parquet",
        profile_ref=f"datasets/dataset_1/profiles/{version_id}.json",
        row_count=3,
        column_count=1,
        quality_issues=[issue],
    )


def test_issue_id_is_stable_across_non_identity_changes():
    before = _issue()
    after = _issue(
        severity="high",
        metrics={"non_null_count": 999, "dominant_ratio": 1.0},
        message="updated detector wording",
    )

    assert before.issue_id == after.issue_id
    assert before.issue_id == build_profile_issue_id(
        "constant_column",
        {"column": "region"},
    )


def test_issue_id_normalizes_scope_mapping_order():
    first = _issue(scope={"column": "region", "details": {"a": 1, "b": 2}})
    second = _issue(scope={"details": {"b": 2, "a": 1}, "column": "region"})
    changed_scope = _issue(scope={"column": "country", "details": {"a": 1, "b": 2}})
    changed_type = _issue(issue_type="empty_column")

    assert first.issue_id == second.issue_id
    assert first.issue_id != changed_scope.issue_id
    assert first.issue_id != changed_type.issue_id


def test_legacy_issue_payload_without_issue_id_is_upgraded():
    issue = ProfileQualityIssue.model_validate(
        {
            "issue_type": "whitespace_pollution",
            "severity": "low",
            "scope": {"column": "name"},
            "metrics": {"whitespace_pollution_count": 2},
            "message": "legacy payload",
        }
    )

    assert issue.issue_id == build_profile_issue_id(
        "whitespace_pollution",
        {"column": "name"},
    )
    assert issue.model_dump()["issue_id"] == issue.issue_id


def test_generated_profile_serializes_stable_issue_ids():
    profile = profile_dataframe(
        pd.DataFrame({"constant": ["same", "same"]}),
        workspace_id="workspace_1",
        dataset_id="dataset_1",
        version_id="version_000",
        source_content_hash="sha256:source",
        file_ref="datasets/dataset_1/versions/version_000.parquet",
        profile_ref="datasets/dataset_1/profiles/version_000.json",
    )

    issue = next(
        item for item in profile.quality_issues if item.issue_type == "constant_column"
    )
    serialized = profile.model_dump(mode="json")

    assert issue.issue_id
    assert any(item["issue_id"] == issue.issue_id for item in serialized["quality_issues"])


def test_profile_comparison_uses_issue_id_not_severity_or_metrics(monkeypatch):
    before = _profile("version_000", _issue())
    after = _profile(
        "version_001",
        _issue(
            severity="high",
            metrics={"non_null_count": 10},
            message="changed",
        ),
    )

    monkeypatch.setattr(
        "data_formulator.insight.history._require_dataset",
        lambda *args, **kwargs: SimpleNamespace(id="dataset_1"),
    )
    monkeypatch.setattr(
        "data_formulator.insight.history.read_dataset_version",
        lambda store, dataset_id, version_id: SimpleNamespace(
            id=version_id,
            workspace_id="workspace_1",
        ),
    )
    monkeypatch.setattr(
        "data_formulator.insight.history.generate_dataset_version_profile",
        lambda store, workspace_id, dataset_id, version_id: (
            before if version_id == "version_000" else after
        ),
    )

    comparison = compare_dataset_version_profiles(
        object(),
        workspace_id="workspace_1",
        dataset_id="dataset_1",
        before_version_id="version_000",
        after_version_id="version_001",
    )

    assert comparison["resolvedIssues"] == []
    assert comparison["introducedIssues"] == []
    assert len(comparison["unchangedIssues"]) == 1
    assert (
        comparison["unchangedIssues"][0]["before"].issue_id
        == comparison["unchangedIssues"][0]["after"].issue_id
    )


def test_repeated_legacy_proposal_generation_preserves_status(tmp_path: Path):
    store = LocalInsightStore(tmp_path)
    register_dataset_version_zero(
        store,
        workspace_id="workspace_1",
        dataframe=pd.DataFrame({"constant": ["same", "same", "same"]}),
        original_table_ref="sales_raw",
        dataset_id="dataset_sales",
    )

    initial = generate_cleaning_proposals(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
    )
    proposal = next(item for item in initial if item.problem_type == "constant_column")
    approved = proposal.model_copy(update={"status": "approved"})
    store.write_json(_proposal_path(approved.id), approved)

    repeated = generate_cleaning_proposals(
        store,
        workspace_id="workspace_1",
        dataset_id="dataset_sales",
    )
    repeated_proposal = next(item for item in repeated if item.id == approved.id)

    assert repeated_proposal.status == "approved"
