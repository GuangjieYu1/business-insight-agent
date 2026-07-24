"""Project registration and immutable dataset bootstrap for Business Insight."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import re

import pandas as pd

from data_formulator.insight.domain import Dataset, DatasetVersion, Project
from data_formulator.insight.domain.models import new_id, utc_now
from data_formulator.insight.storage import InsightStore

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


def _optional_registry_id(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InsightRegistryError(f"{field_name} must be a string")
    cleaned = value.strip()
    return cleaned or None


def _dataset_dir(dataset_id: str) -> str:
    return f"datasets/{dataset_id}"


def _dataset_path(dataset_id: str) -> str:
    return f"{_dataset_dir(dataset_id)}/dataset.json"


def _version_json_path(dataset_id: str, version_id: str = VERSION_ZERO_ID) -> str:
    return f"{_dataset_dir(dataset_id)}/versions/{version_id}.json"


def _version_parquet_path(dataset_id: str, version_id: str = VERSION_ZERO_ID) -> str:
    return f"{_dataset_dir(dataset_id)}/versions/{version_id}.parquet"


def _ensure_project_unlocked(
    store: InsightStore,
    *,
    workspace_id: str,
    name: str,
    description: str,
    default_language: str,
) -> ProjectRegistration:
    if store.exists(PROJECT_PATH):
        project = store.read_model(PROJECT_PATH, Project)
        if project.workspace_id != workspace_id:
            raise InsightRegistryError("Project workspace_id does not match active workspace")
        return ProjectRegistration(project=project, created=False)

    project = Project(
        id=new_id("project"),
        workspace_id=workspace_id,
        name=_require_text(name, "name"),
        description=description.strip(),
        default_language=_require_text(default_language, "default_language"),
    )
    store.write_json(PROJECT_PATH, project)
    return ProjectRegistration(project=project, created=True)


def ensure_project(
    store: InsightStore,
    *,
    workspace_id: str,
    name: str = "Business Insight Project",
    description: str = "",
    default_language: str = "zh-CN",
) -> ProjectRegistration:
    """Create the workspace project if missing, otherwise return it unchanged."""

    workspace_id = _require_text(workspace_id, "workspace_id")
    with store.workspace_lock():
        return _ensure_project_unlocked(
            store,
            workspace_id=workspace_id,
            name=name,
            description=description,
            default_language=default_language,
        )


def read_project(store: InsightStore) -> Project | None:
    if not store.exists(PROJECT_PATH):
        return None
    return store.read_model(PROJECT_PATH, Project)


def _find_dataset_by_original_table_ref(
    store: InsightStore,
    original_table_ref: str,
) -> Dataset | None:
    for dataset in list_datasets(store):
        if dataset.original_table_ref == original_table_ref:
            return dataset
    return None


def _existing_registration_locked(
    store: InsightStore,
    *,
    workspace_id: str,
    dataset: Dataset,
    project_name: str,
) -> DatasetRegistration:
    if dataset.workspace_id != workspace_id:
        raise InsightRegistryError("Dataset workspace_id does not match active workspace")
    version = read_dataset_version_zero(store, dataset.id)
    if version is None:
        raise InsightRegistryError(f"Dataset '{dataset.id}' is missing immutable Version 0")
    if version.workspace_id != workspace_id:
        raise InsightRegistryError("Dataset version workspace_id does not match active workspace")

    project = read_project(store)
    if project is None:
        project = _ensure_project_unlocked(
            store,
            workspace_id=workspace_id,
            name=project_name,
            description="",
            default_language="zh-CN",
        ).project
    elif project.workspace_id != workspace_id:
        raise InsightRegistryError("Project workspace_id does not match active workspace")
    return DatasetRegistration(project=project, dataset=dataset, version=version, created=False)


def register_dataset_version_zero(
    store: InsightStore,
    *,
    workspace_id: str,
    dataframe: pd.DataFrame,
    original_table_ref: str,
    dataset_name: str | None = None,
    dataset_id: str | None = None,
    source_material_id: str | None = None,
    project_name: str = "Business Insight Project",
    allow_duplicate: bool = False,
) -> DatasetRegistration:
    """Register a workspace table as an immutable Version 0 snapshot."""

    workspace_id = _require_text(workspace_id, "workspace_id")
    table_ref = _require_text(original_table_ref, "original_table_ref")
    requested_dataset_id = _optional_registry_id(dataset_id, "dataset_id")

    with store.workspace_lock():
        resolved_dataset_id = ""
        if requested_dataset_id is not None:
            resolved_dataset_id = _validate_registry_id(requested_dataset_id, "dataset_id")
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

        if not allow_duplicate:
            existing_dataset = _find_dataset_by_original_table_ref(store, table_ref)
            if existing_dataset is not None:
                return _existing_registration_locked(
                    store,
                    workspace_id=workspace_id,
                    dataset=existing_dataset,
                    project_name=project_name,
                )

        if requested_dataset_id is None:
            resolved_dataset_id = _validate_registry_id(new_id("dataset"), "dataset_id")
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

        project = read_project(store)
        if project is None:
            project = Project(
                id=new_id("project"),
                workspace_id=workspace_id,
                name=_require_text(project_name, "project_name"),
            )
        elif project.workspace_id != workspace_id:
            raise InsightRegistryError("Project workspace_id does not match active workspace")

        staged_dir = store.make_temp_dir("datasets")
        final_dir = _dataset_dir(resolved_dataset_id)
        staged_version_json_path = f"{staged_dir}/versions/{VERSION_ZERO_ID}.json"
        staged_version_parquet_path = f"{staged_dir}/versions/{VERSION_ZERO_ID}.parquet"
        staged_dataset_path = f"{staged_dir}/dataset.json"
        final_project = project.model_copy(
            update={
                "active_dataset_id": resolved_dataset_id,
                "updated_at": utc_now(),
            }
        )
        final_dir_moved = False

        try:
            store.write_parquet(staged_version_parquet_path, dataframe, overwrite=False)
            version = DatasetVersion(
                id=VERSION_ZERO_ID,
                workspace_id=workspace_id,
                dataset_id=resolved_dataset_id,
                content_hash=store.file_sha256(staged_version_parquet_path),
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

            store.write_json(staged_version_json_path, version)
            store.write_json(staged_dataset_path, dataset)

            if (
                store.exists(dataset_path)
                or store.exists(version_json_path)
                or store.exists(version_parquet_path)
            ):
                raise InsightAlreadyRegisteredError(
                    f"Dataset '{resolved_dataset_id}' already has immutable Version 0"
                )
            store.move_tree(staged_dir, final_dir)
            final_dir_moved = True
            store.write_json(PROJECT_PATH, final_project)
        except Exception:
            with suppress(Exception):
                if final_dir_moved:
                    store.remove_tree(final_dir)
                else:
                    store.remove_tree(staged_dir)
            raise

        return DatasetRegistration(project=final_project, dataset=dataset, version=version, created=True)


def list_datasets(store: InsightStore) -> list[Dataset]:
    datasets: list[Dataset] = []
    for relative_path in store.list("datasets"):
        if relative_path.endswith("/dataset.json"):
            datasets.append(store.read_model(relative_path, Dataset))
    return sorted(datasets, key=lambda dataset: dataset.created_at)


def read_dataset(store: InsightStore, dataset_id: str) -> Dataset | None:
    dataset_id = _validate_registry_id(dataset_id, "dataset_id")
    path = _dataset_path(dataset_id)
    if not store.exists(path):
        return None
    return store.read_model(path, Dataset)


def read_dataset_version(store: InsightStore, dataset_id: str, version_id: str) -> DatasetVersion | None:
    dataset_id = _validate_registry_id(dataset_id, "dataset_id")
    version_id = _validate_registry_id(version_id, "version_id")
    path = _version_json_path(dataset_id, version_id)
    if not store.exists(path):
        return None
    return store.read_model(path, DatasetVersion)


def read_dataset_version_zero(store: InsightStore, dataset_id: str) -> DatasetVersion | None:
    return read_dataset_version(store, dataset_id, VERSION_ZERO_ID)