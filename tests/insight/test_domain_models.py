import pytest
from pydantic import ValidationError

from data_formulator.insight.domain import Claim, ClaimType, DatasetProfile, DatasetVersion, SupportLevel


def test_dataset_version_rejects_path_traversal():
    with pytest.raises(ValidationError):
        DatasetVersion(
            id="version_1",
            workspace_id="ws_1",
            dataset_id="dataset_1",
            content_hash="abc",
            row_count=1,
            column_count=1,
            file_ref="../outside.parquet",
        )


def test_supported_claim_requires_evidence():
    with pytest.raises(ValidationError):
        Claim(
            id="claim_1",
            workspace_id="ws_1",
            statement="Feature X improves the model.",
            claim_type=ClaimType.MODEL_ATTRIBUTION,
            support_level=SupportLevel.DERIVED,
            confidence="medium",
            evidence_refs=[],
        )


def test_unsupported_claim_may_have_no_evidence():
    claim = Claim(
        id="claim_1",
        workspace_id="ws_1",
        statement="There is not enough evidence.",
        claim_type=ClaimType.CAUSAL_HYPOTHESIS,
        support_level=SupportLevel.UNSUPPORTED,
        confidence="low",
        evidence_refs=[],
    )
    assert claim.evidence_refs == []


def test_dataset_profile_rejects_path_traversal_refs():
    with pytest.raises(ValidationError):
        DatasetProfile(
            id="profile_1",
            workspace_id="ws_1",
            dataset_id="dataset_1",
            version_id="version_000",
            source_content_hash="sha256:abc",
            file_ref="datasets/dataset_1/versions/version_000.parquet",
            profile_ref="../outside.json",
            row_count=0,
            column_count=0,
        )
