"""Project and immutable dataset registration for Business Insight."""

from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd

from data_formulator.insight.domain import Dataset, DatasetVersion, Project
from data_formulator.insight.domain.models import new_id, utc_now
from data_formulator.insight.storage import LocalInsightStore

PROJECT_PATH = "project.json"
VERSION_ZERO_ID = "version_000"
_REGISTRY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class InsightRegistryError(ValueError):
    """Raised when a project or dataset cannot be registered safely."""


class InsightAlreadyRegisteredError(InsightRegistryError):
    """Raised when a registry operation would overwrite immutable state."""


@dataclass(frozen=True)
class ProjectRegistration:
    project: Project
    created: bool


@dataclass(frozen=True)
class DatasetRegistration:
    project: Project
    dataset: Dataset
    version: DatasetVersion
    created: bool


def _require_text(value: str | None, field_name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise InsightRegistryError(f"{field_name} is required")
    return cleaned


def _validate_registry_id(value: str, field_name: str) -> str:
    if not _REGISTRY_ID_RE.fullmatch(value):
        raise InsightRegistryError(
            f"{field_name} must contain only letters, numbers, underscore, or dash"
        )
    return value


def ensure_project(
    store: LocalInsightStore,
    *,
    workspace_id: str,
    name: str = "Business Insight Project",
    description: str = "",
    default_language: str = "zh-CN",
) -> ProjectRegistration:
    """Create the workspace project if missing, otherwise return it unchanged."""

    if store.exists(PROJECT_PATH):
        return ProjectRegistration(project=store.read_model(PROJECT_PATH, Project), created=False)

    project = Project(
        id=new_id("project"),
        workspace_id=_require_text(workspace_id, "workspace_id"),
        name=_require_text(name, "name"),
        description=description.strip(),
        default_language=_require_text(default_language, "default_language"),
    )
    store.write_json(PROJECT_PATH, project)
    return ProjectRegistration(project=project, created=True)


def read_project(store: LocalInsightStore) -> Project | None:
    if not store.exists(PROJECT_PATH):
        return None
    return store.read_model(PROJECT_PATH, Project)


def _dataset_dir(dataset_id: str) -> str:
    return f"datasets/{dataset_id}"


def _dataset_path(dataset_id: str) -> str:
    return f"{_dataset_dir(dataset_id)}/dataset.json"


def _version_json_path(dataset_id: str, version_id: str = VERSION_ZERO_ID) -> str:
    return f"{_dataset_dir(dataset_id)}/versions/{version_id}.json"


def _version_parquet_path(dataset_id: str, version_id: str = VERSION_ZERO_ID) -> str:
    return f"{_dataset_dir(dataset_id)}/versions/{version_id}.parquet"


def register_dataset_version_zero(
    store: LocalInsightStore,
    *,
    workspace_id: str,
    dataframe: pd.DataFrame,
    original_table_ref: str,
    dataset_name: str | None = None,
    dataset_id: str | None = None,
    source_material_id: str | None = None,
    project_name: str = "Business Insight Project",
) -> DatasetRegistration:
    """Register a workspace table as an immutable Version 0 snapshot.

    Version 0 is write-once. A caller may supply ``dataset_id`` for tests or
    deterministic integrations, but an existing dataset/version path is never
    overwritten.
    """

    workspace_id = _require_text(workspace_id, "workspace_id")
    table_ref = _require_text(original_table_ref, "original_table_ref")
    resolved_dataset_id = _validate_registry_id(dataset_id or new_id("dataset"), "dataset_id")

    dataset_path = _dataset_path(resolved_dataset_id)
    version_json_path = _version_json_path(resolved_dataset_id)
    version_parquet_path = _version_parquet_path(resolved_dataset_id)
    if (
        store.exists(dataset_path)
        or store.exists(version_json_path)
        or store.exists(version_parquet_path)
    ):
        raise InsightAlreadyRegisteredError(
            f"Dataset '{resolved_dataset_id}' already has immutable Version 0"
        )

    project_registration = ensure_project(
        store,
        workspace_id=workspace_id,
        name=project_name,
    )

    store.write_parquet(version_parquet_path, dataframe, overwrite=False)
    version = DatasetVersion(
        id=VERSION_ZERO_ID,
        workspace_id=workspace_id,
        dataset_id=resolved_dataset_id,
        content_hash=store.file_sha256(version_parquet_path),
        row_count=int(len(dataframe)),
        column_count=int(len(dataframe.columns)),
        file_ref=version_parquet_path,
    )
    dataset = Dataset(
        id=resolved_dataset_id,
        workspace_id=workspace_id,
        name=_require_text(dataset_name or table_ref, "dataset_name"),
        source_material_id=source_material_id,
        original_table_ref=table_ref,
        original_version_id=version.id,
        active_version_id=version.id,
    )

    store.write_json(version_json_path, version)
    store.write_json(dataset_path, dataset)

    project = project_registration.project.model_copy(
        update={
            "active_dataset_id": dataset.id,
            "updated_at": utc_now(),
        }
    )
    store.write_json(PROJECT_PATH, project)
    return DatasetRegistration(project=project, dataset=dataset, version=version, created=True)


def list_datasets(store: LocalInsightStore) -> list[Dataset]:
    datasets: list[Dataset] = []
    for relative_path in store.list_files("datasets"):
        if relative_path.endswith("/dataset.json"):
            datasets.append(store.read_model(relative_path, Dataset))
    return sorted(datasets, key=lambda dataset: dataset.created_at)


def read_dataset(store: LocalInsightStore, dataset_id: str) -> Dataset | None:
    dataset_id = _validate_registry_id(dataset_id, "dataset_id")
    path = _dataset_path(dataset_id)
    if not store.exists(path):
        return None
    return store.read_model(path, Dataset)


def read_dataset_version_zero(store: LocalInsightStore, dataset_id: str) -> DatasetVersion | None:
    dataset_id = _validate_registry_id(dataset_id, "dataset_id")
    path = _version_json_path(dataset_id)
    if not store.exists(path):
        return None
    return store.read_model(path, DatasetVersion)
