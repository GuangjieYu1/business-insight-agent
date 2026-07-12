"""Version-aware profiling for immutable Business Insight dataset versions."""

from __future__ import annotations

import time

from data_formulator.insight.domain import DatasetProfile
from data_formulator.insight.profiling import (
    DEFAULT_PROFILE_LIMITS,
    PROFILE_CONFIGURATION_HASH,
    PROFILER_VERSION,
    InsightProfileError,
    InsightProfileNotFoundError,
    ProfileLimits,
    _check_deadline,
    _matches_current_profile,
    _profile_path,
    _validate_source_limits,
    profile_dataframe,
)
from data_formulator.insight.registry import (
    InsightRegistryError,
    read_dataset,
    read_dataset_version,
)
from data_formulator.insight.storage import InsightStore


def _resolve_dataset_version(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str,
):
    try:
        dataset = read_dataset(store, dataset_id)
        version = read_dataset_version(store, dataset_id, version_id)
    except InsightRegistryError as exc:
        raise InsightProfileError(str(exc)) from exc

    if dataset is None:
        raise InsightProfileNotFoundError(f"Dataset not found: {dataset_id}")
    if version is None:
        raise InsightProfileNotFoundError(
            f"Dataset version not found: {dataset_id}/{version_id}"
        )
    if dataset.workspace_id != workspace_id or version.workspace_id != workspace_id:
        raise InsightProfileError("Dataset workspace_id does not match active workspace")
    if version.dataset_id != dataset.id:
        raise InsightProfileError("Dataset version metadata is inconsistent")
    return dataset, version


def generate_dataset_version_profile(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str,
    limits: ProfileLimits = DEFAULT_PROFILE_LIMITS,
) -> DatasetProfile:
    """Generate or reuse a deterministic profile for any immutable dataset version."""

    dataset, version = _resolve_dataset_version(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        version_id=version_id,
    )
    profile_ref = _profile_path(dataset.id, version.id)

    if store.exists(profile_ref):
        try:
            existing_profile = store.read_model(profile_ref, DatasetProfile)
        except Exception:
            existing_profile = None
        if existing_profile is not None and _matches_current_profile(
            existing_profile,
            workspace_id=workspace_id,
            dataset_id=dataset.id,
            version_id=version.id,
            source_content_hash=version.content_hash,
            file_ref=version.file_ref,
            profile_ref=profile_ref,
        ):
            return existing_profile

    deadline = time.monotonic() + limits.timeout_seconds if limits.timeout_seconds > 0 else None
    _validate_source_limits(store, version.file_ref, limits)
    _check_deadline(deadline)
    dataframe = store.read_parquet(version.file_ref)
    _check_deadline(deadline)
    profile = profile_dataframe(
        dataframe,
        workspace_id=workspace_id,
        dataset_id=dataset.id,
        version_id=version.id,
        source_content_hash=version.content_hash,
        file_ref=version.file_ref,
        profile_ref=profile_ref,
        profiler_version=PROFILER_VERSION,
        configuration_hash=PROFILE_CONFIGURATION_HASH,
        limits=limits,
        deadline=deadline,
        profile_timestamp=version.created_at,
    )
    store.write_json(profile_ref, profile)
    return profile


def read_dataset_version_profile(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset_id: str,
    version_id: str,
) -> DatasetProfile | None:
    """Read a saved profile after validating its dataset, version, and workspace."""

    dataset, version = _resolve_dataset_version(
        store,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        version_id=version_id,
    )
    profile_ref = _profile_path(dataset.id, version.id)
    if not store.exists(profile_ref):
        return None

    profile = store.read_model(profile_ref, DatasetProfile)
    if profile.workspace_id != workspace_id:
        raise InsightProfileError("Profile workspace_id does not match active workspace")
    if profile.dataset_id != dataset.id or profile.version_id != version.id:
        raise InsightProfileError("Profile dataset version metadata is inconsistent")
    if profile.source_content_hash != version.content_hash:
        raise InsightProfileError("Profile source content hash does not match dataset version")
    return profile
